# DynamoDB 試験環境の比較

2026-10-05 に実行した結果、LocalStack 2.1.0、LocalStack 4.14.0、DynamoDB Local 3.3.1 のすべてで、指定された 6 項目が成功した。各言語の試験には **DynamoDB Local 3.3.1 を digest で固定して使うことを推奨する**。D-5 の旧項目返却と DY-12 の Streams も、AWS 公式イメージだけで再現できた。採用の決定は指揮役が行う。

対象は[実装計画の 4.1](../../../docs/plan/implementation-plan.md#41-試験基盤の確認)に記した試験基盤の比較で、[DynamoDB 仕様](../../../docs/spec/storage/dynamodb.md)が前提とする機能をローカル環境で確認した。

## 実行方法

Docker が起動している環境と uv、Python 3.11 以上を用意し、リポジトリのルートで実行する。依存関係は `uv.lock`、イメージは `probe.py` のタグと digest で固定している。

```sh
uv run --frozen --project tools/spikes/dynamodb-emulators \
  python tools/spikes/dynamodb-emulators/probe.py
```

既存の実測結果を残して再実行する場合は、保存先を変える。

```sh
uv run --frozen --project tools/spikes/dynamodb-emulators \
  python tools/spikes/dynamodb-emulators/probe.py --output results-rerun
```

`--environment A`、`B`、`C` で 1 環境だけ実行できる。保存先はこのディレクトリ配下に限定される。結果は各環境の JSON とコンテナログに出力される。`run.json` は直近の実行のホスト・SDK・Docker 情報、各環境の JSON はその環境の実行日時を含む。

スクリプトはイメージを pull して、永続ボリュームを持たない専用コンテナを順番に起動する。ホストの公開ポートは `127.0.0.1` の空きポートを自動割り当てする。DynamoDB と DynamoDB Streams の両クライアントに同じローカル endpoint、リージョン `us-east-1`、ダミー資格情報 `dummy` / `dummy` を明示する。AWS の資格情報や LocalStack のトークンは渡さない。LocalStack は `SERVICES=dynamodb,dynamodbstreams`、`EAGER_SERVICE_LOADING=1`、`DISABLE_EVENTS=1`、DynamoDB Local は `-inMemory -sharedDb -disableTelemetry` で起動する。

正常終了、検査失敗、Ctrl-C、SIGTERM では `finally` で所有するコンテナを強制停止・削除する。検査項目の `failure` は比較結果として保存し、終了コードは 0 とする。起動・実行基盤の失敗、またはコンテナの削除失敗は終了コード 1 になるので、能力の判定には JSON の `checks.*.status` も確認する。

強制終了や Docker 自体の停止で後片付けできなかった場合は、このスパイク専用のラベルで確認する。

```sh
docker ps -a --filter label=event-store-adapter.dynamodb-spike
docker ps -aq --filter label=event-store-adapter.dynamodb-spike |
  while IFS= read -r container; do docker rm -f "$container"; done
```

## 対象版とトークン

| 環境 | Docker Hub のタグ | トークン | 選定根拠 |
|:--|:--|:--|:--|
| A | `localstack/localstack:2.1.0` | 不要、未設定で実行成功 | 既存 5 リポジトリの試験の固定版 |
| B | `localstack/localstack:4.14.0` | 不要、未設定で実行成功 | 調査時点のトークン不要の最新正式版 |
| C | `amazon/dynamodb-local:latest` = `3.3.1` | 不要、未設定で実行成功 | `latest` と `3.3.1` の manifest digest が一致し、起動ログも 3.3.1 |
| 比較対象外 | 現行 `localstack/localstack:latest` | 必要 | トークン未用意のため pull・起動はしていない |

B の選定は次の公開情報と実測を合わせたもの。

1. [LocalStack の Docker イメージ説明](https://docs.localstack.cloud/aws/customization/other-installations/docker-images/)は、セマンティック版の最後を 4.14.0 とし、2026 年 3 月末から暦ベースの版に移ると説明している。
2. [2026.03.0 の公式告知](https://blog.localstack.cloud/localstack-for-aws-release-2026-03-0/)は、2026-03-23 の統合イメージから起動に認証トークンが必要と説明している。一時的な回避の期限は 2026-04-06 であり、今回の選定には含めていない。
3. [Docker Hub の 4.x タグ API](https://hub.docker.com/v2/repositories/localstack/localstack/tags/?name=4.&page_size=100)を全 2 ページ取得し、正式な `4.x.y` の最大値が 4.14.0 であることを確認した。[4.14.0 のタグ情報](https://hub.docker.com/v2/repositories/localstack/localstack/tags/4.14.0)の最終更新は `2026-02-26T10:41:15.725761Z` だった。
4. その digest のイメージをトークンなしで起動し、DynamoDB と Streams の API 呼び出しが成功した。開発版・日次版は採用候補に含めていない。

取得したタグ一覧、照会 URL、各アーキテクチャの digest は [results/tags.json](results/tags.json) に保存した。C の [latest のタグ情報](https://hub.docker.com/v2/repositories/amazon/dynamodb-local/tags/latest)と [3.3.1 のタグ情報](https://hub.docker.com/v2/repositories/amazon/dynamodb-local/tags/3.3.1)の digest は一致した。[AWS のリリース履歴](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/DynamoDBLocalHistory.html)にも 3.3.1 が載っている。

| 環境 | 再実行時に固定する manifest digest |
|:--|:--|
| A | `sha256:74c3cb7cfa3d8a8ea9e786c0974dddf6ea60e7cea91e7a739f93cecafc09a9e2` |
| B | `sha256:3ebc37595918b8accb852f8048fef2aff047d465167edd655528065b07bc364a` |
| C | `sha256:ff89bd48ff32cd8d9be5fee8873b65b8854dc408f1afe881be6eb00247bc0dab` |

`latest` は変わるため、C の再実行も観測した digest に固定する。将来の最新版を比較するときはタグ API を再確認し、`IMAGES["C"]` の digest を更新する。

## 確認結果

「成功」は以下に記した要求・値の検査を通過したことを表す。実測応答は [A.json](results/A.json)、[B.json](results/B.json)、[C.json](results/C.json) に保存した。

| 確認項目 | A: LocalStack 2.1.0 | B: LocalStack 4.14.0 | C: DynamoDB Local 3.3.1 |
|:--|:--|:--|:--|
| 1a. 条件付き Update の取り消しで旧項目を返す | 成功 | 成功 | 成功 |
| 1b. 条件付き Put の取り消しで旧項目を返す | 成功 | 成功 | 成功 |
| 2. head の NEW_IMAGE、INSERT → MODIFY | 成功 | 成功。初期化待ちが必要だった | 成功 |
| 3. 1 パーティションで 1 MB を超える強整合 Query のページ送り | 成功、9 件 + 3 件 | 成功、9 件 + 3 件 | 成功、9 件 + 3 件 |
| 4. BatchGetItem の強整合オプション | 成功、3 テーブルの値を取得 | 成功、3 テーブルの値を取得 | 成功、3 テーブルの値を取得 |
| 5. ソートキー属性の有無による疎な GSI、KEYS_ONLY | 成功、対象 1 件だけを射影 | 成功、対象 1 件だけを射影 | 成功、対象 1 件だけを射影 |
| 6. `ttl` の TTL 有効化 | 成功、ENABLED | 成功、ENABLED | 成功、ENABLED |

### 検査内容と挙動の違い

- **旧項目の返却**: head に `seq_nr=7` と識別用属性を入れ、Update は `seq_nr = :prev`（`:prev=6`）、Put は `attribute_not_exists(aid)` で失敗させた。いずれも `ReturnValuesOnConditionCheckFailure=ALL_OLD` を指定した。2 操作のトランザクションの 2 番目を失敗させ、`TransactionCanceledException`、`CancellationReasons[1].Code=ConditionalCheckFailed`、その `Item` が旧項目全体と一致することを検査した。別の成功するはずの Put が残らず、head も更新されないことを強整合 GetItem で確認した。
- **Streams**: DescribeTable の `LatestStreamArn` と `NEW_IMAGE` を確認し、DescribeStream、GetShardIterator（TRIM_HORIZON）、GetRecords で同じ aid の INSERT、MODIFY を順に読んだ。NewImage の `seq_nr` は 1、2 で、OldImage はなく、2 件は同じ shard に載った。C の ARN とレコードのリージョンは `ddblocal`、A/B は `us-east-1` だった。各言語の試験では C の ARN から通常の AWS リージョンを推測せず、Streams にも endpoint を明示する必要がある。
- **B の初期化**: 待機前の実行では DescribeStream が `ENABLING` を返し、GetShardIterator は内部 Kinesis の `ResourceInUseException` を包んだ `InternalError` で失敗した。[待機前の JSON](results/B-before-stream-wait.json)と[ログ](results/B-before-stream-wait.log)を保存した。最終スクリプトでは、書き込み前に Streams が `ENABLED` になり iterator を取得できるまで最大 30 秒待つ。その手順で成功した。テーブルの ACTIVE だけを開始条件にすると不足する。
- **A の初期化ログ**: [A のログ](results/A.log)でも、Streams の準備前に行った取り消し検査用 Put の転送で `ResourceInUseException` が出た。A/B とも、表の INSERT → MODIFY の検査は iterator の取得後に書き込んだ項目に対する結果である。試験開始時にはテーブルだけでなく Streams の準備も待つ必要がある。
- **Query**: 同じ aid に 120,000 バイトの ASCII payload を持つ項目を 12 件、合計 1,440,000 バイト書いた。`ConsistentRead=true` を指定し、`Limit` を指定せず Query した。最初の応答に LastEvaluatedKey があり、ExclusiveStartKey を使って 12 件を欠落・重複なく順に読めた。3 環境とも 9 件 + 3 件だった。最初のページの payload 合計は 1,080,000 バイトで、厳密な 1 MiB 以下への切り詰めまでは検証結果に含めない。
- **BatchGetItem**: head・journal・snapshot に設定項目を入れ、各テーブルに `ConsistentRead=true` を指定して 3 件とも取得した。今回 UnprocessedKeys は空だった。再要求の処理は備えているが、未処理キーを発生させる試験はしていない。
- **疎な GSI**: snapshot のキーは `aid` / `skey`、GSI のキーは `aid` / `active_history_seq_nr`、射影は KEYS_ONLY とした。同じ aid の 3 件のうち、GSI のソートキー属性を持つ 1 件だけが載り、返る属性はテーブルのキー 2 個と GSI のソートキーだけだった。payload は返らなかった。
- **TTL**: UpdateTimeToLive で `ttl` を有効にし、DescribeTimeToLive で属性名と ENABLED を確認した。期限切れの削除は調べていない。

強整合の 2 項目は、オプションが受理され、直前に書いた期待値を取得できることの検査である。並行実行における読み取り一貫性を証明するものではない。[AWS の DynamoDB Local 使用上の注意](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/DynamoDBLocal.UsageNotes.html)も、ローカルの読み取りと shard 作成が実サービスと異なることを説明している。今回の成功は、このスパイクの 6 項目に対する結果であり、実 AWS の全挙動への適合を示すものではない。

## 起動の速さ

macOS / arm64、Docker Desktop の Linux / arm64 で、各イメージを事前に取得した後に計測した。Python 3.13.13、boto3 1.42.70、botocore 1.42.97 を使った。起動時間は `docker run` の開始から、ダミー資格情報による DynamoDB ListTables の最初の成功までで、pull とテーブル作成を含まない。反復ベンチマークは行っていないので、差の統計的な有意性は評価しない。

| 環境 | 起動時間（秒） | Streams 検査開始後の読取準備待ち（秒） |
|:--|--:|--:|
| A | 2.249 | 0.057 |
| B | 3.402 | 0.307 |
| C | 0.992 | 0.009 |

Streams の準備待ちは、テーブル作成と取り消し検査の後、Streams 検査を開始してから iterator を取得するまでの時間であり、コンテナ起動からの総時間ではない。詳細は各環境の `startup_seconds`、`checks.2_streams_new_image.stream_ready_seconds` と [run.json](results/run.json) を参照。

## 推奨と次の選択肢

1. **推奨: 各言語を DynamoDB Local 3.3.1 に統一する。** D-5 と DY-12 を含む 6 項目が成功し、トークンも LocalStack の独自 Streams 実装も不要になる。DynamoDB と Streams に同じ endpoint を明示し、イメージを上記 digest で固定する。今回の起動時間は約 1〜3 秒だった。反復計測はしていないため、速さの差だけを採用理由にはしない。
2. **移行を見送る場合: LocalStack を固定して使う。** 2.1.0 は今回の項目が成功したので継続できる。新しいトークン不要版を選ぶなら 4.14.0 が候補だが、Streams の準備待ちを各言語の試験にも入れる。どちらも現行の統合イメージより前の版になる。
3. **現行 LocalStack の機能・継続更新を必要とする場合: トークンを用意して別途比較する。** 今回はトークンがないため未検証で、採用可否の結論は出していない。

仕様・計画書は変更していない。今回起動したコンテナはすべて停止・削除し、各環境の JSON の `container_removed=true` と、専用ラベルによる `docker ps -a` が空であることを確認した。
