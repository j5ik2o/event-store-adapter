# Check a recorded repository audit for omissions

This manual, offline Python 3 CLI compares the explicit [16-repository ledger](repository_coverage_ledger.json) with a PM inventory and its per-repository GraphQL responses. It reports omitted examples even when the operator does not list their names again. Local checkout availability does not affect the ledger. dotnet and php remain GitHub audit targets.

Run from the repository root. Obtain an acquisition bundle from your PM collector containing `inventory.json` and the per-repository `<repo>.json` GraphQL responses described below. This CLI does not include a live collector. Copy the complete bundle into a local directory and replace `/path/to/your/pm-audit` with that directory.

```sh
audit_dir="/path/to/your/pm-audit"
python3 tools/pm/repository_coverage.py \
  --inventory "$audit_dir/inventory.json" \
  --records-dir "$audit_dir"
python3 -m unittest discover -s tools/pm -p 'test_repository_coverage.py' -v
```

The implementation's historical inventory recorded `2026-11-10T15:09:36.787078+00:00` and returned exit 0 with 16 successful repositories. That acquisition bundle is not included in a checkout; its original `/tmp/pm-handoff-live-audit` path belongs to the implementation environment. The observation does not describe current GitHub state. The tool does not fetch data, execute input commands, change files, configure CI, schedule runs, or enforce T3 gates.

## Create a local example

To try the checker without an acquisition bundle, run this complete example from the repository root. It creates synthetic responses with zero open items for all ledger repositories. These files demonstrate input consistency, not a real GitHub audit or a reproduction of the historical acquisition.

```sh
audit_dir="$(mktemp -d)"
python3 - "$audit_dir" <<'PY'
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

directory = Path(sys.argv[1])
ledger = json.loads(Path("tools/pm/repository_coverage_ledger.json").read_text())
results = []
for entry in ledger["repositories"]:
    name = entry["repo"].split("/", 1)[1]
    repository = {"name": name}
    for connection in ("pullRequests", "issues", "milestones"):
        repository[connection] = {"nodes": [], "pageInfo": {"hasNextPage": False}}
    response = {"data": {"repository": repository}}
    (directory / (name + ".json")).write_text(json.dumps(response), encoding="utf-8")
    results.append({"repo": name, "prs": 0, "issues": 0,
                    "milestones": [], "pagination": []})
inventory = {"at": datetime.now(timezone.utc).isoformat(), "results": results}
(directory / "inventory.json").write_text(json.dumps(inventory), encoding="utf-8")
PY
python3 tools/pm/repository_coverage.py \
  --inventory "$audit_dir/inventory.json" --records-dir "$audit_dir"
```

Expect exit 0, `status: consistent`, and 16 `successful` names. Keep the generated directory for inspection. Use a collector's actual responses instead of these synthetic files when checking an operational audit.

## Inputs and scope

`--ledger` defaults to the adjacent ledger JSON. `schema_version` must be the JSON integer `1`; booleans and floating-point values are invalid. Schema version 1 has a nonempty `repositories` list of unique full `j5ik2o/repo` names. Each row references nonempty `sources` entries with `url` and `scope`. The ledger is an explicit reviewable audit input. It cannot prove that its own list contains every repository the owner manages. Change it when the owner changes scope.

The ledger maps each repository to its evidence. The README lists the eight library implementations. The operations policy and implementation plan cover six registered implementation repositories. They do not define this broader audit boundary. The example README lists four language examples. Kotlin and Scala examples and both coordinator repositories are included by the explicit PM work order. The start comment records the 16-repository acquisition; the work order and supplied inventory provide the exact names. External-owner Swift and PHP links in the READMEs do not expand this mandate. No operations policy is changed.

`--inventory` is a JSON object with a timezone-aware ISO `at` timestamp and nonempty `results` list. Successful rows require a short lowercase `repo`, nonnegative integer `prs` and `issues`, a `milestones` list, and a `pagination` list. A row with a nonempty `error` declares acquisition failure, even if it also contains a repository name or success fields. An error row can omit the summary fields. Duplicate JSON keys and nonstandard numeric constants are invalid.

