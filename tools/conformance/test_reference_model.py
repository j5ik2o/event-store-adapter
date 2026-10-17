"""仕様の状態機械が、もっともらしい誤期待も検出することを確かめる。"""

import copy
import unittest

import data
from data import fnv1a64, materialize
from manifest import DEFAULT_ROOT, read_json
from reference_model import equal_json, replay


def case(relative, identifier):
    return next(c for c in read_json(DEFAULT_ROOT / relative)['cases'] if c['id'] == identifier)


class ReferenceModelTests(unittest.TestCase):
    def test_every_distributed_scenario_replays_all_logical_operations(self):
        for path in DEFAULT_ROOT.rglob('*.json'):
            doc = read_json(path)
            if doc.get('format') != 'scenarios':
                continue
            for scenario in doc['cases']:
                with self.subTest(scenario=scenario['id']):
                    report = replay(materialize(scenario))
                    self.assertEqual(report.checked, len(scenario['steps']) + ('initialization' in scenario))
                    self.assertEqual(len(report.skipped), 1)
                    self.assertIn('SDK要求', report.skipped[0][1])

    def test_memory_unsupported_capability_is_configuration_error(self):
        for identifier in ['memory-ttl-unsupported', 'memory-change-feed-unsupported']:
            with self.subTest(case=identifier):
                scenario = case('memory/configuration.json', identifier)
                self.assertEqual(replay(copy.deepcopy(scenario)).checked, 1)
                scenario['initialization']['expect']['error']['category'] = 'storage'
                with self.assertRaisesRegex(ValueError, '参照モデルと期待が不一致'):
                    replay(scenario)

    def test_gap_is_contract_violation_even_if_expected_optimistic_lock(self):
        scenario = case('scenarios/core/write-read.json', 'core-gap-event')
        scenario['steps'][1]['expect']['error']['category'] = 'optimistic-lock'
        with self.assertRaisesRegex(ValueError, '参照モデルと期待が不一致'):
            replay(scenario)

    def test_transaction_conflict_on_any_item_wins_over_head_gap(self):
        scenario = case('dynamodb/write-errors.json', 'dynamodb-condition-gap')
        fault = next(f for f in scenario['faults'] if f['phase'] == 'commit')
        fault['details']['cancellation_reasons'].append({'target': 'current-snapshot', 'code': 'TransactionConflict'})
        with self.assertRaisesRegex(ValueError, '参照モデルと期待が不一致'):
            replay(scenario)

    def test_head_condition_is_read_before_journal_condition(self):
        scenario = case('dynamodb/write-errors.json', 'dynamodb-condition-gap')
        fault = next(f for f in scenario['faults'] if f['phase'] == 'commit')
        fault['details']['cancellation_reasons'][0] = {'target': 'journal', 'code': 'ConditionalCheckFailed'}
        replay(scenario)

    def test_failed_write_does_not_advance_head(self):
        scenario = case('scenarios/core/write-read.json', 'core-gap-event')
        read = next(s for s in scenario['steps'] if s['op'] == 'getLatestSnapshotById')
        read['expect']['head_seq_nr'] = 7
        with self.assertRaisesRegex(ValueError, '参照モデルと期待が不一致'):
            replay(scenario)

    def test_event_read_is_inclusive_and_preserves_envelope(self):
        scenario = case('scenarios/core/write-read.json', 'core-replay-without-snapshot')
        read = next(s for s in scenario['steps'] if len(s['expect'].get('events', [])) >= 2)
        read['expect']['events'].pop(0)
        with self.assertRaisesRegex(ValueError, '参照モデルと期待が不一致'):
            replay(scenario)

    def test_ttl_deadline_cannot_be_replaced_by_one(self):
        scenario = case('dynamodb/retention.json', 'dynamodb-retention-ttl-once')
        scenario['steps'][0]['observe']['history']['marked'][1]['ttl'] = 1
        with self.assertRaisesRegex(ValueError, '履歴・TTL期限'):
            replay(scenario)

    def test_previously_marked_history_cannot_have_its_deadline_extended(self):
        scenario = case('dynamodb/retention.json', 'dynamodb-retention-ttl-once')
        scenario['steps'][1]['observe']['history']['marked'][1]['ttl'] = 4102445860
        with self.assertRaisesRegex(ValueError, '履歴・TTL期限'):
            replay(scenario)

    def test_retention_failure_keeps_committed_event_and_notifies(self):
        scenario = case('scenarios/core/retention-errors.json', 'core-retention-failure-after-commit')
        scenario['steps'][1]['observe']['notifications'] = []
        with self.assertRaisesRegex(ValueError, '保持失敗通知'):
            replay(scenario)

    def test_history_pages_are_verbatim_and_omit_flag_is_consistent(self):
        scenario = case('dynamodb/retention.json', 'dynamodb-retention-gsi-missing-new')
        scenario['faults'][0]['details']['history_pages'][0].insert(0, 2)
        with self.assertRaisesRegex(ValueError, 'omit_just_written_history'):
            replay(scenario)

    def test_commit_response_loss_keeps_the_committed_write(self):
        scenario = case('scenarios/core/retention-errors.json', 'core-storage-commit-failure')
        scenario['faults'][0]['injection'] = 'replace-response'
        self.assertEqual(scenario['steps'][1]['expect'], {'result': 'none'})
        with self.assertRaisesRegex(ValueError, '参照モデルと期待が不一致'):
            replay(scenario)

    def test_batch_interleave_uses_new_snapshot_and_old_head(self):
        scenario = case('dynamodb/read.json', 'dynamodb-snapshot-ahead-of-head')
        scenario['steps'][1]['expect']['head_seq_nr'] = 2
        with self.assertRaisesRegex(ValueError, '参照モデルと期待が不一致'):
            replay(scenario)

    def test_shared_store_duplicate_seq_is_optimistic_lock(self):
        scenario = case('memory/stores.json', 'memory-store-shared')
        scenario['steps'][4]['expect'] = {'result': 'success'}
        with self.assertRaisesRegex(ValueError, '参照モデルと期待が不一致'):
            replay(scenario)

    def test_lock_held_append_is_storage_error_not_optimistic_lock(self):
        scenario = case('sqlite/write-lock.json', 'sqlite-write-lock-busy')
        self.assertGreater(replay(copy.deepcopy(scenario)).checked, 0)
        held = next(i for i, s in enumerate(scenario['steps']) if s['op'] == 'holdWriteLock')
        blocked = scenario['steps'][held + 1]
        self.assertEqual(blocked['expect']['error']['category'], 'storage')
        blocked['expect']['error']['category'] = 'optimistic-lock'
        with self.assertRaisesRegex(ValueError, '参照モデルと期待が不一致'):
            replay(scenario)

    def test_lock_held_append_cannot_be_expected_to_succeed(self):
        scenario = case('sqlite/write-lock.json', 'sqlite-write-lock-busy')
        held = next(i for i, s in enumerate(scenario['steps']) if s['op'] == 'holdWriteLock')
        scenario['steps'][held + 1]['expect'] = {'result': 'success'}
        with self.assertRaisesRegex(ValueError, '参照モデルと期待が不一致'):
            replay(scenario)

    def test_stage5_shared_store_stale_append_is_optimistic_lock(self):
        scenario = case('scenarios/stores/shared.json', 'store-shared-persistent')
        self.assertGreater(replay(copy.deepcopy(scenario)).checked, 0)
        stale = [s for s in scenario['steps']
                 if s['op'] == 'persistEvent' and s.get('store') == 'second'
                 and s['expect'].get('error', {}).get('category') == 'optimistic-lock']
        self.assertGreaterEqual(len(stale), 1)
        for step in stale:
            step['expect'] = {'result': 'success'}
        with self.assertRaisesRegex(ValueError, '参照モデルと期待が不一致'):
            replay(scenario)

    def test_seeded_configuration_mismatch_is_configuration_error(self):
        mismatches = [c for c in read_json(DEFAULT_ROOT / 'sqlite/configuration.json')['cases']
                      if 'configuration' in c.get('seed', {})
                      and 'error' in c['initialization']['expect']]
        self.assertGreaterEqual(len(mismatches), 3)
        for scenario in mismatches:
            with self.subTest(case=scenario['id']):
                self.assertEqual(scenario['initialization']['expect']['error']['category'], 'configuration')
                self.assertEqual(replay(copy.deepcopy(scenario)).checked, 1)
                scenario['initialization']['expect'] = {'result': 'success'}
                with self.assertRaisesRegex(ValueError, '参照モデルと期待が不一致'):
                    replay(scenario)

    def test_seeded_configuration_match_cannot_be_expected_to_fail(self):
        matches = [c for c in read_json(DEFAULT_ROOT / 'sqlite/configuration.json')['cases']
                   if 'configuration' in c.get('seed', {})
                   and c['initialization']['expect'].get('result') == 'success']
        self.assertGreaterEqual(len(matches), 1)
        for scenario in matches:
            with self.subTest(case=scenario['id']):
                scenario['initialization']['expect'] = {
                    'error': {'category': 'configuration', 'message': {'must_contain': [], 'must_not_contain': []}}}
                with self.assertRaisesRegex(ValueError, '参照モデルと期待が不一致'):
                    replay(scenario)

    def test_sqlite_unsupported_capability_is_configuration_error(self):
        unsupported = [c for c in read_json(DEFAULT_ROOT / 'sqlite/configuration.json')['cases']
                       if 'seed' not in c and 'error' in c['initialization']['expect']]
        self.assertEqual(len(unsupported), 2)
        for scenario in unsupported:
            with self.subTest(case=scenario['id']):
                self.assertEqual(replay(copy.deepcopy(scenario)).checked, 1)
                scenario['initialization']['expect']['error']['category'] = 'storage'
                with self.assertRaisesRegex(ValueError, '参照モデルと期待が不一致'):
                    replay(scenario)

    def test_memory_shared_configuration_keeps_one_history(self):
        scenario = case('memory/stores.json', 'memory-store-shared-configuration')
        self.assertGreater(replay(copy.deepcopy(scenario)).checked, 0)
        observed = [s for s in scenario['steps'] if 'history' in s.get('observe', {})]
        self.assertGreaterEqual(len(observed), 1)
        last = observed[-1]['observe']['history']
        self.assertEqual(len(last['active']), 1)
        last['active'] = [last['active'][0] - 1, last['active'][0]]
        with self.assertRaisesRegex(ValueError, '履歴'):
            replay(scenario)

    def test_payload_mutation_does_not_change_reread_value(self):
        for identifier in ['memory-payload-written-mutation', 'memory-payload-read-mutation']:
            with self.subTest(case=identifier):
                scenario = case('memory/payload-isolation.json', identifier)
                mutated = copy.deepcopy(scenario['fixtures']['events']['e1'])
                mutated['payload']['items'][0]['qty'] = 99
                scenario['fixtures']['events']['e1-mutated'] = mutated
                scenario['steps'][-1]['expect']['events'] = ['e1-mutated']
                with self.assertRaisesRegex(ValueError, '参照モデルと期待が不一致'):
                    replay(scenario)

    def test_string_generation_preserves_byte_length_and_source(self):
        scenario = case('dynamodb/write-errors.json', 'dynamodb-item-size-event')
        expanded = materialize(scenario)
        self.assertEqual(scenario['fixtures']['events']['e1']['payload'], '')
        self.assertEqual(len(expanded['fixtures']['events']['e1']['payload'].encode('utf-8')), 420000)
        custom = {'fixtures': {'events': {'e': {'payload': ''}}},
                  'generators': [{'target': '/fixtures/events/e/payload', 'character': '猫', 'byte_length': 6}]}
        self.assertEqual(materialize(custom)['fixtures']['events']['e']['payload'], '猫猫')
        custom['generators'][0]['byte_length'] = 5
        with self.assertRaisesRegex(ValueError, '文字幅の倍数'):
            materialize(custom)
        invalid = copy.deepcopy(custom)
        invalid['generators'][0].update(target='/fixtures/events/missing/payload', byte_length=6)
        with self.assertRaisesRegex(ValueError, '生成の対象が不正'):
            materialize(invalid)

    def test_hash_matches_all_specification_vectors(self):
        for vector in read_json(DEFAULT_ROOT / 'values/hash.json')['cases']:
            with self.subTest(vector=vector['id']):
                self.assertEqual(fnv1a64(vector['input']['utf8']), vector['expect']['value'])

    def test_json_comparison_does_not_equate_boolean_and_number(self):
        self.assertFalse(equal_json({'x': True}, {'x': 1}))
        self.assertTrue(equal_json({'x': 1.0, 'y': [None]}, {'y': [None], 'x': 1}))


    # ---- Spanner と Bigtable の事例 ----

    def faulted_step(self, scenario, phase):
        fault = next(f for f in scenario['faults'] if f['phase'] == phase)
        return scenario['steps'][fault['operation'] - 1]

    def test_spanner_change_feed_request_is_configuration_error_unsupported(self):
        scenario = case('spanner/configuration.json', 'spanner-change-feed-unsupported')
        self.assertEqual(replay(copy.deepcopy(scenario)).checked, 1)
        scenario['initialization']['expect']['error']['category'] = 'storage'
        with self.assertRaisesRegex(ValueError, '参照モデルと期待が不一致'):
            replay(scenario)

    def test_spanner_ttl_request_alone_is_not_an_unsupported_capability_unsupported(self):
        scenario = case('spanner/configuration.json', 'spanner-seeded-ttl-configuration-match')
        self.assertEqual(scenario['store']['retention_mode'], 'ttl')
        self.assertEqual(scenario['initialization']['expect'], {'result': 'success'})
        self.assertGreater(replay(copy.deepcopy(scenario)).checked, 0)
        scenario['initialization']['expect'] = {
            'error': {'category': 'configuration', 'message': {'must_contain': [], 'must_not_contain': []}}}
        with self.assertRaisesRegex(ValueError, '参照モデルと期待が不一致'):
            replay(scenario)

    def test_spanner_seeded_mismatches_are_configuration_errors_seeded(self):
        mismatches = [c for c in read_json(DEFAULT_ROOT / 'spanner/configuration.json')['cases']
                      if 'configuration' in c.get('seed', {}) and 'error' in c['initialization']['expect']]
        self.assertEqual(len(mismatches), 7)
        for scenario in mismatches:
            with self.subTest(case=scenario['id']):
                self.assertEqual(scenario['initialization']['expect']['error']['category'], 'configuration')
                self.assertEqual(replay(copy.deepcopy(scenario)).checked, 1)
                scenario['initialization']['expect'] = {'result': 'success'}
                with self.assertRaisesRegex(ValueError, '参照モデルと期待が不一致'):
                    replay(scenario)

    def test_spanner_seeded_match_cannot_be_expected_to_fail_seeded(self):
        matches = [c for c in read_json(DEFAULT_ROOT / 'spanner/configuration.json')['cases']
                   if 'configuration' in c.get('seed', {}) and c['initialization']['expect'].get('result') == 'success']
        self.assertEqual(len(matches), 2)
        for scenario in matches:
            with self.subTest(case=scenario['id']):
                self.assertGreater(replay(copy.deepcopy(scenario)).checked, 0)
                scenario['initialization']['expect'] = {
                    'error': {'category': 'configuration', 'message': {'must_contain': [], 'must_not_contain': []}}}
                with self.assertRaisesRegex(ValueError, '参照モデルと期待が不一致'):
                    replay(scenario)

    def test_spanner_grace_days_are_compared_in_client_config_and_policy_seeded(self):
        def agree_config(c):
            c['seed']['configuration']['ttl_grace_days'] = c['store']['ttl_grace_days']

        def agree_policy(c):
            c['seed']['row_deletion_policy_days'] = c['store']['ttl_grace_days']

        def agree_client(c):
            c['store']['ttl_grace_days'] = c['seed']['configuration']['ttl_grace_days']

        agreements = {'spanner-seeded-ttl-grace-config-mismatch': agree_config,
                      'spanner-seeded-ttl-grace-policy-mismatch': agree_policy,
                      'spanner-seeded-ttl-grace-client-mismatch': agree_client}
        for identifier, agree in agreements.items():
            with self.subTest(case=identifier):
                scenario = case('spanner/configuration.json', identifier)
                self.assertEqual(replay(copy.deepcopy(scenario)).checked, 1)
                agree(scenario)
                # 3 か所の日数のうち違いが 1 か所だけだった事例は、その 1 か所を揃えると他の 2 か所では食い違いが残らない。
                with self.assertRaisesRegex(ValueError, '参照モデルと期待が不一致'):
                    replay(scenario)

    def test_spanner_non_positive_client_grace_days_is_configuration_error_without_seed_seeded(self):
        scenario = case('spanner/configuration.json', 'spanner-ttl-grace-days-not-positive')
        self.assertNotIn('seed', scenario)
        self.assertLessEqual(scenario['store']['ttl_grace_days'], 0)
        self.assertEqual(replay(copy.deepcopy(scenario)).checked, 1)
        scenario['initialization']['expect'] = {'result': 'success'}
        with self.assertRaisesRegex(ValueError, '参照モデルと期待が不一致'):
            replay(scenario)

    def test_spanner_aborted_within_retry_limit_commits_once_aborted(self):
        scenario = case('spanner/commit.json', 'spanner-aborted-retry-within-limit')
        fault = scenario['faults'][0]
        self.assertEqual((fault['kind'], fault['phase'], fault['injection']),
                         ('transaction-aborted', 'commit', 'replace-request'))
        self.assertLessEqual(fault['repeat']['count'], scenario['store']['transaction_retry_limit'])
        self.assertGreater(replay(copy.deepcopy(scenario)).checked, 0)
        step = scenario['steps'][fault['operation'] - 1]
        step['expect'] = {'error': {'category': 'storage', 'message': {'must_contain': [], 'must_not_contain': []}}}
        with self.assertRaisesRegex(ValueError, '参照モデルと期待が不一致'):
            replay(scenario)

    def test_spanner_aborted_beyond_retry_limit_is_storage_error_aborted(self):
        scenario = case('spanner/commit.json', 'spanner-aborted-retry-limit-exceeded')
        fault = scenario['faults'][0]
        self.assertGreater(fault['repeat']['count'], scenario['store']['transaction_retry_limit'])
        self.assertGreater(replay(copy.deepcopy(scenario)).checked, 0)
        self.faulted_step(scenario, 'commit')['expect'] = {'result': 'success'}
        with self.assertRaisesRegex(ValueError, '参照モデルと期待が不一致'):
            replay(scenario)

    def test_spanner_aborted_exactly_at_retry_limit_still_commits_aborted(self):
        scenario = case('spanner/commit.json', 'spanner-aborted-retry-limit-exceeded')
        scenario['faults'][0]['repeat']['count'] = scenario['store']['transaction_retry_limit']
        with self.assertRaisesRegex(ValueError, '参照モデルと期待が不一致'):
            replay(scenario)

    def test_spanner_commit_response_loss_makes_resend_an_optimistic_lock_response_lost(self):
        scenario = case('spanner/commit.json', 'spanner-commit-response-lost')
        self.assertEqual(scenario['faults'][0]['injection'], 'replace-response')
        report = replay(copy.deepcopy(scenario))
        self.assertEqual(report.checked, len(scenario['steps']))
        self.assertEqual(len(report.skipped), 1)
        resend = [s for s in scenario['steps'] if s['expect'].get('error', {}).get('category') == 'optimistic-lock']
        self.assertEqual(len(resend), 1)
        resend[0]['expect'] = {'result': 'success'}
        with self.assertRaisesRegex(ValueError, '参照モデルと期待が不一致'):
            replay(scenario)

    def test_bigtable_conditional_update_response_loss_makes_resend_an_optimistic_lock_response_lost(self):
        scenario = case('bigtable/journal-write.json', 'bigtable-cas-response-lost')
        self.assertEqual((scenario['faults'][0]['phase'], scenario['faults'][0]['injection']),
                         ('commit', 'replace-response'))
        report = replay(copy.deepcopy(scenario))
        self.assertEqual(report.checked, len(scenario['steps']))
        resend = [s for s in scenario['steps'] if s['expect'].get('error', {}).get('category') == 'optimistic-lock']
        self.assertEqual(len(resend), 1)
        resend[0]['expect'] = {'result': 'success'}
        with self.assertRaisesRegex(ValueError, '参照モデルと期待が不一致'):
            replay(scenario)

    def test_bigtable_unsupported_capabilities_are_configuration_errors_bigtable(self):
        for identifier in ['bigtable-ttl-unsupported', 'bigtable-change-feed-unsupported']:
            with self.subTest(case=identifier):
                scenario = case('bigtable/configuration.json', identifier)
                self.assertEqual(replay(copy.deepcopy(scenario)).checked, 1)
                scenario['initialization']['expect']['error']['category'] = 'storage'
                with self.assertRaisesRegex(ValueError, '参照モデルと期待が不一致'):
                    replay(scenario)

    def test_bigtable_seeded_mismatches_are_configuration_errors_bigtable(self):
        identifiers = ['bigtable-seeded-table-envelope-limit-mismatch', 'bigtable-seeded-keep-count-mismatch',
                       'bigtable-seeded-envelope-limit-mismatch']
        for identifier in identifiers:
            with self.subTest(case=identifier):
                scenario = case('bigtable/configuration.json', identifier)
                self.assertEqual(scenario['initialization']['expect']['error']['category'], 'configuration')
                self.assertEqual(replay(copy.deepcopy(scenario)).checked, 1)
                scenario['initialization']['expect'] = {'result': 'success'}
                with self.assertRaisesRegex(ValueError, '参照モデルと期待が不一致'):
                    replay(scenario)

    def test_bigtable_journal_and_head_configurations_are_compared_bigtable(self):
        scenario = case('bigtable/configuration.json', 'bigtable-seeded-table-envelope-limit-mismatch')
        configuration = scenario['seed']['configuration']
        configuration['head'] = copy.deepcopy(configuration['journal'])
        with self.assertRaisesRegex(ValueError, '参照モデルと期待が不一致'):
            replay(scenario)

    def test_bigtable_seeded_match_cannot_be_expected_to_fail_bigtable(self):
        scenario = case('bigtable/configuration.json', 'bigtable-seeded-configuration-match')
        self.assertGreater(replay(copy.deepcopy(scenario)).checked, 0)
        scenario['initialization']['expect'] = {
            'error': {'category': 'configuration', 'message': {'must_contain': [], 'must_not_contain': []}}}
        with self.assertRaisesRegex(ValueError, '参照モデルと期待が不一致'):
            replay(scenario)

    def test_bigtable_default_envelope_limit_store_is_created_envelope_limit(self):
        scenario = case('bigtable/journal-write.json', 'bigtable-cas-response-lost')
        self.assertNotIn('envelope_limit_bytes', scenario['store'])
        scenario['initialization'] = {'expect': {'result': 'success'}}
        self.assertGreater(replay(scenario).checked, 1)

    def test_bigtable_envelope_limit_outside_the_allowed_range_is_configuration_error_envelope_limit(self):
        for limit in (8388609, 16):
            with self.subTest(limit=limit):
                scenario = case('bigtable/journal-write.json', 'bigtable-cas-response-lost')
                scenario['store']['envelope_limit_bytes'] = limit
                scenario['steps'], scenario['faults'] = [], []
                scenario['initialization'] = {'expect': {
                    'error': {'category': 'configuration', 'message': {'must_contain': [], 'must_not_contain': []}}}}
                self.assertEqual(replay(copy.deepcopy(scenario)).checked, 1)
                scenario['initialization'] = {'expect': {'result': 'success'}}
                with self.assertRaisesRegex(ValueError, '参照モデルと期待が不一致'):
                    replay(scenario)

    def test_bigtable_envelope_limit_at_the_boundaries_is_accepted_envelope_limit(self):
        for limit in (8388608, 17):
            with self.subTest(limit=limit):
                scenario = case('bigtable/journal-write.json', 'bigtable-cas-response-lost')
                scenario['store']['envelope_limit_bytes'] = limit
                scenario['steps'], scenario['faults'] = [], []
                scenario['initialization'] = {'expect': {'result': 'success'}}
                self.assertEqual(replay(scenario).checked, 1)

    def test_bigtable_over_limit_append_is_contract_violation_before_any_write_envelope_limit(self):
        scenario = materialize(case('bigtable/envelope-limit.json', 'bigtable-envelope-over-limit'))
        self.assertGreater(replay(copy.deepcopy(scenario)).checked, 0)
        rejected = next(s for s in scenario['steps']
                        if s['expect'].get('error', {}).get('category') == 'contract-violation')
        original = copy.deepcopy(rejected['expect'])
        rejected['expect'] = {'result': 'success'}
        with self.assertRaisesRegex(ValueError, '参照モデルと期待が不一致'):
            replay(scenario)
        rejected['expect'] = original
        rejected['expect']['error']['category'] = 'storage'
        rejected['expect']['error'].pop('rule')
        with self.assertRaisesRegex(ValueError, '参照モデルと期待が不一致'):
            replay(scenario)

    def test_bigtable_previous_event_write_failure_is_storage_error_phase(self):
        scenario = case('bigtable/journal-write.json', 'bigtable-previous-event-write-failure')
        self.assertEqual(self.faulted_step(scenario, 'journal-write-previous')['expect']['error']['category'], 'storage')
        self.assertGreater(replay(copy.deepcopy(scenario)).checked, 0)
        self.faulted_step(scenario, 'journal-write-previous')['expect'] = {'result': 'success'}
        with self.assertRaisesRegex(ValueError, '参照モデルと期待が不一致'):
            replay(scenario)

    def test_bigtable_previous_event_write_failure_does_not_advance_the_head_phase(self):
        scenario = case('bigtable/journal-write.json', 'bigtable-previous-event-write-failure')
        read = next(s for s in scenario['steps'] if s['op'] == 'getEventsByIdSinceSeqNr')
        self.assertEqual(read['expect']['events'], ['e1'])
        read['expect']['events'] = ['e1', 'e2']
        with self.assertRaisesRegex(ValueError, '参照モデルと期待が不一致'):
            replay(scenario)

    def test_bigtable_new_tail_write_failure_keeps_the_append_successful_phase(self):
        scenario = case('bigtable/journal-write.json', 'bigtable-new-tail-write-failure')
        self.assertEqual(self.faulted_step(scenario, 'journal-write-tail')['expect'], {'result': 'success'})
        self.assertGreater(replay(copy.deepcopy(scenario)).checked, 0)
        self.faulted_step(scenario, 'journal-write-tail')['expect'] = {
            'error': {'category': 'storage', 'message': {'must_contain': [], 'must_not_contain': []}}}
        with self.assertRaisesRegex(ValueError, '参照モデルと期待が不一致'):
            replay(scenario)

    def test_bigtable_new_tail_write_failure_loses_no_event_in_later_reads_phase(self):
        scenario = case('bigtable/journal-write.json', 'bigtable-new-tail-write-failure')
        reads = [s for s in scenario['steps'] if s['op'] == 'getEventsByIdSinceSeqNr']
        self.assertEqual(reads[-1]['expect']['events'], ['e1', 'e2', 'e3'])
        reads[-1]['expect']['events'] = ['e1', 'e3']
        with self.assertRaisesRegex(ValueError, '参照モデルと期待が不一致'):
            replay(scenario)

    # ---- Bigtable の封筒の符号化と復元 ----

    def test_envelope_encoding_matches_hand_computed_bytes_envelope(self):
        self.assertEqual(
            data.encode_bigtable_event('Order-9', 1, 0, '', b'').hex(),
            '0100074f726465722d39' + '0000000000000001' + '0000000000000000' + '00000000' + '00000000')
        self.assertEqual(
            data.encode_bigtable_event('注文-1', 2**53 - 1, -1, 'é', b'\xff').hex(),
            '01' + '0008' + 'e6b3a8e696872d31' + '001fffffffffffff' + 'ffffffffffffffff'
            + '00000002' + 'c3a9' + '00000001' + 'ff')
        self.assertEqual(data.encode_bigtable_event('A', 1, -2**63, '', b'').hex()[24:40], '8000000000000000')
        self.assertEqual(data.encode_bigtable_event('A', 1, 2**63 - 1, '', b'').hex()[24:40], '7fffffffffffffff')
        self.assertEqual(
            data.encode_bigtable_snapshot(1, 'm', b'\x01\x02').hex(),
            '01' + '0000000000000001' + '00000001' + '6d' + '00000002' + '0102')

    def test_envelope_decoding_rejects_malformed_bytes_envelope(self):
        valid = data.encode_bigtable_event('Order-9', 1, 0, '', b'')
        malformed = {
            'trailing-byte': valid + b'\x00',
            'length-mismatch': valid[:-4] + bytes.fromhex('00000005') + bytes(4),
            'unknown-version': b'\x02' + valid[1:],
            'truncated': valid[:-1],
        }
        for label, raw in malformed.items():
            with self.subTest(case=label):
                with self.assertRaises(data.EnvelopeFormatError):
                    data.decode_bigtable_envelope('event', raw)
        snapshot = data.encode_bigtable_snapshot(1, '', b'')
        with self.assertRaises(data.EnvelopeFormatError):
            data.decode_bigtable_envelope('snapshot', snapshot + b'\x00')


if __name__ == '__main__':
    unittest.main()
