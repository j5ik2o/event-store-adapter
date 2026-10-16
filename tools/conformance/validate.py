#!/usr/bin/env python3
"""JSON Schema、規則番号、参照、ID、網羅表、manifest を検査する。"""

import argparse
import copy
from collections import defaultdict
from pathlib import Path
import re
import sys

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from data import epoch_nanoseconds, fnv1a64, materialize, resolve_pointer
from manifest import DEFAULT_ROOT, read_json, verify
from reference_model import equal_json, replay

DEFAULT_SPEC_ROOT = Path(__file__).resolve().parents[2] / "docs" / "spec"
FORMATS = {"values", "scenarios", "layout", "coverage", "manifest"}
DY19_APIS = {"GetItem", "BatchGetItem", "Query", "TransactWriteItems", "BatchWriteItem", "UpdateItem"}
PHASES = {
    "persistEvent": {"serialize-event", "commit"},
    "persistEventAndSnapshot": {"serialize-event", "serialize-snapshot", "commit",
                                "retention-query", "retention-delete", "retention-mark"},
    "getLatestSnapshotById": {"read-snapshot", "deserialize-snapshot"},
    "getEventsByIdSinceSeqNr": {"read-events", "deserialize-event"},
    "initialize": {"configuration-read", "configuration-create"},
    "createStore": set(),
    "holdWriteLock": set(),
    "releaseWriteLock": set(),
    "mutateWrittenPayload": set(),
    "mutateReadPayload": set(),
}
STORE_OPERATIONS = {"createStore"}
LOCK_OPERATIONS = {"holdWriteLock", "releaseWriteLock"}
# 段階 5 の保存先。2つ目のストアの共有と、保存先に記録した設定の種まきを使える。
STAGE5_BACKENDS = {"sqlite", "spanner", "bigtable"}
# 論理的な設定の種まき（seed.configuration）の項目名。保存先のプロファイルの config の項目名と一致させる。
CONFIGURATION_FIELDS = {
    "sqlite": {"store_id", "layout_version", "keep_snapshot_count", "retention_mode", "change_feed_enabled"},
}
# 保存先に固有の規則番号。段階 5 の保存先の共有の場面は共通契約の番号だけを使う。
PROFILE_RULE_PREFIXES = ("MEM-", "DY-", "D-", "SQ-")
MUTATION_OPERATIONS = {"mutateWrittenPayload", "mutateReadPayload"}
READ_OPERATIONS = {"getLatestSnapshotById", "getEventsByIdSinceSeqNr"}


def check_value(case, where):
    """値表の期待値と入力の転記ミスを、保存先実装を使わずに検出する。"""
    inputs, expected = case["input"], case["expect"]
    violated = None
    if case["operation"] == "buildAid":
        aggregate = inputs["aggregate_id"]
        value = aggregate["type_name"] + "-" + aggregate["value"]
        if "-" in aggregate["type_name"]:
            violated = "T-11"
        elif len(value.encode("utf-8")) > 1024:
            violated = "T-12"
    elif case["operation"] == "validateOccurredAt":
        nanoseconds = epoch_nanoseconds(inputs["iso8601"])
        if str(nanoseconds) != inputs["epoch_nanoseconds"]:
            raise ValueError(f"{where}: ISO 8601 とエポックナノ秒が不一致")
        value = str(nanoseconds)
        if not -(2**63) <= nanoseconds <= 2**63 - 1:
            violated = "T-13"
        if case.get("representation", {}).get("time_precision") == "milliseconds" and nanoseconds % 1_000_000:
            raise ValueError(f"{where}: ミリ秒境界がミリ秒で表せない")
    elif case["operation"] == "fnv1a64":
        value = fnv1a64(inputs["utf8"])
    else:
        value = inputs["seq_nr"]
        if not 0 <= value <= 2**53 - 1:
            violated = "T-9"
        elif value == 0 and inputs["context"] == "event":
            violated = "W-6"
    if violated:
        error = expected.get("error", {})
        if error.get("category") != "contract-violation" or error.get("rule") != violated:
            raise ValueError(f"{where}: 境界の期待規則が不一致: {violated}")
    elif "error" in expected or not equal_json(expected.get("value"), value):
        raise ValueError(f"{where}: 値の期待が入力と不一致")


