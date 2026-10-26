<a id="dynamodb-試験環境の比較"></a>
# Comparison of DynamoDB test environments

In the results run on 2026-10-05, the specified 6 items succeeded on all of LocalStack 2.1.0, LocalStack 4.14.0, and DynamoDB Local 3.3.1. For each language's tests, we **recommend using DynamoDB Local 3.3.1 pinned by digest**. D-5's return of the old item and DY-12's Streams could also be reproduced with the official AWS image alone. The decision to adopt is made by the coordinator.

The subject is the comparison of test foundations described in [4.1 of the implementation plan](../../../docs/plan/implementation-plan.md#41-試験基盤の確認), and we confirmed in a local environment the features that the [DynamoDB specification](../../../docs/spec/storage/dynamodb.md) presupposes.

<a id="実行方法"></a>
## How to run

Prepare an environment where Docker is running, plus uv and Python 3.11 or later, and run from the repository root. Dependencies are pinned by `uv.lock`, and images by the tags and digests in `probe.py`.

```sh
uv run --frozen --project tools/spikes/dynamodb-emulators \
  python tools/spikes/dynamodb-emulators/probe.py
```

To keep the existing measured results and run again, change the output location.

```sh
uv run --frozen --project tools/spikes/dynamodb-emulators \
  python tools/spikes/dynamodb-emulators/probe.py --output results-rerun
```

You can run just one environment with `--environment A`, `B`, or `C`. The output location is restricted to under this directory. The results are output to each environment's JSON and the container logs. `run.json` contains the host, SDK, and Docker information of the latest run, and each environment's JSON contains that environment's run date and time.

The script pulls the images and starts dedicated containers without persistent volumes one after another. The host's published port is automatically assigned from the free ports of `127.0.0.1`. The same local endpoint, the region `us-east-1`, and the dummy credentials `dummy` / `dummy` are specified explicitly for both the DynamoDB and DynamoDB Streams clients. No AWS credentials or LocalStack token are passed. LocalStack is started with `SERVICES=dynamodb,dynamodbstreams`, `EAGER_SERVICE_LOADING=1`, and `DISABLE_EVENTS=1`, and DynamoDB Local with `-inMemory -sharedDb -disableTelemetry`.

On normal exit, check failure, Ctrl-C, and SIGTERM, the owned containers are forcibly stopped and removed in `finally`. A `failure` of a check item is saved as a comparison result, and the exit code is 0. A failure of startup or the execution foundation, or a failure to remove a container, gives exit code 1, so also check the JSON's `checks.*.status` to judge a capability.

If cleanup could not be done because of a forced termination or the stopping of Docker itself, check with this spike's dedicated label.

```sh
docker ps -a --filter label=event-store-adapter.dynamodb-spike
docker ps -aq --filter label=event-store-adapter.dynamodb-spike |
  while IFS= read -r container; do docker rm -f "$container"; done
```

<a id="対象版とトークン"></a>
## Target versions and tokens

| Environment | Docker Hub tag | Token | Basis for selection |
|:--|:--|:--|:--|
| A | `localstack/localstack:2.1.0` | Not required; ran successfully unset | The pinned version of the tests in the existing 5 repositories |
| B | `localstack/localstack:4.14.0` | Not required; ran successfully unset | The latest official version not requiring a token at the time of investigation |
| C | `amazon/dynamodb-local:latest` = `3.3.1` | Not required; ran successfully unset | The manifest digests of `latest` and `3.3.1` match, and the startup log is also 3.3.1 |
| Not compared | Current `localstack/localstack:latest` | Required | Not pulled or started, because no token was prepared |

The selection of B combines the following public information and measurements.

1. [LocalStack's Docker image description](https://docs.localstack.cloud/aws/customization/other-installations/docker-images/) states that the last semantic version is 4.14.0, and that it will move to calendar-based versions from the end of March 2026.
2. [The official announcement of 2026.03.0](https://blog.localstack.cloud/localstack-for-aws-release-2026-03-0/) states that from the unified image of 2026-03-23, an authentication token is required to start. The deadline of the temporary workaround is 2026-04-06, and it is not included in this selection.
3. We fetched all 2 pages of [Docker Hub's 4.x tag API](https://hub.docker.com/v2/repositories/localstack/localstack/tags/?name=4.&page_size=100) and confirmed that the maximum of the official `4.x.y` is 4.14.0. The last update of [the tag information of 4.14.0](https://hub.docker.com/v2/repositories/localstack/localstack/tags/4.14.0) was `2026-02-26T10:41:15.725761Z`.
4. We started the image of that digest without a token, and the DynamoDB and Streams API calls succeeded. Development versions and daily versions are not included as adoption candidates.

The fetched tag list, the query URLs, and the digest of each architecture are saved in [results/tags.json](results/tags.json). The digests of C's [tag information of latest](https://hub.docker.com/v2/repositories/amazon/dynamodb-local/tags/latest) and [tag information of 3.3.1](https://hub.docker.com/v2/repositories/amazon/dynamodb-local/tags/3.3.1) matched. 3.3.1 is also listed in [AWS's release history](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/DynamoDBLocalHistory.html).

| Environment | Manifest digest to pin when re-running |
|:--|:--|
| A | `sha256:74c3cb7cfa3d8a8ea9e786c0974dddf6ea60e7cea91e7a739f93cecafc09a9e2` |
| B | `sha256:3ebc37595918b8accb852f8048fef2aff047d465167edd655528065b07bc364a` |
| C | `sha256:ff89bd48ff32cd8d9be5fee8873b65b8854dc408f1afe881be6eb00247bc0dab` |

`latest` changes, so C's re-runs are also pinned to the observed digest. When comparing a future latest version, check the tag API again and update the digest of `IMAGES["C"]`.

<a id="確認結果"></a>
## Results

"Success" means that the checks of the requests and values described below passed. The measured responses are saved in [A.json](results/A.json), [B.json](results/B.json), and [C.json](results/C.json).

| Check item | A: LocalStack 2.1.0 | B: LocalStack 4.14.0 | C: DynamoDB Local 3.3.1 |
|:--|:--|:--|:--|
| 1a. A cancelled conditional Update returns the old item | Success | Success | Success |
| 1b. A cancelled conditional Put returns the old item | Success | Success | Success |
| 2. head's NEW_IMAGE, INSERT → MODIFY | Success | Success. A wait for initialization was needed | Success |
| 3. Paging of a strongly consistent Query exceeding 1 MB in one partition | Success, 9 items + 3 items | Success, 9 items + 3 items | Success, 9 items + 3 items |
| 4. BatchGetItem's strongly consistent option | Success, obtained the values of 3 tables | Success, obtained the values of 3 tables | Success, obtained the values of 3 tables |
| 5. A sparse GSI by the presence of the sort-key attribute, KEYS_ONLY | Success, projected only the 1 target item | Success, projected only the 1 target item | Success, projected only the 1 target item |
| 6. Enabling TTL on `ttl` | Success, ENABLED | Success, ENABLED | Success, ENABLED |

<a id="検査内容と挙動の違い"></a>
### What was checked and differences in behavior

- **Return of the old item**: We put `seq_nr=7` and an identifying attribute in head, and made the Update fail with `seq_nr = :prev` (`:prev=6`) and the Put with `attribute_not_exists(aid)`. Both specified `ReturnValuesOnConditionCheckFailure=ALL_OLD`. We made the second of the two operations in a transaction fail, and checked that `TransactionCanceledException`, `CancellationReasons[1].Code=ConditionalCheckFailed`, and its `Item` matched the whole old item. With a strongly consistent GetItem we confirmed that another Put that should have succeeded did not remain, and that head was not updated.
- **Streams**: We checked DescribeTable's `LatestStreamArn` and `NEW_IMAGE`, and read the INSERT and MODIFY of the same aid in order with DescribeStream, GetShardIterator (TRIM_HORIZON), and GetRecords. NewImage's `seq_nr` was 1 and 2, there was no OldImage, and the 2 items were on the same shard. C's ARN and the record region were `ddblocal`, and A/B were `us-east-1`. In each language's tests, do not guess a normal AWS region from C's ARN, and the endpoint must also be specified explicitly for Streams.
- **Initialization of B**: In the run before waiting, DescribeStream returned `ENABLING`, and GetShardIterator failed with an `InternalError` wrapping the internal Kinesis `ResourceInUseException`. We saved [the JSON before waiting](results/B-before-stream-wait.json) and [the log](results/B-before-stream-wait.log). In the final script, it waits up to 30 seconds, before writing, until Streams becomes `ENABLED` and an iterator can be obtained. It succeeded with that procedure. Using only the table being ACTIVE as the start condition is insufficient.
- **Initialization log of A**: In [A's log](results/A.log) as well, `ResourceInUseException` occurred in the forwarding of the Put for the cancellation check, performed before Streams was ready. For both A/B, the table's INSERT → MODIFY check is a result for items written after the iterator was obtained. At the start of the tests, it is necessary to wait not only for the table but also for Streams to be ready.
- **Query**: We wrote 12 items, each with a 120,000-byte ASCII payload, to the same aid, for a total of 1,440,000 bytes. We queried with `ConsistentRead=true` and without specifying `Limit`. The first response had a LastEvaluatedKey, and using ExclusiveStartKey the 12 items could be read in order without omissions or duplicates. All 3 environments gave 9 items + 3 items. The total payload of the first page was 1,080,000 bytes, and truncation to a strict 1 MiB or less is not included in the verification results.
- **BatchGetItem**: We put configuration items in head, journal, and snapshot, specified `ConsistentRead=true` for each table, and obtained all 3. UnprocessedKeys was empty this time. The handling of re-requests is provided, but no test that generates unprocessed keys was done.
- **Sparse GSI**: The snapshot's key was `aid` / `skey`, the GSI's key was `aid` / `active_history_seq_nr`, and the projection was KEYS_ONLY. Of the 3 items with the same aid, only the 1 that has the GSI's sort-key attribute appeared, and the only attributes returned were the table's 2 keys and the GSI's sort key. The payload was not returned.
- **TTL**: We enabled `ttl` with UpdateTimeToLive, and confirmed the attribute name and ENABLED with DescribeTimeToLive. Deletion upon expiry was not investigated.

The 2 strongly consistent items are checks that the option is accepted and that the expected value written just before can be obtained. They do not prove read consistency under concurrent execution. [AWS's usage notes for DynamoDB Local](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/DynamoDBLocal.UsageNotes.html) also explain that local reads and shard creation differ from the real service. This success is the result for this spike's 6 items, and does not show conformance to all the behavior of real AWS.

<a id="起動の速さ"></a>
## Startup speed

Measured after pre-fetching each image, on macOS / arm64 with Docker Desktop's Linux / arm64. We used Python 3.13.13, boto3 1.42.70, and botocore 1.42.97. The startup time is from the start of `docker run` to the first success of DynamoDB ListTables with dummy credentials, and does not include pull or table creation. We did not run repeated benchmarks, so we do not evaluate the statistical significance of the differences.

| Environment | Startup time (seconds) | Read-readiness wait after the start of the Streams check (seconds) |
|:--|--:|--:|
| A | 2.249 | 0.057 |
| B | 3.402 | 0.307 |
| C | 0.992 | 0.009 |

The Streams readiness wait is the time from the start of the Streams check, after the table creation and the cancellation check, until the iterator is obtained, and is not the total time from the container start. For details, see each environment's `startup_seconds` and `checks.2_streams_new_image.stream_ready_seconds`, and [run.json](results/run.json).

<a id="推奨と次の選択肢"></a>
## Recommendation and next options

1. **Recommended: unify each language on DynamoDB Local 3.3.1.** The 6 items including D-5 and DY-12 succeeded, and neither a token nor LocalStack's own Streams implementation is needed. Specify the same endpoint explicitly for DynamoDB and Streams, and pin the image by the digest above. This time the startup time was about 1 to 3 seconds. Because repeated measurements were not done, the difference in speed alone is not made the reason for adoption.
2. **If migration is deferred: pin LocalStack and keep using it.** 2.1.0 can be continued because this time's items succeeded. If a newer version not requiring a token is chosen, 4.14.0 is the candidate, but the wait for Streams readiness must also be put into each language's tests. Both are versions earlier than the current unified image.
3. **If the features and continued updates of the current LocalStack are needed: prepare a token and compare separately.** It is unverified because no token was available this time, and no conclusion on whether to adopt has been reached.

The specification and plan documents were not changed. All containers started this time were stopped and removed, and we confirmed that each environment's JSON has `container_removed=true` and that `docker ps -a` with the dedicated label is empty.
