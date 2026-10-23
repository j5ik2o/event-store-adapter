> この文書は [README.md](README.md) の日本語版です。英語版が正本で、食い違うときは英語版に従います。

# 利用者向けの文書の型

このディレクトリは、6 言語のリポジトリ（rs、js、java、kotlin、scala、go）の利用者向けの文書の型の正本を置く。各リポジトリは `template.json` を写し、CI で [`tools/user-docs/check.py`](../tools/user-docs/README.ja.md) により文書を照合する。

英語の `X.md` が正本で、日本語の `X.ja.md` は補助である。食い違うときは英語に従う。照合するのは構造だけで、文章の中身は照合しない。

型の版: `1.0.0`。

## 文書の組

どのリポジトリも、次の 3 種の文書を、英語と日本語の 1 組ずつ提供する。ファイル名・置き場所・見出しは、どのリポジトリでも同じにする。違うのは言語に固有のコードと準備の手順だけである。

| 文書 | 英語のファイル | 日本語のファイル |
|:--|:--|:--|
| README | `README.md` | `README.ja.md` |
| 保存先のスキーマの文書（メモリを除く保存先ごとに 1 つ） | `docs/{接頭辞}_DATABASE_SCHEMA.md` | `docs/{接頭辞}_DATABASE_SCHEMA.ja.md` |
| 移行ガイド | `docs/MIGRATION_GUIDE.md` | `docs/MIGRATION_GUIDE.ja.md` |

パスはすべて、リポジトリの文書の起点（`repo.json` の `docs_root`）からの相対である。

## 保存先

次の順が、README の「保存先」の下の H3 の順になる。

| id | 英語 | 日本語 | スキーマの文書の接頭辞 |
|:--|:--|:--|:--|
| `memory` | Memory | メモリ | なし（残すデータがないため、スキーマの文書を置かない） |
| `dynamodb` | DynamoDB | DynamoDB | `DYNAMODB` |
| `sqlite` | SQLite | SQLite | `SQLITE` |
| `spanner` | Spanner | Spanner | `SPANNER` |
| `bigtable` | Bigtable | Bigtable | `BIGTABLE` |

## 日本語の文書の先頭の一行

日本語の文書（`X.ja.md`）の最初の行は、次の形とする。`{english}` は同じ場所の英語の文書のファイル名（例: `README.md`）。

```
> この文書は [{english}]({english}) の日本語版です。英語版が正本で、食い違うときは英語版に従います。
```

## README

- H1: 英語・日本語とも、`repo.json` のパッケージ名そのもの。
- H2: 次の順で、ちょうどこれだけ。

| 英語 | 日本語 |
|:--|:--|
| Overview | 概要 |
| Installation | インストール |
| Quick start | はじめに |
| Storages | 保存先 |
| Serialization | 直列化 |
| Retention | 保持 |
| Errors | エラー |
| Migration | 移行 |
| Conformance | 適合 |
| License | ライセンス |

- 「Storages」（「保存先」）の下の H3 は、リポジトリが提供する保存先の表示名を、上の表の順に並べたものと一致する（英語の文書は英語の表示名、日本語の文書は日本語の表示名）。
- ほかの H2 の下の H3 は自由だが、同じ H2 の下の数は英語と日本語で等しい。

## 保存先のスキーマの文書

- H1: 英語は `{英語の表示名} storage schema`、日本語は `{日本語の表示名} の保存先のスキーマ`。
- H2: 次の順で、ちょうどこれだけ。H3 は自由で、同じ H2 の下の数は英語と日本語で等しい。

| 英語 | 日本語 |
|:--|:--|
| Layout | 配置 |
| Configuration | 設定 |
| Initialization | 初期化 |
| Records | 記録 |
| Writes and reads | 書き込みと読み取り |
| Retention | 保持 |
| Operations | 運用 |

## 移行ガイド

- H1: 英語は `Migration guide`、日本語は `移行ガイド`。
- H2: 次の順で、ちょうどこれだけ。H3 は自由で、同じ H2 の下の数は英語と日本語で等しい。