def specification_rules(spec_root):
    core = (spec_root / "core-contract.md").read_text(encoding="utf-8")
    dynamo = (spec_root / "storage" / "dynamodb.md").read_text(encoding="utf-8")
    memory = (spec_root / "storage" / "memory.md").read_text(encoding="utf-8")
    hash_spec = (spec_root / "storage" / "hash.md").read_text(encoding="utf-8")
    sqlite = (spec_root / "storage" / "sqlite.md").read_text(encoding="utf-8")
    texts = "\n".join([core, dynamo, memory, hash_spec, sqlite])
    # defined は 5 つの仕様の文書が定義の行で定める規則。判断番号 D-n・MEM-D・SQ-D と草案の規則は含めない。
    defined = set(re.findall(r"^- \*\*(?:必須|推奨|任意) ([A-Z]+-\d+)\*\*", texts, re.M))
    active = defined | set(re.findall(r"^\| (D-\d+) \|", dynamo, re.M))
    mentioned = set(re.findall(r"\b(?:K|T|H|W|R|E|S|SP|DY|D|F|MEM|SQ)-\d+\b", texts))
    return active, mentioned, defined


def check_single_aggregate_scope(case, where):
    """DY-19: 操作中の要求の API 名と aid を絞る観測が、全操作に付いていること。"""
    if case["backends"] != ["dynamodb"]:
        raise ValueError(f"{where}: DY-19 の観測は backends が dynamodb だけの場面に置く")
    if "DY-19" not in case["rules"]:
        raise ValueError(f"{where}: request_scope を使う場面の rules に DY-19 がない")
    if not case["steps"]:
        raise ValueError(f"{where}: DY-19 の場面は操作を持つ")
    for index, step in enumerate(case["steps"], 1):
        scope = step.get("observe", {}).get("request_scope")
        if scope is None:
            raise ValueError(f"{where}/{index}: DY-19 の場面の全操作に request_scope が必要")
        if set(scope["apis"]) != DY19_APIS:
            raise ValueError(f"{where}/{index}: DY-19 の request_scope.apis が 6 種類と一致しない")
    own = {step["arguments"]["aggregate_id"]["type_name"] + "-" + step["arguments"]["aggregate_id"]["value"]
           for step in case["steps"] if "aggregate_id" in step["arguments"]}
    own |= {case["fixtures"]["events"][step["arguments"]["event"]]["aggregate_id"]["type_name"] + "-"
            + case["fixtures"]["events"][step["arguments"]["event"]]["aggregate_id"]["value"]
            for step in case["steps"] if "event" in step["arguments"]}
    others = {item["values"]["aid"] for item in case.get("seed", {}).get("items", [])
              if item["values"]["aid"] != "__config__"} - own
    if not others:
        raise ValueError(f"{where}: DY-19 の場面は操作の集約と異なる集約の記録を seed に置く")


def written_aid(case, step):
    return aid_text(case["fixtures"]["events"][step["arguments"]["event"]]["aggregate_id"])


def aid_text(identifier):
    return identifier["type_name"] + "-" + identifier["value"]


