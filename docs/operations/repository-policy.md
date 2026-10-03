# リポジトリ運用方針

event-store-adapter グループの各リポジトリが従う、CI・ブランチ保護・マージ・レビュー・依存更新・エージェント運用の共通方針。2026-10-03 にオーナーと合意した。方針を変えるときは、オーナーの合意を得る。

対象は Orca に登録している次の 6 リポジトリである。README に載っている php・swift・dotnet は、Orca に登録した時点で対象に加える。

- [event-store-adapter-rs](https://github.com/j5ik2o/event-store-adapter-rs)
- [event-store-adapter-js](https://github.com/j5ik2o/event-store-adapter-js)
- [event-store-adapter-java](https://github.com/j5ik2o/event-store-adapter-java)
- [event-store-adapter-scala](https://github.com/j5ik2o/event-store-adapter-scala)
- [event-store-adapter-kotlin](https://github.com/j5ik2o/event-store-adapter-kotlin)
- [event-store-adapter-go](https://github.com/j5ik2o/event-store-adapter-go)

## 1. CI

- PR の CI には、対象パスの絞り込み（`paths`・`paths-ignore`）を付けない。絞り込みがあると、対象外のファイルだけを変える PR で CI が走らず、必須チェックが「待ち」のまま止まるからである。
- CI には、すべてのジョブの結果をまとめる集約ジョブ `CI Success` を置く。`if: always()` で必ず走り、依存先のどれかが成功以外（失敗・キャンセル・スキップ）なら失敗する。GitHub はスキップを合格とみなすので、上流の失敗で下流がスキップになったときも取りこぼさないためである。
- 外部の状況だけで全 PR が止まるジョブ（脆弱性の監査など）は、`CI Success` の依存に含めない。
- 各ジョブに `timeout-minutes` を付け、依存の取得などで止まったときに GitHub の既定の 6 時間まで待たないようにする。値は直近の成功した実行時間に余裕を持たせてリポジトリごとに決め、根拠を PR に書く。

### 公開の workflow

2026-10-03 にオーナーと合意した。java・kotlin・js の Snapshot の公開で見つかった問題（PR のブランチの公開、古いコミットの公開、公開の前の main への push）を、全リポジトリで繰り返さないためである。

- Snapshot など、main の変更のたびに公開する workflow は、PR の CI では公開しない。
- 公開するのは、main への push か定期実行の CI が成功したコミットで、起動した時点と公開の直前の両方で main の先頭であるものだけにする。checkout はそのコミットの SHA で行う。古い run を再実行したときも、公開の直前の確認で古いコードを公開しない。
- 公開のジョブから main にコミットや push をしない。Snapshot の版は、ジョブの中だけで決める。
- パッケージの登録先が OIDC の Trusted Publishing に対応しているときは、長く使うトークンではなく OIDC で公開する。対応していない登録先（Maven Central など）のときだけ、トークンを Secrets に置く（7 章）。

## 2. ブランチ保護（main）

- 必須のステータスチェックは `CI Success` の 1 つだけにする。matrix のジョブ名を直接必須にすると、matrix を変えたときに名前がずれるからである。
- 「マージ前にブランチを最新にする」（strict）を有効にする。
- 「会話の解決を必須」は有効にしない。独自の workflow によるゲートも使わない。bot（Codex など）は Renovate が PR を作り直すたびに指摘を残し、必須にすると CI が通る更新まで止まるからである（2026-10-03 に一度有効にして確認した）。bot の指摘は参考情報として扱う。
- 人手や worker の PR は、コーディネーターがマージ前に未解決のスレッドをすべて処理する。対応が必要なものは直し、不要なものは理由を返信してから解決にする。

## 3. マージ

- マージ方法は squash だけを許可する。マージコミットと rebase はリポジトリの設定で無効にする。
- マージ後はブランチを自動で削除する。

## 4. AI レビュー

- AI レビューは GitHub App（CodeRabbit、Devin Review、Codex など）に一本化する。
- workflow で動かす AI レビュー（OpenAI Reviewer、PR-Agent など）は置かない。そのための API キーの Secret も置かない。
- GitGuardian のセキュリティ検査は全リポジトリで有効にしておく。

## 5. 依存の更新（Renovate）

- 基本設定は全リポジトリ共通とする。`config:recommended` を土台に、minor・patch・pin・digest と devDependencies は、必須チェックが通れば自動マージする。
- メジャー更新は自動マージしない。
- 開いたままの Renovate の PR は、コーディネーターが定期的に棚卸しする。CI が通るものはマージする。通らないものは、worker に修正させるか、対応しない理由を `renovate.json` のブロック設定に `description` 付きで記録する（java の JUnit のメジャー更新のブロックと同じ形）。判断が必要なものだけオーナーに上げる。

## 6. エージェントによる運用

- 各リポジトリへの変更は、本リポジトリのセッション（コーディネーター）が Orca の orchestration で worker に指示して行う。オーナーはコーディネーターとだけやりとりする。
- worker は PR の作成までを行い、マージはしない。マージはコーディネーターが差分とチェック結果を確認してから、この方針に沿って行う。
- aidlc は使わない。takt は使ってよい。
- 用済みのワークツリーは破棄する。リポジトリにない未コミットの成果物が残っている場合は、退避してから破棄する。

## 7. オーナーが管理するもの

- Secrets（公開用の GPG 鍵など）と、リポジトリの公開・権限の設定はオーナーが管理する。コーディネーターは必要な名前と手順を調べて伝える。

## 8. takt の配置

2026-10-03、オーナーの不在中に、オーナーが示した方向(参照するスクリプトと設定、役割の分担)に沿って推奨で決め、同日にオーナーが確認した。

takt を使うリポジトリは、次の配置にそろえる。テンプレートは本リポジトリの `tools/takt/` にあり、各リポジトリには同じ内容を写す。変えるときは、まずテンプレートを変え、全リポジトリへ配る。

| 置き場所 | 内容 | 出どころ |
|:--|:--|:--|
| `.takt/workflows/`、`.takt/steps/`、`.takt/facets/` | takt-workflows の日本語バンドル(flash-default など) | [ideo-plus/takt-workflows](https://github.com/ideo-plus/takt-workflows) のインストーラーを、コミット `1760ce095a0ba4aba0b357b08bdf0e65ef910b92` に固定して実行する |
| `.takt/.takt-workflows`、`.takt/.gitignore` | 導入したバンドルの言語と版、追跡するファイルの許可リスト | インストーラーが作る |
| `.takt/runtime.yaml` | プロファイルとステップの割り当て | `tools/takt/runtime.yaml` |
| `.takt/config.yaml` | 言語、並列数、利用上限での切り替え | `tools/takt/config.yaml` |
| `.claude/settings.json` | takt のステップに `.takt/` の部品を読ませない設定 | インストーラーが既存の設定にマージする |
| `scripts/run-takt.sh`、`scripts/takt-claude.sh` | claude のアカウントを指定して takt を起動する入口 | `tools/takt/scripts/` |
| `mise.toml` | takt の版の固定(`"npm:takt" = "0.68.0"`) | 各リポジトリ |

- 役割の分担は、設計(計画・再計画)を Opus 5.5、レビュー(裁定・最終ゲート)を GPT-6.1-Sol、実装(テスト・実装)を Sonnet 5.5 とする。GPT-6.1-Sol を使うので、takt は 0.67 以上にする。
- takt の版は、全リポジトリで同じにする。Renovate では takt を更新しない(各リポジトリの `renovate.json` で、理由を `description` に書いて止める)。新しい版に上げるときは、コーディネーターが上の表の版と全リポジトリの `mise.toml` を同時に上げる。Renovate の自動更新に任せると、リポジトリごとに更新の日がずれて版がばらつくからである(2026-10-03 に 0.67.1 と 0.68.0 が混在した。同日オーナーと合意)。
- `~/.takt/runtime.yaml`(全体の設定)には何も書かない。全体の設定はすべてのプロジェクトに重ねて読まれるからである。
- 実行ログやセッションの状態(`.takt/runs/` など)はコミットしない。インストーラーが作る `.takt/.gitignore` に従う。
- インストーラーが入れる `.takt/tools/`(DDD 向けワークフロー用の ddd-lint。約 13MB で、プラットフォーム固有のバイナリを含む)はコミットしない。標準のワークフロー flash-default では使わないからである。`.takt/.gitignore` の `tools/` の許可を外す。インストーラーを入れ直したときは、この変更をやり直す。

## 適合状況（2026-10-03）

1〜4 章と 8 章は、6 リポジトリすべてで適合している。必須チェックは `CI Success` だけで、strict が有効（会話の解決の必須は無効）、マージは squash のみ、CI の全ジョブに `timeout-minutes` があり、workflow で動く AI レビューと独自のスレッドのゲートはない。同日に足した 1 章の「公開の workflow」には、java・kotlin・js・scala が適合している（scala は #853、js は手動実行の CI を除く #990 も含む）。rs は crates.io の OIDC への移行の途中である（下の表）。go はパッケージの登録先に公開しないので対象外。8 章の takt の版は、同日に 6 リポジトリとも 0.68.0 にそろえ、Renovate では更新しない設定にした（rs #240、js #992、java #686、scala #854、kotlin #822、go #383）。

| 残っている項目 | 対象 | 担当 |
|:--|:--|:--|
| scala の v1.0.338 の公開 | scala | 2026-10-03 にオーナーが `SONATYPE_USERNAME`・`SONATYPE_PASSWORD` を Central Portal のユーザートークンに更新し、同日 12:27 UTC の Snapshot で 2.13 と 3 の公開が通った。ただし、更新の前に動いたタグ `v1.0.338` の release（同日 02:38 UTC）は、Central Portal へのアップロードが HTTP 401 で失敗しており、Maven Central に出ていない。失敗したジョブを再実行して公開するかは、オーナーが決める。オーナー |
| rs の crates.io への公開の認証（1 章「公開の workflow」） | rs | 2026-10-03 にオーナーが crates.io で Trusted Publishing を登録し、#239 をマージした。タグの push で、`rust-lang/crates-io-auth-action` が OIDC で得たトークンを使って公開する。最初の OIDC での公開は v3.0.4 になる（毎日 00:00 UTC の定期実行で、変更があれば作られる）。公開を確かめたら、オーナーが `CARGO_TOKEN` を削除する（7 章）。コーディネーターとオーナー |
| Renovate の PR の棚卸し（5 章） | 全リポジトリ | コーディネーター。初回は 2026-10-03 に実施（Java 11 と両立しないメジャー更新は理由付きでブロック）。同日の 2 回目で、lint で止まっていた js の biome・jest の minor 更新を #978 で通した。js の mise.toml の sbt は、使っておらず conda-forge に 2.0.10 がなく `mise install` が失敗したので、#984 で外した。同日の 3 回目で、js の pnpm 12 を #982 で取り込み、TypeScript 7 は ts-jest と ts-node が直接対応するまで #987 でブロックした。`@google-cloud/spanner` v9 は、公開 API が利用者の `Database` を受け取るため、オーナーの判断で peerDependencies（`^8.7.1 \|\| ^9.0.0`）に移した（#986） |

ブロック中のメジャー更新は、Gradle 9 への移行（java #679、kotlin #807）と scala の JDK 25（#848）のあと、2026-10-03 に見直した。java #681・kotlin #815 で Spotless 8（kotlin は ktlint 1.8.0 による整形を含む）と foojay 1.0 のブロックを外し、Gradle を動かす JDK を 25 にした。Gradle 用の JDK の更新は LTS だけを許可する。JUnit 6 と、テスト用の JDK 11 のメジャー更新は、Java 11 でのテストを続ける限りブロックのまま。scala の sbt 2 は、プラグインの対応とビルド定義の移行を待つ理由に書き直して、ブロックを続ける（#850）。scala の `sbt-ci-release` を止める旧形式のルールは、効いていなかったので削除した（#852）。

java と kotlin の Snapshot workflow は、PR のブランチで CI が成功したときにも、そのブランチを checkout して Sonatype に公開していた（2023 年から。2026-10-02 には Renovate のブランチが公開され、マージ後に消えたブランチの checkout で失敗した）。2026-10-03 に java #682・#684、kotlin #817・#818・#820 で、main への push と定期実行の CI が成功し、かつ起動した時点と公開の直前の両方で main の先頭であるコミットだけを、その SHA で公開するように直し、main で公開が成功することを確かめた。

js の Snapshot workflow は、公開の前にバージョンを上げるコミットを main に push していた（公開に失敗しても版だけが上がり、push のたびに開いている PR が main より古くなり、provenance も付けられなかった）。同日、オーナーの判断で、版をジョブの中だけで決めて（`X.Y.Z-snapshot.<run_number>.<run_attempt>`）main には push しない形にし、公開の条件を java・kotlin とそろえた（#985）。main で `snapshot` タグに provenance 付きで公開され、`latest` が動かないことを確かめた。

js の npm への公開は、2026-09-16 の v3.1.1 の release から、`NPM_TOKEN` での公開が `404 Not Found - PUT` で失敗していた。2026-10-03 に、オーナーの判断で npm の Trusted Publishing（OIDC）に切り替えた。#983 で workflow を整え（`id-token: write`、Snapshot の `--tag snapshot`、既存のタグを手動で公開し直す入口）、オーナーの承認を得て npm の CLI（`npm trust github`）で `release.yml` と `snapshot.yml` を信頼済みの公開元に登録した。v3.1.1 を OIDC で公開し直し、spanner を peer 依存にした変更（#986）を含む 4.0.0 を、オーナーの判断でメジャーとしてリリースした（#989 で移行の注記を追加。`latest` は 4.0.0）。続けてオーナーが `NPM_TOKEN` を削除し、npm の Publishing access をトークンを許さない設定（`mfa=publish`）に切り替えた。workflow からも `NODE_AUTH_TOKEN` を外し（#991）、main でトークンなしに、Snapshot を OIDC と provenance 付きで公開できることを確かめた（`4.0.1-snapshot.5405.1`）。

js の Spanner の emulator テスト（任意で実行するもの）は、最新の emulator イメージに shell がなく起動待ちで失敗していた。直す過程で、書き込みが拒否されたときにトランザクションをロールバックしていない実装のバグが見つかり、spanner v8 では待ち続ける原因になっていたので、ロールバックを足して直した（#988。v8・v9 とも全件成功）。
