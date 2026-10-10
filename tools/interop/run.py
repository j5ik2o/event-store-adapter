#!/usr/bin/env python3
"""固定 Local の所有3表で6言語の公開操作を測り、原票と終了値を保存する。"""
import argparse
import base64
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
import traceback
import uuid

import boto3
from botocore.config import Config
from build import source_fingerprints, verify_artifacts
from query_observer import QueryObserver, item_bytes

HERE = Path(__file__).resolve().parent
PINS = json.loads((HERE / "snapshots.json").read_text())
LANGUAGES = list(PINS["sources"])
BASE_NS = 1760000000123000000


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=evidence) + "\n")


def evidence(value):
    if isinstance(value, bytes):
        return {"base64": base64.b64encode(value).decode(), "bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}
    if isinstance(value, datetime):
        return {"iso8601": value.isoformat()}
    raise TypeError(type(value).__name__)


def event(value, writer, number, nanos=None, padding=None):
    payload = {"writer": writer, "number": number, "message": "共通の実ペイロード🌱", "values": [True, 7, "保存"]}
    if padding is not None:
        payload["padding"] = padding
    return {"type_name": "Interop", "value": value, "seq_nr": number,
            "occurred_at_ns": str(nanos if nanos is not None else BASE_NS + number * 1000000),
            "manifest": "" if number == 1 else f"interop-event/{writer}/v1", "payload": payload}


def snapshot(writer, number):
    return {"seq_nr": number, "manifest": "interop-state/v1",
            "aggregate": {"writer": writer, "applied": number, "message": "実スナップショット🌱"}}


def expected_event(input, reader):
    precision = PINS["precision_ns"][reader]
    nanos = int(input["occurred_at_ns"])
    return {"aid": f"{input['type_name']}-{input['value']}", "seq_nr": input["seq_nr"],
            "occurred_at_ns": str((nanos // precision) * precision),
            "manifest": input["manifest"], "payload": input["payload"]}


class Driver:
    def __init__(self, language, definition, output, observer):
        self.language, self.output, self.observer = language, output, observer
        self.replies = queue.Queue()
        self.count = 0
        self.stderr = (output / f"{language}-stderr.log").open("w")
        environment = dict(os.environ, **definition["env"])
        self.process = subprocess.Popen(definition["argv"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=self.stderr, text=True, env=environment)

        def receive():
            for line in self.process.stdout:
                self.replies.put(line)
            self.replies.put(None)
        self.thread = threading.Thread(target=receive, daemon=True)
        self.thread.start()

    def call(self, request, scenario):
        self.count += 1
        context = {"language": self.language, "scenario": scenario, "call": self.count}
        self.observer.context = context
        row = dict(context, request=request)
        path = self.output / f"{self.language}-calls.jsonl"
        # 応答を待つ前に入力を残すので途中終了も追える。
        with path.open("a") as stream:
            stream.write(json.dumps(dict(row, phase="sent"), ensure_ascii=False) + "\n")
        self.process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
        self.process.stdin.flush()
        line = self.replies.get(timeout=60)
        if line is None:
            raise RuntimeError(f"{self.language} exited during {scenario}: {self.process.poll()}")
        reply = json.loads(line)
        with path.open("a") as stream:
            stream.write(json.dumps(dict(row, phase="received", response=reply), ensure_ascii=False) + "\n")
        return reply

    def close(self):
        self.process.stdin.close()
        terminated = False
        try:
            code = self.process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            terminated = True
            self.process.terminate()
            try:
                code = self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                code = self.process.wait(timeout=5)
        self.thread.join(timeout=5)
        self.process.stdout.close()
        self.stderr.close()
        return {"language": self.language, "exit": code, "terminated": terminated, "calls": self.count}


class Local:
    def __init__(self, output):
        self.output = output
        self.owner = uuid.uuid4().hex
        self.container = None
        self.sdk = None
        self.created_tables = []
        self.commands = []
        prefix = "eswa_interop_" + self.owner[:12]
        self.tables = {kind: f"{prefix}_{kind}" for kind in ("journal", "snapshot", "head")}

    def command(self, argv):
        result = subprocess.run(argv, capture_output=True, text=True)
        row = {"argv": argv, "exit": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
        self.commands.append(row)
        save(self.output / "resource-commands.json", self.commands)
        if result.returncode:
            raise RuntimeError(f"resource command failed: {row}")
        return result.stdout.strip()

    def start(self):
        cid = self.output / "container.id"
        name = "eswa-interop-" + self.owner[:12]
        try:
            self.container = self.command(["docker", "run", "-d", "--name", name, "--label", f"eswa.interop.owner={self.owner}",
                "--cidfile", str(cid), "-p", "127.0.0.1::8000", PINS["dynamodb_local"],
                "-jar", "DynamoDBLocal.jar", "-sharedDb", "-inMemory"])
        finally:
            if cid.exists():
                self.container = cid.read_text().strip()
            save(self.output / "ownership.json", {"owner": self.owner, "container": self.container, "tables": self.tables})
        address = self.command(["docker", "port", self.container, "8000/tcp"])
        if not address.startswith("127.0.0.1:") or "\n" in address:
            raise RuntimeError(f"unexpected Local port: {address}")
        self.endpoint = "http://" + address
        image = json.loads(self.command(["docker", "image", "inspect", PINS["dynamodb_local"]]))[0]
        save(self.output / "local-image.json", {"Id": image["Id"], "RepoDigests": image["RepoDigests"], "requested": PINS["dynamodb_local"]})
        self.sdk = boto3.client("dynamodb", endpoint_url=self.endpoint, region_name="us-east-1",
                                aws_access_key_id="local", aws_secret_access_key="local",
                                config=Config(connect_timeout=2, read_timeout=30, retries={"max_attempts": 2}))
        for attempt in range(30):
            try:
                self.sdk.list_tables()
                break
            except Exception:
                if attempt == 29:
                    raise
                time.sleep(0.5)
        for kind, table in self.tables.items():
            attributes = [{"AttributeName": "aid", "AttributeType": "S"}]
            keys = [{"AttributeName": "aid", "KeyType": "HASH"}]
            definition = {"TableName": table, "AttributeDefinitions": attributes,
                          "KeySchema": keys, "BillingMode": "PAY_PER_REQUEST"}
            if kind != "head":
                sort_key = "seq_nr" if kind == "journal" else "skey"
                attributes.append({"AttributeName": sort_key, "AttributeType": "N"})
                keys.append({"AttributeName": sort_key, "KeyType": "RANGE"})
            if kind == "snapshot":
                attributes.append({"AttributeName": "active_history_seq_nr", "AttributeType": "N"})
                definition["GlobalSecondaryIndexes"] = [{"IndexName": "history", "KeySchema": [keys[0],
                    {"AttributeName": "active_history_seq_nr", "KeyType": "RANGE"}], "Projection": {"ProjectionType": "KEYS_ONLY"}}]
            if kind == "head":
                definition["StreamSpecification"] = {"StreamEnabled": True, "StreamViewType": "NEW_IMAGE"}
            # 名前はこの実行が一度だけ作る。要求後の応答不明でも終了処理で同じ名前を照合する。
            self.created_tables.append(table)
            self.sdk_call("create_table", **definition)
            self.sdk.get_waiter("table_exists").wait(TableName=table, WaiterConfig={"Delay": 1, "MaxAttempts": 15})
            self.sdk_call("describe_table", TableName=table)

    def sdk_call(self, operation, **request):
        response = getattr(self.sdk, operation)(**request)
        with (self.output / "sdk.jsonl").open("a") as stream:
            stream.write(json.dumps({"operation": operation, "request": request, "response": response}, ensure_ascii=False, default=evidence) + "\n")
        return response

    def configurations(self):
        observed = {}
        for kind, table in self.tables.items():
            key = {"aid": {"S": "__config__"}}
            if kind != "head":
                key["seq_nr" if kind == "journal" else "skey"] = {"N": "0"}
            item = self.sdk_call("get_item", TableName=table, Key=key, ConsistentRead=True).get("Item")
            expected = {"aid": "S", "store_id": "S", "layout_version": "N"}
            if kind != "head":
                expected["seq_nr" if kind == "journal" else "skey"] = "N"
            attributes(item, expected)
            assert item["layout_version"] == {"N": "1"}
            assert item["store_id"]["S"]
            observed[kind] = item
        assert len({i["store_id"]["S"] for i in observed.values()}) == 1
        return observed

    def item(self, kind, aid, number=None):
        key = {"aid": {"S": aid}}
        if kind != "head":
            key["seq_nr" if kind == "journal" else "skey"] = {"N": str(number)}
        return self.sdk_call("get_item", TableName=self.tables[kind], Key=key, ConsistentRead=True)["Item"]

    def close(self):
        outcome = {"tables": [], "container": self.container, "errors": []}
        if self.sdk:
            for table in reversed(self.created_tables):
                try:
                    self.sdk_call("delete_table", TableName=table)
                    self.sdk.get_waiter("table_not_exists").wait(TableName=table, WaiterConfig={"Delay": 1, "MaxAttempts": 15})
                    outcome["tables"].append({"name": table, "deleted": True})
                except self.sdk.exceptions.ResourceNotFoundException:
                    outcome["tables"].append({"name": table, "absent": True})
                except Exception as error:
                    outcome["errors"].append(str(error))
            self.sdk.close()
        if self.container:
            try:
                inspected = json.loads(self.command(["docker", "inspect", self.container]))[0]
                if inspected["Config"]["Labels"].get("eswa.interop.owner") != self.owner:
                    raise RuntimeError("container owner mismatch")
                self.command(["docker", "rm", "-f", self.container])
                remaining = self.command(["docker", "ps", "-a", "--filter", f"id={self.container}", "--format", "{{.ID}}"])
                assert remaining == ""
                outcome["container_absent"] = True
            except Exception as error:
                outcome["errors"].append(str(error))
        save(self.output / "cleanup.json", outcome)
        return outcome


def attributes(item, expected):
    assert item is not None and set(item) == set(expected), (item, expected)
    assert {name: next(iter(value)) for name, value in item.items()} == expected


def physical(local, first, second, state):
    aid = "Interop-" + first["value"]
    journal_shape = {"aid": "S", "seq_nr": "N", "occurred_at": "N", "manifest": "S", "payload": "B"}
    journal = []
    for input in (first, second):
        item = local.item("journal", aid, input["seq_nr"])
        attributes(item, journal_shape)
        assert item["aid"] == {"S": aid} and item["seq_nr"] == {"N": str(input["seq_nr"])}
        assert item["occurred_at"] == {"N": input["occurred_at_ns"]} and item["manifest"] == {"S": input["manifest"]}
        assert json.loads(item["payload"]["B"]) == input["payload"]
        journal.append(item)
    current = local.item("snapshot", aid, 0)
    history = local.item("snapshot", aid, state["seq_nr"])
    shape = {"aid": "S", "skey": "N", "seq_nr": "N", "manifest": "S", "payload": "B", "last_updated_at": "N"}
    attributes(current, shape)
    attributes(history, dict(shape, active_history_seq_nr="N"))
    for item, skey in ((current, 0), (history, state["seq_nr"])):
        assert item["aid"] == {"S": aid} and item["skey"] == {"N": str(skey)}
        assert item["seq_nr"] == {"N": str(state["seq_nr"])} and item["manifest"] == {"S": state["manifest"]}
        assert item["last_updated_at"] == {"N": str(int(second["occurred_at_ns"]) // 1000000)}
        assert json.loads(item["payload"]["B"]) == state["aggregate"]
    assert history["active_history_seq_nr"] == {"N": str(state["seq_nr"])}
    assert history["payload"]["B"] == current["payload"]["B"]
    head = local.item("head", aid)
    attributes(head, {"aid": "S", "type_name": "S", "seq_nr": "N", "events": "L"})
    assert head["aid"] == {"S": aid} and head["type_name"] == {"S": "Interop"} and head["seq_nr"] == {"N": str(second["seq_nr"])}
    assert len(head["events"]["L"]) == 1
    head_event = head["events"]["L"][0]["M"]
    attributes(head_event, {"seq_nr": "N", "occurred_at": "N", "manifest": "S", "payload": "B"})
    assert head_event == {k: v for k, v in journal[-1].items() if k != "aid"}
    return {"aid": aid, "journal": journal, "snapshot_current": current, "snapshot_history": history, "head": head, "passed": True}


def main():
    if not __debug__:
        raise RuntimeError("run requires assertions; run without -O or PYTHONOPTIMIZE")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (args.build / "build-failure.json").exists():
        raise RuntimeError("build failed; rebuild successfully before running")
    inputs = json.loads((args.build / "buildinputs.json").read_text())
    if inputs["currentSnapshot"] != PINS or inputs["driver_sources"] != source_fingerprints():
        raise RuntimeError("build inputs are stale; rebuild before running")
    verify_artifacts(inputs)
    definition = json.loads((args.build / "drivers.json").read_text())
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    local = Local(output)
    drivers, observer = {}, None
    report = {"status": "running", "currentSnapshot": PINS, "matrix": [], "sequential": [],
              "precision": [], "optimistic_lock": [], "physical": [], "pagination": [], "configurations": []}
    save(output / "buildinputs.json", inputs)

    def checkpoint():
        save(output / "acceptance.json", report)

    def call(language, request, scenario):
        reply = drivers[language].call(request, scenario)
        assert reply["status"] == "ok", (language, scenario, reply)
        return reply["result"]

    def read(language, inputs, state, scenario):
        identifier = {"type_name": inputs[0]["type_name"], "value": inputs[0]["value"]}
        observed = call(language, {"op": "getEvents", "id": identifier, "seq_nr": 1}, scenario)
        expected = [expected_event(input, language) for input in inputs]
        latest = call(language, {"op": "getLatestSnapshot", "id": identifier}, scenario)
        expected_latest = {"head_seq_nr": inputs[-1]["seq_nr"], "snapshot": state}
        row = {"reader": language, "expected_events": expected, "observed_events": observed,
               "expected_latest": expected_latest, "observed_latest": latest,
               "precision_ns": PINS["precision_ns"][language], "passed": observed == expected and latest == expected_latest}
        assert row["passed"], row
        return row

    try:
        local.start()
        observer = QueryObserver(local.endpoint, local.tables["journal"], output / "queries.jsonl")
        config = dict(local.tables, endpoint=observer.endpoint, history_index="history", retention_count=16)
        save(output / "configuration-input.json", config)
        baseline = None
        for language in LANGUAGES:
            drivers[language] = Driver(language, definition[language], output, observer)
            call(language, {"op": "create", "config": config}, "initial-create")
            actual = local.configurations()
            baseline = actual if baseline is None else baseline
            assert actual == baseline
            report["configurations"].append({"language": language, "stage": "create", "actual": actual, "unchanged": True})
        fixtures = {}
        for language in LANGUAGES:
            inputs = [event(language, language, number) for number in (1, 2)]
            state = snapshot(language, 2)
            call(language, {"op": "persistEvent", "event": inputs[0]}, "writer")
            call(language, {"op": "persistEventAndSnapshot", "event": inputs[1], "snapshot": state}, "writer")
            fixtures[language] = (inputs, state)
        for writer, (inputs, state) in fixtures.items():
            for reader in LANGUAGES:
                row = read(reader, inputs, state, "matrix")
                row["writer"] = writer
                report["matrix"].append(row)
                checkpoint()
            report["physical"].append(physical(local, *inputs, state))
        # ヘッドは進むがスナップショットは番号4に残る。包含開始も実入口で確認する。
        shared, state = [], None
        for number, language in enumerate(LANGUAGES, 1):
            input = event("shared", language, number)
            shared.append(input)
            if number in (2, 4):
                state = snapshot(language, number)
                call(language, {"op": "persistEventAndSnapshot", "event": input, "snapshot": state}, "sequential")
            else:
                call(language, {"op": "persistEvent", "event": input}, "sequential")
            actual = local.configurations()
            assert actual == baseline
            report["configurations"].append({"language": language, "stage": "sequential", "actual": actual, "unchanged": True})
            report["sequential"].append({"writer": language, "number": number,
                "reads": [read(reader, shared, state, "sequential") for reader in LANGUAGES]})
            checkpoint()
        for language in LANGUAGES:
            suffix = call(language, {"op": "getEvents", "id": {"type_name": "Interop", "value": "shared"}, "seq_nr": 4}, "inclusive-start")
            assert suffix == [expected_event(input, language) for input in shared[3:]]
            duplicate = dict(shared[-1], payload={"attempt": "duplicate"})
            reply = drivers[language].call({"op": "persistEvent", "event": duplicate}, "duplicate")
            assert reply["status"] == "error" and reply["category"] == "optimisticLock", reply
            report["optimistic_lock"].append({"language": language, "response": reply, "unchanged_read": read(language, shared, state, "after-duplicate"), "passed": True})
        head = local.item("head", "Interop-shared")
        current = local.item("snapshot", "Interop-shared", 0)
        assert head["seq_nr"] == {"N": "6"} and current["seq_nr"] == {"N": "4"}
        report["snapshot_head_distinction"] = {"head": head, "snapshot": current, "passed": True}
        native = event("native-nanoseconds", "java", 1, BASE_NS + 456789)
        call("java", {"op": "persistEvent", "event": native}, "precision")
        for language in LANGUAGES:
            report["precision"].append(read(language, [native], None, "precision"))
        page_events = []
        for number in range(1, 13):
            language = LANGUAGES[(number - 1) % 6]
            input = event("pagination", language, number, padding="x" * (120 * 1024))
            page_events.append(input)
            call(language, {"op": "persistEvent", "event": input}, "pagination-write")
        query = {"TableName": local.tables["journal"], "KeyConditionExpression": "aid = :aid AND seq_nr >= :seq_nr",
                 "ExpressionAttributeValues": {":aid": {"S": "Interop-pagination"}, ":seq_nr": {"N": "1"}},
                 "ConsistentRead": True, "ScanIndexForward": True}
        raw_pages = []
        while True:
            response = local.sdk_call("query", **query)
            raw_pages.append(response)
            key = response.get("LastEvaluatedKey")
            if not key:
                break
            query["ExclusiveStartKey"] = key
        raw_items = [item for page in raw_pages for item in page["Items"]]
        raw_size = sum(len(item["payload"]["B"]) for item in raw_items)
        assert len(raw_items) == 12 and raw_size > 1024 * 1024
        native_pages = len(raw_pages) > 1
        report["local_physical_boundary"] = {"payload_bytes": raw_size, "raw_pages": len(raw_pages),
            "raw_page_counts": [len(page["Items"]) for page in raw_pages],
            "last_evaluated_keys": [page.get("LastEvaluatedKey") for page in raw_pages],
            "status": "verified" if native_pages else "not-observed", "counted_as_native_pagination_success": native_pages}
        # 実応答が過大だったときだけ、受入済みの実接頭辞＋実末キー方式を適用する。
        observer.correct_oversized_pages = not native_pages
        for language in LANGUAGES:
            before = len(observer.records)
            row = read(language, page_events, None, "pagination-read")
            pages = observer.records[before:]
            assert len(pages) >= 2, (language, "pagination was not observed")
            for index, page in enumerate(pages):
                request = page["request"]
                assert "Limit" not in request and request.get("ConsistentRead") is True
                assert request.get("ScanIndexForward", True) is True
                if index:
                    assert request["ExclusiveStartKey"] == pages[index - 1]["effective_response"]["LastEvaluatedKey"]
            row.update(page_count=len(pages), corrected_pages=sum(page["corrected_from_actual_prefix"] for page in pages),
                       verification_mode="native-local" if native_pages else "accepted-real-prefix-boundary")
            report["pagination"].append(row)
            checkpoint()
        for language in LANGUAGES:
            call(language, {"op": "create", "config": config}, "reopen")
            actual = local.configurations()
            assert actual == baseline
            report["configurations"].append({"language": language, "stage": "reopen", "actual": actual, "unchanged": True})
        report["status"] = "passed" if native_pages else "passed-with-local-boundary-limitation"
        report["summary"] = {"matrix_passed": len(report["matrix"]), "matrix_required": 36,
                             "sequential_steps": len(report["sequential"]), "driver_languages": len(drivers)}
    except BaseException as error:
        report["status"] = "failed"
        report["failure"] = {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}
    finally:
        report["driver_exits"] = []
        for driver in drivers.values():
            try:
                report["driver_exits"].append(driver.close())
            except Exception as error:
                report["driver_exits"].append({"language": driver.language, "cleanup_error": str(error)})
        if observer:
            observer.close()
        report["cleanup"] = local.close()
        if report["cleanup"]["errors"] or any(row.get("exit") != 0 or row.get("terminated") for row in report["driver_exits"]):
            report["status"] = "failed"
        report["source_sha256"] = source_fingerprints()
        checkpoint()
    print(json.dumps({"status": report["status"], "matrix": len(report["matrix"]), "output": str(output)}, ensure_ascii=False))
    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