def check_stores(case, where):
    """MEM-2: 2つ目のストアの生成と参照名、独立の場面が空振りの成功にならないこと。"""
    steps = case["steps"]
    uses = any(step["op"] in STORE_OPERATIONS or "store" in step for step in steps)
    if not uses:
        return
    backends = case["backends"]
    if backends == ["memory"]:
        if "MEM-2" not in case["rules"]:
            raise ValueError(f"{where}: 2つ目のストアを使う場面の rules に MEM-2 がない")
    elif set(backends) <= STAGE5_BACKENDS:
        specific = [rule for rule in case["rules"] if rule.startswith(PROFILE_RULE_PREFIXES)]
        if specific:
            raise ValueError(f"{where}: 段階 5 の保存先で2つ目のストアを使う場面の rules は共通契約の番号だけにする: {specific}")
    else:
        raise ValueError(f"{where}: 2つ目のストアを使う場面は backends が memory だけ、"
                         "または sqlite・spanner・bigtable のいずれかだけでなければならない")
    created = {"primary"}
    for index, step in enumerate(steps, 1):
        if "store" in step and step["store"] not in created:
            raise ValueError(f"{where}/{index}: 生成前のストアを参照している: {step['store']}")
        if step["op"] != "createStore":
            continue
        args = step["arguments"]
        if step["expect"] != {"result": "success"}:
            raise ValueError(f"{where}/{index}: ストアの生成は成功を期待する")
        if args["storage"] == "new" and backends != ["memory"]:
            raise ValueError(f"{where}/{index}: storage = new の createStore はメモリの場面だけで使える")
        if args["name"] in created:
            raise ValueError(f"{where}/{index}: ストア名が予約名 primary または既出の名前: {args['name']}")
        if args["storage"] == "shared" and args["shared_with"] not in created:
            raise ValueError(f"{where}/{index}: 共有元のストアが生成前: {args['shared_with']}")
        created.add(args["name"])
        if args["storage"] == "new":
            check_independent_store(case, index, where)


def check_write_lock(case, where):
    """SQ-7: 書き込みのロックを持ち続ける操作が、sqlite だけの場面で、取得と解放が対応して使われること。"""
    steps = case["steps"]
    if not any(step["op"] in LOCK_OPERATIONS for step in steps):
        return
    if case["backends"] != ["sqlite"]:
        raise ValueError(f"{where}: 書き込みのロックを持ち続ける操作は backends が sqlite だけの場面で使う")
    if "SQ-7" not in case["rules"]:
        raise ValueError(f"{where}: 書き込みのロックを持ち続ける場面の rules に SQ-7 がない")
    if "lock_wait_milliseconds" not in case["store"]:
        raise ValueError(f"{where}: 書き込みのロックを持ち続ける場面は store.lock_wait_milliseconds を指定する")
    held = False
    for index, step in enumerate(steps, 1):
        if step["op"] == "holdWriteLock":
            if held:
                raise ValueError(f"{where}/{index}: すでに持っているロックをもう一度持とうとしている")
            held = True
        elif step["op"] == "releaseWriteLock":
            if not held:
                raise ValueError(f"{where}/{index}: 持っていないロックを放そうとしている")
            held = False
    if held:
        raise ValueError(f"{where}: 書き込みのロックを放さないまま場面が終わる")


def check_seeded_configuration(case, where):
    """論理的な設定の種まきが、1つの保存先の項目名だけで書かれ、生成の結果を観測すること。"""
    configuration = case.get("seed", {}).get("configuration")
    if configuration is None:
        return
    backends = case["backends"]
    if len(backends) != 1 or backends[0] not in CONFIGURATION_FIELDS:
        raise ValueError(f"{where}: 設定の種まきは項目名の表がある1つの保存先の場面だけで使える")
    if set(configuration) != CONFIGURATION_FIELDS[backends[0]]:
        raise ValueError(f"{where}: 設定の種まきの項目名が {backends[0]} のプロファイルの config と一致しない")
    if "initialization" not in case:
        raise ValueError(f"{where}: 設定の種まきを使う場面は生成の結果（initialization）を観測する")


