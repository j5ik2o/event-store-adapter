# コーディネーター引き継ぎ（HAND_OFF）

- 最終更新: **2026-11-08 10:09 JST**
- 更新者: コーディネーター
- 更新方針: マイルストーンの完了または大きな方針変更のたび、およびそれとは別に最長1時間おきに更新する。HAND_OFF の PR は同時に1本までとし、前の PR がマージされるまで次を作らない。
- 使い方: 次の担当は、会話履歴や端末の下書きに依存せず、このファイルだけで現在地と次の作業を再開できるようにする。数値と状態は更新時点の実測であり、次の更新時に再確認する。

## 0. 現況サマリ

- **ESA 7repo**（common, js, java, kotlin, scala, go, rs）: open PR は **0**、非 Dashboard の open Issue も **0**。open Issue は常設の Renovate Dependency Dashboard **6件のみ**。
- 各言語 repo の main CI は **failed なし**。2026-11-08 10:09 JST 時点で js / go / rs は 19:26〜19:28 JST、java は 08:27 JST の直近実行が success、scala も success。kotlin は新しい実行が queued（ランナー待ち、失敗ではない）。common repo には CI がない。
- **現在の実作業**: ESA 側はなし。Renovate は 2026-11-07 19:33 の加藤さんの決定で使用量削減のため **off**。既存 Renovate PR の修正・リベース・整理・クローズは禁止（WIP 超過の解消目的でも）。マージしてよいのは CI 全緑かつ未対応コメントなしのものだけ。cqrs-es は 6 言語の RMU 復旧と後続（デプロイ資産・staticcheck・運用手順・障害注入 e2e）まで完了。hub #20（`9d78adc`）と #21（`ffc1264`）、kotlin #14 / #16（`f1925bf` / `9200537`）、scala #15（`550de5d`）が MERGED。open の実装 PR はなく、hub の追跡は #3 のみ。詳細は cqrs 側の HAND_OFF を参照。
- **次のマイルストーン**: `cqrs-es-example` の **M2**（ESA v5 移行と RMU 復旧）は rs / js / java / go で完了。6 言語の RMU 復旧 A 案と後続も完了。残るのは hub #3 の完了確認のみ。ハブの HAND_OFF は PR #21 まで MERGED（[docs/HAND_OFF.md](https://github.com/j5ik2o/cqrs-es-example/blob/main/docs/HAND_OFF.md)）。
- **WIP（Renovate を除く）**: **0**。Renovate は rs 5 / java 3 / js 3 が open だが、off と「WIP に数えない」方針のため WIP には含めず、修正・リベース・整理・クローズもしない。加藤さんの指示があるまで当方は新規 PR を作らない（HAND_OFF の定期更新 PR はこの禁止の対象外）。
- **ESA 側の次の節目**: 30 保存先の実装完了（2026-10-28）後の「公開の準備」。java を先に正式版として出し、kotlin・scala を java の正式版へ切り替えてから出す。各版は公開直前にオーナー承認を取る。まだ着手していない。
- **残置 worktree**: `java-769-notification-thread`（B 案の未コミット差分）と `rs-349-review`（untracked の aidlc 監査ファイル）。クリーン確認ができないため保持している。詳細は「3. Orca の現況」。
- **PR #83** は CLOSED。再開・再実装しない。

## 1. マイルストーンと完了条件

### 1.1 ESA: 公開の準備（未着手・オーナー承認待ち）

- 2026-10-27/28 に、6 言語 × 5 保存先 = 30 組の実装がそろい、マイルストーン「全言語で全保存先を提供する」は閉じた。
- 完了条件（実績）: 6 言語それぞれで 5 保存先を使えること、実際の SQLite ファイルまたは DynamoDB Local / Spanner / Bigtable のエミュレーターに対する適合試験で失敗 0・未検証 0、英語と日本語の文書がそろうこと、提供していないことを理由に保存先全体を対象外にしないこと。
- 次の作業: 公開の準備。java を先に出し、kotlin・scala を java の正式版へ切り替えてから出す。各言語の版は公開直前にオーナー承認を取る。
- 公開・リリース・force push は、オーナーの明示承認がない限り禁止。
- 参照: [docs/plan/implementation-plan.ja.md](plan/implementation-plan.ja.md) の「30 組の実装がそろった（2026-10-28）」。

