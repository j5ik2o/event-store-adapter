> この文書は [CONTRIBUTING.md](CONTRIBUTING.md) の日本語版です。英語版が正本で、食い違うときは英語版に従います。

# ハブへの貢献の案内

このリポジトリは、event-store-adapter グループ（rs・js・java・kotlin・scala・go）のハブである。共通の仕様、設計判断、用語集、適合テストデータ、共有の道具を置いている。この案内は、それぞれの置き場所と、変更を手元で確かめる方法を示す。既存のファイルと現在のスクリプトで確かめられる事実だけを書く。

## 文書の言語

開発者向けの文書は、英語の `X.md` を正本、日本語の `X.ja.md` を補助とする。食い違うときは英語版に従う。下の表で「英語と日本語」と書いた文書がこの決まりに従う。

現時点で日本語だけの文書がある。`docs/spec/` の仕様、運用方針 `docs/operations/repository-policy.md`、`docs/plan/` の計画である。`conformance/README.md` と `conformance/COVERAGE.md` は配布する適合テストデータの一部（下を参照）なので、配布したとおり日本語のまま保つ。`tools/takt/facets/` のワークフローの部品は、ワークフローを日本語で実行するので日本語で書いている。

## どこに何があるか

| 必要なもの | 場所 | 言語 |
|:--|:--|:--|
| 共通の仕様（共通契約、ストレージプロファイル、ハッシュ） | [docs/spec/README.md](docs/spec/README.md) | 日本語のみ |
| 設計判断 | [docs/adr/](docs/adr/)（下の一覧を参照） | 英語と日本語 |
| 共有する概念の用語集 | [CONTEXT.ja.md](CONTEXT.ja.md)（[英語版](CONTEXT.md)） | 英語と日本語 |
| 適合テストデータ: 開発者向けの案内 | [docs/conformance-guide.ja.md](docs/conformance-guide.ja.md)（[英語版](docs/conformance-guide.md)） | 英語と日本語 |
| 適合テストデータ: 配布した README と網羅表 | [conformance/README.md](conformance/README.md)、[conformance/COVERAGE.md](conformance/COVERAGE.md) | 日本語（固定した配布データ） |
| 公開 API の形と照合 | [api-surface/README.ja.md](api-surface/README.ja.md)（[英語版](api-surface/README.md)） | 英語と日本語 |
| 利用者向けの文書の型 | [user-docs/README.ja.md](user-docs/README.ja.md)（[英語版](user-docs/README.md)）。照合は [tools/user-docs/README.ja.md](tools/user-docs/README.ja.md)（[英語版](tools/user-docs/README.md)） | 英語と日本語 |
| 運用方針（CI、ブランチ保護、マージ、レビュー、依存更新、エージェント運用） | [docs/operations/repository-policy.md](docs/operations/repository-policy.md) | 日本語のみ |
| 各言語の実装計画 | [docs/plan/implementation-plan.md](docs/plan/implementation-plan.md) | 日本語のみ |
| 指揮役のエージェントへの指示 | [CLAUDE.ja.md](CLAUDE.ja.md)（[英語版](CLAUDE.md)） | 英語と日本語 |

### 設計判断

- [ADR-0001: 封筒モデルを基準にした言語中立の仕様](docs/adr/0001-language-neutral-spec-based-on-envelope-model.ja.md)（[英語版](docs/adr/0001-language-neutral-spec-based-on-envelope-model.md)）
- [ADR-0002: 集約ヘッドをスナップショットから分離する](docs/adr/0002-separate-aggregate-head-from-snapshot.ja.md)（[英語版](docs/adr/0002-separate-aggregate-head-from-snapshot.md)）
- [ADR-0003: 保存される値の表現を固定する](docs/adr/0003-fix-storage-value-representations.ja.md)（[英語版](docs/adr/0003-fix-storage-value-representations.md)）
- [ADR-0004: 楽観ロックに seq_nr を使う](docs/adr/0004-use-seq-nr-for-optimistic-locking.ja.md)（[英語版](docs/adr/0004-use-seq-nr-for-optimistic-locking.md)）
- [ADR-0005: 追記の原子性を観測できる確定で定める](docs/adr/0005-define-append-atomicity-by-observable-commit.ja.md)（[英語版](docs/adr/0005-define-append-atomicity-by-observable-commit.md)）
- [ADR-0006: 論理シャードをやめ、集約 ID をキーにする](docs/adr/0006-key-by-aggregate-id-instead-of-logical-shards.ja.md)（[英語版](docs/adr/0006-key-by-aggregate-id-instead-of-logical-shards.md)）
- [ADR-0007: Bigtable のスナップショット履歴を対応するイベントと同じ行に置く](docs/adr/0007-store-bigtable-snapshot-history-with-events.ja.md)（[英語版](docs/adr/0007-store-bigtable-snapshot-history-with-events.md)）
- [ADR-0008: Bigtable の封筒を固定バイナリ形式で保存する](docs/adr/0008-fix-bigtable-envelope-binary-format.ja.md)（[英語版](docs/adr/0008-fix-bigtable-envelope-binary-format.md)）

