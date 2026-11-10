# Manual CI status probe

`ci_status.py` reports status evidence for one immutable commit and a target branch on github.com. It uses Python 3 and authenticated `gh`. It sends GET requests only. It has no CI integration.

Without `--replay`, all three target flags (`--repo`, `--head`, and `--branch`) are required. Missing target flags and unreadable replay paths produce JSON with `execution.state=unknown` and an explicit stderr diagnostic. Argument-parser usage errors and `--help` use argparse's normal output instead.

```sh
python3 tools/pm/ci_status.py --repo j5ik2o/event-store-adapter-php \
  --head 7b5e0b8bf476ff9a6a2b14d5364da0171ad4e110 --branch main \
  --save /tmp/php35.capture.json > /tmp/php35.report.json
python3 tools/pm/ci_status.py --replay /tmp/php35.capture.json
python3 -m unittest discover -s tools/pm -p test_ci_status.py -v
```

## Output and exit codes

Stdout is one JSON object. Nonzero exits also write a brief diagnostic to stderr.

- Exit 0 means that all observed check runs, latest commit statuses, suites, workflow runs, and nonempty actual jobs report success. It does not assert test contents.
- Exit 1 means that acquisition completed but execution failed, is incomplete, or has no jobs. An empty collection never yields success.
- Exit 2 means that input or acquisition is invalid or incomplete. This includes 403, 404, missing pages, inconsistent counts, duplicate IDs, or a foreign head. It does not mean CI failed.

`configuration` reports branch protection, active branch rules, and required context names with app IDs. `known` with an empty list differs from `unknown`. A protected branch whose protection API cannot be read remains unknown, even if active rules can be read. This conservative choice also covers ruleset-only protection when the legacy endpoint returns 404. Required workflow policies are reported as unsupported acquisition evidence.

`required_gate` evaluates status contexts only. It does not predict merge eligibility, branch freshness, reviews, bypass permissions, merge queues, or merge-commit checks. Its states are `accepted`, `not_accepted`, `none`, and `unknown`. Successful, skipped, and neutral check conclusions can satisfy the context policy. Absent contexts do not. Multiple matching checks remain ambiguous. A context supplied by both a check and a commit status must satisfy both. An app-bound requirement cannot be proved by a commit status without app identity.

The combined-status endpoint promises the latest state per context. Repeated contexts in an acquired response are inconsistent evidence, so the probe reports acquisition errors and an unknown aggregate. It retains every status observation, including failures, rather than choosing the first or last state.

`actual_jobs` reports `success`, `failure`, `incomplete`, `absent`, or `unknown` separately. All observed jobs must conclude success. Skipped or neutral jobs never establish execution success. `execution` also accounts for external checks, suites, workflow runs, and statuses. A queued external app suite with zero observed jobs leaves execution incomplete. It does not establish a failed Actions job. `observed_failure` retains known failures even when acquisition errors make the aggregate unknown.

Malformed response envelopes, required-check configuration, rows, and identifiers add acquisition errors without discarding other successfully parsed observations. This includes a missing response body after a failed check was already observed. Invalid raw JSON cannot establish trustworthy observations; it produces the smaller invalid-input envelope instead.

`test_execution` always reports `unverified`. Successful job IDs and each job's steps provide pointers for further investigation. Job or step names do not prove test commands, test selection, assertions, nonzero test counts, or environment coverage. A green test command that skips every environment requires logs or artifacts to distinguish it from executed tests. This probe does not fetch those artifacts or certify that evidence.

The arrays retain API conclusions and identifiers, including unknown or null conclusions. `counts` separates check runs, commit statuses, suites, workflow runs, and jobs. Suite counts describe observed associations, not a claim that an external app has Actions jobs. `observed_check_count` covers the latest checks returned by the commit endpoint.

## Capture and replay contract

A version 1 capture has `schema_version`, `repository`, `head`, `branch`, `captured_at`, and `responses`. Each response is keyed by its relative REST path, including query parameters. It contains `http_status`, `body`, and `next`. `next` is a relative path from the response Link header, or null when there is no next page. A missing response or missing pagination metadata prevents success. An unavailable request has a null status if no HTTP response could be decoded.

