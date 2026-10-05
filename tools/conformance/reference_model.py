"""共通契約の状態機械。実装やSDK呼び出しの検査を代替しない。"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json

from data import epoch_nanoseconds


@dataclass
class Aggregate:
    head: int | None = None
    journal: dict = field(default_factory=dict)
    snapshot: dict | None = None
    history: dict = field(default_factory=dict)


@dataclass
class ReplayReport:
    checked: int = 0
    skipped: list = field(default_factory=list)


def aid(identifier):
    return identifier['type_name'] + '-' + identifier['value']


def envelope(value):
    return dict(value, manifest=value.get('manifest', ''))


def error(category, rule=None):
    result = {'error': {'category': category}}
    if rule:
        result['error']['rule'] = rule
    return result


def equal_json(left, right):
    """JSONの真偽値と数値を区別し、数値の表記差とオブジェクト順を無視する。"""
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(equal_json(left[k], right[k]) for k in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(equal_json(a, b) for a, b in zip(left, right))
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    return type(left) is type(right) and left == right


class Model:
    def __init__(self, case):
        self.case = case
        self.store = case['store']
        self.events = case['fixtures']['events']
        self.snapshots = case['fixtures']['snapshots']
        self.aggregates = {}
        self.clock = case.get('clock', {}).get('epoch_seconds')
        self.notifications = []
        self.targets = []
        self.seed(case.get('seed', {}).get('items', []))

    def state(self, identifier):
        return self.aggregates.setdefault(identifier, Aggregate())

    def seed(self, items):
        for item in items:
            values = item['values']
            identifier = values['aid']
            if identifier == '__config__':
                continue
            state = self.state(identifier)
            seq = int(values['seq_nr'])
            if item['table'] == 'head':
                state.head = seq
            elif item['table'] == 'journal':
                seconds, nanoseconds = divmod(int(values['occurred_at']), 10**9)
                time = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds)
                type_name, value = identifier.split('-', 1)
                state.journal[seq] = {'aggregate_id': {'type_name': type_name, 'value': value},
                                      'seq_nr': seq, 'manifest': values['manifest'],
                                      'occurred_at': time.strftime('%Y-%m-%dT%H:%M:%S') + f'.{nanoseconds:09d}Z',
                                      'payload': item['binary_json']['payload']}
            elif int(values['skey']) == 0:
                state.snapshot = {'seq_nr': seq, 'manifest': values['manifest'],
                                  'aggregate': item['binary_json']['payload']}
            else:
                state.history[seq] = int(values['ttl']) if 'ttl' in values else None

    def initialize(self):
        if self.store['retention_count'] == 0:
            return error('configuration')
        faults = [f for f in self.case.get('faults', []) if f['operation'] == 0]
        for fault in faults:
            if fault['kind'] == 'sdk-error':
                if fault['phase'] == 'configuration-create' and fault['details'].get('install_items'):
                    configs = fault['details']['install_items']
                    return self.config_result(configs)
                return error('storage')
            if fault['kind'] == 'sdk-response' and fault['details'].get('unprocessed_keys'):
                if fault['repeat']['mode'] == 'until-operation-finishes' or ('retry_limit' in self.store and fault['repeat']['count'] > self.store['retry_limit']):
                    return error('storage')
        return self.config_result(self.case.get('seed', {}).get('items', []))

    @staticmethod
    def config_result(items):
        configs = [i['values'] for i in items if i['values']['aid'] == '__config__']
        if configs and (len(configs) != 3 or len({c['store_id'] for c in configs}) != 1
                        or any(c['layout_version'] != '1' for c in configs)):
            return error('configuration')
        return {'result': 'success'}

    @staticmethod
    def fault_error(fault, event=None):
        if fault['kind'] == 'serialization-error':
            return error('serialization')
        if fault['kind'] == 'storage-error':
            return error('storage')
        if fault['kind'] != 'sdk-error':
            return None
        reasons = fault['details'].get('cancellation_reasons', [])
        for reason in reasons:
            if reason['code'] == 'TransactionConflict':
                return error('optimistic-lock')
            if reason['code'] == 'ConditionalCheckFailed':
                if reason['target'] == 'journal' or event['seq_nr'] == 1:
                    return error('optimistic-lock')
                if reason['target'] == 'head':
                    old = reason['old_head_seq_nr'] or 0
                    return error('optimistic-lock') if event['seq_nr'] <= old else error('contract-violation', 'W-8')
        return error('storage')

    def validate_write(self, event, snapshot):
        aggregate = event['aggregate_id']
        if '-' in aggregate['type_name']:
            return error('contract-violation', 'T-11')
        if len(aid(aggregate).encode('utf-8')) > 1024:
            return error('contract-violation', 'T-12')
        seq = event['seq_nr']
        if not 0 <= seq <= 2**53 - 1:
            return error('contract-violation', 'T-9')
        if seq == 0:
            return error('contract-violation', 'W-6')
        if not -(2**63) <= epoch_nanoseconds(event['occurred_at']) <= 2**63 - 1:
            return error('contract-violation', 'T-13')
        if snapshot is not None and snapshot['seq_nr'] != seq:
            return error('contract-violation', 'W-9')
        return None

    def oversize(self, event, snapshot):
        """既存ケースは属性値だけで400KiB超となる。厳密な項目境界はモデル対象外。"""
        def length(value):
            return len(value.encode('utf-8'))
        def binary(value):
            return len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
        identifier = length(aid(event['aggregate_id']))
        head = identifier + length(event['aggregate_id']['type_name']) + length(event.get('manifest', '')) + binary(event['payload'])
        snap = 0 if snapshot is None else identifier + length(snapshot.get('manifest', '')) + binary(snapshot['aggregate'])
        return max(head, snap) > 409600

    def write(self, args, faults):
        event = self.events[args['event']]
        snapshot = self.snapshots[args['snapshot']] if 'snapshot' in args else None
        failure = self.validate_write(event, snapshot)
        if failure:
            return failure
        for fault in faults:
            if fault['phase'] in {'serialize-event', 'serialize-snapshot'}:
                failure = self.fault_error(fault, event)
                if failure:
                    return failure
        if self.case['backends'] == ['dynamodb'] and self.oversize(event, snapshot):
            return error('contract-violation')
        for fault in faults:
            if fault['phase'] == 'commit':
                failure = self.fault_error(fault, event)
                if failure:
                    return failure
        state = self.state(aid(event['aggregate_id']))
        seq, head = event['seq_nr'], state.head
        if (seq == 1 and head is not None) or seq in state.journal or (head is not None and seq <= head):
            return error('optimistic-lock')
        if seq != (head or 0) + 1:
            return error('contract-violation', 'W-8')
        # 原子的に確定し、保持はその後に行う。
        state.head = seq
        state.journal[seq] = envelope(event)
        if snapshot is not None:
            state.snapshot = envelope(snapshot)
            if self.store['retention_count'] is not None:
                state.history[seq] = None
                self.retain(state, seq, faults)
        return {'result': 'success'}

    def retain(self, state, written_seq, faults):
        relevant = [f for f in faults if f['phase'].startswith('retention-')]
        for fault in relevant:
            if fault['phase'] == 'retention-query' and self.fault_error(fault):
                self.notifications = ['retention-failure']
                return
        candidates = {seq for seq, ttl in state.history.items() if ttl is None}
        for fault in relevant:
            if 'history_pages' in fault['details']:
                candidates = {seq for page in fault['details']['history_pages'] for seq in page}
                if not candidates <= state.history.keys():
                    raise ValueError('参照モデル: 履歴応答に未保存の番号がある')
                if fault['details'].get('omit_just_written_history', False) and written_seq in candidates:
                    raise ValueError('参照モデル: omit_just_written_historyと履歴ページが不一致')
        candidates.add(written_seq)
        self.targets = sorted(candidates, reverse=True)[self.store['retention_count']:]
        for fault in relevant:
            if fault['phase'] != 'retention-query' and self.fault_error(fault):
                self.notifications = ['retention-failure']
                return
        for seq in self.targets:
            if self.store['retention_mode'] == 'delete':
                del state.history[seq]
            elif state.history[seq] is None:
                if self.clock is None:
                    raise ValueError('参照モデル: TTLの時計が未指定')
                state.history[seq] = self.clock + self.store['ttl_grace_seconds']

    def execute(self, step, faults):
        self.notifications, self.targets = [], []
        self.clock = step.get('clock_epoch_seconds', self.clock)
        if step['op'].startswith('persist'):
            return self.write(step['arguments'], faults)
        state = self.state(aid(step['arguments']['aggregate_id']))
        old_head = state.head
        for fault in faults:
            if fault['kind'] == 'read-interleave':
                interleaved = fault['details']['interleaved_operation']
                result = self.write(interleaved['arguments'], [])
                if result != {'result': 'success'}:
                    raise ValueError('参照モデル: 差し込み追記が成立しない')
            failure = self.fault_error(fault)
            if failure:
                return failure
        if step['op'] == 'getLatestSnapshotById':
            head = old_head if any(f['kind'] == 'read-interleave' for f in faults) else state.head
            return {'result': 'none'} if head is None else {'result': 'snapshot', 'head_seq_nr': head, 'snapshot': state.snapshot}
        start = step['arguments']['seq_nr']
        return {'result': 'events', 'events': [event for seq, event in sorted(state.journal.items()) if seq >= start]}

    def expected(self, expectation):
        if 'error' in expectation:
            result = error(expectation['error']['category'], expectation['error'].get('rule'))
        else:
            result = dict(expectation)
            if result.get('result') == 'events':
                result['events'] = [envelope(self.events[name]) for name in result['events']]
            if result.get('result') == 'snapshot' and result['snapshot'] is not None:
                result['snapshot'] = envelope(self.snapshots[result['snapshot']])
        return result

    def compare(self, actual, expected, where):
        expected = self.expected(expected)
        # 規則番号を期待しない分類だけのケースでは、モデルの番号も比較しない。
        if 'error' in expected and 'rule' not in expected['error']:
            actual = error(actual['error']['category']) if 'error' in actual else actual
        if not equal_json(actual, expected):
            # 大きいpayloadは診断文へ展開しない。
            label = lambda value: value.get('error', value.get('result'))
            raise ValueError(f'{where}: 参照モデルと期待が不一致: actual={label(actual)!r}, expected={label(expected)!r}')

    def observe(self, step, where):
        observation = step.get('observe', {})
        if 'notifications' in observation and observation['notifications'] != self.notifications:
            raise ValueError(f'{where}: 参照モデルの保持失敗通知と不一致')
        if 'history' in observation:
            args = step['arguments']
            identifier = self.events[args['event']]['aggregate_id'] if 'event' in args else args['aggregate_id']
            history = self.state(aid(identifier)).history
            expected = observation['history']
            active = {seq for seq, ttl in history.items() if ttl is None}
            marked = {seq: ttl for seq, ttl in history.items() if ttl is not None}
            if (active != set(expected['active']) or marked != {x['seq_nr']: x['ttl'] for x in expected['marked']}
                    or set(expected['absent']) & history.keys()):
                raise ValueError(f'{where}: 参照モデルの履歴・TTL期限と不一致')
        for request in observation.get('requests', []):
            constraints = request['constraints']
            if request['phase'] == 'retention-mark':
                if 'expires' in constraints and constraints['expires'] != self.clock + self.store['ttl_grace_seconds']:
                    raise ValueError(f'{where}: 参照モデルのTTL要求期限と不一致')
                if 'target_seq_nrs' in constraints and set(constraints['target_seq_nrs']) != set(self.targets):
                    raise ValueError(f'{where}: 参照モデルのTTL対象番号と不一致')


def replay(case):
    model, report = Model(case), ReplayReport()
    if 'initialization' in case:
        model.compare(model.initialize(), case['initialization']['expect'], case['id'] + '/initialize')
        report.checked += 1
    unknown_state = None
    for index, step in enumerate(case['steps'], 1):
        where = f"{case['id']}/{index}"
        faults = [f for f in case.get('faults', []) if f['operation'] == index]
        # 送信後の書き込み失敗は確定状態が仕様から決まらないため、以後も推測しない。
        for fault in faults:
            if fault['injection'] == 'replace-response' and fault['kind'] in {'sdk-error', 'storage-error'}:
                if fault['phase'] == 'commit':
                    unknown_state = '送信後の書き込み応答の失敗では確定状態が不明'
                elif fault['phase'] in {'retention-delete', 'retention-mark'}:
                    unknown_state = '送信後の保持応答の失敗では履歴の確定状態が不明'
        if unknown_state:
            report.skipped.append((where, unknown_state))
            continue
        model.compare(model.execute(step, faults), step['expect'], where)
        model.observe(step, where)
        report.checked += 1
    # 項目の物理型・SDK要求・メッセージは状態機械から観測できない。
    report.skipped.append((case['id'], 'SDK要求・物理属性・メッセージの実装検査は実行器が担当'))
    return report
