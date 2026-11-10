# Check limited verification inheritance

PMs can compare byte-bound recorded runs with an explicit current checklist.
Python 3.9 or later and the standard library suffice. The CLI reads local files,
never runs recorded commands, fetches URLs, or changes records.

From the repository root, create and inspect a self-contained synthetic example:

```sh
example_parent=$(mktemp -d)
python3 -B tools/pm/inheritance_example.py "$example_parent/bundle"
python3 -B tools/pm/inheritance_evidence.py "$example_parent/bundle/input.json"
python3 -B -m unittest discover -s tools/pm -p test_inheritance_evidence.py -v
```

The CLI exits 0 with `state: inherited`, `recorded_new_runs: []`, and
`current_execution_complete: false`. The example reconstructs fictional records;
it establishes no historical execution. The generator requires a new directory
and retains written files if a later write fails. Run with `/usr/bin/python3`
to exercise the macOS system Python too.

## Input reference

The generated `input.json` and `old.json` are complete templates. Objects accept
exactly the documented fields. Version is integer 1, excluding booleans. Duplicate
JSON keys, unknown or missing fields, duplicate identities, empty required lists,
and invalid types are errors. Strings must be nonempty, trimmed, and at most
2048 characters. Arrays contain at most 128 entries. Each file is a regular file
of at most 1 MiB. Relative paths resolve against the JSON file containing them.
Absolute paths are accepted. Use stable files during inspection; reads are not
atomic across the bundle. SHA values alone do not bind files to Git revisions.
The person preparing the bundle must obtain and check the correct revisions.

The root has `schema_version`, full lowercase SHA40 `head` and `base`, nonempty
`requirements`, `prior_runs`, `new_runs`, and `inherited` arrays. Requirements
have unique `id`, `conditions`, and nonempty `targets`. Each target has semantic
`name`, local `path`, and lowercase SHA256 `sha256`. Target names are unique
within a requirement or run. Paths can differ between old and current snapshots.
The CLI hashes actual bytes and compares target names and hashes exactly.

Run arrays contain references with exactly `path` and `sha256`. The referenced
JSON file binds these fields:

| Field | Contract |
| --- | --- |
| `schema_version` | Integer 1 |
| `run_id` | Nonempty identity, unique across both lanes |
| `head`, `base` | Full lowercase SHA40 |
| `verdict` | `pass`, `fail`, `unknown`, or `not_run` |
| `provenance` | `kind`: `recorded` or `reconstructed`; `source`: locator text |
| `conditions` | Exactly `runtime`, `command`, `suite` |
| `targets` | Nonempty array of named local file references |
| `evidence` | Nonempty array of local `path` and `sha256` references |
| `unverified` | Array of nonempty gap descriptions |

Each condition is nonempty text or `null`. Use `null` for an unknown fact.
`unknown`, `n/a`, `?`, and `null` strings are rejected. Record the effective
runtime, OS, architecture, relevant resource limits, full command, and suite
selection. Equality is exact text equality, without normalization or defaults.
Equal null conditions never qualify. The CLI cannot recognize a misleading
nonempty description or verify that the declared conditions describe execution.

Each inheritance edge has exactly `requirement` and `run_id`, referring to an
existing requirement and prior run. Duplicate edges are errors. A prior run
qualifies only with original `pass`, no gaps, known matching conditions, the same
base, and identical complete target names and hashes. Head may differ for this
limited slice. New runs must match the current head and base. Old and new suites
are never added together as new execution coverage. Reusing an evidence hash in
any two records is conservatively rejected, even if IDs or paths differ. For
legitimate repeated executions with identical stdout, save distinct evidence
bundles containing run identity and execution metadata rather than listing the
same stdout bytes as two runs.

A run may cover multiple requirements and is counted once. A rejected explicit
inheritance edge prevents successful accounting even if a separate new pass
covers that requirement. New failed observations remain visible and do not erase
other passes. There is no latest-run or supersession inference.

## Output and exit contract

