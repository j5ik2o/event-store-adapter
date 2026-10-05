"""ローカルコンテナだけで DynamoDB の仕様前提を比較する。"""

import argparse
import json
import platform
import signal
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import boto3
import botocore
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError


ROOT = Path(__file__).resolve().parent
IMAGES = {
    "A": "localstack/localstack:2.1.0@sha256:74c3cb7cfa3d8a8ea9e786c0974dddf6ea60e7cea91e7a739f93cecafc09a9e2",
    "B": "localstack/localstack:4.14.0@sha256:3ebc37595918b8accb852f8048fef2aff047d465167edd655528065b07bc364a",
    "C": "amazon/dynamodb-local:latest@sha256:ff89bd48ff32cd8d9be5fee8873b65b8854dc408f1afe881be6eb00247bc0dab",
}
LABEL = "event-store-adapter.dynamodb-spike"
HEAD, JOURNAL, SNAPSHOT = "spike-head", "spike-journal", "spike-snapshot"


def docker(*args, check=True, timeout=60):
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=check, timeout=timeout
    )


def client(service, endpoint):
    # 明示的な資格情報と endpoint により AWS の資格情報探索・接続を避ける。
    return boto3.Session().client(
        service,
        endpoint_url=endpoint,
        aws_access_key_id="dummy",
        aws_secret_access_key="dummy",
        region_name="us-east-1",
        config=Config(
            connect_timeout=2,
            read_timeout=5,
            retries={"total_max_attempts": 1},
            proxies={},
        ),
    )


