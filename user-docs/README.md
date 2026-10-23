# User documentation template

This directory holds the canonical template for the user-facing documents of the six language repositories (rs, js, java, kotlin, scala, go). Each repository copies `template.json` and checks its documents against it in CI with [`tools/user-docs/check.py`](../tools/user-docs/README.md).

The English `X.md` is the source of truth. The Japanese `X.ja.md` is an aid; when the two differ, the English one wins. The checker verifies structure only: it does not check the wording.

Template version: `1.0.0`.

## Document sets

Every repository provides three kinds of documents, each as an English and a Japanese file. The file names, locations and headings are the same in every repository. Only the language-specific code and setup steps differ.

| Document | English file | Japanese file |
|:--|:--|:--|
| README | `README.md` | `README.ja.md` |
| Storage schema (one per storage except Memory) | `docs/{PREFIX}_DATABASE_SCHEMA.md` | `docs/{PREFIX}_DATABASE_SCHEMA.ja.md` |
| Migration guide | `docs/MIGRATION_GUIDE.md` | `docs/MIGRATION_GUIDE.ja.md` |

All paths are relative to the documentation root of the repository (`docs_root` in `repo.json`).

## Storages

The order below is the order of the H3 headings under "Storages" in the README.

| id | English | Japanese | Schema file prefix |
|:--|:--|:--|:--|
| `memory` | Memory | メモリ | none (no schema document, because nothing persists) |
| `dynamodb` | DynamoDB | DynamoDB | `DYNAMODB` |
| `sqlite` | SQLite | SQLite | `SQLITE` |
| `spanner` | Spanner | Spanner | `SPANNER` |
| `bigtable` | Bigtable | Bigtable | `BIGTABLE` |

## First line of Japanese documents

The first line of every Japanese document (`X.ja.md`) is the following. `{english}` is the file name of the English document in the same directory, for example `README.md`.

```
> この文書は [{english}]({english}) の日本語版です。英語版が正本で、食い違うときは英語版に従います。
```

## README

- H1: the package name from `repo.json`, in both languages.
- H2: exactly the following, in this order.

| English | Japanese |
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

- The H3 headings under "Storages" are the display names of the storages the repository provides, in the order of the table above (English names in the English file, Japanese names in the Japanese file).
- H3 headings under the other H2 headings are free, but their number under the same H2 must be equal in English and Japanese.

## Storage schema documents

- H1: `{English name} storage schema` in English, `{Japanese name} の保存先のスキーマ` in Japanese.
- H2: exactly the following, in this order. H3 is free, with equal counts per H2 in both languages.

| English | Japanese |
|:--|:--|
| Layout | 配置 |
| Configuration | 設定 |
| Initialization | 初期化 |
| Records | 記録 |
| Writes and reads | 書き込みと読み取り |
| Retention | 保持 |
| Operations | 運用 |

## Migration guide

- H1: `Migration guide` in English, `移行ガイド` in Japanese.
- H2: exactly the following, in this order. H3 is free, with equal counts per H2 in both languages.

| English | Japanese |
|:--|:--|
| Overview | 概要 |
| Code changes | コードの変更 |
| Data migration | データの移行 |
| Verification and cutover | 確認と切り替え |

Lines inside fenced code blocks (``` or ~~~) are not headings and their links are not checked.

Writing rules for documents:

- Write headings only with a leading `#` (ATX style). Do not use underlined headings (`===` or `---`); the checker counts only `#` headings.
- Write each link on a single line. The checker does not check links that span lines.
- Keep English and Japanese content aligned, and do not change the first line of the Japanese document.

## Moved files

When a document is renamed, a short file stays at the old path so that links from published READMEs do not break. Its content is fixed. `{link}` is the relative path from the old file's directory to the new document, with `/` separators.

English (`docs/OLD_NAME.md`):

```
# Moved

This document has moved to [{link}]({link}).
```

Japanese (`docs/OLD_NAME.ja.md`): the first line of Japanese documents, a blank line, then the following. The link points to the new Japanese document (`.ja.md`).

```
# 移動しました

この文書は [{link}]({link}) に移りました。
```

For example, `docs/OLD_NAME.md` moved to `docs/DYNAMODB_DATABASE_SCHEMA.md` contains the link `DYNAMODB_DATABASE_SCHEMA.md`, and `docs/OLD_NAME.ja.md` contains `DYNAMODB_DATABASE_SCHEMA.ja.md`.

## Documents outside the template

A repository may keep other user-facing documents directly under `docs/` (for example `docs/MIGRATION_GUIDE_v3.md`). List them in `extra_documents` of `repo.json`. Each needs an English and a Japanese file, and the Japanese one starts with the first line above. Their headings are not checked. Developer documents go in a subdirectory of `docs/`, which the checker does not inspect. Any other `.md` file directly under `docs/` is an error.

## `repo.json`

The repository setting lives at `user-docs/repo.json`. All five keys are required, and unknown keys are errors.

| Key | Meaning |
|:--|:--|
| `package` | The package name, used as the README H1 |
| `docs_root` | The documentation root, relative to the repository root (`.` or `packages/library`) |
| `storages` | The ids of the storages the repository provides (at least one, no duplicates) |
| `extra_documents` | English paths of documents outside the template, relative to `docs_root` |
| `moved` | Old English path mapped to the new English path, relative to `docs_root`; the new path must be a template document or an extra document |

Paths must be relative, must not contain `..`, must end with `.md`, and must not end with `.ja.md` (write the English path; the Japanese path is derived).

Example with the documentation root at the repository root:

```json
{
  "package": "event-store-adapter-rs",
  "docs_root": ".",
  "storages": ["memory", "dynamodb"],
  "extra_documents": ["docs/MIGRATION_GUIDE_v3.md"],
  "moved": {"docs/OLD_NAME.md": "docs/DYNAMODB_DATABASE_SCHEMA.md"}
}
```

Example with the documentation root at `packages/library`:

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

| Key | Meaning |
|:--|:--|
| `format`, `version` | Always `user-docs-template` and `1.0.0` |
| `japanese_first_line` | The first line of Japanese documents; `{english}` is replaced by the English file name |
| `storages` | The storages above (`id`, `en`, `ja`, `schema_prefix`) |
| `documents.readme`, `documents.schema`, `documents.migration_guide` | `path` (`{prefix}` is the schema prefix), `h1`, `h2` (a list of `en`/`ja` pairs); for the README, `h1` is `package` and `storages_h2` names the "Storages" H2 |
| `moved` | The fixed form of moved files (`en`, `ja`); `{link}` and `{first_line}` are replaced by the checker |
