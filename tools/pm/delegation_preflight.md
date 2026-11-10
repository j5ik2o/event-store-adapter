# Manual delegation preflight

`delegation_preflight.py` compares a requested repository/project with a sourced
execution scope, assigned checkout metadata, and git observations. It is a manual
check for [#125](https://github.com/j5ik2o/event-store-adapter/issues/125), under
[#120](https://github.com/j5ik2o/event-store-adapter/issues/120). It requires only
Python 3.9 or later and, in live mode, git. It does not launch tasks or change T3.

## Run a self-contained control

From the repository root:

```sh
python3 tools/pm/delegation_preflight.py tools/pm/delegation_preflight_examples.json --case common-alias
python3 tools/pm/delegation_preflight.py tools/pm/delegation_preflight_examples.json --case java-local-rejection
python3 -B -m unittest discover -s tools/pm -p test_delegation_preflight.py -v
```

The first command exits 0 with `plan: compatible`, `assignment: matched`, and
`checkout: snapshot_match`. The second exits 1 with `plan: rejected`,
`assignment: unassigned`, and `checkout: not_observed`.

The live-success behavior test reads an existing common checkout without creating
or changing a repository. By default it finds that checkout from the test file
location. For a downloaded source snapshot, set `PREFLIGHT_TEST_CHECKOUT` to an
existing common checkout when running the tests. Only this test is skipped if no
checkout is available and the variable is absent. Its assignment is a synthetic
control built from independent git reads, not proof of a T3 allocation. The test
compares clean or dirty status with the recorded status; it does not certify that
execution is safe in a dirty tree.

The examples contain extracted evidence and explicitly marked synthetic controls.
The Java project id/root/origin are extracted from the recorded project list.
The exact `invalid_request` response is extracted from the failed local dispatch.
Its project was listed, and codex/gpt-6.1-sol was available, but the API rejected
another local project. No taskId or childThreadId was issued. The policy envelope
models that restriction; it is not a new API capability report. See the
[contemporary record](https://github.com/j5ik2o/event-store-adapter-java/issues/818#issuecomment-6779461098).
Source paths in the collection are references only. Neither the examples nor the
checker reads the author's `/tmp` files at runtime. `constraints=[]` from provider
capabilities does not prove that another project's checkout can be prepared.

## Observe a provided checkout

Prepare an input JSON from the `common-alias` case's `input` object. Fill its
requested target and scope from the actual work order/API scope evidence. Fill
assignment metadata from the checkout allocation record, including full commit,
branch, expected status and absolute physical root. Do not invent an assignment
from a planned target or from a project list. Then run:

```sh
python3 tools/pm/delegation_preflight.py /path/to/input.json --checkout /absolute/provided/checkout
```

Live mode ignores the input snapshot and obtains five fixed observations. The
explicit checkout path must resolve to `assignment.path`; otherwise it reports a
mismatch without observing that path. With no assignment it reports
`not_observed`. Use the physical root, rather than a symlink or subdirectory.
Do not create another checkout to make a failing comparison pass.

The git allowlist is `rev-parse --show-toplevel`, local config lookup of all
`remote.origin.url` values, `rev-parse --verify HEAD`,
`symbolic-ref --quiet --short HEAD`, and
`status --porcelain=v1 --untracked-files=all`. Each command has a 15-second timeout.
The checker clears inherited `GIT_*` overrides, disables optional index locks,
fsmonitor and untracked-cache use for these invocations, and never changes git
configuration. It performs no network requests. It never executes input commands.
Detached HEAD, missing origin, multiple origin URLs, and acquisition errors cannot
produce a complete live match. Earlier observations remain in the report when a
later command fails. Git observations are sequential, not an atomic snapshot.

## Input reference

The version 1 document has these fields. Unlisted fields are invalid.

| Record | Fields and types |
| --- | --- |
| `schema_version` | Exactly integer `1`; booleans and floats are invalid. |
| `requested` | Nonempty string `repo`, nonempty string `project_id`, required `environment_id` which is a string or null for local execution. |
| `scope` | String or null `policy`, `project_id`, `environment_id`, `repo`, `source`. Missing scope or policy gives `unknown`. Missing evidence for a known policy gives `incomplete`. |
| `assignment` | Null or object with strings `path`, `repo`, `project_id`, `head`, `branch`, `status`. All fields required. Path is absolute; head is a full lowercase 40- or 64-hex object id. Only status can be empty. Omission means unassigned. |
| `snapshot` | Optional object with `root`, `origin`, `head`, `branch`, `status` observations. Each is exactly `{ "value": "string" }` or `{ "error": "string" }`. Missing observations remain incomplete. |
| `host_aliases` | Optional map of lowercase hostname strings to canonical hostname strings. Exactly one explicit mapping is applied, with no recursive aliases. |

`scope.policy` recognizes `local_parent_project` and `environment_project`.
Any other string or null gives `unknown`. A known policy requires a nonempty
source reference, project id and repo. The environment policy additionally
requires an environment id. Local policy requires the requested environment to
be null. Environment policy requires it to equal the recorded environment.
Both require the requested project and repository to match the sourced scope.
A source string records the operator's evidence; it does not authenticate it.

Repository locators accept HTTPS, SSH URLs, or SCP-style SSH syntax with an
owner/repository path. Optional `.git` is removed. GitHub host and owner/repository
case are normalized. Other host paths retain case. Explicit ports, including `:0` and an empty `:` suffix, query strings,
fragments and unsupported forms do not match. Host aliases require explicit
mapping, such as `j5ik2o.github.com` to `github.com`. Another forge with the same
owner/repository is a different identity. This compares URL syntax, not remote
content or server authenticity. Credentials in remote URLs are discarded before
output. Raw URLs, supplied error messages, and status filenames are not echoed.

JSON duplicate keys, nonstandard numeric constants, unexpected types and malformed
records exit 2. Null is allowed only where specified. No bool/int coercion occurs.
The report exposes `plan`, `assignment`, and `checkout` separately. Plan acceptance
cannot substitute for checkout observations. Target/assignment repo and project
must match; root, HEAD, branch and status must match the assigned values, and
observed origin must match both requested and assigned repository identities.
Unassigned snapshots never count as verified checkouts.

| Result | Exit and output |
| --- | --- |
| All selected comparisons match | 0, JSON `comparison: consistent`. Snapshot mode reports `snapshot_match`; only live mode can report `live_match`. |
| Rejected, unknown, incomplete, unassigned or mismatched | 1, JSON `comparison: blocked` with separate verdicts, observations and reason codes. No stderr. |
| Invalid input or unreadable input file | 2, JSON `comparison: invalid_input` and a generic stderr diagnostic without raw external values. |
| Invalid CLI arguments | 2, argparse usage on stderr, no JSON. Help exits 0. |

## Limits

Exit 0 means consistency for the chosen observation mode. It does not mean API
acceptance, actual launch, safety, owner approval, merge eligibility, all-repository
coverage, absence of another worker, actual push consistency, cleanup permission,
or SDK/CI runtime test success. Snapshot mode compares supplied records only.
A manual live match does not guarantee future child checkout membership or T3
launch success. The child must repeat git checks at its own start. This checker
does not enable cross-project dispatch, prepare a Java checkout, or implement
Java #818. Independent review remains a separate PM step.