def check_independent_store(case, index, where):
    """独立の場面は、先に別のストアへ書き、新しいストアで同じ集約を読むこと。"""
    steps = case["steps"]
    name = steps[index - 1]["arguments"]["name"]
    written = {written_aid(case, step) for step in steps[:index - 1]
               if step["op"].startswith("persist") and step["expect"].get("result") == "success"}
    read = {aid_text(step["arguments"]["aggregate_id"]) for step in steps[index:]
            if step["op"] in READ_OPERATIONS and step.get("store") == name}
    if not written or not written & read:
        raise ValueError(f"{where}/{index}: 独立の場面は、生成より前に別のストアへ書き、"
                         f"新しいストア {name} で同じ集約を読む必要がある")


def check_payload_mutations(case, where):
    """MEM-6: 書き換えの位置が、書き込んだペイロードに実在し、値を実際に変えること。"""
    steps = case["steps"]
    events = case["fixtures"]["events"]
    for index, step in enumerate(steps, 1):
        if step["op"] not in MUTATION_OPERATIONS:
            continue
        if case["backends"] != ["memory"]:
            raise ValueError(f"{where}: ペイロードを書き換える場面は backends が memory だけでなければならない")
        if "MEM-6" not in case["rules"]:
            raise ValueError(f"{where}: ペイロードを書き換える場面の rules に MEM-6 がない")
        args = step["arguments"]
        if not 1 <= args["operation"] < index:
            raise ValueError(f"{where}/{index}: 書き換えの対象の操作番号が、それより前の操作ではない")
        target = steps[args["operation"] - 1]
        if step["op"] == "mutateWrittenPayload":
            if not target["op"].startswith("persist") or target["expect"].get("result") != "success":
                raise ValueError(f"{where}/{index}: 書き込み後の書き換えの対象が、成功した書き込みではない")
            name = target["arguments"]["event"]
        else:
            if target["op"] != "getEventsByIdSinceSeqNr" or args["event"] not in target["expect"].get("events", []):
                raise ValueError(f"{where}/{index}: 取得結果の書き換えの対象に、そのイベントを返す読み取りがない")
            name = args["event"]
        container, key = resolve_pointer(copy.deepcopy(events[name]["payload"]), args["pointer"])
        if equal_json(container[key], args["value"]):
            raise ValueError(f"{where}/{index}: 書き換え後の値が現在の値と同じで、空振りになる: {args['pointer']}")


def rule_sort(rule):
    prefix, number = rule.rsplit("-", 1)
    return prefix, int(number)


def assert_rules(rules, active, where):
    for rule in rules:
        if rule not in active:
            raise ValueError(f"{where}: 規則が仕様に定義されていない（または削除済み）: {rule}")


def case_aids(case):
    aggregates = [event["aggregate_id"] for event in case.get("fixtures", {}).get("events", {}).values()]
    aggregates += [step["arguments"]["aggregate_id"] for step in case.get("steps", [])
                   if "aggregate_id" in step["arguments"]]
    if "aggregate_id" in case.get("input", {}):
        aggregates.append(case["input"]["aggregate_id"])
    result = {identifier["type_name"] + "-" + identifier["value"] for identifier in aggregates}
    result.update(item["values"]["aid"] for item in case.get("seed", {}).get("items", [])
                  if item["values"]["aid"] != "__config__")
    return result


