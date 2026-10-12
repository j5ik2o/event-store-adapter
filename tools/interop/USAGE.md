# 6言語で同じ DynamoDB Local を読み書きする

[共通契約](../../docs/spec/core-contract.md) と [DynamoDB 保存仕様](../../docs/spec/storage/dynamodb.md) の相互運用を実測する、一度きりの検証ツールです。
`snapshots.json` に固定した指定コミットのソースを取得し、6言語の薄いドライバーをビルドします。
Docker で DynamoDB Local を起動し、各言語の公開 API だけを通して、6言語の書き手と6言語の読み手の全組み合わせを確かめます。
結果は `acceptance.json` に保存します。

## 用意するもの

Docker、Python 3.12以降（boto3）、Java、Gradle 9.8 の配布物、Go、Rust、Node.js 24以降、pnpm。

## 実行する

出力先は `tools/interop` の外に置いてください。

```sh
python3 -m venv /tmp/eswa-interop-env
/tmp/eswa-interop-env/bin/pip install boto3
/tmp/eswa-interop-env/bin/python tools/interop/build.py --output /tmp/eswa-interop-build --gradle /path/to/gradle-9.8/bin/gradle
/tmp/eswa-interop-env/bin/python tools/interop/run.py --build /tmp/eswa-interop-build --output /tmp/eswa-interop-result
```

Java の成果物を取得済みなら、`--java-artifact-directory` でそのディレクトリを渡せます。
単体テストは同じ venv で `cd tools/interop && /tmp/eswa-interop-env/bin/python -m unittest test_run -v` を実行します。

## 出力

- `acceptance.json`: 全検証の結果と終了状態
- `<language>-calls.jsonl`: 各言語ドライバーへの呼び出しと応答
- `sdk.jsonl`: 測定側が boto3 で直接行った要求と応答（表の作成、保存された項目の読み取りなど）
- `queries.jsonl`: ドライバーが journal に送った Query の要求と応答、実項目のバイト数
- `buildinputs.json`: 使った固定値と取得したソース
- `build-commands.json`: ビルドコマンド、ログの場所、終了値、所要時間
- `cleanup.json`: 後片付けの結果

## 固定する値

`snapshots.json` は、ソースのコミット、アーカイブの SHA-256、Java の開発中スナップショットの jar、言語ごとの時刻精度を固定します。
JavaScript の精度がミリ秒なのは、公開 API が `Date` を使うためです。
コミットを更新するときは、対応するアーカイブの SHA-256 も一緒に更新してください。
