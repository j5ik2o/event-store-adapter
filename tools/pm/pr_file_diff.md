# Retrieve selected PR file patches

Use Python 3 and an installed `gh` with existing GitHub authentication. This tool only issues GET requests to github.com. It needs no Python dependencies.

```sh
python3 tools/pm/pr_file_diff.py https://github.com/j5ik2o/event-store-adapter-java/pull/814 \
  --file conformance/memory/configuration.json
python3 tools/pm/pr_file_diff.py j5ik2o/event-store-adapter-java 814 \
  --file conformance/memory/configuration.json --file conformance/memory/stores.json
python3 tools/pm/pr_file_diff.py --help
```

`--file` selects exact current filenames, without glob expansion inside the tool. Quote shell metacharacters at your shell. For renames, use the current filename. The JSON preserves `previous_filename` when available. Unselected paths are counted without printing their content.

`revision` records the head SHA, base SHA, file count, and line totals before and after pagination. The tool requests 100 files per page until a short page or the documented 3,000-file ceiling. It rejects duplicate paths, mismatched file counts, mismatched PR line totals, inconsistent file counts, malformed hunks, incomplete hunks, and patch line totals that disagree with file metadata. It treats reaching the ceiling as incomplete, including exactly 3,000 files.

`api_consistent: true` means the selected textual patches pass those checks. **It does not prove a complete Git diff.** The API does not provide an independent completeness guarantee for patch content. Consequently this API-only tool always returns `complete: false` and exits 1, including when it successfully retrieves a consistent patch. In that case `reasons` contains `api_only_completeness_unproven` and the patch remains available as `validated-api-patch`. Consumers must inspect the JSON rather than suppress the exit status or treat it as proof of completeness. `complete` is reserved for proven completeness, which this tool cannot establish.

Missing selections and missing or invalid patches have `state: unavailable` and `patch: null`. The API alone cannot reliably distinguish a binary file from an omitted patch, so the reason says `patch_missing_binary_or_omitted`. Zero text changes have `state: metadata-only`, with separate reasons for a rename and other binary or metadata changes. Neither is an empty verified diff. Head/base checks cannot detect a revision change followed by a revert between requests.

JSON output defaults to 1 MiB and has an 8 MiB hard maximum. Set `--max-output-bytes` between 1024 and 8388608. If JSON would exceed that budget, the tool returns a small incomplete envelope with `output_limit`, omitting both selection and file content. API responses have a 16 MiB read limit per request and each request has a 45-second timeout. Transport errors do not echo `gh` errors, credentials, or environment values. Argument-parser usage errors exit 2.

Run the independent fake-`gh` fixtures without credentials or network access.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/pm -p test_pr_file_diff.py -v
```

The files endpoint's page size and 3,000-file ceiling come from the [official GitHub REST documentation](https://docs.github.com/en/rest/pulls/pulls#list-pull-requests-files). Hunk and count checks are conservative local validation, not a GitHub promise of patch completeness. The [official gh diff usage](https://cli.github.com/manual/gh_pr_diff) accepts one PR argument and has no positional path selection.
