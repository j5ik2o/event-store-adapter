# Manual artifact evidence checks

Use `artifact_evidence.py` when delegating work and when accepting its files.
It requires Python 3.9 or later and only the standard library. It does not read
GitHub or T3 state, install hooks, poll, or execute commands from input files.
A clean checkout and an updated thread do not establish progress.

## Contract before delegation

Save a JSON object with these fields. Relative paths are relative to the JSON
file containing them, never the shell working directory. Absolute paths work too.

```json
{
  "task_id": "example-127",
  "artifact_root": ".",
  "first_artifact": "first.md",
  "deadline": "2030-01-01T12:00:00+09:00",
  "required_files": [
    {"path": "check.py", "role": "script"},
    {"path": "response.json", "role": "raw"},
    {"path": "run.log", "role": "log"},
    {"path": "report.md", "role": "report"}
  ]
}
```

All five fields are required. The deadline requires a timezone. The root is the
storage destination. Evidence paths must resolve inside it. Choose an explicit
first deliverable, separate from the final manifest. It may also be a required
report. A missing first deliverable is `pending_missing` or `overdue_missing`.
A present file is only `present_now`, including after the deadline.

Each required file has one role. All four roles must appear, with multiple files
per role allowed. Resolved duplicate paths fail. Roles are declarations, not
proof that the content is useful or that a script ran. The reviewer must choose
the required checklist independently and inspect relevant content. Completeness
means equality with this checklist, not a complete directory or all possible task
requirements. A hash match for a partial list alone does not establish acceptance.

## Self-contained example

Run from the repository root. This creates a fresh temporary example and executes
only the trusted CLI. The example evidence is synthetic and proves no past work.

```sh
example_dir=$(mktemp -d)
python3 - "$example_dir" <<'PY'
import json
from pathlib import Path
import sys
root = Path(sys.argv[1])
files = [('check.py', 'script'), ('response.json', 'raw'),
         ('run.log', 'log'), ('report.md', 'report')]
for name, role in files:
    (root / name).write_text('Synthetic ' + role + '\n')
(root / 'first.md').write_text('Synthetic first result\n')
(root / 'task.json').write_text(json.dumps({
    'task_id': 'example-127', 'artifact_root': '.',
    'first_artifact': 'first.md', 'deadline': '2030-01-01T00:00:00Z',
    'required_files': [{'path': name, 'role': role} for name, role in files]
}))
PY
python3 tools/pm/artifact_evidence.py progress "$example_dir/task.json"
python3 tools/pm/artifact_evidence.py generate "$example_dir/task.json" --output "$example_dir/manifest.json"
python3 tools/pm/artifact_evidence.py verify "$example_dir/manifest.json" --contract "$example_dir/task.json"
```

`generate` hashes only explicit required files and creates its output exclusively.
It refuses to overwrite an existing manifest. It can generate a final inventory
while the first deliverable is absent. Generation itself reports
`evidence: not_assessed`; follow with `verify --contract` for acceptance.
The manifest must be separate from the first deliverable and required files,
and must not include itself. Preserve its hash externally if authenticity matters.

## Existing manifests

`verify MANIFEST` accepts exactly three container shapes, a top-level array,
`{"files": [...]}`, or `{"artifacts": [...]}`. Rows require `path`, integer
`bytes`, and lowercase hexadecimal `sha256`. Relative and absolute paths can mix.
Object metadata and extra row fields are ignored, except explicit `complete`
and `truncated` flags. `complete: false` and `truncated: true` are rejected.
Both wrapper keys together, duplicate JSON keys, malformed rows, empty lists,
and duplicate resolved paths are errors. Nonstandard count/completeness metadata
is not interpreted. Supply a contract to detect omitted required files.

Without `--contract`, exit zero means only that every listed file currently
matches its size and hash. `evidence` stays `not_assessed`. With a contract,
`satisfied_now` requires the exact checklist, matching hashes, and a present
first deliverable. A manifest omitted from disk cannot be verified. An empty or
truncated manifest cannot satisfy the contract. This tool does not authenticate
the contract or prove that the producer declared every necessary artifact.

## Limits and result interpretation

The tool reads no directory entries and accepts no globs. It caps JSON inputs at
1 MiB, lists at 256 files, individual content at 16 MiB, and total hashed content
at 64 MiB. Strings are capped at 1024 characters. Results contain aggregate counts
and at most one error capped at 400 characters; file contents are never printed.
A limit error stops inspection with `inspection_complete: false`. No partial list
is returned as a successful complete inspection. Split a large task into explicit
reviewable contracts rather than raising the limits or scanning build output.

Commands emit one JSON object. Exit 0 means the requested operation succeeded;
exit 1 means missing first evidence or an unmet acceptance checklist; exit 2
means invalid input, unavailable evidence, mismatch, or a limit error. Argparse
usage errors also exit 2 and print usage. No output uses a generic progress PASS.

`historical_saved_at`, `completed_by_deadline`, and `continuous_progress` remain
`unknown`. Neither mtime nor current presence proves a past save or timely
completion. Observations occur during this invocation and are not atomic across
files. Keep evidence stable during inspection. Missing files, changed content,
and special files fail. Human content review and independent review remain
separate from integrity and checklist checks.

Run behavior tests with:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/pm -p test_artifact_evidence.py -v
```

The tests reconstruct overdue absence and a 7259-entry inventory from the failure
classes recorded in issue #127. They are not recovered original inputs or proof
of the original 50-minute loop. Old bundle hash checks are current observations
of old evidence, distinct from newly executed tests.
