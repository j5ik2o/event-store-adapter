"""仕様の状態機械が、もっともらしい誤期待も検出することを確かめる。"""

import copy
import unittest

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

    def test_post_send_commit_error_explicitly_skips_unknown_state(self):
        scenario = case('scenarios/core/retention-errors.json', 'core-storage-commit-failure')
        scenario['faults'][0]['injection'] = 'replace-response'
        report = replay(scenario)
        self.assertEqual(report.checked, 0)
        self.assertEqual(len(report.skipped), len(scenario['steps']) + 1)
        self.assertIn('確定状態が不明', report.skipped[0][1])

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


if __name__ == '__main__':
    unittest.main()
