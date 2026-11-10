# Compare a T3 inventory with Git worktrees

This manual Python 3.9+ CLI compares a saved current T3 export with a separate Git observation. It never calls T3, contacts workers, waits for tasks, or grants cleanup permission. Every tree remains `retain`, including trees whose reported owner is completed. An exit of zero means that the supplied inventory and observations agree within their declared scope. It does not mean the work is accepted or a tree can be deleted.

## Acquire one current export

Use the actual MCP `t3_thread_list` with the intended `projectId`, `includeSubagents=true`, and no status, settled, snoozed or title filters. Start without a cursor. Save each response, then follow every `nextCursor` until null. Do not mix earlier delegation or approval history into this inventory. On API failure, save an error page and keep prior pages. A changing total, duplicate ID, missing parent, cycle, missing page or unknown scope prevents a complete result.

Construct an export JSON object with these fields:

- `schema_version`: integer 1.
- `source`: nonempty acquisition description. `at`: timezone-aware ISO timestamp.
- `projectId` and `parentThreadId`: exact intended project and PM IDs. The current worker is not the PM.
- `includeSubagents`: the actual boolean request value. `filters`: `{}` for an unfiltered request.
- `pages`: response objects with an added `cursor` equal to the request cursor, null for the first page. Each successful page requires `projectId`, nonnegative integer `total`, `nextCursor`, and `threads`. An unsuccessful page is `{"error":"acquisition failed"}`.
- Each thread requires `threadId`, `projectId`, `parentThreadId`, `relationshipToParent`, `status`, `updatedAt`. Parent and relationship are both null for a root; otherwise the relationship is `fork` or `subagent`. Preserve the actual status; idle is not completed.
- `metadata`: one `t3_thread_read` thread object per relevant PM/descendant whose provided path is absent from the list. Use `limit=1`, `maxCharsPerItem=1`, `runLimit=1` and discard conversation items. Save `threadId`, parent, relationship, status, `updatedAt`, `worktreePath`, `branch`, and optionally `pendingRequestCount` and `projectId`. An explicit metadata project must agree with the export and listing. On failure save `threadId` and `error`. Do not query running workers. Metadata reads are one-time inventory reads, not polling. A changed metadata timestamp or status is reported as inconsistent with the list rather than silently overwriting it.
- Optional `auditPaths`: exact known audit-only paths. Other non-root paths are classified as work trees. This classification is supplied context, not authenticated ownership.

The graph is checked across the supplied project listing. A parent outside that scope is a gap. A missing/null path is unknown, even for a read-only worker. The CLI cannot prove the export's request flags, completeness claims, authenticity or freshness. Preserve the acquisition record for review. Raw conversation bodies and credentials do not belong in the export.

## Observe Git independently

Prepare a roots JSON file containing the intended repositories and their existing absolute root paths:

```json
{"host_aliases":{"j5ik2o.github.com":"github.com"},"repositories":[{"repo":"j5ik2o/event-store-adapter","root":"/absolute/existing/root"}]}
```

Run these commands from the repository:

```sh
python3 tools/pm/thread_worktree_audit.py observe-git roots.json > git.json
python3 tools/pm/thread_worktree_audit.py check export.json git.json > result.json
```

The default ledger is the adjacent `repository_coverage_ledger.json`, currently covering 16 repositories. Missing roots must remain in the roots file so their observation failures stay visible. `--ledger path.json` selects a smaller explicitly declared scope, with `repositories` containing `repo` objects. This is a different scope and must not be described as the complete group inventory.

Git capture uses only fixed commands: `worktree list --porcelain -z`, top-level path, local origin, branch, HEAD, status with all untracked files, five commit IDs and dates, upstream and ahead count. It disables optional locks, fsmonitor and untracked cache for each process, ignores inherited Git environment overrides, does not fetch, and changes no configuration. Input never supplies a command. Paths with spaces, Unicode or newlines are parsed using NUL delimiters. Origins become credential-free syntactic identities through the existing preflight identity parser; explicit host aliases are caller assertions. Git errors retain the other observations. A missing upstream is unknown, not proof that nothing is unpushed. Ahead counts describe locally stored upstream refs; they do not prove current remote state. Git processes have a 15-second timeout each.