def clean_response(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, dict):
        return {k: clean_response(v) for k, v in value.items() if k != "ResponseMetadata"}
    if isinstance(value, list):
        return [clean_response(v) for v in value]
    return value


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def setup(db):
    db.create_table(
        TableName=HEAD,
        AttributeDefinitions=[{"AttributeName": "aid", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "aid", "KeyType": "HASH"}],
        BillingMode="PAY_PER_REQUEST",
        StreamSpecification={"StreamEnabled": True, "StreamViewType": "NEW_IMAGE"},
    )
    for table, skey in [(JOURNAL, "seq_nr"), (SNAPSHOT, "skey")]:
        kwargs = dict(
            TableName=table,
            AttributeDefinitions=[
                {"AttributeName": "aid", "AttributeType": "S"},
                {"AttributeName": skey, "AttributeType": "N"},
            ],
            KeySchema=[
                {"AttributeName": "aid", "KeyType": "HASH"},
                {"AttributeName": skey, "KeyType": "RANGE"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        if table == SNAPSHOT:
            kwargs["AttributeDefinitions"].append(
                {"AttributeName": "active_history_seq_nr", "AttributeType": "N"}
            )
            kwargs["GlobalSecondaryIndexes"] = [{
                "IndexName": "active-history",
                "KeySchema": [
                    {"AttributeName": "aid", "KeyType": "HASH"},
                    {"AttributeName": "active_history_seq_nr", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "KEYS_ONLY"},
            }]
        db.create_table(**kwargs)
    for table in [HEAD, JOURNAL, SNAPSHOT]:
        db.get_waiter("table_exists").wait(
            TableName=table, WaiterConfig={"Delay": 1, "MaxAttempts": 60}
        )


def transaction(db, kind, evidence):
    aid = f"transaction-{kind}"
    old = {"aid": {"S": aid}, "seq_nr": {"N": "7"}, "marker": {"S": "old"}}
    db.put_item(TableName=HEAD, Item=old)
    if kind == "Update":
        operation = {
            "TableName": HEAD,
            "Key": {"aid": {"S": aid}},
            "UpdateExpression": "SET seq_nr = :next",
            "ConditionExpression": "seq_nr = :prev",
            "ExpressionAttributeValues": {":prev": {"N": "6"}, ":next": {"N": "8"}},
            "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
        }
    else:
        operation = {
            "TableName": HEAD,
            "Item": {"aid": {"S": aid}, "seq_nr": {"N": "8"}},
            "ConditionExpression": "attribute_not_exists(aid)",
            "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
        }
    side_key = {"aid": {"S": f"side-{kind}"}, "seq_nr": {"N": "1"}}
    try:
        db.transact_write_items(TransactItems=[
            {"Put": {"TableName": JOURNAL, "Item": side_key}},
            {kind: operation},
        ])
    except ClientError as exc:
        evidence["response"] = clean_response(exc.response)
        require(exc.response["Error"]["Code"] == "TransactionCanceledException", "取り消し例外が違う")
        reasons = exc.response.get("CancellationReasons", [])
        evidence["head_after"] = clean_response(db.get_item(
            TableName=HEAD, Key={"aid": {"S": aid}}, ConsistentRead=True
        ))
        evidence["side_after"] = clean_response(db.get_item(
            TableName=JOURNAL, Key=side_key, ConsistentRead=True
        ))
        require(evidence["head_after"].get("Item") == old, "head が変更された")
        require("Item" not in evidence["side_after"], "取り消された別操作が残った")
        require(len(reasons) == 2, "操作ごとの取り消し理由がない")
        require(reasons[0].get("Code") == "None", "成功する操作の理由が違う")
        require(reasons[1].get("Code") == "ConditionalCheckFailed", "条件不成立の位置が違う")
        require(reasons[1].get("Item") == old, "取り消し理由の該当要素に旧項目がない")
    else:
        raise AssertionError("条件不成立なのにトランザクションが成功した")


def streams(db, stream, evidence):
    table = db.describe_table(TableName=HEAD)["Table"]
    evidence["stream_specification"] = table.get("StreamSpecification")
    evidence["latest_stream_arn"] = table.get("LatestStreamArn")
    require(table.get("StreamSpecification") == {
        "StreamEnabled": True, "StreamViewType": "NEW_IMAGE"
    }, "NEW_IMAGE が有効になっていない")
    require(evidence["latest_stream_arn"], "LatestStreamArn がない")
    arn = evidence["latest_stream_arn"]
    evidence["describe_stream"] = clean_response(stream.describe_stream(StreamArn=arn))
    # テーブル ACTIVE と Streams の読取可能時機は異なる。書く前に iterator を取得する。
    ready_started = time.monotonic()
    deadline = ready_started + 30
    iterators, seen = {}, set()
    evidence["readiness_errors"] = []
    while time.monotonic() < deadline:
        description = stream.describe_stream(StreamArn=arn)["StreamDescription"]
        evidence["ready_stream_status"] = description.get("StreamStatus")
        if description.get("StreamStatus") == "ENABLED":
            for shard in description.get("Shards", []):
                sid = shard["ShardId"]
                try:
                    iterators[sid] = stream.get_shard_iterator(
                        StreamArn=arn, ShardId=sid, ShardIteratorType="TRIM_HORIZON"
                    )["ShardIterator"]
                    seen.add(sid)
                except ClientError as exc:
                    message = exc.response["Error"].get("Message", "")
                    if "ResourceInUseException" not in message:
                        raise
                    evidence["readiness_errors"].append(clean_response(exc.response))
            if iterators:
                break
        time.sleep(0.25)
    evidence["stream_ready_seconds"] = round(time.monotonic() - ready_started, 3)
    require(iterators, "Streams が 30 秒以内に読取可能にならない")
    aid = "stream-target"
    db.put_item(TableName=HEAD, Item={"aid": {"S": aid}, "seq_nr": {"N": "1"}})
    db.update_item(
        TableName=HEAD, Key={"aid": {"S": aid}},
        UpdateExpression="SET seq_nr = :next",
        ExpressionAttributeValues={":next": {"N": "2"}},
    )
    records, events = [], []
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        # 初期 shard が遅れて作られる場合と DescribeStream のページ送りに対応する。
        params = {"StreamArn": arn}
        while True:
            description = stream.describe_stream(**params)["StreamDescription"]
            for shard in description.get("Shards", []):
                sid = shard["ShardId"]
                if sid not in seen:
                    seen.add(sid)
                    iterators[sid] = stream.get_shard_iterator(
                        StreamArn=arn, ShardId=sid, ShardIteratorType="TRIM_HORIZON"
                    )["ShardIterator"]
            last = description.get("LastEvaluatedShardId")
            if not last:
                break
            params["ExclusiveStartShardId"] = last
        for sid, iterator in list(iterators.items()):
            if not iterator:
                continue
            response = stream.get_records(ShardIterator=iterator, Limit=100)
            iterators[sid] = response.get("NextShardIterator")
            for record in response.get("Records", []):
                if record.get("dynamodb", {}).get("Keys", {}).get("aid") == {"S": aid}:
                    records.append(clean_response(record))
                    events.append({"shard": sid, "event": record["eventName"],
                                   "seq_nr": record["dynamodb"].get("NewImage", {}).get("seq_nr")})
        evidence["records"] = records
        evidence["events"] = events
        if len(events) >= 2:
            break
        time.sleep(0.25)
    require([e["event"] for e in events] == ["INSERT", "MODIFY"], "INSERT → MODIFY を順に読めない")
    require([e["seq_nr"] for e in events] == [{"N": "1"}, {"N": "2"}], "NewImage の値が違う")
    require(events[0]["shard"] == events[1]["shard"], "同じ aid の変更が別 shard に載った")
    require(all("OldImage" not in r["dynamodb"] for r in records), "NEW_IMAGE に OldImage がある")


def pagination(db, evidence):
    count, payload_size = 12, 120_000
    payload = "x" * payload_size
    for n in range(1, count + 1):
        db.put_item(TableName=JOURNAL, Item={
            "aid": {"S": "pagination"}, "seq_nr": {"N": str(n)}, "payload": {"S": payload}
        })
    evidence.update(payload_bytes=count * payload_size, pages=[], seq_nrs=[])
    kwargs = dict(
        TableName=JOURNAL, KeyConditionExpression="aid = :aid",
        ExpressionAttributeValues={":aid": {"S": "pagination"}}, ConsistentRead=True,
    )
    for _ in range(20):
        # Limit は指定しない。1 MiB の応答上限による分割を確かめる。
        response = db.query(**kwargs)
        items = response["Items"]
        require(all(i["payload"] == {"S": payload} for i in items), "payload が欠けた")
        evidence["seq_nrs"].extend(int(i["seq_nr"]["N"]) for i in items)
        last = response.get("LastEvaluatedKey")
        evidence["pages"].append({
            "count": response["Count"], "payload_bytes": len(items) * payload_size,
            "last_evaluated_key": last,
        })
        if not last:
            break
        kwargs["ExclusiveStartKey"] = last
    else:
        raise AssertionError("ページ送りが終了しない")
    require(evidence["pages"][0]["last_evaluated_key"], "最初の Query に LastEvaluatedKey がない")
    require(evidence["seq_nrs"] == list(range(1, count + 1)), "欠落・重複・順序違いがある")


def batch_get(db, evidence):
    expected, requests = {}, {}
    for table, sort in [(HEAD, None), (JOURNAL, "seq_nr"), (SNAPSHOT, "skey")]:
        item = {"aid": {"S": "__config__"}, "store_id": {"S": "spike"}, "layout_version": {"N": "1"}}
        key = {"aid": {"S": "__config__"}}
        if sort:
            item[sort] = key[sort] = {"N": "0"}
        db.put_item(TableName=table, Item=item)
        expected[table] = [item]
        requests[table] = {"Keys": [key], "ConsistentRead": True}
    evidence["requests"] = requests
    gathered = {table: [] for table in requests}
    evidence["responses"] = []
    for attempt in range(5):
        response = db.batch_get_item(RequestItems=requests)
        evidence["responses"].append(clean_response(response))
        for table, items in response.get("Responses", {}).items():
            gathered[table].extend(items)
        requests = response.get("UnprocessedKeys", {})
        if not requests:
            break
        for request in requests.values():
            request["ConsistentRead"] = True
        time.sleep(0.1 * 2 ** attempt)
    require(not requests, "UnprocessedKeys を読み切れない")
    require(gathered == expected, "3 テーブルの強整合読み取りの値が違う")


def sparse_gsi(db, evidence):
    for n in [0, 1, 2]:
        item = {"aid": {"S": "sparse"}, "skey": {"N": str(n)}, "payload": {"S": "not-projected"}}
        if n == 0:
            item["active_history_seq_nr"] = {"N": "2"}
        db.put_item(TableName=SNAPSHOT, Item=item)
    deadline = time.monotonic() + 10
    while True:
        response = db.query(
            TableName=SNAPSHOT, IndexName="active-history", ConsistentRead=False,
            KeyConditionExpression="aid = :aid", ExpressionAttributeValues={":aid": {"S": "sparse"}},
        )
        evidence["response"] = clean_response(response)
        if response["Items"] or time.monotonic() >= deadline:
            break
        time.sleep(0.25)
    require(response["Items"] == [{
        "aid": {"S": "sparse"}, "skey": {"N": "0"}, "active_history_seq_nr": {"N": "2"}
    }], "疎な GSI の対象項目または KEYS_ONLY の射影が違う")


def ttl(db, evidence):
    evidence["update"] = clean_response(db.update_time_to_live(
        TableName=SNAPSHOT, TimeToLiveSpecification={"Enabled": True, "AttributeName": "ttl"}
    ))
    evidence["describe"] = clean_response(db.describe_time_to_live(TableName=SNAPSHOT))
    description = evidence["describe"]["TimeToLiveDescription"]
    require(description.get("AttributeName") == "ttl", "TTL 属性が違う")
    require(description.get("TimeToLiveStatus") in ["ENABLING", "ENABLED"], "TTL が有効にならない")


def run_probe(name, output):
    image = IMAGES[name]
    container = f"dynamodb-spike-{name.lower()}-{uuid.uuid4().hex[:8]}"
    result = {
        "environment": name, "image": image, "token_required": False,
        "executed_at_utc": datetime.now(timezone.utc).isoformat(), "checks": {},
    }
    try:
        pull_started = time.monotonic()
        docker("pull", image, timeout=600)
        result["pull_seconds"] = round(time.monotonic() - pull_started, 3)
        inspection = json.loads(docker("image", "inspect", image).stdout)[0]
        result["image_metadata"] = {k: inspection.get(k) for k in ["Id", "RepoDigests", "Architecture", "Os", "Created"]}
        result["image_metadata"]["labels"] = inspection["Config"].get("Labels")
        port = 8000 if name == "C" else 4566
        args = ["run", "-d", "--name", container, "--label", LABEL, "-p", f"127.0.0.1::{port}"]
        if name != "C":
            args.extend(["-e", "SERVICES=dynamodb,dynamodbstreams", "-e", "EAGER_SERVICE_LOADING=1",
                         "-e", "DISABLE_EVENTS=1", "-e", "AWS_ACCESS_KEY_ID=dummy", "-e", "AWS_SECRET_ACCESS_KEY=dummy"])
        args.append(image)
        if name == "C":
            args.extend(["-jar", "DynamoDBLocal.jar", "-inMemory", "-sharedDb", "-disableTelemetry"])
        started = time.monotonic()
        docker(*args)
        published = docker("port", container, f"{port}/tcp").stdout.strip()
        require(published.startswith("127.0.0.1:"), "ループバック以外のポートが公開された")
        endpoint = f"http://{published}"
        db, stream = client("dynamodb", endpoint), client("dynamodbstreams", endpoint)
        deadline = started + 180
        while True:
            try:
                db.list_tables()
                break
            except (BotoCoreError, ClientError):
                if time.monotonic() >= deadline:
                    raise TimeoutError("DynamoDB の起動待ちが 180 秒を超えた")
                time.sleep(0.25)
        result["startup_seconds"] = round(time.monotonic() - started, 3)
        setup(db)
        checks = {
            "1_update_all_old": lambda e: transaction(db, "Update", e),
            "1_put_all_old": lambda e: transaction(db, "Put", e),
            "2_streams_new_image": lambda e: streams(db, stream, e),
            "3_query_pagination": lambda e: pagination(db, e),
            "4_batch_get_consistent": lambda e: batch_get(db, e),
            "5_sparse_gsi_keys_only": lambda e: sparse_gsi(db, e),
            "6_ttl_enable": lambda e: ttl(db, e),
        }
        for key, probe in checks.items():
            evidence = {}
            check_started = time.monotonic()
            try:
                probe(evidence)
                evidence["status"] = "success"
            except (AssertionError, BotoCoreError, ClientError) as exc:
                evidence.update(status="failure", error=str(exc))
                if isinstance(exc, ClientError):
                    evidence["error_response"] = clean_response(exc.response)
            evidence["seconds"] = round(time.monotonic() - check_started, 3)
            result["checks"][key] = evidence
            print(f"{name} {key}: {evidence['status']}", flush=True)
    except Exception as exc:
        result["runner_error"] = str(exc)
        print(f"{name} runner error: {exc}", flush=True)
    finally:
        try:
            logs = docker("logs", container, check=False)
            (output / f"{name}.log").write_text(logs.stdout + logs.stderr, encoding="utf-8")
        finally:
            removed = docker("rm", "-f", container, check=False)
            remaining = docker("ps", "-aq", "--filter", f"name=^/{container}$")
            result["container_removed"] = removed.returncode == 0 and not remaining.stdout.strip()
        (output / f"{name}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def handle_sigterm(*_):
    raise KeyboardInterrupt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=["all", *IMAGES], default="all")
    parser.add_argument("--output", default="results", help="このスパイク配下の結果保存先")
    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    require(output.is_relative_to(ROOT) and output != ROOT, "結果はスパイク配下のサブディレクトリに保存する")
    output.mkdir(parents=True, exist_ok=True)
    # SIGTERM でも finally を通し、所有するコンテナを片付ける。
    signal.signal(signal.SIGTERM, handle_sigterm)
    manifest = {
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "host": platform.platform(), "python": platform.python_version(),
        "boto3": boto3.__version__, "botocore": botocore.__version__,
        "environments": list(IMAGES) if args.environment == "all" else [args.environment],
        "docker_version": docker("version", "--format", "{{json .}}").stdout.strip(),
    }
    (output / "run.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    results = [run_probe(name, output) for name in (IMAGES if args.environment == "all" else [args.environment])]
    # 能力差の failure は比較結果。起動・実行基盤の失敗と後片付け失敗だけ終了コードを変える。
    return int(any("runner_error" in r or not r["container_removed"] for r in results))


if __name__ == "__main__":
    raise SystemExit(main())