def check_message(case, error, where):
    message = error.get("message", {})
    required = message.get("must_contain", [])
    rule = error.get("rule")
    if rule and rule.startswith("D-"):
        raise ValueError(f"{where}: 判断番号は契約違反の必須規則番号ではない")
    aids = case_aids(case)
    for token in required:
        if not token:
            raise ValueError(f"{where}: must_containに空文字列は指定できない")
        if token in aids or token == rule:
            continue
        if any(token in identifier for identifier in aids) or (rule and token in rule):
            raise ValueError(f"{where}: must_containがaidまたは規則番号の部分文字列: {token!r}")
    if rule and error["category"] == "contract-violation":
        field = {"validateOccurredAt": "event_seq_nr", "validateSeqNr": "seq_nr"}.get(case.get("operation"))
        if field and str(case["input"][field]) not in required:
            raise ValueError(f"{where}: 値表に関係する番号のメッセージ期待がない")
    # 書き込みの番号は操作から決める。ヘッド番号は必須にしない。
    expectations = [(s["expect"].get("error"), s["arguments"]) for s in case.get("steps", [])]
    for expected, args in expectations:
        if expected is not error or "event" not in args:
            continue
        event = case["fixtures"]["events"][args["event"]]
        seq = str(event["seq_nr"])
        if error["category"] == "optimistic-lock":
            identifier = event["aggregate_id"]
            identifier = identifier["type_name"] + "-" + identifier["value"]
            if identifier not in required or seq not in required:
                raise ValueError(f"{where}: 楽観ロックにaidと追記番号のメッセージ期待がない")
        elif rule and error["category"] == "contract-violation" and seq not in required:
            raise ValueError(f"{where}: 契約違反に追記番号のメッセージ期待がない")


def check_fault(case, fault, where):
    details, kind = fault["details"], fault["kind"]
    allowed = {
        "serialization-error": {"message"},
        "storage-error": {"message", "scope"},
        "sdk-error": {"code", "message", "cancellation_reasons", "install_items"},
        "sdk-response": {"responses", "unprocessed_keys", "history_pages",
                         "omit_just_written_history", "unprocessed_first_n"},
        "read-interleave": {"after", "then", "interleaved_operation"},
    }
    if set(details) - allowed[kind]:
        raise ValueError(f"{where}: 障害の種類とdetailsが不一致")
    if kind == "read-interleave" and set(details) != allowed[kind]:
        raise ValueError(f"{where}: BatchGetItem応答の組み立て指定が不足")
    if kind == "sdk-error" and "code" not in details:
        raise ValueError(f"{where}: SDK失敗のcodeがない")
    if "history_pages" in details and fault["phase"] != "retention-query":
        raise ValueError(f"{where}: 履歴ページは保持読み取りにだけ指定できる")
    if "omit_just_written_history" in details and "history_pages" not in details:
        raise ValueError(f"{where}: omit_just_written_historyにhistory_pagesがない")
    reasons = details.get("cancellation_reasons")
    if details.get("code") == "TransactionCanceledException":
        if fault["phase"] not in {"commit", "configuration-create"} or not reasons:
            raise ValueError(f"{where}: トランザクション取消の対象項目がない")
        if fault["injection"] != "replace-request":
            raise ValueError(f"{where}: 取り消された要求を確定してはならない")
        if fault["operation"] == 0:
            targets = ["configuration:journal", "configuration:snapshot", "configuration:head"]
        else:
            step = case["steps"][fault["operation"] - 1]
            targets = ["journal", "head"]
            if step["op"] == "persistEventAndSnapshot":
                targets.append("current-snapshot")
                if case["store"]["retention_count"] is not None:
                    targets.append("history-snapshot")
        if [r["target"] for r in reasons] != targets:
            raise ValueError(f"{where}: CancellationReasonsは要求の各項目に1要素（非該当はNone）必要")
        for reason in reasons:
            needs_old_head = reason["target"] == "head" and reason["code"] == "ConditionalCheckFailed"
            if needs_old_head != ("old_head_seq_nr" in reason):
                raise ValueError(f"{where}: 旧ヘッドの指定と取消理由が不一致")
    elif reasons:
        raise ValueError(f"{where}: CancellationReasonsはTransactionCanceledExceptionだけに指定できる")