`--records-dir` contains `<repo>.json` responses for every row that does not declare an error. These are the PM collector's GraphQL envelopes, with `data.repository.name` and the `pullRequests`, `issues`, and `milestones` connections. Each connection needs object `nodes` and boolean `pageInfo.hasNextPage`. Names and counts must agree with the inventory, and milestone nodes must equal its summary. Empty nodes are valid. Empty files, null repositories, missing connections, and absent raw files cannot pass.

GraphQL `errors` prevent success even alongside usable partial data. Any true `hasNextPage` or `hasPreviousPage` in supplied `pageInfo`, or nonempty inventory `pagination`, means incomplete acquisition. No pagination is followed. For multiple fetched pages, produce a separate reviewed complete acquisition record rather than relabel this partial input.

Success covers the recorded query's top-level open PR, issue, and milestone connections, plus pagination metadata actually supplied by that query. It does not verify node body semantics or discover omitted nested fields. In particular, the supplied query's issue labels have no pagination metadata. Closed issues, historic records, all-issue-records-current.json, threads-current.json, and worktrees-current.json are outside this check. The timestamp and short repository owner binding are assertions from the PM collector. The CLI does not authenticate GitHub responses, verify the owner on GitHub, certify freshness, or audit the quality of PM decisions.

## JSON and exit contract

The CLI writes one JSON object to stdout. Argument syntax errors use argparse's stderr and exit 2. Other invalid inputs emit `schema_version: 1`, `status: invalid_input`, and `errors`. Once the envelope and ledger validate, every output includes the following fields.

| Field | Meaning |
| --- | --- |
| `expected`, `observed` | Sorted unique full names from the ledger and inventory. |
| `successful` | Records with consistent query evidence, excluding duplicated names. Unexpected names may appear here but still prevent overall success. |
| `missing` | Expected names absent from the inventory. A named failed row is observed, not missing. |
| `unexpected` | Observed names outside the ledger. |
| `duplicates` | Names with multiple inventory rows. No duplicate counts as successful. |
| `failed` | Inventory acquisition errors or GraphQL errors. |
| `incomplete` | Unconsumed pagination in otherwise valid evidence. |
| `invalid_records` | Missing, malformed, or contradictory record evidence. |
| `errors` | Envelope or ledger errors. Empty for validated envelopes. |
| `at`, `scope` | Recorded collection time and the limit of the claim. |

Record diagnostic entries include `repo`, zero-based inventory `index`, and `reason`. Categories can overlap across rows. Structural contradictions take priority over pagination within a row. Invalid records take exit priority over other gaps, which remain visible in the JSON.

| Exit | Status | Meaning |
| --- | --- | --- |
| 0 | `consistent` | Exact expected set, one successful record each, no diagnostics. |
| 1 | `coverage_gap` | Missing, unexpected, duplicated, failed, or incomplete acquisition. |
| 2 | `invalid_input` | Invalid ledger, envelope, file, or per-repository evidence. |

## Reproduce the omission pattern

[Issue #124](https://github.com/j5ik2o/event-store-adapter/issues/124) records that examples were omitted. The historical raw audit input was not recovered. [repository_coverage_missing_examples.json](repository_coverage_missing_examples.json) is a reconstructed nine-library inventory with synthetic zero counts. The CLI tests create matching synthetic response files and verify that the CLI lists all seven missing example repositories. They also prove that valid zero-item acquisitions succeed and that failed acquisitions with names cannot claim completeness.

The CLI tests create their own temporary response files, so they run from a checkout without the historical acquisition bundle. Implementation evidence and its temporary paths are recorded in [PR #132](https://github.com/j5ik2o/event-store-adapter/pull/132). Those files are not repository assets or prerequisites for the local example.
