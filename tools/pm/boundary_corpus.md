# Rerun PM CLI boundary evidence

Run the manual corpus from a checkout with Python 3.9 or later. It needs only the standard library and the four existing PM CLIs.

```sh
python3 -B tools/pm/boundary_corpus.py
python3 -B -m unittest discover -s tools/pm -p test_boundary_corpus.py -v
```

The runner prints the evidence directory. To choose a location, pass `--output /path/to/new/run`. The directory must not exist. Keep it to inspect inputs, exact commands, stdout, stderr, exit codes, generated manifests, source SHA256 values, results, and the evidence SHA256 manifest. It creates local files only inside that directory. It never imports existing test modules.

Relative output locations are resolved from the caller's working directory before fixtures run. If an executed target emits invalid JSON or malformed retention evidence, the case remains a contract mismatch; those observations do not become incomplete execution. A target that exits before calling the fake `gh` has zero recorded calls and remains a contract mismatch.

To rerun one contrast, select its exact ID. Repeat `--case` to select several. A selected run establishes only those cases.

```sh
python3 -B tools/pm/boundary_corpus.py --case ci-late_body --case ci-legal_null
/usr/bin/python3 -B tools/pm/boundary_corpus.py --case pr-huge_hunk_integer
```

Read each entry in `boundary_corpus.json` for its target, source, reconstructed input or named generation recipe, expected underlying exit, JSON fields, stderr presence, evidence retention, output creation, and runtime requirements. The table is not a common validator for different product JSON contracts. The runner's checker compares observations with those declarations.

## Interpret the result

The corpus exits 0 only when every selected case executes and matches its contract. It exits 1 for a contract mismatch and 2 for incomplete execution, unsupported fixtures, or unknown case selection. A mismatch remains visible in the per-case results even when another case makes the overall run incomplete. Zero cases never pass. A product exit 1 or 2 can be the correct observation, but only the complete declared contract earns a case pass. Neither product exit is silently converted to product success.

`pr_file_diff` always declares completeness unproven, including its legal patch control. The corpus checks exit 1 and `complete: false`. Its isolated fake `gh` executable returns three saved synthetic responses and records argv. No GitHub GET occurs. It rejects unexpected non-GET invocations. Other targets consume local replay or local evidence fixtures. No API, container, credentials, arbitrary command from JSON, or user artifact is required.

`repository_coverage` includes integer, boolean, floating-point schema versions, a recursive raw response, and a named acquisition failure. The recursive case checks that the record remains diagnosed and excluded from successful results. Valid zero-item acquisition is a legal control.

`artifact_evidence` generates a manifest and passes it to the actual reader with its contract. Its short-path control includes Unicode, a quote, and a backslash. Rejection cases assert no manifest output. The absolute-path expansion and serialized JSON escape limit cases require long Unicode paths. The runner checks PATH_MAX and creates the fixture before invoking the CLI. Unsupported filesystems produce `unsupported`, never pass. Fixture creation failure is not evidence against an old CLI.

`ci_status` covers later body loss, missing suite and successful-job IDs, contradictory same-name contexts, invalid lifecycle, required status missing versus explicit null, strict boolean versus integer schema, and a finite legal extension. Partial-response cases compare every retained input row and field, all collection counts, acquisition errors, and the independent observed failure. The successful-job pointer list must exclude a missing ID. Required policy and execution remain separate from proof of real test contents.

## Compare historical sources

The default run uses the adjacent four CLI files. To compare the same reconstructed inputs with historical versions, explicitly supply a trusted source directory with files at `<full SHA>/<target>.py`. The runner does not download or execute source paths supplied in corpus data. Targets are allowlisted; SHA and case names are bounded to hexadecimal or simple identifiers. Supplying `--historical-dir` authorizes executing those local Python sources. Review their bytes first.

Acquire sources with read-only GitHub commands outside the corpus. For example:

```sh
mkdir -p /path/to/sources/bbfc4a34f44220af891474b06fc6604b586d1ce0
gh api repos/j5ik2o/event-store-adapter/commits/bbfc4a34f44220af891474b06fc6604b586d1ce0
gh api -H 'Accept: application/vnd.github.raw+json' \
  'repos/j5ik2o/event-store-adapter/contents/tools/pm/pr_file_diff.py?ref=bbfc4a34f44220af891474b06fc6604b586d1ce0' \
  > /path/to/sources/bbfc4a34f44220af891474b06fc6604b586d1ce0/pr_file_diff.py
python3 -B tools/pm/boundary_corpus.py --case pr-invalid_marker \
  --historical-dir /path/to/sources
```

Use all full SHAs declared in the JSON for a full comparison. The corpus records source hashes but does not authenticate supplied sources against GitHub. Acquisition is a separate network operation. Missing sources are incomplete. Historical runs must match a specific observed regression signature or legal control. An arbitrary old failure does not pass. For the old huge integer, a saved capability probe runs with the same child interpreter and environment as the target. If that runtime accepts 5000 digits, the old CLI must misclassify the patch as API-consistent; otherwise it must raise a digit-limit ValueError. This includes backported limits and limits disabled or raised through the environment; parent-only interpreter flags are not assumed to reach the child. Old recursion must specifically produce a RecursionError with no JSON. These are exceptions to the normal structured-output expectations, restricted to historical comparisons.

## Scope and implementation evidence

This new runner, declaration table, behavior tests, and document implement the manual corpus portion of [issue 136](https://github.com/j5ik2o/event-store-adapter/issues/136) and its checkpoint100 backlog. The four targets are `pr_file_diff.py` from PR130, `repository_coverage.py` from PR132, `artifact_evidence.py` from PR133, and `ci_status.py` from PR143. `verification_conditions` and `check_delegations` are outside this corpus.

Fixtures reconstruct reported counterexamples. They are not the original API bodies or historical input acquisition. The CI sample shape is limited inheritance from the existing test fixture, with explicit reconstructed mutations. Later-body and suite-ID cases use a synthetic sample rather than the historical PHP capture. Source reports are provenance references, not runtime dependencies. Earlier reviewers' executions are not new passes from this corpus.

At fixed main `a63b307e5d8e5a1801e0eed40921f3757ae23c02`, the implementation was exercised on macOS with Python 3.9.6 and 3.15.2. Each runtime executed 21 cases against current and historical sources. The two long-path cases were unsupported and unexecuted on both runtimes. Full runs therefore report incomplete, not PASS. Linux long-path before/after remains unverified in this implementation session; earlier PR133 Linux evidence is reference only. The behavior tests check incorrect exits, lost JSON fields, missing diagnostics, unintended output, evidence erasure, counts, and unknown selections.

This corpus does not claim coverage of all CLI inputs, all GitHub schemas, response authenticity, current CI health, actual test execution, or merge eligibility. It adds no CI wiring, workflow, shared validator, or skill. CI enforcement and the existing all-skip discussion remain separate in issue 134. Independent review and PM acceptance of this change remain pending; issue 136 stays open.