def check_case(case, data_format, where, active):
    assert_rules(case["rules"], active, where)
    expectations = [case["expect"]] if data_format == "values" else []
    if data_format == "scenarios":
        fixtures = case["fixtures"]
        events, snapshots = fixtures["events"], fixtures["snapshots"]
        for event in events.values():
            epoch_nanoseconds(event["occurred_at"])
        if "initialization" in case:
            if "request_scope" in case["initialization"].get("observe", {}):
                raise ValueError(f"{where}: 生成には request_scope を置けない（DY-19 の対象外）")
            expectations.append(case["initialization"]["expect"])
            if "error" in case["initialization"]["expect"] and case["steps"]:
                raise ValueError(f"{where}: 生成失敗後の操作は指定できない")
        for index, step in enumerate(case["steps"], 1):
            args = step["arguments"]
            for key, pool in [("event", events), ("snapshot", snapshots)]:
                if key in args and args[key] not in pool:
                    raise ValueError(f"{where}/{index}: 未定義の {key}: {args[key]}")
            expected = step["expect"]
            expectations.append(expected)
            for event in expected.get("events", []):
                if event not in events:
                    raise ValueError(f"{where}/{index}: 未定義の期待イベント: {event}")
            snapshot = expected.get("snapshot")
            if snapshot is not None and snapshot not in snapshots:
                raise ValueError(f"{where}/{index}: 未定義の期待スナップショット: {snapshot}")
            result = expected.get("result")
            allowed = {"persistEvent": {"success"}, "persistEventAndSnapshot": {"success"},
                       "getLatestSnapshotById": {"none", "snapshot"},
                       "getEventsByIdSinceSeqNr": {"events"},
                       "createStore": {"success"}, "mutateWrittenPayload": {"success"},
                       "holdWriteLock": {"success"}, "releaseWriteLock": {"success"},
                       "mutateReadPayload": {"success"}}
            if result is not None and result not in allowed[step["op"]]:
                raise ValueError(f"{where}/{index}: 操作と返り値の種類が一致しない")
        check_stores(case, where)
        check_write_lock(case, where)
        check_seeded_configuration(case, where)
        check_payload_mutations(case, where)
        for fault in case.get("faults", []):
            operation = fault["operation"]
            if operation == 0:
                if "initialization" not in case:
                    raise ValueError(f"{where}: 初期化の障害に初期化期待値がない")
            elif type(operation) is not int or not 1 <= operation <= len(case["steps"]):
                raise ValueError(f"{where}: 障害の操作番号が範囲外: {operation}")
            op = "initialize" if operation == 0 else case["steps"][operation - 1]["op"]
            if fault["phase"] not in PHASES[op]:
                raise ValueError(f"{where}: 障害の段階が対象操作にない: {fault['phase']}")
            check_fault(case, fault, where)
            interleaved = fault["details"].get("interleaved_operation")
            if interleaved:
                if interleaved.get("op") not in {"persistEvent", "persistEventAndSnapshot"}:
                    raise ValueError(f"{where}: 差し込み操作が書き込みではない")
                arguments = interleaved["arguments"]
                if arguments.get("event") not in events:
                    raise ValueError(f"{where}: 差し込みイベントが未定義")
                if interleaved["op"] == "persistEventAndSnapshot" and arguments.get("snapshot") not in snapshots:
                    raise ValueError(f"{where}: 差し込みスナップショットが未定義")
        if case.get("requires") == ["ttl"] and case["store"]["retention_mode"] != "ttl":
            raise ValueError(f"{where}: TTL 能力条件と保持方式が不一致")
        if "DY-19" in case["rules"] or any("request_scope" in step.get("observe", {}) for step in case["steps"]):
            check_single_aggregate_scope(case, where)
        # 期限切れ方式と変更フィードを提供しない保存先（メモリ: MEM-3・MEM-12、SQLite: SQ-11・SQ-20）
        if case["backends"] in (["memory"], ["sqlite"]) and (case["store"]["retention_mode"] == "ttl"
                                                             or case["store"].get("change_feed")):
            category = case.get("initialization", {}).get("expect", {}).get("error", {}).get("category")
            if category != "configuration":
                raise ValueError(f"{where}: {case['backends'][0]}が提供しない設定を求める場面は、生成の configuration エラーを期待する")
        if case["store"].get("change_feed") and case["backends"] not in (["memory"], ["sqlite"]):
            raise ValueError(f"{where}: change_feed を求める場面は backends が memory だけ、または sqlite だけでなければならない")
        if "lock_wait_milliseconds" in case["store"] and case["backends"] != ["sqlite"]:
            raise ValueError(f"{where}: lock_wait_milliseconds は backends が sqlite だけの場面に置く")
        for backend in ("memory", "sqlite"):
            if (case["store"]["retention_mode"] == "ttl" and backend in case["backends"]
                    and case["backends"] != [backend]):
                raise ValueError(f"{where}: {backend} を含む ttl の要求は backends が {backend} だけでなければならない")
    elif data_format == "values":
        required_input = {"buildAid": "aggregate_id", "validateOccurredAt": "iso8601",
                          "validateSeqNr": "seq_nr", "fnv1a64": "utf8"}[case["operation"]]
        if required_input not in case["input"]:
            raise ValueError(f"{where}: 値操作と入力の種類が一致しない")
        check_value(case, where)
    for expected in expectations:
        error = expected.get("error")
        if error:
            check_message(case, error, where)
        if error and "rule" in error:
            assert_rules([error["rule"]], active, where)
            if error["rule"] not in case["rules"]:
                raise ValueError(f"{where}: エラー規則が対象規則にない: {error['rule']}")
            if error["rule"] not in error["message"]["must_contain"]:
                raise ValueError(f"{where}: 契約違反のメッセージに規則番号の期待がない")
        if (error and error["category"] == "contract-violation" and "rule" not in error
                and "D-7" not in case["rules"]):
            raise ValueError(f"{where}: 契約違反に規則番号がない")