| 英語 | 日本語 |
|:--|:--|
| Overview | 概要 |
| Code changes | コードの変更 |
| Data migration | データの移行 |
| Verification and cutover | 確認と切り替え |

コードブロック（``` または ~~~）の中の行は見出しではなく、その中のリンクも照合しない。

## 移ったことを示すファイル

文書の名前を変えたときは、公開済みの README からのリンクを切らないために、古いパスに短いファイルを残す。内容は固定である。`{link}` は、古いファイルのディレクトリから新しい文書への相対パスで、区切りは `/` とする。

英語（`docs/OLD_NAME.md`）:

```
# Moved

This document has moved to [{link}]({link}).
```

日本語（`docs/OLD_NAME.ja.md`）: 日本語の文書の先頭の一行、空行、次の内容の順。リンクは新しい日本語の文書（`.ja.md`）を指す。

```
# 移動しました

この文書は [{link}]({link}) に移りました。
```

例: `docs/OLD_NAME.md` が `docs/DYNAMODB_DATABASE_SCHEMA.md` に移ったなら、英語のファイルのリンクは `DYNAMODB_DATABASE_SCHEMA.md`、日本語のファイルのリンクは `DYNAMODB_DATABASE_SCHEMA.ja.md` になる。

## 型の外の文書

リポジトリは、`docs/` の直下に、型にない利用者向けの文書（例: `docs/MIGRATION_GUIDE_v3.md`）を置いてよい。`repo.json` の `extra_documents` に並べる。どれも英語と日本語の両方が要り、日本語の文書は上の先頭の一行で始める。見出しは照合しない。開発者向けの文書は `docs/` の下のディレクトリに分けて置く。照合の対象にならない。`docs/` の直下のそれ以外の `.md` は誤りである。

## `repo.json`

リポジトリの設定は `user-docs/repo.json` に置く。5 つのキーはすべて必須で、知らないキーは誤りになる。

| キー | 意味 |
|:--|:--|
| `package` | パッケージ名。README の H1 になる |
| `docs_root` | 文書の起点。リポジトリのルートからの相対（`.` や `packages/library`） |
| `storages` | リポジトリが提供する保存先の id の並び（1 つ以上、重複なし） |
| `extra_documents` | 型の外の文書の英語のパスの並び。`docs_root` からの相対 |
| `moved` | 古い英語のパスから新しい英語のパスへの対応。`docs_root` からの相対。新しいパスは型の文書か型の外の文書にする |

パスは相対パスで、`..` を含まず、`.md` で終わり、`.ja.md` では終わらない（英語のパスで書く。日本語のパスは導出する）。

文書の起点がルートの例:

```json
{
  "package": "event-store-adapter-rs",
  "docs_root": ".",
  "storages": ["memory", "dynamodb"],
  "extra_documents": ["docs/MIGRATION_GUIDE_v3.md"],
  "moved": {"docs/OLD_NAME.md": "docs/DYNAMODB_DATABASE_SCHEMA.md"}
}
```

文書の起点が `packages/library` の例:

```json
{
  "package": "event-store-adapter-js",
  "docs_root": "packages/library",
  "storages": ["memory", "dynamodb", "sqlite"],
  "extra_documents": [],
  "moved": {}
}
```

## `template.json`

| キー | 意味 |
|:--|:--|
| `format`, `version` | 常に `user-docs-template` と `1.0.0` |
| `japanese_first_line` | 日本語の文書の先頭の一行。`{english}` は英語のファイル名に置き換わる |
| `storages` | 上の保存先（`id`、`en`、`ja`、`schema_prefix`） |
| `documents.readme`、`documents.schema`、`documents.migration_guide` | `path`（`{prefix}` はスキーマの接頭辞）、`h1`、`h2`（`en` と `ja` の組の並び）。README の `h1` は `package` で、`storages_h2` が「Storages」の H2 を指す |
| `moved` | 移ったことを示すファイルの固定形（`en`、`ja`）。`{link}` と `{first_line}` は照合の道具が置き換える |
