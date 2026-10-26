<a id="main-の-ci-の失敗を-issue-で知らせるワークフロー"></a>
# Workflow that reports main CI failures through an issue

The canonical source of the workflow that reports main CI failures, copied with the same content into the repositories of the 6 languages.

| File | Role |
|---|---|
| `main-ci-failure.yml` | The workflow to copy into each repository's `.github/workflows/` |

<a id="何をするか"></a>
## What it does

When a CI workflow completes on main (`workflow_run`), it handles only runs whose original trigger was `push` or `schedule` (a scheduled run).

- Conclusion `failure`, `timed_out`, or `startup_failure` (a failure to start): look for an open issue with the label `ci-failure-on-main`. If there is none, create an issue; if there is one, add a comment to that issue. The body and the comment state the URL of the original run, the commit, the trigger, and the names of the failed jobs.
- Conclusion `success`: if there is an open issue, comment the URL of the successful run and close it. CI runs can overlap, so the issue is closed only by a success newer than the last failure recorded in the issue. Newness is compared by the CI workflow's run number (`run_number`) and attempt count (`run_attempt`, which increases when re-run), so it also closes when a failed run is re-run and succeeds.
- If the label does not exist, create it.

The number of concurrent runs is not limited. If it were limited, a waiting notification could be replaced by a later one and disappear. In exchange, when two failures finish at almost the same time, two issues may be created.

A failure of a check outside `CI Success` and a failure of `CI Success` itself are treated in the same way, as a failure of the CI workflow. It uses only GitHub issues and their notifications, and uses no external notification or Secret. The permissions are only `issues: write` and `actions: read`.

<a id="各リポジトリへの写し方"></a>
## How to copy into each repository

1. Copy `main-ci-failure.yml` to that repository's `.github/workflows/main-ci-failure.yml`.
2. Change only one place in the file, `on.workflow_run.workflows`, to match the `name:` of that repository's CI workflow. rs is `ci`, and the other 5 are `CI` (the canonical source is `CI`). Change nothing else.

<a id="写した後の確かめ方"></a>
## How to verify after copying

1. Merge the copied workflow into main.
2. Run `main-ci-failure` in Actions with `workflow_dispatch`, and pass as the input `run_id` the ID of a past failed main CI run (one from a push or a scheduled run).
3. Confirm that an issue with the label `ci-failure-on-main` was created.
4. When the verification is finished, close that issue.

If you pass the ID of a past successful run, you can also verify the process of closing an open issue.

<a id="ci-success-の依存に入れない"></a>
## Do not include it in the dependencies of `CI Success`

This workflow only notifies; it is not a mechanism to block merging. Do not include it in the dependencies of CI's `CI Success`, nor in the required checks of branch protection.