The schema version must be integer 1, excluding booleans and floats. Only null terminates pagination; false, zero, empty strings, and other non-string markers are invalid. Both live and replay JSON reject duplicate object keys and non-finite numeric constants.

The capture stores response bodies and pagination information, never request authentication headers or gh stderr. Bodies may contain repository metadata. Treat private captures as private. Replay requires no token and makes no API requests. Captures are evidence supplied by their author, not signed GitHub attestations.

Acquisition follows next links with at most 100 pages per list and checks totals where supplied. It validates head SHA on checks, suites, workflow runs, jobs, and combined statuses, and validates job run and attempt IDs. Checks use `filter=latest`; workflow jobs use the current run's attempt endpoint. Historical attempts are not claims about the current attempt. Combined statuses provide the latest context states. Duplicate IDs are rejected. Missing or changed totals prevent success.

Requests are sequential observations, not an atomic GitHub snapshot. `captured_at` is the start time. A rerun or policy edit during acquisition can require a fresh probe. The branch flag identifies the target policy, while the SHA identifies execution evidence. Neither the capture nor the report claims the SHA is the current PR head. The report does not infer required contexts from job names.

## Regression evidence

The test file includes projections of GET responses acquired during this implementation on 2026-11-10 UTC. These projections retain IDs, conclusions, associations, totals, and pagination metadata used by the evaluator. They omit unrelated response fields. They are saved-response regressions, not new acquisition during tests. Synthetic cases test CLI exits, stderr, pagination, no data, success, failure, skip, neutral, and unknown evidence.

- PHP35 at `7b5e0b8bf476ff9a6a2b14d5364da0171ad4e110` has required `test` skipped and lint and review failed. The policy is accepted while execution fails.
- Common138 at `c4a181a4d43bc21394bbe33ebf2887dbf73c1365` has eight external queued suites with no observed jobs, two completed app suites, and no workflow jobs. Required contexts are absent on the unprotected branch. Execution is incomplete.
- JS1127 at `f1cde8989835f43421df5b605e0d1ef5a93d44ed` has nine successful Actions jobs and an accepted required context. External queued suites and a neutral app keep the overall execution incomplete. This real positive job control is distinct from the synthetic case where every observation succeeds.

Full local captures, JSON reports, stderr, and exits are in `/tmp/pm-ci-status-probe/`. Earlier sweep and independent-review records were reference material, not substitutes for acquisition. The implementation retrieved all three specified heads successfully. No historical API response was reconstructed and presented as a new response.

## GitHub API references

These official sources define the evidence used here.

- [Protected branch status checks](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches#require-status-checks-before-merging) describes success, skipped, and neutral acceptance, app sources, and same-name status and check requirements.
- [Get branch protection](https://docs.github.com/en/rest/branches/branch-protection#get-branch-protection) defines required checks and the Administration read permission.
- [Get rules for a branch](https://docs.github.com/en/rest/repos/rules#get-rules-for-a-branch) returns active branch rules across configuration levels.
- [List check runs for a Git reference](https://docs.github.com/en/rest/checks/runs#list-check-runs-for-a-git-reference) defines filters, conclusions, and app identity.
- [List check suites for a Git reference](https://docs.github.com/en/rest/checks/suites#list-check-suites-for-a-git-reference) defines suite status and head SHA.
- [Get combined status for a specific reference](https://docs.github.com/en/rest/commits/statuses#get-the-combined-status-for-a-specific-reference) defines latest context states and the response SHA.
- [List workflow runs](https://docs.github.com/en/rest/actions/workflow-runs#list-workflow-runs-for-a-repository) defines head filters and run attempts.
- [List jobs for a workflow run attempt](https://docs.github.com/en/rest/actions/workflow-jobs#list-jobs-for-a-workflow-run-attempt) defines actual jobs and step conclusions.
- [REST pagination](https://docs.github.com/en/rest/using-the-rest-api/using-pagination-in-the-rest-api) defines Link headers and next pages.