### 道具

- main の CI の失敗の通知: [tools/ci-failure-notice/README.ja.md](tools/ci-failure-notice/README.ja.md)（[英語版](tools/ci-failure-notice/README.md)）
- リリースノートのスクリプト: [tools/release-notes/README.ja.md](tools/release-notes/README.ja.md)（[英語版](tools/release-notes/README.md)）
- 6 言語の相互運用の検証: [tools/interop/USAGE.ja.md](tools/interop/USAGE.ja.md)（[英語版](tools/interop/USAGE.md)）
- DynamoDB 試験環境の比較: [tools/spikes/dynamodb-emulators/README.ja.md](tools/spikes/dynamodb-emulators/README.ja.md)（[英語版](tools/spikes/dynamodb-emulators/README.md)）

## 適合テストデータ

`conformance/` のディレクトリは、各言語のリポジトリへそのまま配る。`conformance/manifest.json` の SHA-256 で固定している。中のファイルを手で編集せず、改行も変換しない。規範は `docs/spec/` の文書で、データは規則を追加しない。`conformance/COVERAGE.md` は生成した固定データである。データの開発者向けの案内は [docs/conformance-guide.ja.md](docs/conformance-guide.ja.md) である。

仕様の中の規則の定義行は、日本語の区分（`必須`・`推奨`・`任意`）か、英語の MUST・SHOULD・MAY で書く。案内は両方の形を説明している。

## 公開 API の形

`api-surface/surface.json` は、共通契約が各言語の公開 API に求める形を書いたもので、各言語が CI で照合する。版を上げる手順を含め、[api-surface/README.ja.md](api-surface/README.ja.md) を参照する。

## 手元の検査

リポジトリのルートから実行する。各コマンドは、上に挙げた文書から取っている。

```sh
# 適合テストデータを manifest と照合する（Python 3 の標準ライブラリだけ）
python3 tools/conformance/manifest.py verify

# Schema・規則番号・参照・ID・網羅表・参照モデルを検査する
# （Python 3.11 以上と uv が要る）
uv run --project tools/conformance --locked python tools/conformance/validate.py

# 適合テストの道具の単体試験
uv run --project tools/conformance --locked python -m unittest discover -s tools/conformance -p 'test_*.py'

# 利用者向けの文書の照合の道具の単体試験
python3 -m unittest discover -s tools/user-docs -p 'test_*.py'

# リリースノートのスクリプトの試験
python3 -B -m unittest discover -s tools/release-notes -p 'test_*.py' -v
```

適合テストデータを変えたときは、[docs/conformance-guide.ja.md](docs/conformance-guide.ja.md) の順に再生成して照合する。`tools/interop/` の相互運用の検証と `tools/spikes/dynamodb-emulators/` の試験環境の比較は、Docker などが要るので、それぞれの案内に従う。

## 文書を変えるとき

- `AGENTS.md` は編集しない。人間だけが編集すると指定されていて、リンクだけの修正にも当てはまる（[CLAUDE.ja.md](CLAUDE.ja.md) を参照）。
- 日本語版 `X.ja.md` がある英語の `X.md` を変えるときは、同じ変更で両方を変える。日本語版の 1 行目は、英語の原本へのリンクである。
- 仕様や運用方針を変えるときは、それらの文書に書いてあるとおり、リポジトリのオーナーの合意を得る。
