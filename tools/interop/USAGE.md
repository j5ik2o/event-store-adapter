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

Gradle 9.8 の配布物の `bin/gradle` が通常の `gradle` コマンドで使える場合は `--gradle` を省略できます。シンボリックリンクは実行先を解決します。起動後に配布物を選ぶラッパーは扱わないため、`--gradle` に配布物の `bin/gradle` を直接指定してください。
ビルドと測定結果の出力先は `tools/interop` の外に置いてください。出力先の実パスを解決し、このソースディレクトリ自身やその配下を指す場合は、ディレクトリの作成・取得・コンパイル・資源の開始前に拒否します。シンボリックリンク経由でも同じ条件で判定します。
受入済み Java のファイルがある場合は `--java-artifact-directory` でそのディレクトリを指定できます。
ソースアーカイブは、初回に指定コミットの HTTPS 取得で確認した SHA-256 を `snapshots.json` に固定しています。再利用するキャッシュも新規取得も、この期待値に一致してから内容を読みます。指定コミットを更新するときは、対応する `source_archives` のコミットと期待ハッシュも更新してください。両者のコミットが食い違う場合は取得前に拒否します。
取得済みソースは指定コミットのアーカイブとファイル集合・内容・シンボリックリンクを照合し、追加されたソースも拒否します。この入口が生成する JavaScript の依存ディレクトリと `packages/library/dist` だけを照合対象から除きます。他言語のビルド出力は取得済みソースの外に置きます。
取得と展開は専用の一時ディレクトリで検証してから確定するため、途中で失敗しても同じ出力先で全ビルドを再試行できます。取得済みソースの欠落だけなら既存アーカイブから復旧し、元の欠落と復旧結果を `source-recovery.jsonl` に記録します。追加や改変が混在する場合は元のキャッシュを残して拒否します。読めないアーカイブや期待ハッシュと異なるアーカイブは再取得します。新規取得のハッシュが違う場合はキャッシュを確定せずに拒否します。
取得キャッシュの親 `sources` は、取得・一時領域の作成・置換・欠落復旧より前に、出力先の内側にある通常のディレクトリかを確認します。リンクや通常ファイルの場合は拒否し、参照先のアーカイブや欠落ディレクトリを変更しません。測定前のソース照合でも同じ親を確認します。
ビルドが読む言語別のリンクも指定コミットの取得先へ更新し、Java の公開 sources 成果物をそのソースと照合します。
Java の実行用とソース用の2成果物も固定ハッシュで照合します。壊れた出力キャッシュを無効にし、明示指定されたディレクトリ、または固定された公式の開発中成果物から専用の一時領域へ取得します。2成果物のハッシュと指定ソースとの一致を確認してから確定するため、コピーや取得が中断しても同じ出力先で再試行できます。明示指定したディレクトリのファイルが欠けている、または不正な場合は拒否し、通信で代替しません。
成功済みのビルドがあり、指定コミットと他のドライバー、その実行時の入力が変わっていなければ、`build.py --only rust` のように変更した対象だけ再ビルドできます。
ビルド開始時に前回の成功記録を無効にするため、取得やビルドに失敗した後は全ドライバーを再ビルドしてください。
前回のコマンド履歴や入力記録のJSONを読めない場合も、成功記録を無効にして `build-failure.json` へ失敗を残します。不正なJSONを修復または取り除いてから、同じ出力先で全ビルドを再試行できます。
測定はビルド失敗の記録、現在のソースや取得先との不一致、成果物のバイト数や指紋の不一致を資源取得前に拒否します。ソースを変えた場合も、測定の前に再ビルドが必要です。
ビルドの既知メタデータ保存先がシンボリックリンクなら、取得と子コマンドの起動前に拒否します。対象は `build-commands.json`・`buildinputs.json`・`drivers.json`・`build-failure.json`・`source-inputs.json`・`js-runtime-inputs.json`・`source-recovery.jsonl` です。失敗記録は同じ親ディレクトリの一時ファイルから置換するため、保存先がリンクでも外部の参照先へ書き込みません。
各ビルドコマンドの起動前には、その試行が保存する `build-<対象>-<試行回数>.log` と、標準出力を分ける場合の `.stdout` も確認します。出力先の内側にある通常ファイル以外が既にあれば拒否し、参照先へ書き込みません。
Java・Kotlin・Scala は、実クラスパスの各ディレクトリの参照先、存在状態、全ファイルの集合と内容を `buildinputs.json` に記録します。クラスと実行時リソースの追加・欠落・改変、ディレクトリの参照変更を測定前に拒否します。現在存在しないリソース用ディレクトリも記録し、後からの作成を検出します。ディレクトリ内部のシンボリックリンクや通常ファイル以外の入力は扱いません。
全ビルドと `--only jvm` は、選択されたJava・Kotlin・Scalaのクラスとリソースの生成先だけを清掃して再生成します。Gradleのキャッシュ、他言語の生成物、その外の利用者ファイルは清掃しません。部分ビルドは、清掃前に前回入力の整合性を確認します。
取得と清掃の前に、`jvm` の親生成先と `classes`・`resources` が出力先の内側にある通常のディレクトリかを確認します。いずれかがシンボリックリンクなら拒否し、両子も参照先も変更しません。
同じ段階で、Gradleが保存する `jvm/classpath.txt`・`jvm/dependencies.txt` も確認します。既存の保存先がシンボリックリンクや通常ファイル以外なら、取得・清掃・Gradle起動前に拒否します。
GoとRustの生成パッケージも、選択された場合だけ既知の入力から更新します。Goの生成先は `main.go`・`go.mod`・`go.sum`・`driver`、Rustの生成先は `Cargo.toml`・`Cargo.lock`・`src/main.rs` と `target` ディレクトリだけを扱います。余剰のGoソースやCargoの `build.rs`・ライブラリ・追加バイナリ・例・試験・性能測定用の入力が残っていれば、取得とコンパイル前に拒否します。余剰入力を確認して生成先から取り除き、全ビルドを再試行してください。Rustを選択した場合は、既存の `target` 全体を出力先直下の `.rust-target-backup-*/target` へ退避し、空の生成先から依存を含めてビルドします。退避した元データ、`Cargo.lock`、未選択のRust生成物、他言語の生成物、生成パッケージ外の利用者ファイルは清掃しません。生成パッケージのルートや既知の入力がシンボリックリンクなら拒否し、その参照先は変更しません。
Goのビルドと依存一覧取得は、子の環境だけに `GOWORK=off`、空の `GOFLAGS`、`GOENV=off` を設定します。`GOFLAGS` のファイル差し替えや、保存済みのGo環境設定を採用せず、取得済みの固定ソースを使います。親の環境と設定ファイルは変更しません。適用した設定は `buildinputs.json` の `go_build_environment` に記録します。GoのモジュールとRustの依存指定に書くパスは引用し、空白・引用符・バックスラッシュを保ちます。
Rustを選択したビルドは、Cargoの呼出し場所である `tools/interop` と全親ディレクトリの `.cargo/config`・`.cargo/config.toml`、`CARGO_HOME`（未指定なら利用者ホームの `.cargo`）の `config`・`config.toml` を取得前と各Cargo起動前に検査します。この入口では外部のCargo設定を扱わないため、存在する場合は内容を読まずに拒否します。探索先と設定ファイルが存在しないことを `buildinputs.json` の `cargo_config_inputs` に記録します。`RUSTC`・`CARGO_BUILD_RUSTC` と、それぞれの `RUSTC_WRAPPER`・`RUSTC_WORKSPACE_WRAPPER` 相当の環境指定も、値を記録せずに拒否します。親の環境、共有設定、認証情報は変更せず、共有の `CARGO_HOME` とレジストリーのキャッシュは再利用します。
Cargoのビルドと依存情報取得では、子の `CARGO_TARGET_DIR`・`CARGO_BUILD_TARGET_DIR`・`CARGO_BUILD_BUILD_DIR` を、記録と起動に使う `rust-driver/target` に固定します。ビルドには同じ `--target-dir` も渡し、依存情報が返した実出力先と照合します。設定は `cargo_build_environment` に記録します。別の対象プラットフォームを選ぶ `CARGO_BUILD_TARGET` と、出力やコンパイル内容を変更できる `RUSTFLAGS`・`CARGO_ENCODED_RUSTFLAGS`・`CARGO_BUILD_RUSTFLAGS`・`CARGO_TARGET_<対象>_RUSTFLAGS`、対象別のリンカーを選ぶ `CARGO_TARGET_<対象>_LINKER` は、取得や子コマンドの起動前に変数名だけを示して拒否します。依存情報の構造化結果は標準出力を保存した `.stdout` ファイルだけから解析します。標準エラーの診断と標準出力は従来の `.log` にも残し、`CARGO_LOG` による診断があっても実終了値に従って判定します。
Java・Kotlin・Scalaをビルドする場合は、実際に使うGradle配布物と利用者ホームを確定します。利用者ホームの `init.gradle`・`init.gradle.kts`、利用者ホームと配布物の `init.d` にある `.gradle`・`.gradle.kts` ファイルがあれば、内容を読まず、取得とクラス清掃の前に拒否します。実適用される利用者ホーム・`drivers/jvm`・配布物直下の `gradle.properties` も検査し、非空ファイルとシンボリックリンクを内容を読まずに拒否します。空の通常ファイルは利用でき、存在とバイト数を記録します。Gradleの起動直前にも再確認し、同じ利用者ホームを `--gradle-user-home` で指定します。適用先と初期化スクリプトの不存在、設定ファイルの状態を `gradle_init_inputs` に記録し、既存のキャッシュ、共有設定、認証情報は保持します。
薄いJava・Kotlin・Scalaドライバーの入力指紋には、コンパイル対象になる隠しソースも含めます。Javaは `drivers/jvm` 直下の `.java` ファイル、Kotlin・Scalaは同ディレクトリ配下の `.kt`・`.scala` ファイルを記録します。隠し親ディレクトリのKotlin・Scalaソースも、測定前と未選択ドライバーの部分ビルド前に照合します。`drivers` 自身と全言語の通常配下・隠し配下のディレクトリがシンボリックリンクなら、取得・コンパイル・測定資源の開始前に拒否します。実在する通常ファイルへのリンクは内容を指紋に記録し、固定ライブラリを指す `sources` 内のソース別名リンクも引き続き利用します。無関係な隠しキャッシュは指紋に追加しません。
JavaScript は、このドライバーが実際に読み込む本体と依存のコード、パッケージ情報、依存の解決先を `js-runtime-inputs.json` に記録します。測定前にコードを実行せず照合し、実行中に記録外のファイルを読み込もうとした場合も拒否します。未使用の依存ファイルは記録しません。
JavaScriptを選択したビルドでは、取得ソースのルートと `packages/library`・`packages/examples`・`packages/tests` にある既存の `node_modules` を、出力先直下の `.js-dependencies-backup-*` 内へ退避します。その後、固定された依存指定から `pnpm install --frozen-lockfile` で再生成し、以前の依存コードの改変を新しい実行入力として採用しません。退避した全データと内部のリンク、リンク先、共有のパッケージキャッシュ、未選択のJavaScript依存は保持します。
固定ソースのpnpmは12.10.1です。このソースはpnpmfileのフックを必要としないため、導入とビルドに `--ignore-pnpmfile` を渡します。子の環境でも `PNPM_CONFIG_IGNORE_PNPMFILE=true` と同じ設定の表記違いを固定し、入れ子のpnpmへ引き継ぎます。外部のフックを実行せず、親の設定・環境・認証情報は変更しません。適用した引数と環境は `buildinputs.json` の `pnpm_hook_settings` に記録し、JavaScriptを選ばない部分ビルドでは前回の記録を保持します。
ビルド、JavaScriptの入力記録・照合、ドライバー、所有資源の管理コマンドを起動するときは、子の環境から `NODE_OPTIONS`、`JAVA_TOOL_OPTIONS`、`JDK_JAVA_OPTIONS`、`_JAVA_OPTIONS`、`JAVA_OPTS`、`GRADLE_OPTS`、`LD_PRELOAD`、`LD_AUDIT`、`DYLD_INSERT_LIBRARIES` を除きます。検査より先に追加コードを読む経路を閉じるためです。親の環境は変えず、`PATH`、`JAVA_HOME`、通常の設定と明示ドライバー入力を引き継ぎます。
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
- `source-recovery.jsonl`：不完全な取得済みアーカイブやソースの欠落と、再取得・復旧の記録。
- `ownership.json`、`resource-commands.json`、`cleanup.json`：所有資源、実コマンド、表の削除とコンテナの終了。

36組には全言語が正確に表せるミリ秒の時刻を使います。さらに全6言語の書き手へミリ秒未満を含む時刻を渡し、公開操作で書きます。独立したソフトウェア開発キットで実保存時刻を読み、書き手の精度に基づく期待値と照合して `precision_writes` に保存します。その6件を全6言語の読み手で読む36組を `precision` に記録します。JavaScriptの書き込み時のミリ秒丸めと、他言語が保存したナノ秒をJavaScriptで読むときの丸めを区別します。公開操作とQueryの件数は実呼出し数を記録します。
全6言語の重複追記の拒否では、独立したソフトウェア開発キットで取得した完全な集約ヘッドを前後で比較し、両実項目を `optimistic_lock` に残します。ジャーナルと最新スナップショットの公開読み取りも、引き続き不変を確認します。
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
