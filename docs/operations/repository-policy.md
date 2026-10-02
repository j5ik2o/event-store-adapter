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
| `mise.toml` | takt の版の固定(`"npm:takt" = "0.67.1"`) | 各リポジトリ |

- 役割の分担は、設計(計画・再計画)を Opus 5.5、レビュー(裁定・最終ゲート)を GPT-6.1-Sol、実装(テスト・実装)を Sonnet 5.5 とする。GPT-6.1-Sol を使うので、takt は 0.67 以上にする。
- `~/.takt/runtime.yaml`(全体の設定)には何も書かない。全体の設定はすべてのプロジェクトに重ねて読まれるからである。
- 実行ログやセッションの状態(`.takt/runs/` など)はコミットしない。インストーラーが作る `.takt/.gitignore` に従う。
- インストーラーが入れる `.takt/tools/`(DDD 向けワークフロー用の ddd-lint。約 13MB で、プラットフォーム固有のバイナリを含む)はコミットしない。標準のワークフロー flash-default では使わないからである。`.takt/.gitignore` の `tools/` の許可を外す。インストーラーを入れ直したときは、この変更をやり直す。

## 適合状況（2026-10-03）

1〜4 章と 8 章は、6 リポジトリすべてで適合している。必須チェックは `CI Success` だけで、strict が有効（会話の解決の必須は無効）、マージは squash のみ、CI の全ジョブに `timeout-minutes` があり、workflow で動く AI レビューと独自のスレッドのゲートはない。

| 残っている項目 | 対象 | 担当 |
|:--|:--|:--|
| scala の publish の認証情報 | scala | GPG 鍵は更新後に署名まで通った（2026-10-03）。いまは Central Portal へのアップロードが `Server redirected too many times` で失敗する。`SONATYPE_USERNAME`・`SONATYPE_PASSWORD` が 2023 年の値のままで、成功している java（2025-04 更新）と異なるため、Central Portal のユーザートークンへの更新が要る。オーナー（7 章） |
| Renovate の PR の棚卸し（5 章） | 全リポジトリ | コーディネーター。初回は 2026-10-03 に実施（Java 11 と両立しないメジャー更新は理由付きでブロック） |
| ブロック中のメジャー更新の見直し | java・kotlin・scala | Gradle 9 への移行（java #679、kotlin #807）と scala の JDK 25（#848）を 2026-10-03 にオーナーが承認した。マージ後に、Spotless 8・foojay 1.0・sbt 2 などのブロックを見直す。JUnit 6 は Java 11 でのテストを続ける限りブロックのまま。コーディネーター |