One JSON object is written to stdout. Normal results leave stderr empty.
Argument errors use argparse usage on stderr and exit 2.

- Exit 0: every supplied requirement has an eligible new or inherited observation,
  and all explicit inheritance edges qualify.
- Exit 1: input is inspectable, but requirements are uncovered or inheritance is
  rejected. Inspect `requirements[].rejected[].reasons` and `unverified`.
- Exit 2: invalid input, unavailable bytes, hash mismatch, or a read limit. Inspect
  `errors` and `inspection_complete: false`. Already collected `observations`
  remain in stdout. `verified_files` retains each byte-checked file even if a later
  file in the same record fails. Failed records are never reported as verified observations.

`requirements` reports `new`, `inherited`, or `unverified`, qualifying run IDs,
and rejection reasons. `observations` retains original records, verdicts,
provenance, conditions, gaps, file hashes, and source references.
`recorded_new_runs` and `inherited_runs` are distinct lists of qualifying run IDs,
not measured test counts. Rejected or unrelated new observations are still shown
in `observations`. `all_requirements_accounted` concerns only the supplied list.
`current_execution_complete` requires new coverage for every supplied requirement.
Neither flag is global validation, CI success, independent review, or merge
eligibility. An omitted requirement cannot be discovered by this CLI.

A URL is only a source locator. It cannot replace local evidence. Record JSON and
evidence bytes are checked against supplied hashes, but authenticity, truthful
verdicts, complete original inputs, GitHub authorization, and actual test execution
are not authenticated. `authenticity_verified` and `execution_verified` stay
false. A reconstructed input stays reconstructed even when its bytes match.
Do not turn an unknown historical command into a known condition to obtain exit 0.

## Fixed historical slices

PR131 changed tests between `292e2e541749324e493e76ee923cac8401281588` and
`84f53f5d5cd36e92ac4fd43c76e8d1306f032906`, base
`b668618f57aacf241516126c300a1c14d6d2b38b`. PR132 changed documentation between
`d19912b00e45220facb80cd5dafa486845e37828` and
`f5e45d3ae9090ed829a0005f848decfe46c6fa35`, base
`7077fc1af85204738e716f04b6fc572f83f04b58`.

The [PR131 old review](https://github.com/j5ik2o/event-store-adapter/pull/131#issuecomment-6770507874)
and [PR132 old review](https://github.com/j5ik2o/event-store-adapter/pull/132#issuecomment-6771392931)
record original PASS decisions. The [PR131 delta review](https://github.com/j5ik2o/event-store-adapter/pull/131#issuecomment-6770631446)
and [PR132 documentation review](https://github.com/j5ik2o/event-store-adapter/pull/132#issuecomment-6771704386)
separate new execution from old coverage. The source snapshots listed below were
retrieved at both fixed revisions and compared byte for byte for this change.
These historical suites were not rerun. Original per-run inputs were not
recovered. Reconstructed illustrative contracts do not authenticate inheritance
of their original runtime, commands, limits, or complete review coverage.

| PR | Unchanged source | SHA256 at both revisions |
| --- | --- | --- |
| 131 | `verification_conditions.py` | `c518c24725f99ec22a9f9e2c2bf22b7fdf5cb649eb52bc372f7c214ba83bee10` |
| 132 | `repository_coverage.py` | `0edbfdf740ed71f52d1f2ec2c4a70f8ca4c7d780383573ce78fa4cc25831c726` |

The behavior suite includes unchanged-slice inheritance, changed conditions and
source bytes, original FAIL and gaps, missing or changed evidence, duplicate run
identity, renamed old evidence as new, and distinct new-suite counting. Use the
synthetic generator above to build portable inputs without any author's temporary
files. Historical source acquisition and reconstructed contrasts are separate
from the new behavior tests. This extends #129's manual tooling; it does not
reopen its closed scope. Linux, Cloud, Docker, Java, original old case collections,
and actual GitHub build/test CI are outside this change.
