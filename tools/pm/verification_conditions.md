# Compare recorded verification conditions

Run the manual comparison with Python 3. No packages, GitHub access, Java, or Docker are required.

```sh
python3 tools/pm/verification_conditions.py tools/pm/verification_conditions_java814.json
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/pm -p test_verification_conditions.py -v
```

The Java example exits 1. Inspect `scope_overlap` for the author's and old reviewer's repeated JDK11 conformance scope. Their command strings differ, so they are not an exact `overlap`. Inspect `different_fields` before treating two observations as equivalent. The new review adds JDK17 full-suite conditions on a different revision. It cannot satisfy `old-head-jdk17-full`. Unknown resource limits prevent these historical records from qualifying as fully specified passing conditions.

## Input contract

The example JSON is a complete input template. The root contains exactly `schema_version: 1`, `requirements`, and `runs`. Both arrays must be nonempty. Each array has unique string IDs. Unknown keys, missing fields, duplicate JSON keys, and invalid values are errors.

Each requirement contains `id` and `conditions`. Each run contains `id`, `actor`, `role`, `conditions`, `result`, `evidence`, and `unverified`.

- `actor` identifies a session, not necessarily a GitHub login. `role` is `author` or `review`. These are declarations. The CLI does not establish independence.
- `result` is `pass`, `fail`, `unknown`, or `not_run`.
- `evidence` is an array of nonempty locator strings. It may be empty, but an eligible pass requires evidence. A URL or local path records a location. It does not prove existence, authenticity, contents, or success. The CLI does not fetch evidence.
- `unverified` is an array of nonempty strings describing gaps within that run's conditions. Any entry prevents an eligible pass. Put other unexecuted conditions in separate requirements or `not_run` runs rather than attaching unrelated gaps to a successful run.

`conditions` has exactly these fields.

| Field | Value |
| --- | --- |
| `repository` | Repository identity |
| `revision`, `base` | Lowercase full 40-character hex commit IDs |
| `jdk` | Actual test JDK, including known version details |
| `runtime` | Runner JDK, operating system, architecture, and relevant runtime details |
| `command` | Recorded command text, never executed |
| `suite` | Explicit test selection |
| `resources` | Object with exactly `heap`, `cpu`, `memory`, `parallelism` |

Every scalar condition accepts a nonempty string or `null`. Use `null` for unknown facts. Common placeholders such as `unknown`, `n/a`, and `?` are rejected. Record effective limits, not intended environment variables. Resource strings should include units and scope. The tool compares strings exactly, without unit conversion, shell parsing, suite hierarchy, or defaults. Choose consistent labels when preparing records. Preserve different commands rather than normalizing away potentially significant flags.

A condition is eligible only when all fields are known, its result is `pass`, evidence is nonempty, and `unverified` is empty. Null values never act as wildcards, including when both records contain null. Free text is caller supplied. Validation cannot detect fabricated metadata or a lie written as a nonempty string.

## Output contract

`overlap` lists exact author/review condition matches, regardless of result. A second pass on identical conditions adds confirmation, not breadth. `added_review_conditions` lists review observations without an exact author condition match. Addition does not mean success or broader suite coverage. Failed and unexecuted observations can appear here.

`scope_overlap` lists pairs with the same known repository, revision, base, JDK, and suite. It reports command, runtime, and resource differences and the author's unknown fields. This helps identify repeated test selections even when execution details differ. It is diagnostic only and cannot satisfy a requirement.

`runs` reports eligibility and machine-readable reason codes with field paths. `requirements` reports exact matching runs, eligible author/review coverage, and reasons. `unverified` lists uncovered requirement IDs. A failed run does not erase another eligible successful observation. Both remain in the output for inspection. For a new failure or changed conditions, create a separate requirement or remove the superseded run rather than assuming chronology or latest-run semantics.

`complete` is true only when every explicit requirement has an eligible exact passing run. It can be true; the tests demonstrate this with fully specified synthetic records. It means coverage of the supplied requirement list, not global completeness, review approval, CI success, or permission to merge. The CLI cannot discover omitted requirements. Review coverage is reported separately from author coverage. `evidence_verified` and `independence_verified` remain false.

Exit codes are 0 for covered input, 1 for valid input with uncovered requirements, and 2 for invalid or unreadable input. Input errors emit JSON with `complete: false` and `errors` containing `code` and `path`. Argument usage errors follow argparse conventions on stderr. No input command is executed and no network request is made.

## Java814 and Java815 evidence

The example fixes old revision `7334a49330aa7d647930da0777b60a3a9ac9b0f3`, repaired revision `0450b26184912af9c15d7572ca8e6c26c6091bf0`, and base `d0237ddcd76149fae8296fedea1f4b1f1d281ae5`. It records historical executions, not a new Java run.

- [Author result](https://github.com/j5ik2o/event-store-adapter-java/issues/813#issuecomment-6767842659) records JDK11 conformance success and unexecuted full repository/JDK17 conditions. The existing `validation-final.log` in `/tmp/java-conformance-813.P9mfG3/` confirms the JDK11 executable path and BUILD SUCCESSFUL.
- [Old independent review](https://github.com/j5ik2o/event-store-adapter-java/pull/814#issuecomment-6767996357) records its command, base, JDK25 runner, JDK11 test selection, and unexecuted full suite and JDK17/19. Its existing `/tmp/M-java-conformance-review.vaacmO/jdk11.log` confirms 11.0.32.1, macOS/aarch64, and `gradle.exit` is 0. The author's runner details and both old executions' effective limits remain unknown here. A configured default is not proof of an observed limit.
- [Issue815](https://github.com/j5ik2o/event-store-adapter-java/issues/815) records the old head's JDK17 full-suite CI OOM at a 512MB test heap. JDK11 conformance successes did not cover that condition. The `not_run` record represents the old reviewer's gap, not the CI execution itself.
- [New independent review](https://github.com/j5ik2o/event-store-adapter-java/pull/814#issuecomment-6768867219) records JDK17 full suite and core-only execution at the repaired revision. Existing `/tmp/m-java-oom-review.36z1GL/run.sh`, `full.exit`, and `worker-flags.log` confirm the command, exit 0, and MaxHeapSize=536870912. CPU, process memory, and parallelism limits remain unknown in the example. This review broadened the old review's selection, while repeating the repaired author's JDK17 selection. The example does not fabricate an exact repaired-author command to claim an exact match.

Current PR text can change. The fixed comments and revisions above preserve the historical distinction. Source snapshots, CLI outputs, and implementation audit material are kept outside the repository in `/tmp/pm-verification-conditions/`. Local evidence paths are locators and may be unavailable on other machines.

This tool does not integrate T3 or CI, recover missing ledger entries, or certify independent review. The PM arranges independent review of this implementation separately.
