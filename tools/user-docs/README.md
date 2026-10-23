# User documentation checker

`check.py` checks that the user-facing documents of a repository follow the template in [`user-docs/`](../../user-docs/README.md). It needs Python 3.11 or later and uses only the standard library. It does not use the network.

## Run

From the repository root:

```sh
python3 tools/user-docs/check.py
```

It reads `user-docs/template.json` (the copied template) and `user-docs/repo.json` (the repository setting). To check another location, pass its root:

```sh
python3 tools/user-docs/check.py --root DIR
```

All errors are collected and printed to standard error with the file path and line number, and the exit code is 1. Without errors it prints the number of checked documents and exits with 0.

It checks that the required documents exist in English and Japanese, the H1 and H2 headings (and the H3 headings under "Storages"), the equal H3 counts between languages, the first line of Japanese documents, relative links, documents outside the template, moved files, and that every `.md` file directly under `docs/` is accounted for. It does not check the wording.

## Test

```sh
python3 -m unittest discover -s tools/user-docs -p 'test_*.py'
```

The tests build small document trees in a temporary directory and run the checker on them.

## Copy to a repository

1. Copy `user-docs/template.json` and `tools/user-docs/check.py` with identical content.
2. Write `user-docs/repo.json` (see [`user-docs/README.md`](../../user-docs/README.md)).
3. In the CI job that `CI Success` depends on, verify the copies against fixed SHA-256 values with `sha256sum -c`, then run `python3 tools/user-docs/check.py`.

When the template or the checker changes in the hub, copy both files again and update the fixed SHA-256 values.