Saved Git records contain `source`, `at`, and `repositories`. Each repository has `repo`, `root`, `listing` as `{"value":"NUL-delimited porcelain"}` or `{"error":"..."}`, and `trees`. Each tree has `path`, `at`, and `observations`, with the fixed field names in `GIT` in the script. Each observation is exactly one string `value` or `error`. `origin.value` is the normalized identity, never the raw URL. Snapshot checks compare these saved observations; metadata alone never counts as live Git verification. Git capture is separate and does not make the offline checker a real-time monitor.

## Run portable positive and negative examples

The committed examples are synthetic snapshots, including a Unicode path with a space. They require no author files, credentials, repository creation or services:

```sh
example_dir=$(mktemp -d)
python3 - "$example_dir" <<'PY'
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
d = json.loads(pathlib.Path('tools/pm/thread_worktree_examples.json').read_text(encoding='utf-8'))
for name in ('export', 'git', 'ledger'):
    (p / (name + '.json')).write_text(json.dumps(d[name]), encoding='utf-8')
d['export']['includeSubagents'] = False
(p / 'top-only.json').write_text(json.dumps(d['export']), encoding='utf-8')
PY
python3 tools/pm/thread_worktree_audit.py check "$example_dir/export.json" "$example_dir/git.json" --ledger "$example_dir/ledger.json"
# Expected: exit 0, consistent, all cleanup decisions retain.
python3 tools/pm/thread_worktree_audit.py check "$example_dir/top-only.json" "$example_dir/git.json" --ledger "$example_dir/ledger.json"
# Expected: exit 1, includeSubagents_not_true, known threads and commits retained.
python3 -m unittest discover -s tools/pm -p test_thread_worktree_audit.py -v
```

## Interpret results

Stdout is one JSON document. Exit 0 means consistent records; exit 1 means coverage, observation or reconciliation needs review; exit 2 means malformed/unreadable input. Nonzero exits also print a generic stderr diagnostic. Invalid individual page, thread, metadata and repository records are recorded without discarding other parsed records. Malformed Git fields become unknown errors while the other fields and following trees remain available; an invalid listing does not discard independently supplied tree observations. Invalid metadata fields likewise preserve the other validated fields. A malformed whole JSON document, duplicate key, parser resource failure or unreadable file produces `invalid_input`; facts that cannot be parsed cannot be recovered. Booleans are not accepted as integers. Unknown lifecycle enum values are invalid. Standard argparse usage errors use exit 2 and stderr without JSON. Output does not copy arbitrary extra API fields or conversation items.

Each thread retains valid listing rows in `list_observations` and validated metadata fields or acquisition failures in `metadata_observations`. Duplicate records do not overwrite earlier evidence. The primary metadata view retains the first parsed observation; it is not a selected winner. Conflicting or duplicate observations make `git_comparison=ambiguous`. All observed owner paths and failure/waiting states remain available for conservative review. Each tree reports source-linked Git observations, candidate owner IDs and cleanup conditions. PR merged, successful main CI after merge, no remaining assignee, non-shared ownership, saved information, no tree-only artifacts and authenticated approval remain unknown unless this tool can directly observe their limited Git component. This minimal version intentionally does not accept self-reported PR or ownership booleans as proof. Interrupted, failed, cancelled, rolled-back and question-waiting owners are explicit cleanup exclusions. Root trees are shared and retained. No remove, force, branch deletion or thread deletion function exists.

`stale=not_assessed_single_observation` preserves uncertainty. Consider the actual status, last update, commit dates, untracked status and observation interval in a separate human review. One timestamp or clean tree does not demonstrate stagnation. Read-only or API work can have useful results outside Git. These observations are sequential and can race ongoing work.

Current API controls demonstrate the omission class caused by top-only or truncated listings. They do not revalidate a historical incident without its original inputs and complete evidence. Historical reconstruction remains tracked in issue #120.
