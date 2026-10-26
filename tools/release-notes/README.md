<a id="リリースノートを作る共通のスクリプト"></a>
# Shared scripts that create release notes

The canonical source of the scripts that create the GitHub Release release notes, used by the version-bump workflows of the repositories of the 6 languages. The only record of changes is these release notes, created from Conventional Commits subjects.

| File | Role |
|---|---|
| `create-release-note-header.py` | Outputs the version heading line |
| `create-release-note-body.py` | Outputs the list for each section from the commits |
| `test_release_notes.py` | Tests of the two scripts |

They run with only Python 3.10 or later and the standard library.

<a id="呼び方workflow-に書く形"></a>
## How to call them (the form written in the workflow)

```sh
python3 .github/create-release-note-header.py "$SERVER_URL" "$REPOSITORY" "$PREV_TAG" "$NEXT_TAG" > changelog.txt
git log "$PREV_TAG..$NEXT_TAG" --no-merges --format='%H%x1f%s%x1f%b%x1e' \
  | python3 .github/create-release-note-body.py "$SERVER_URL" "$REPOSITORY" >> changelog.txt
```

`$SERVER_URL` is `https://github.com`, and `$REPOSITORY` is `owner/name`. Do not narrow `git log` with `--grep`. The body script decides the types.

<a id="入力の形body"></a>
## Input format (body)

Standard input separates commits with `\x1e`, and each commit is passed in the form "full hash `\x1f` subject `\x1f` body". Newlines before and after the separator are ignored. For empty input, it outputs nothing and ends with exit code 0.

<a id="出力の形"></a>
## Output format

The header outputs a line of the form `### [5.0.2](https://github.com/o/r/compare/v5.0.1...v5.0.2) (YYYY-MM-DD)`.

The body outputs, in the following order, only the sections that have items, each as `### 見出し` (heading), and places one blank line after each section. Within a section, the input order is kept.

1. `⚠ BREAKING CHANGES`
2. `Features` (feat), `Bug Fixes` (fix), `Performance Improvements` (perf), `Reverts` (revert), `Documentation` (docs), `Styles` (style), `Code Refactoring` (refactor), `Tests` (test), `Build Systems` (build), `Continuous Integration` (ci), `Chores` (chore), `Other Changes` (other types)

The form of an item:

```
* **スコープ:** 説明 ([#番号](SERVER_URL/REPOSITORY/pull/番号)) ([短いハッシュ](SERVER_URL/REPOSITORY/commit/完全なハッシュ))
```

- The subject has the form `型(スコープ)!: 説明` (type, scope, description). The scope and `!` can be omitted. A trailing ` (#数字)` in the description is extracted as the PR number.
- A breaking change is any of: a `!` immediately after the type in the subject; a line in the body starting with `BREAKING CHANGE:` or `BREAKING-CHANGE:`; or a subject starting with `BREAKING CHANGE:` or `BREAKING-CHANGE:`. It is listed in the breaking-changes section and also in its type's section.
- The sentence listed in the breaking-changes section is the sentence after the marker in the body. The sentence extends up to a blank line or the next footer line (a `語: 値` or `語 #値` form such as `Co-authored-by: x` or `Refs #12`). If the body has multiple markers, each marker that has a sentence becomes one item (a marker without a sentence does not become an item). If the body has no marker, or no marker has a sentence, use, in this order, the sentence after the marker in the subject, the description of the subject, and the subject itself.
- A commit whose subject is not in the Conventional Commits form is listed in the breaking-changes section only when it has a breaking-change marker.

<a id="配り方"></a>
## Distribution

- Each repository copies `create-release-note-header.py` and `create-release-note-body.py` directly under `.github/`, and `test_release_notes.py` into the same directory as that repository's version-bump tests (`.github/` for rs and go, `.github/tests/` for js, java, kotlin, and scala), with the same content. Do not change the content.
- When the hub's canonical source is changed, the coordinator redistributes to the 6 repositories.

<a id="試験"></a>
## Tests

```sh
python3 -B -m unittest discover -s tools/release-notes -p 'test_*.py' -v
```