def coverage_text(documents, coverage, defined):
    rows = defaultdict(list)
    for relative, document in documents.items():
        if document["format"] in {"values", "scenarios", "layout"}:
            for case in document["cases"]:
                for rule in case["rules"]:
                    rows[rule].append(f"[{case['id']}]({relative})")
    exclusions = {item["rule"]: item["reason"] for item in coverage["exclusions"]}
    lines = ["# 規則の網羅表", "", "`tools/conformance/validate.py --update-coverage` がデータから生成する表である。",
             "場面に規則を列挙したことは実装の適合を意味しない。実行器が規則ごとの結果を報告する。", "",
             "| 規則 | ケース | 対象外の理由 |", "|:--|:--|:--|"]
    for rule in sorted(set(rows) | set(coverage["required_rules"]) | defined | set(exclusions), key=rule_sort):
        lines.append(f"| {rule} | {'、'.join(sorted(rows[rule])) or '—'} | {exclusions.get(rule, '—')} |")
    lines += ["", "## 対象を限定した理由", ""]
    for note in coverage["notes"]:
        lines += [f"- **{note['topic']}**: {note['reason']}"]
    return "\n".join(lines) + "\n"


def validate(root, spec_root, update_coverage=False, check_manifest=True):
    schemas = {}
    registry = Registry()
    for path in sorted((root / "schema").glob("*.json")):
        schema = read_json(path)
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            raise ValueError(f"{path}: Schema が draft 2020-12 ではない")
        Draft202012Validator.check_schema(schema)
        schemas[path.name.removesuffix(".schema.json")] = schema
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    if set(schemas) != FORMATS | {"common"}:
        raise ValueError("schema のファイル集合が不正")
    active, mentioned, defined = specification_rules(spec_root)
    documents, identifiers = {}, {}
    model_checked, model_skipped = 0, []
    for path in sorted(root.rglob("*.json")):
        if path.parent == root / "schema":
            continue
        document = read_json(path)
        data_format = document.get("format") if isinstance(document, dict) else None
        if data_format not in FORMATS:
            raise ValueError(f"{path}: 未定義のデータ形式: {data_format}")
        validator = Draft202012Validator(schemas[data_format], registry=registry)
        errors = sorted(validator.iter_errors(document), key=lambda error: str(error.json_path))
        if errors:
            raise ValueError(f"{path}: Schema 不一致: {errors[0].json_path}: {errors[0].message}")
        relative = path.relative_to(root).as_posix()
        documents[relative] = document
        for case in document.get("cases", []):
            identifier = case["id"]
            if identifier in identifiers:
                raise ValueError(f"ID 重複: {identifier}: {identifiers[identifier]} と {relative}")
            identifiers[identifier] = relative
            expanded = materialize(case)
            check_case(expanded, data_format, f"{relative}:{identifier}", active)
            if data_format == "scenarios":
                report = replay(expanded)
                model_checked += report.checked
                model_skipped += report.skipped
    coverage = documents.get("coverage.json")
    if coverage is None:
        raise ValueError("coverage.json がない")
    covered = {rule for document in documents.values() for case in document.get("cases", [])
               for rule in case["rules"]}
    exclusions = {item["rule"] for item in coverage["exclusions"]}
    if len(exclusions) != len(coverage["exclusions"]):
        raise ValueError("対象外の規則が重複")
    for item in coverage["exclusions"]:
        if item["rule"] not in mentioned:
            raise ValueError(f"対象外の規則が仕様にない: {item['rule']}")
        if (item["status"] == "deleted") != (item["rule"] not in active):
            raise ValueError(f"対象外の規則の削除状態が仕様と不一致: {item['rule']}")
    assert_rules(set(coverage["required_rules"]) - exclusions, active, "coverage.json")
    missing = (set(coverage["required_rules"]) | defined) - covered - exclusions
    if missing or covered & exclusions:
        raise ValueError(f"網羅の不一致: 未網羅={sorted(missing)}, 対象外なのにケースあり={sorted(covered & exclusions)}")
    text = coverage_text(documents, coverage, defined)
    coverage_path = root / "COVERAGE.md"
    if update_coverage:
        coverage_path.write_text(text, encoding="utf-8")
    elif not coverage_path.is_file() or coverage_path.read_text(encoding="utf-8") != text:
        raise ValueError("COVERAGE.md がデータと不一致。--update-coverage で生成すること")
    if check_manifest:
        verify(root)
    counts = {kind: sum(len(doc.get("cases", [])) for doc in documents.values() if doc["format"] == kind)
              for kind in ["values", "scenarios", "layout"]}
    return len(schemas), len(documents), counts, len(covered), len(exclusions), model_checked, model_skipped


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--spec-root", type=Path, default=DEFAULT_SPEC_ROOT,
                        help="core-contract.md・storage/dynamodb.md・storage/memory.md・storage/hash.md・storage/sqlite.md があるディレクトリ")
    parser.add_argument("--update-coverage", action="store_true",
                        help="網羅表を再生成する（その後 manifest rebuild が必要）")
    args = parser.parse_args()
    try:
        schemas, documents, counts, covered, excluded, model_checked, model_skipped = validate(
            args.root, args.spec_root, args.update_coverage, not args.update_coverage)
        print(f"schema: OK ({schemas} schemas, {documents} data files)")
        print(f"ids/references: OK ({sum(counts.values())} unique cases; {counts})")
        print(f"rules/coverage: OK ({covered} covered rules, {excluded} exclusions)")
        external = "SDK要求・物理属性・メッセージの実装検査は実行器が担当"
        skipped_operations = sum(reason != external for _, reason in model_skipped)
        print(f"reference model: OK ({model_checked} operations, {skipped_operations} skipped operations; "
              f"external checks delegated in {len(model_skipped) - skipped_operations} scenarios)")
        for where, reason in model_skipped:
            if reason != "SDK要求・物理属性・メッセージの実装検査は実行器が担当":
                print(f"model skip: {where}: {reason}")
        print("coverage: updated" if args.update_coverage else "manifest: OK")
    except Exception as error:
        print(f"validation: FAILED: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