### 1.2 cqrs-es: M2（rs / js / java / go は完了、残るは hub #3 の追跡のみ）

- 対象: `cqrs-es-example` ハブと、`cqrs-es-example-rs` / `-js` / `-java` / `-go`。順序は **rs → js → java → go**（rs が最初、go が最後）。
- M3 で Kotlin を新規作成、M4 で Scala を作り直す。
- 目標 ESA 版: Go / Java / Kotlin / Scala は v5.1.0、JS / Rust は v5.2.0（2026-11-06 時点でタグ確認済み）。
- **共通完了条件（各言語）**: [cqrs-es-example/docs/acceptance-criteria.md](https://github.com/j5ik2o/cqrs-es-example/blob/main/docs/acceptance-criteria.md) §8.1。
  - 目標の ESA 版を固定し、v5 の envelope API を使う。
  - イベントのメタデータを payload に埋め込まず、envelope で運ぶ。
  - journal / snapshot / head の 3 テーブルと snapshot の GSI を `dynamodb-setup` で作る。
  - 3 テーブルの `__config__` を同じ `store_id` と `layout_version=1` で作る。
  - Write API が 8 つの Mutation と `healthCheck` を公開する。
  - Read API が 6 つの Query を公開し、`userAccountId` で閲覧範囲を絞る。
  - **RMU が head の Streams を購読し、`(aggregate_id, seq_nr)` で重複を捨て、飛びを journal から埋める。**（M2 の head Streams 条件）
  - RMU が処理位置を `read_model_positions` に記録する。
  - `docker compose` と LocalStack で Write → RMU → Read の e2e が成功する。
  - main の CI が lint / test / e2e のすべてで緑。PR の CI も同じ 3 ジョブで緑。
  - 検査の無効化・失敗の握りつぶしをしない。
  - README と `docs/` に起動方法、ポート、環境変数、e2e の実行方法を書く。
  - Renovate の未処理更新を説明できる状態にする（Renovate は 19:33 に off。既存 PR の整理はしない）。
- 現況（acceptance-criteria §9 と 2026-11-08 10:09 JST の実測）: 6 言語の RMU 復旧 A 案が揃い、M2 の主要作業は完了。後続も kotlin #14 / #16、scala #15 が MERGED し、open の実装 PR はない。hub #20 `9d78adc` と #21 `ffc1264` も MERGED。hub の追跡は #3 のみ。個別の経緯は cqrs 側の HAND_OFF を参照。
- M2 中の Renovate: 2026-11-07 19:33 に使用量削減のため **off**。既存 Renovate PR の修正・リベース・整理・クローズは禁止（WIP 超過の解消目的でも）。マージは CI 全緑＋未対応コメントなしのものだけ。判断は acceptance-criteria §10.h 待ちだが、当面は上記を優先する。1 リポジトリあたり open PR は 3 本まで（Renovate を除く）。

### 1.3 判断待ち（オーナー）

`cqrs-es-example/docs/acceptance-criteria.md` の以下は「状態: 判断待ち」。推奨案は文書に記載があるが、決定ではない。

- §10.f Kotlin / Scala のビルドと JDK。推奨: Kotlin は Gradle KTS + JDK 17、Scala は sbt + Scala 3.6.4、CI の JDK を 17 にそろえる。
- §10.g AWS デプロイ用資産（Rust の Terraform / Helm、JS の Lambda）を残すか。推奨: 当面残し、M0〜M4 の対象外と明記。
- §10.h Renovate の運用。推奨: patch のみ CI 緑で自動、minor / major は手動、ESA はすべて手動。
- §10.i ドメインイベントの互換性とデータ移行。推奨: 既存 LocalStack データは移行せず作り直す。
- §10.j GraphQL の型名・スカラー・操作集合。推奨: Go のスキーマを基準に `GroupChat` / `Member` / `Message`、`NaiveDateTime`、`editMessage` を必須にする。
- §10.k Read Model の保存先。推奨: M2〜M4 は MySQL を続け、DynamoDB の 3 テーブルとは別だと明記する。

ESA 側の後で検討する課題（次のマイルストーン候補、オーナー判断待ち）:

- Spanner で ABORTED したトランザクションを待たずに再試行している（java・js）。
- java の SQLite / Spanner / Bigtable の非同期版が、呼び出し元のスレッドで I/O を行って完了済みの Future を返す（kotlin・scala はこれを包む）。

## 2. リポジトリごとの open PR / Issue（2026-11-08 10:09 JST）

### 2.1 ESA 7repo

open PR はすべて 0。非 Dashboard の open Issue も 0。open Issue は次の常設 Dashboard のみ。閉じない。

- common `event-store-adapter`: なし
- js: [#4 Dependency Dashboard](https://github.com/j5ik2o/event-store-adapter-js/issues/4)
- java: [#4 Dependency Dashboard](https://github.com/j5ik2o/event-store-adapter-java/issues/4)
- kotlin: [#4 Dependency Dashboard](https://github.com/j5ik2o/event-store-adapter-kotlin/issues/4)
- scala: [#4 Dependency Dashboard](https://github.com/j5ik2o/event-store-adapter-scala/issues/4)
- go: [#3 Dependency Dashboard](https://github.com/j5ik2o/event-store-adapter-go/issues/3)
- rs: [#12 Dependency Dashboard](https://github.com/j5ik2o/event-store-adapter-rs/issues/12)

### 2.2 cqrs-es リポジトリ

ハブ `cqrs-es-example`:

- Issue: [#3 [M2] 追跡: ESA v5 移行（rs → js → java → go）](https://github.com/j5ik2o/cqrs-es-example/issues/3)（#13 / #4 は CLOSED）
- PR: なし（#21 は MERGED `ffc1264`、#20 は `9d78adc`、#19 は `c9410e2`、#18 は `fdb2e48`、#17 は `882b460`、#16 は `5dc6fb0`、#15 は `80857d3`、#14 は `583b5e9`、#11 / #12 も MERGED）

`cqrs-es-example-rs`:

- Issue: [#551 Renovate PR を整理する](https://github.com/j5ik2o/cqrs-es-example-rs/issues/551)、[#8 Dependency Dashboard](https://github.com/j5ik2o/cqrs-es-example-rs/issues/8)（#547〜#550 / #600 / #604 は CLOSED）
- PR: [#597 Terraform aws v6](https://github.com/j5ik2o/cqrs-es-example-rs/pull/597)、[#592 aws_lambda_events v1](https://github.com/j5ik2o/cqrs-es-example-rs/pull/592)、[#591 mysql Docker tag v26](https://github.com/j5ik2o/cqrs-es-example-rs/pull/591)（判断待ち・paths-ignore）、[#590 Helm mysql v14](https://github.com/j5ik2o/cqrs-es-example-rs/pull/590)、[#582 sqlx 0.9.0](https://github.com/j5ik2o/cqrs-es-example-rs/pull/582)（#601 は `f958c54`、#602 は `e5d2227`、#603 は `a5ee641`、#605 は `0f1ea05` で MERGED）

`cqrs-es-example-js`:

- Issue: [#830 Renovate PR を整理する](https://github.com/j5ik2o/cqrs-es-example-js/issues/830)、[#4 Dependency Dashboard](https://github.com/j5ik2o/cqrs-es-example-js/issues/4)（#825〜#829 / #836 / #838 / #840 は CLOSED）
- PR: [#819 functions-framework v5](https://github.com/j5ik2o/cqrs-es-example-js/pull/819)、[#812 @types/node](https://github.com/j5ik2o/cqrs-es-example-js/pull/812)、[#811 yargs v18](https://github.com/j5ik2o/cqrs-es-example-js/pull/811)（M2 は #831 `834fe15`、#832 `108ceee`、#833 `72e704b`、#834 `437f230`、#835 `bd6d933`、#837 `f7de1cf`、#839 `e1ca7ef`、#841 `2288a2f` で MERGED）

`cqrs-es-example-java`:

- Issue: [#588 Renovate PR を整理する](https://github.com/j5ik2o/cqrs-es-example-java/issues/588)、[#4 Dependency Dashboard](https://github.com/j5ik2o/cqrs-es-example-java/issues/4)（#583〜#587 / #623 / #625 / #627 は CLOSED）
- PR: [#616 Spring Boot v4](https://github.com/j5ik2o/cqrs-es-example-java/pull/616)、[#608 java-jdk v25](https://github.com/j5ik2o/cqrs-es-example-java/pull/608)、[#559 Gradle v9](https://github.com/j5ik2o/cqrs-es-example-java/pull/559)（#400 は `a4a1035`、#618 `b8d1a91`、#619 `914f7d1`、#620 `8fd6020`、#621 `ed3540a`、#622 `8547e1c`、#624 `c73b03c`、#626 `ec846f8`、#629 `3b31c75` で MERGED）

`cqrs-es-example-go`:

- Issue: [#32 Windows 11/WSL2 support](https://github.com/j5ik2o/cqrs-es-example-go/issues/32)、[#29 Deploy to AWS](https://github.com/j5ik2o/cqrs-es-example-go/issues/29)、[#7 Dependency Dashboard](https://github.com/j5ik2o/cqrs-es-example-go/issues/7)（#672 / #680 / #682 / #684 は CLOSED）
- PR: なし（#687 は MERGED `759fae4`、#686 は `98ceb9c`、#678 / #679 / #681 / #683 / #685 / #573 も MERGED）。

`cqrs-es-example-kotlin`: open Issue / PR なし（#14 は MERGED `f1925bf`、#16 は `9200537`、#12 は `ac3ec0d`）。

`cqrs-es-example-scala`: open Issue / PR なし（#15 は MERGED `550de5d`、#13 は `8640751`、#9 は `03d1951`）。

WIP（Renovate を除く open PR 数、上限3本）:

| repo | open PR（Renovate 除く） | Renovate | 状態 |
|---|---:|---:|---|
| rs | 0 | 5 | Renovate のみ（off、待機） |
| js | 0 | 3 | Renovate のみ（off、待機） |
| java | 0 | 3 | Renovate のみ（off、待機） |
| go | 0 | 0 | 完了（#687 / #686 が MERGED） |
| kotlin | 0 | 0 | 完了（#14 / #16 が MERGED） |
| scala | 0 | 0 | 完了（#15 が MERGED） |
| hub | 0 | 0 | 範囲内 |

WIP は Renovate を除くすべての open PR を数える。現在は **0**。Renovate（rs 5 / java 3 / js 3）は off のため触らず新規 PR も作らない。

## 3. Orca の現況（worktree / 端末 / 担当）

### 3.1 この担当の残置（クリーン確認できず保持）

- `java-769-notification-thread`（branch `codex/java-769-notification-thread`）
  - B 案（caller 通知を許容）の未コミット差分が残る。A2 採用（PR #799）で superseded。証拠として保持。
  - 端末: `term_43e70d9c-3c0c-4844-9334-14b16d9ae82b`（Claude）、`term_d9376131-e741-487d-8665-ffd27b550429`（shell）
- `rs-349-review`（branch `codex/rs-349-review`）
  - tracked の変更なし。untracked の `aidlc/spaces/default/intents/260822-sqlite-event-store/audit/...md` があるため保持。
  - 端末: `term_7d5cc176-0429-4fef-9d4b-0718ce7362b8`（Claude）、`term_97732367-58e8-46a2-a1b3-33afb29c9af8`（shell）

### 3.2 共通 repo で他担当が進行中の worktree（触らない）

PR #83 は CLOSED。再開・再実装しない。以下は PR #83 関連の別担当資源で、停止・削除・変更をしない。

- `agent-ops-diagnose`: `term_73e33bed-94a4-444a-bee1-71ca9f3f8cda`（Claude）、`term_ca624530-c277-44cc-bd65-238a495b1bf9`（shell）
- `agent-ops-dispatch`: `term_b2973939-dc0a-4f82-8d4d-2f9a6a69db02`（Claude）、`term_57d399eb-5700-471f-9984-529adfe4540f`（shell）
- `agent-ops-review`: `term_f4de705c-1cba-4f0c-a95d-03991a458b69`（Claude）、`term_37b36f3b-9307-455b-9bca-71a296f0cfba`（shell）
- `agent-ops-spark-review`: `term_437151fa-8884-4079-80f7-bdc07b2b966a`（Claude）、`term_da7319e6-1178-4df5-9f10-8efe8764f4bd`（shell）

### 3.3 cqrs-es 側の既存端末（別担当・触らない）

- ハブ `cqrs-es-example`: `term_ef396ce5-c56b-4441-94b1-bd8b142d5435`（Claude、コーディネーション）、`term_4680cda7-808d-4887-98f0-2da8ff8d0b8e`（shell）
- `cqrs-es-example-go`: `term_af94f730-218c-4527-9f13-e62067336a63`（main の Terminal 1 のみ）
  - go の M2 は完了（#678 / #679 / #573 MERGED、#670 / #671 CLOSED、M2 マイルストーン closed）。専用 worktree / 端末は残っていない。
- `cqrs-es-example-java`: `term_cb059c36-a7ad-469d-8a8a-2bc678b8f894`
- `cqrs-es-example-js`: `term_39976e11-4982-402d-be21-07dbc999ede4`
- `cqrs-es-example-rs`: `term_625a3beb-f065-4e44-9053-7ee55f1e161b`
- `cqrs-es-example-kotlin`: `term_14fdcce0-7011-4e62-a9bd-c0078a074339`

### 3.4 過去の作業ツリー

`deps-*` や `sbt-git-*` などの completed worktree が各 repo に残っている。他担当由来のものを含むため、削除は所有者とクリーン状態を確認してから行う。無条件の一括削除はしない。

## 4. 加藤さんの決定と禁止事項

- **WIP は repo ごと（Renovate を除く）**。異なる repo を同じ worktree で同時に編集しない。cqrs-es は 1 repo あたり open PR 3 本まで（Renovate を除く）。
  - 現状（Renovate を除く）: open PR は 0。Renovate は rs 5 / java 3 / js 3 が open だが WIP に数えず、off のため修正・リベース・整理・クローズをせず、新規 PR も作らない。rs #591 は判断待ち（paths-ignore）。
- **Renovate は off**（2026-11-07 19:33、使用量削減）。既存 Renovate PR の修正・リベース・整理・クローズは禁止（WIP 超過の解消目的でも）。マージは CI 全緑かつ未対応コメントなしのものだけ（Grok Bot 側のコメントも確認する）。
- **Bugbot の確認を必須**とする。未対応の Bugbot 指摘・レビューコメントが残る PR はマージしない。
- **AGENTS.md は人間専用**。追加・変更・削除をしない。リンク修正だけでも触らない。
- **docker prune 禁止**。他担当の image / container を削除しない。自分の probe 画像だけを、正確な ID / 参照を確認して個別に片付ける。
- **公開・リリース・force push 禁止**。オーナーの明示承認がない限り行わない。
- **PR #83 は再開・再実装しない**（CLOSED）。
- **Renovate の Dependency Dashboard は閉じない**。
- **main への直 push は禁止**。ブランチから PR を作る。
- **PR のタイトル・本文は日本語**、**コミットは英語の Conventional Commit**。
- **HAND_OFF の PR は同時に1本まで**。前の PR がマージされるまで次を作らない。
- **現在の新規着手はしない**。Renovate は off、既存 Renovate PR は読み取り専用。加藤さんの追加指示なしに M2 の実装や他 repo の作業を始めない。HAND_OFF の定期更新 PR は例外として本方針に従い作成する。
- **マージ条件**: 全チェック緑、未対応コメントなし、非ドラフト、conflict なし。squash で英語 Conventional subject を `--subject` に明示し、`--match-head-commit` を付ける。BEHIND なら update-branch → 再 CI 後に同じ条件で判断する。
- **マージ後**: main CI を確認する。Issue は実際に main へ修正が入り、追跡作業が消えたことを確認してから閉じる。Dependency Dashboard は閉じない。
- **テスト・監査・CI を弱めない**。allow、ignore、検査削除、タイムアウト延長やリトライだけで緑にしない。失敗は原因を直す。
- **不要な環境依存 lint / 基盤を追加しない**。既存の Orca / pstack / toolchain を使う。
- **未コミット・untracked の変更を保護**する。削除・上書き・force push の前に必ず確認する。
- **他担当の端末・worktree・image・container を停止・削除しない**。操作は自分の担当資源に限定する。
- **main CI を理由なく再実行しない**。失敗時のみ原因を直して再実行する。

## 5. 次にやること

1. **Renovate の扱い（読み取り専用・待機）**
   - Renovate は 2026-11-07 19:33 に使用量削減のため off。新しい更新 PR は作らない。
   - 既存 Renovate PR の修正・リベース・整理・クローズはしない（WIP 超過の解消目的でも）。
   - マージしてよいのは、CI が全緑かつ未対応コメントがないものだけ（Grok Bot 側も確認）。BEHIND でも update-branch しない。
   - Renovate は WIP に数えない。Dependency Dashboard は閉じない。
2. **cqrs-es M2（完了・当方は待機）**
   - 計画順は rs → js → java → go。**go は完了**（#678 / #679 / #681 / #683 / #685 / #573 MERGED、#670 / #671 / #680 / #682 / #684 CLOSED、M2 マイルストーン closed）。
   - rs / js / java / go の v5 移行・RMU 復旧・M2 後続は完了（rs #605、js #841、java #629、go #685 が MERGED。java #627 も CLOSED）。hub #13 と #4 は CLOSED、残る追跡は #3 のみ。
   - kotlin は M3 の #4 / #5 / #6 / #8 と M3 後続 #12 / #14 / #16 が MERGED。open Issue / PR はない。
   - scala は M4 後続 #9 / #13 / #15 が MERGED。open Issue / PR はない。
   - go は M1 後続 #672 が CLOSED、#686 / #687 が MERGED `98ceb9c` / `759fae4`（staticcheck の CI 実行を含む）。
   - 完了条件は §1.2。特に **head の Streams 購読、`(aggregate_id, seq_nr)` の重複除去、journal からの飛び補完、`read_model_positions` の記録**を満たす。
   - ハブの HAND_OFF は PR #21 まで MERGED `ffc1264`。ESA 側の本ファイルは 10:09 に更新した。
   - WIP（Renovate を除く）は 0。Renovate は rs 5 / java 3 / js 3 が open だが off のため触らず、新規 PR も作らない。rs #591 は判断待ち（paths-ignore）。
   - 当方は実装に着手しない。加藤さんの追加指示なしに M2 の実装を始めない。1 repo あたり open PR 3 本まで（Renovate を除く）。Bugbot 確認必須。テスト・CI を弱めない。
3. **ESA の公開準備（オーナー承認待ち）**
   - java を先に正式版、kotlin・scala を java の正式版へ切り替え。各版は公開直前にオーナー承認。
4. **HAND_OFF の更新**
   - マイルストーン完了・大きな方針変更のたび、および最長1時間おき。更新 PR は1本ずつ。
5. **残置 worktree の整理**
   - `java-769-notification-thread` と `rs-349-review` は未コミット/untracked のため、内容を確認してから判断する。他担当資源は触らない。
6. **main CI の確認**
   - 各言語の main CI を定期的に確認し、失敗があれば原因を直す。

## 6. 最終更新

- 2026-11-08 10:09 JST
