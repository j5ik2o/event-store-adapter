> この文書は [README.md](README.md) の日本語版です。英語版が正本で、食い違うときは英語版に従います。

# リリースノートを作る共通のスクリプト

6 言語のリポジトリの版上げの workflow が使う、GitHub Release のリリースノートを作るスクリプトの正本。変更の記録は、Conventional Commits の件名から作るこのリリースノートだけとする。

| ファイル | 役割 |
|---|---|
| `create-release-note-header.py` | 版の見出し行を出す |
| `create-release-note-body.py` | コミットから節ごとの一覧を出す |
| `test_release_notes.py` | 2 つのスクリプトの試験 |

Python 3.10 以上と標準ライブラリだけで動く。

## 呼び方（workflow に書く形）

```sh
python3 .github/create-release-note-header.py "$SERVER_URL" "$REPOSITORY" "$PREV_TAG" "$NEXT_TAG" > changelog.txt
git log "$PREV_TAG..$NEXT_TAG" --no-merges --format='%H%x1f%s%x1f%b%x1e' \
  | python3 .github/create-release-note-body.py "$SERVER_URL" "$REPOSITORY" >> changelog.txt
```

`$SERVER_URL` は `https://github.com`、`$REPOSITORY` は `owner/name`。`git log` を `--grep` で絞らない。型の判定は body のスクリプトがする。

## 入力の形（body）

標準入力に、`\x1e` でコミットを区切り、各コミットを「完全なハッシュ `\x1f` 件名 `\x1f` 本文」の形で渡す。区切りの前後の改行は無視する。空の入力では何も出さず、終了コード 0 で終わる。

## 出力の形

header は `### [5.0.2](https://github.com/o/r/compare/v5.0.1...v5.0.2) (YYYY-MM-DD)` の行を出す。

body は次の順に、項目のある節だけを `### 見出し` で出し、各節の後に空行を 1 つ置く。節の中は入力の順のまま。

1. `⚠ BREAKING CHANGES`
2. `Features`（feat）、`Bug Fixes`（fix）、`Performance Improvements`（perf）、`Reverts`（revert）、`Documentation`（docs）、`Styles`（style）、`Code Refactoring`（refactor）、`Tests`（test）、`Build Systems`（build）、`Continuous Integration`（ci）、`Chores`（chore）、`Other Changes`（ほかの型）

項目の形:

```
* **スコープ:** 説明 ([#番号](SERVER_URL/REPOSITORY/pull/番号)) ([短いハッシュ](SERVER_URL/REPOSITORY/commit/完全なハッシュ))
```

- 件名は `型(スコープ)!: 説明` の形。スコープと `!` は省略できる。説明の末尾の ` (#数字)` は PR の番号として取り出す。
- 破壊的な変更は、件名の型の直後に `!` がある、本文に `BREAKING CHANGE:`・`BREAKING-CHANGE:` で始まる行がある、件名が `BREAKING CHANGE:`・`BREAKING-CHANGE:` で始まる、のどれか。破壊的な変更の節に載せ、型の節にも載せる。
- 破壊的な変更の節に載せる文は、本文の印の後ろの文とする。文は、空行か、次の footer の行（`Co-authored-by: x`、`Refs #12` のような `語: 値`・`語 #値` の形）の手前までとする。本文に印が複数あれば、文のある印ごとに 1 項目にする（文のない印は項目にしない）。本文に印がないか、どの印にも文がなければ、件名の印の後ろの文、件名の説明、件名そのものの順に使う。
- 件名が Conventional Commits の形でないコミットは、破壊的な変更の印があるときだけ、破壊的な変更の節に載せる。

## 配り方

- 各リポジトリは、`create-release-note-header.py` と `create-release-note-body.py` を `.github/` の直下に、`test_release_notes.py` を、そのリポジトリの版上げの試験と同じディレクトリ（rs・go は `.github/`、js・java・kotlin・scala は `.github/tests/`）に、同じ内容で写す。内容は変えない。
- ハブの正本を変えたら、コーディネーターが 6 リポジトリに配り直す。

## 試験

```sh
python3 -B -m unittest discover -s tools/release-notes -p 'test_*.py' -v
```
