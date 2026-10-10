# 6言語で同じ DynamoDB Local を読み書きする

共通契約 v4 と [DynamoDB 保存仕様](../../docs/spec/storage/dynamodb.md) の相互運用を実測する入口です。
各言語のドライバーが公開の生成入口と4操作を呼びます。既存の適合試験は再実行しません。
共通処理は入力、結果の記録、比較、資源の管理を担当します。

## 実行する

Docker、Python 3.12以降、Java、Gradle 9.8、Go、Rust、Node.js 24以降、pnpmを用意します。
取得する本体のソースと Java の開発中成果物は `snapshots.json` に固定しています。
共通契約の版と各ライブラリの版は別です。正式リリースを仮定せず、使用した入力を `buildinputs.json` に残します。

```sh
python3 -m venv /tmp/eswa-interop-env
/tmp/eswa-interop-env/bin/pip install boto3
python3 tools/interop/build.py --output /tmp/eswa-interop-build --gradle /path/to/gradle-9.8/bin/gradle
/tmp/eswa-interop-env/bin/python tools/interop/run.py --build /tmp/eswa-interop-build --output /tmp/eswa-interop-result
```

Gradle 9.8 が通常の `gradle` コマンドで使える場合は `--gradle` を省略できます。
受入済み Java のファイルがある場合は `--java-artifact-directory` でそのディレクトリを指定できます。
取得済みソースは指定コミットのアーカイブとファイル集合・内容・シンボリックリンクを照合し、追加されたソースも拒否します。この入口が生成する JavaScript の依存ディレクトリと `packages/library/dist` だけを照合対象から除きます。他言語のビルド出力は取得済みソースの外に置きます。
ビルドが読む言語別のリンクも指定コミットの取得先へ更新し、Java の公開 sources 成果物をそのソースと照合します。
成功済みのビルドがあり、指定コミットと他のドライバー、その実行時の入力が変わっていなければ、`build.py --only rust` のように変更した対象だけ再ビルドできます。
ビルド開始時に前回の成功記録を無効にするため、取得やビルドに失敗した後は全ドライバーを再ビルドしてください。
測定はビルド失敗の記録、現在のソースや取得先との不一致、成果物のバイト数や指紋の不一致を資源取得前に拒否します。ソースを変えた場合も、測定の前に再ビルドが必要です。
JavaScript は、このドライバーが実際に読み込む本体と依存のコード、パッケージ情報、依存の解決先を `js-runtime-inputs.json` に記録します。測定前にコードを実行せず照合し、実行中に記録外のファイルを読み込もうとした場合も拒否します。未使用の依存ファイルは記録しません。
検証には Python の `assert` を使います。`-O` と `PYTHONOPTIMIZE` による最適化実行は、取得と測定の入口で拒否します。
測定結果の出力先には、存在しない新しいディレクトリを指定してください。

入口の回帰試験は、上記の仮想環境で次のように実行できます。

```sh
/tmp/eswa-interop-env/bin/python -m unittest discover -s tools/interop -p 'test_entrypoints.py' -v
```

実行ごとに digest 固定の DynamoDB Local をループバックアドレスの空きポートで起動し、所有する journal・snapshot・head の3表と履歴索引を一度作ります。
設定項目はライブラリの生成処理が作ります。全言語で同じ表と設定を使い、独立したソフトウェア開発キットの読み取りで照合します。
終了時には、成功・失敗を問わずその実行が作った表とコンテナを削除します。

## 原票を読む

- `acceptance.json`：6書き手×6読み手の36組、順次追記、楽観ロック、時刻の期待と実測、保存属性、ページ読み取り、資源終了。
- `<言語>-calls.jsonl`：公開操作へ渡した入力と、その実応答。長時間動くドライバーの終了値は `driver_exits` に記録します。
- `sdk.jsonl`：独立したソフトウェア開発キットの要求・応答。バイナリは Base64、バイト数、SHA-256を保存します。
- `queries.jsonl`：公開読み取りが送った実 Query、Local の原応答、有効な応答、実項目のバイト数、続きのキー。
- `buildinputs.json`、`build-commands.json`：各ソースのコミット、アーカイブと成果物の SHA-256、実ビルドコマンドの終了値。
- `source-inputs.json`、`js-runtime-inputs.json`：取得先の実参照先とファイル集合の指紋、JavaScript の実読込ファイル・パッケージ情報・依存の解決先。
- `ownership.json`、`resource-commands.json`、`cleanup.json`：所有資源、実コマンド、表の削除とコンテナの終了。

36組には全言語が正確に表せるミリ秒の時刻を使います。別のナノ秒イベントを6言語で読み、JavaScript の標準時刻型への変換と、他言語のナノ秒保持を区別して記録します。
順次追記では最後のヘッドが6、最新スナップショットが4になるため、両者を区別した読み取りも確認します。

## Local のページ境界を区別する

まず12件の約120 KiBのペイロードを公開操作で書き、補正なしの Local を独立して Query します。
Local が実際に続きのキーを返せば、そのまま全言語の複数ページ読み取りを検証します。
バイナリ属性の実総量が1 MiBを超えても原応答が一度に返る場合は、原票の `local_physical_boundary.status` を `not-observed` とし、物理境界の成功には数えません。

この条件でだけ、受入済み Java の `DynamoDbEventQueryPagination` と同じ方式で実応答の項目サイズを測り、1 MiB以内の実接頭辞と実末項目のキーを返します。
続きは、そのキーを使った Local への実 Query です。原応答と補正した応答を両方保存します。
`Limit` や期待イベントからの応答生成は使いません。
この検証は `accepted-real-prefix-boundary`、全体の結果は `passed-with-local-boundary-limitation` として通常の物理境界成功と区別します。
根拠は [保存仕様の全ページ読み取り](../../docs/spec/storage/dynamodb.md#72-イベント) と、受入済みラッパーの試験原票にある実接頭辞・実末キー・実次 Query の方式です。
