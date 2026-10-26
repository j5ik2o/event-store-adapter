<a id="リポジトリ運用方針"></a>
# Repository Operations Policy

The common policy on CI, branch protection, merging, review, dependency updates, and agent operations that each repository of the event-store-adapter group follows. Agreed with the owner on 2026-10-03. To change the policy, obtain the owner's agreement.

The policy applies to the following six repositories registered in Orca. php, swift, and dotnet, which are listed in the README, will be added to the scope when they are registered in Orca.

- [event-store-adapter-rs](https://github.com/j5ik2o/event-store-adapter-rs)
- [event-store-adapter-js](https://github.com/j5ik2o/event-store-adapter-js)
- [event-store-adapter-java](https://github.com/j5ik2o/event-store-adapter-java)
- [event-store-adapter-scala](https://github.com/j5ik2o/event-store-adapter-scala)
- [event-store-adapter-kotlin](https://github.com/j5ik2o/event-store-adapter-kotlin)
- [event-store-adapter-go](https://github.com/j5ik2o/event-store-adapter-go)

<a id="1-ci"></a>
## 1. CI

- Do not add path filters (`paths`, `paths-ignore`) to the CI of PRs. With a filter, CI does not run on a PR that changes only files outside the filter, and the required check stays stuck in "pending".
- CI has an aggregate job, `CI Success`, that collects the results of all jobs. It always runs with `if: always()`, and fails if any of its dependencies ended with anything other than success (failure, cancellation, or skip). GitHub treats a skip as a pass, so this is to avoid missing the case where a downstream job is skipped because of an upstream failure.
- Do not include in the dependencies of `CI Success` a job that would block every PR purely because of external circumstances (such as a vulnerability audit).
- Give each job a `timeout-minutes`, so that a job stuck on something like fetching dependencies does not wait for GitHub's default of 6 hours. Decide the value per repository by adding some margin to the recent successful run time, and write the rationale in the PR.

<a id="公開の-workflow"></a>
### Publishing Workflow

Agreed with the owner on 2026-10-03. This is so that all repositories avoid repeating the problems found in publishing Snapshots for java, kotlin, and js (publishing a PR's branch, publishing an old commit, and pushing to main before publishing).

- A workflow that publishes on every change to main, such as a Snapshot, does not publish in the CI of a PR.
- Publish only a commit for which the CI of a push to main or of a scheduled run succeeded, and which is the head of main both when the run starts and immediately before publishing. Check out by that commit's SHA. Even when an old run is re-run, the check immediately before publishing prevents publishing old code.
- A workflow that publishes from a release tag (including manual re-publishing of an existing tag) is exempt from the condition in the previous item that requires the head of main and a successful CI on main. It checks out the tag to be published ([the Release workflow of js](https://github.com/j5ik2o/event-store-adapter-js/blob/35de020edcf113191c27fef73aa84707edbcf46e/.github/workflows/release.yml)).
- The publishing job does not commit or push to main. The Snapshot version is decided only inside the job.
- When the package registry supports OIDC Trusted Publishing, publish with OIDC rather than a long-lived token. Only when the registry does not support it (such as Maven Central), place the token in Secrets (chapter 7).

<a id="版上げの-workflow"></a>
### Version Bump Workflow

Revised on 2026-10-05 in line with IP-D1 of the [implementation plan](../plan/implementation-plan.md) (proceed with the rewrite to the new common specification on main).

- The version bump workflow is started only manually. No scheduled run is placed. This is so that intermediate changes of the rewrite that have been merged into main are not published automatically.
- In a manual start, the stage to bump can be chosen with the input `level` (auto, patch, minor, major). With auto, it is decided from the commits since the previous tag.
- The decision is: major if there is a `!` immediately after the type in the subject, or a line starting with `BREAKING CHANGE:` or `BREAKING-CHANGE:` in the body; minor for `feat` and `revert`; patch for all other types including `perf`. If there are no commits to decide from, it ends with a failure.
- Place a unit test of the decision script and a static check of the workflow (actionlint) in CI, and include them in the dependencies of `CI Success`.

<a id="リリースノート"></a>
### Release Notes

Agreed with the owner on 2026-10-15. This is because the record of changes was split into two places, a handwritten `CHANGELOG.md` and the release notes for rs only, while the other five languages had only release notes, so the place to look differed by language.

- The record of changes is only the release notes of the GitHub Release that the version bump workflow creates. `CHANGELOG.md` is not kept. rs's `CHANGELOG.md` is kept as the record up to 5.0.1 and is not updated (rs #305).
- The release notes are created automatically by grouping the commit subjects from the previous tag to the new tag by Conventional Commits type (`feat`, `fix`, and so on). They are not supplemented or corrected by hand.
- The way of creating them is the same in all six repositories. The canonical sources are placed in `tools/release-notes/` of this repository (`create-release-note-header.py`, which creates the heading; `create-release-note-body.py`, which creates the body; and the test `test_release_notes.py`). Each repository copies the two scripts to `.github/` and the test to the same directory as the version bump tests, with identical content. The content is not changed. The version bump workflow passes the subjects and bodies of the commits since the previous tag to the body script with `--no-merges --format='%H%x1f%s%x1f%b%x1e'`. How to call it is in [tools/release-notes/README.md](../../tools/release-notes/README.md).
- The test runs, together with the version bump tests of each repository, in a job included in the dependencies of `CI Success`. When the canonical source in this repository is changed, the coordinator redistributes it to the six repositories.
- Because merging is squash only, as in chapter 3, one PR becomes one commit on main, and its subject becomes one line of the release notes. When merging with squash, the coordinator puts the subject into the Conventional Commits form (such as `fix(deps): ...`) and writes it in words that users can read and understand.
- A breaking change is indicated by a `!` immediately after the type in the subject, or a line starting with `BREAKING CHANGE:` or `BREAKING-CHANGE:` in the body. The version bump decision in the previous item also uses this to make it major.
- The procedure for when users need to change their own configuration is not added to the release notes but written in documents such as the README (the DynamoDB SDK feature specification for rs 5.0.2 is rs #305).

<a id="適合テストデータの照合"></a>
### Verifying the Conformance Test Data

Placed on 2026-10-05 in line with IP-D7 of the implementation plan.

- Each repository copies `conformance/` and `tools/conformance/manifest.py` of this repository with identical content. The content is not changed.
- CI runs `python3 tools/conformance/manifest.py verify` and compares the SHA-256 of `conformance/manifest.json` with a pinned value. This step is placed in a job included in the dependencies of `CI Success`.
- When the data of this repository is changed, the coordinator redistributes it to all repositories and also updates the pinned value.

<a id="公開-api-の形の照合"></a>
### Verifying the Shape of the Public API

Placed on 2026-10-14 in line with item 4 of the acceptance criteria in chapter 5 of the [implementation plan](../plan/implementation-plan.md). Agreed with the owner.

- Each repository copies `api-surface/surface.json` of this repository to `api-surface/surface.json` with identical content. The content is not changed.
- CI compares the SHA-256 of the copy with a pinned value. It runs a test that verifies the shape of the public API from the copy and from the name mapping table that each repository holds (`api-surface/<language>.json`). The verification test also includes a negative test showing that it can report a definition whose shape was deliberately shifted. Both are placed in a job included in the dependencies of `CI Success`.
- When `surface.json` of this repository is changed, the coordinator redistributes it to all repositories and also updates the pinned value. What to change in the same PR is in "Steps when bumping the version" of [api-surface/README.md](../../api-surface/README.md).

<a id="利用者向けの文書の照合"></a>
### Verifying the User-Facing Documentation

Decided on 2026-10-23 (being introduced). It follows from "Tidy the documentation" in the [next milestone](../plan/implementation-plan.md) decided with the owner.

- The set of user-facing documents (the README, the schema document for each storage backend provided, and the migration guide), and the canonical source of their file names, locations, and section structure, are placed in `user-docs/` of this repository. The verification tool is placed in `tools/user-docs/`.
- For documents, the English `X.md` is canonical and the Japanese `X.ja.md` is auxiliary. The head of a Japanese document has a fixed line stating that the English version is canonical.
- Each repository copies the canonical source and the verification tool with identical content, and has a configuration that states the starting point of its documents (for js, `packages/library`) and the storage backends it provides. In CI, it first compares the SHA-256 of the copies (`user-docs/template.json` and `tools/user-docs/check.py`) with pinned values to confirm they are identical to the canonical source, and then verifies the documents. Both steps are placed in a job included in the dependencies of `CI Success`.
- What is verified is that the documents exist, the heading structure, the correspondence of English and Japanese headings, the destinations of relative links, and the first line of the Japanese documents. The content of the prose is not verified.
- When the canonical source is changed, the coordinator redistributes it to all repositories and also updates the pinned values.

<a id="main-の-ci-の失敗の知らせ"></a>
### Notification of CI Failures on main

Placed on 2026-10-15. The owner decided the method and scope. This is because on 2026-10-14, when rs's vulnerability audit (a job outside `CI Success`) failed on main, no notification appeared anywhere and the failure remained until someone happened to notice.

- When the CI of a push to main or of a scheduled run ends with a failure, a timeout (`timed_out`), or a startup failure (`startup_failure`), an issue is created automatically in that repository. If an issue with the label `ci-failure-on-main` is open, a comment is added instead of creating a new one. When a newer CI on main succeeds, the issue is closed. The number of concurrent runs is not limited, so when two failures end at almost the same time, two issues may be created (limiting it would cause a waiting notification to be replaced by a later one and lost).
- The scope is all CI failures on main. It includes failures of jobs outside `CI Success` (rs's `audit`) and failures of `CI Success` itself.
- It only notifies; it is not a mechanism to block merging. It is not included in the dependencies of `CI Success` or in branch protection. It does not use external notifications or Secrets, only GitHub issues and their notifications.
- Each repository copies `tools/ci-failure-notice/main-ci-failure.yml` of this repository to `.github/workflows/main-ci-failure.yml`. The only thing allowed to change is the one place where the name of the CI workflow is written (`ci` for rs, `CI` for the others). When the canonical source is changed, the coordinator redistributes it to the six repositories.
- After copying, follow the procedure in [tools/ci-failure-notice/README.md](../../tools/ci-failure-notice/README.md): pass the ID of a past failed CI run to a manual run, and confirm that an issue is created. A manual run does not check whether the given ID belongs to the CI workflow, so do not pass the run ID of a workflow other than CI.

<a id="2-ブランチ保護main"></a>
## 2. Branch Protection (main)

- The only required status check is `CI Success`. If the job names of a matrix were required directly, the names would drift whenever the matrix changes.
- Enable "Require branches to be up to date before merging" (strict).
- Do not enable "Require conversation resolution". Do not use a gate by a custom workflow either. Bots (such as Codex) leave comments every time Renovate recreates a PR, and making this required would block even updates whose CI passes (we enabled it once on 2026-10-03 and confirmed this). Treat bot comments as reference information.
- For PRs by humans or workers, the coordinator handles all unresolved threads before merging. Fix those that need action, and for those that do not, reply with the reason before resolving.

<a id="3-マージ"></a>
## 3. Merging

- Allow only squash as the merge method. Disable merge commits and rebase in the repository settings.
- Delete the branch automatically after merging.

<a id="4-ai-レビュー"></a>
## 4. AI Review

- Consolidate AI review into GitHub Apps (CodeRabbit, Devin Review, Codex, and so on).
- Do not place AI reviews that run as workflows (OpenAI Reviewer, PR-Agent, and so on). Do not place API key Secrets for them either.
- Keep GitGuardian's security checks enabled in all repositories.

<a id="5-依存の更新renovate"></a>
## 5. Dependency Updates (Renovate)

- The base configuration is common to all repositories. Based on `config:recommended`, minor, patch, pin, digest, and devDependencies updates are merged automatically if the required checks pass.
- Major updates are not merged automatically.
- Renovate is not installed in this repository (the hub). It has no CI or branch protection, and the only things to update are the versions pinned under `tools/` (the conformance test tool, the interoperability tool, and the measurement records). These are pinned as records of measurements, so bumping a version would make them inconsistent with the records (the owner decided this on 2026-10-13 and closed PR #20).
- The coordinator periodically takes stock of Renovate PRs that remain open. Merge those whose CI passes. For those that do not, have a worker fix them, or record the reason for not acting in the block setting of `renovate.json` with a `description` (the same form as the block on the JUnit major update in java). Only escalate to the owner what needs a decision.

<a id="6-エージェントによる運用"></a>
## 6. Operation by Agents

- Changes to each repository are made by the session of this repository (the coordinator) instructing workers through Orca's orchestration. The owner interacts only with the coordinator.
- The coordinator (the command post) runs on Opus 5.5 and concentrates on planning, decisions, and overseeing review. Actual work is delegated to models and harnesses other than Opus (Sonnet 5.5, and models of Ollama Cloud and OpenCode Go). As exceptions, the design of takt (planning and re-planning), the adjudication and final judgment of reviews, and steps with no assignment run on Opus 5.5 (the user instructed this on 2026-10-06; chapter 8). GPT-6.1-Sol is not assigned to regular steps from 2026-10-06. On 2026-10-07 the owner instructed that it be added as a switching candidate for usage limits. The means of actual work may be either Orca's orchestration or takt (the owner instructed this on 2026-10-05).
- Workers go as far as creating a PR and do not merge. The coordinator merges, after checking the diff and the check results, in line with this policy.
- Do not use aidlc. takt may be used.
- Discard worktrees that are no longer needed. If uncommitted artifacts that are not in the repository remain, save them before discarding.

<a id="7-オーナーが管理するもの"></a>
## 7. Things the Owner Manages

- The owner manages Secrets (such as the GPG key for publishing) and the repository's visibility and permission settings. The coordinator investigates the necessary names and procedures and tells the owner.

<a id="8-takt-の配置"></a>
## 8. Layout of takt

On 2026-10-03, while the owner was away, this was decided as a recommendation in line with the direction the owner had indicated (the scripts and settings to refer to, and the division of roles), and the owner confirmed it the same day.

Repositories that use takt align to the following layout. The templates are in `tools/takt/` of this repository, and each repository copies the same content. To change it, first change the templates and then distribute them to all repositories.

| Location | Content | Source |
|:--|:--|:--|
| `.takt/workflows/`, `.takt/steps/`, `.takt/facets/` | The Japanese bundle of takt-workflows (flash-default and others) | Run the installer of [ideo-plus/takt-workflows](https://github.com/ideo-plus/takt-workflows), pinned to commit `1760ce095a0ba4aba0b357b08bdf0e65ef910b92` |
| `.takt/.takt-workflows`, `.takt/.gitignore` | The language and version of the installed bundle, and the allowlist of tracked files | Created by the installer |
| `.takt/runtime.yaml` | Assignment of profiles and steps | `tools/takt/runtime.yaml` |
| `.takt/config.yaml` | Language, parallelism, and switching at usage limits | `tools/takt/config.yaml` |
| `.takt/workflows/light-change.yaml` | A light workflow for small changes (plan → implement → 3 parallel reviewers → fix, up to 17 steps). Modeled on the built-in mini-core, with three reviewers (the user specified this on 2026-10-06). Agreed with the user on 2026-10-05 | `tools/takt/workflows/light-change.yaml` |
| `.takt/facets/instructions/spec-conformance-review.md` | The instruction for the third reviewer of light-change (discrepancy with the specification) | `tools/takt/facets/instructions/spec-conformance-review.md` |
| `.claude/settings.json` | A setting that keeps takt steps from reading the parts under `.takt/` | The installer merges it into the existing settings |
| `.takt/bin/run-takt.sh`, `.takt/bin/takt-claude.sh`, `.takt/bin/takt-codex.sh` | The entry point that starts takt (`run-takt.sh --claude-account <setting> --codex-account <setting>`) and the entry points used when takt starts claude and codex. They point `TAKT_CONFIG_DIR` to the project's `.takt/home` | `tools/takt/bin/`. Copy `scripts/` of [ideo-plus/takt-workflows](https://github.com/ideo-plus/takt-workflows) as is at commit `34d5d5be664ba0f8475817fecfca9c52db77ea86` (the merge of ideo-plus/takt-workflows#67) (the user instructed this on 2026-10-05). The location is `.takt/bin/` to match takt-workflows' installer (`use-lang.sh --launchers-only`), and `!bin/` and `!bin/**` are added to `.takt/.gitignore` (agreed with the user on 2026-10-06). It is not placed in `scripts/` |
| `mise.toml` | Pinning of the takt version (`"npm:takt" = "0.68.0"`) | Each repository |

- The division of roles was specified by the user on 2026-10-06 as follows. GPT-6.1-Sol is not assigned to regular steps and is used as a switching candidate at usage limits (the user specified this on 2026-10-07). Design (planning and re-planning), the adjudication and final judgment of reviews, and steps with no assignment use Opus 5.5. Implementation (writing tests, implementing, and fixing) uses Sonnet 5.5. For the reviewers that run in parallel, one role each is fixed to three kinds of models (it is not a ladder). Sonnet 5.5 takes discrepancy with the specification (light-change) and the structure of the design and CQRS and event sourcing (flash-default). DeepSeek V4.1 Flash takes AI-specific problems (light-change) and backend and security (flash-default). GLM 5.3 Flash takes supervision (light-change) and AI-specific problems, tests, and frontend (flash-default). DeepSeek and GLM are called through OpenCode Go. The steps of writing tests, re-implementing, and fixing start with Sonnet 5.5, and when failures continue, the last stage up the ladder is the default (t2), Opus 5.5. A redo after a fix failed verification (`fix-retry` of flash-default) is also treated as the same escalation target and runs on Opus 5.5. The ddd-family workflows of the takt-workflows bundle do not track the quality-check tools (`.takt/tools`), so they cannot be loaded in this group and are not used. The judge of the review-and-fix loop is also Opus 5.5. When a usage limit is hit, switch in the order Sonnet 5.5 → Opus 5.5 → Codex's GPT-6.1-Sol → OpenCode Go's DeepSeek V4.1 Flash → Ollama Cloud's DeepSeek V4.1 Flash → GLM 5.3 → GLM 5.3 Flash (on 2026-10-07 the user specified adding GPT-6.1-Sol and the three Ollama Cloud models as switching candidates). History so far: on 2026-10-03, design and defaults were Opus 5.5; on 2026-10-05, by agreement with the owner, this was changed to GPT-6.1-Sol; and on 2026-10-06, GPT-6.1-Sol was dropped.
- Use the same takt version in all repositories. Renovate does not update takt (block it in each repository's `renovate.json`, writing the reason in `description`). When moving to a new version, the coordinator bumps the version in the table above and `mise.toml` in all repositories at the same time. If left to Renovate's automatic updates, the update day would differ per repository and the versions would diverge (on 2026-10-03, 0.67.1 and 0.68.0 were mixed. Agreed with the owner the same day).
- Write nothing to `~/.takt/` (the global settings) and do not let it be read. The global settings are read layered over every project. `run-takt.sh` points `TAKT_CONFIG_DIR` to the project's `.takt/home`, so start takt from `run-takt.sh`. `.takt/home` is outside tracking by `.takt/.gitignore`.
- Use the entry point of takt-workflows as is and do not modify it on your own (the user instructed this on 2026-10-05). When a fix is needed, put it into takt-workflows first and then copy it. Removal of environment variables that remain in the calling shell was added to takt-workflows on 2026-10-06 (ideo-plus/takt-workflows#65). `takt-claude.sh` removes the variables for authentication, organization, provider selection, endpoint, model, and subagent model, `takt-codex.sh` removes the variables for authentication, token, endpoint, and external authentication, and `run-takt.sh` removes the API keys passed to takt, before starting.
- Do not commit execution logs or session state (`.takt/runs/` and so on). Follow the `.takt/.gitignore` that the installer creates.
- Do not commit `.takt/tools/` that the installer installs (ddd-lint for the DDD workflows. About 13MB and includes platform-specific binaries). This is because the standard workflow, flash-default, does not use it. Remove the allowance for `tools/` in `.takt/.gitignore`. When the installer is reinstalled, redo this change.

- The Ollama Cloud switching candidates are called from the local Ollama server at `http://localhost:11434/v1` through OpenCode's custom provider `ollama`. On the machine, [sign in to Cloud from the Ollama app or the command line](https://docs.ollama.com/cloud) and start the server. Following the [custom provider settings](https://opencode.ai/docs/providers/), register in OpenCode the provider name `ollama`, the package `@ai-sdk/openai-compatible`, the endpoint above, and the three models `deepseek-v4.1-flash:cloud`, `glm-5.3:cloud`, and `glm-5.3-flash:cloud`. Confirm that the three models appear in the list from `opencode models`, with names starting with `ollama/` (the form without arguments works in both older OpenCode versions and 2.1.1), and that there is Cloud usage quota.

- On a new execution machine, fetch the information of the three Ollama Cloud models with `ollama pull deepseek-v4.1-flash:cloud`, `ollama pull glm-5.3:cloud`, and `ollama pull glm-5.3-flash:cloud`, and confirm each with `ollama show <model name>`. Registering the model names in OpenCode is not a substitute for this preparation ([OpenCode provider settings](https://opencode.ai/docs/providers/)). For GPT-6.1-Sol, prepare a corresponding Codex command line and an available account and workspace setting, and confirm that a short run specifying `gpt-6.1-sol` succeeds with the same account setting as takt ([OpenAI Docs model description](https://learn.chatgpt.com/docs/models)). Concrete start-up examples are in "Starting and supervising takt" in `CLAUDE.md`. If any candidate is unavailable, do not start takt and report to the coordinator. `rate_limit_fallback` is a setting that switches when a usage limit is detected, so do not assume it makes up for insufficient preparation, such as a model not being found or authentication failing, with later candidates.

- When doing the initial environment preparation or changing OpenCode's connection settings, also confirm a response through OpenCode after fetching Ollama's model information. Run `opencode run --model ollama/deepseek-v4.1-flash:cloud 'ツールを使わず準備完了とだけ返答してください'` ("reply only with 'ready', without using tools"), change the value of `--model` to `ollama/glm-5.3:cloud` and `ollama/glm-5.3-flash:cloud`, and confirm the remaining two models too. Start takt after a short response succeeds with all three models. The model list and local model information alone cannot confirm that a response is possible through OpenCode's endpoint or the Cloud account.

- In the run on 2026-10-26, when takt used its default v1 connection method against OpenCode 2.1.1, it failed with `OpenCode CLI opencode v2.1.1 is incompatible with TAKT’s v1 transport. Set TAKT_OPENCODE_VERSION=v1 or v2 and TAKT_OPENCODE_PATH to a matching CLI.`. On a machine that uses this version of OpenCode, pass the environment variable `TAKT_OPENCODE_VERSION=v2` and `TAKT_OPENCODE_PATH`, pointing to the OpenCode executable of that version, when starting takt. Do not modify `run-takt.sh`. Decide the executable's path per machine and do not write it in the repository. A machine that uses OpenCode v1 can stay as it is.

<a id="適合状況2026-10-23"></a>
## Conformance Status (2026-10-23)

As of 2026-10-03, chapters 1–4 and 8 were conformant in all six repositories. The only required check is `CI Success`, strict is enabled (requiring conversation resolution is disabled), merging is squash only, all CI jobs have `timeout-minutes`, and there are no AI reviews run by workflows or custom thread gates. java, kotlin, js, scala, and rs conform to the "Publishing Workflow" in chapter 1, added the same day (scala via #853, js via #990 excluding the manually run CI, and rs including #239). go is out of scope because it does not publish to a package registry. For the takt version in chapter 8, all six repositories were aligned to 0.68.0 the same day, and set not to be updated by Renovate (rs #240, js #992, java #686, scala #854, kotlin #822, go #383).

On 2026-10-05, the division of roles in chapter 8 was revised (design and defaults changed from Opus 5.5 to GPT-6.1-Sol), and the templates were fixed and distributed to `.takt/` of the six repositories (rs #242, js #998, java #689, scala #857, kotlin #824, go #385). Chapter 8 is conformant again in all six repositories.

The "Version Bump Workflow" and "Verifying the Conformance Test Data" in chapter 1, added the same day, are conformed to by all six repositories. The version bump workflow was introduced in rs #244, js #1000, java #691, kotlin #827, scala #860, and go #387, and the verification of conformance test data v1.0.0 in rs #247, js #1003, java #692, kotlin #830, scala #861, and go #388.

The "Verifying the Shape of the Public API" in chapter 1, added on 2026-10-14, is conformed to by all six repositories. The verification of shape 0.1.0 was introduced in go #438, java #740, js #1058, rs #298, kotlin #857, and scala #879. The SHA-256 verification is in the lint job for go, rs, and scala, in the release-tools job for java, and in the release-checks job for js and kotlin. The verification test runs in a dedicated api-surface job for rs and in the test job for the other five repositories. js's test job does not run when the change is only to documents (`.md`, `docs/`, and so on), but it does run when the JSON under `api-surface/` is changed. Every job is included in the dependencies of `CI Success`.

On 2026-10-15, conformance test data 1.1.0 was distributed to the six repositories (rs #301, js #1060 and #1062, java #742, kotlin #859, scala #881, go #442). In all six repositories, the copy and the SHA-256 verification pass with 1.1.0. The two DY-19 cases succeeded with DynamoDB Local, and the one case requiring the memory expiry method succeeded with memory, in all six languages. The one case requiring a change feed succeeded in js as a configuration error for an unexpected setting. The other five languages have no change feed item in their public configuration, so they report it as not representable with a reason.

On 2026-10-15, conformance test data 1.2.0 was distributed to the six repositories (rs #315, js #1071, java #752, kotlin #868, scala #890, go #450). In all six repositories, the copy and the SHA-256 verification pass with 1.2.0. The two MEM-2 cases and the two MEM-6 cases succeeded with memory in all six languages and entered the required cases. The runner of each language has tests that judge as failures a backend that shares records although it was "newly" created, and a backend that returns a saved value without copying it. The existing required judgments are unchanged.

On 2026-10-19, conformance test data 1.3.0 was distributed to the six repositories (rs #317, js #1078, java #755, kotlin #870, scala #893, go #453). In all six repositories, the copy and the SHA-256 verification pass with 1.3.0. The scenario of sharing memory configuration (`memory-store-shared-configuration`, MEM-2) succeeded with memory in all six languages and entered the required cases. The SQLite, Spanner, and Bigtable scenarios and the table of Bigtable envelope values are reported by all six languages as not applicable with the reason that they do not provide those storage backends (a language that implements them in stage 5 will move them to success). The runner of each language has a test that judges as a failure a fake backend that makes a shared instance not use the backend's configuration. The existing required judgments are unchanged.

After stage 5 (2026-10-23), the SQLite and Bigtable scenarios moved to success in rs, and the Spanner scenarios in js (rs 5.1.0, js 5.1.0). The table of Bigtable envelope values also succeeds in rs. The four FNV-1a 64 cases (K-1) succeed in the legs of storage backends that use the hash (js's Spanner, rs's Bigtable), and rs's Bigtable portion was made to run in [rs #337](https://github.com/j5ik2o/event-store-adapter-rs/pull/337). The other legs, and the languages that do not provide such a storage backend (java, kotlin, scala, go, js's SQLite and Bigtable, rs's Spanner), remain not applicable with a reason.

The "Release Notes" in chapter 1, added on 2026-10-15, is conformed to by all six repositories. rs stopped its `CHANGELOG.md` at 5.0.1 (rs #305). Until then, rs, js, java, kotlin, and go created release notes with a Python script that reads only subjects, and scala with `mathieudutour/github-tag-action`, which it uses for version bumps. The Python script did not recognize a `!` right after the type and did not create a section for breaking changes (rs 5.0.0's `feat!:` #287 went into the features section). The canonical source of this repository (#38 and #39) was copied in rs #307 and #308, js #1065 and #1066, java #745 and #746, kotlin #862 and #864, scala #883 and #885, and go #444 and #445. scala still uses the current action to create the tag, and only the release notes are created by the canonical scripts. The new scripts output a section for breaking changes, scopes, and links to PRs and commits.

The "Notification of CI Failures on main" in chapter 1, added on 2026-10-15, is conformed to by all six repositories. The canonical source of this repository (#49 and #53) was copied in rs #313, js #1070, java #750, kotlin #867, scala #888, and go #449. In rs, we passed the failed audit run of 10/14 to a manual run, an issue (rs #314) was created, and we confirmed that passing a new successful run closes it. We confirmed the same in java (java #751).

| Remaining item | Target | Owner |
|:--|:--|:--|
| The crates.io API token `CARGO_TOKEN` (chapter 7) | rs and others | rs moved to OIDC, and the owner deleted the GitHub Secret `CARGO_TOKEN` (2026-10-03). The token of the same name on the crates.io side appears to be used, with a Secret of the same name, by publishing workflows of repositories outside the group such as prop-check-rs, oni-comb-rs, and fraktor-rs. Revoking it would make their publishing fail, so the owner decided the same day to keep it. Revoke it after those repositories move to OIDC. Owner |
| Taking stock of Renovate PRs (chapter 5) | All repositories | Coordinator. The first round was done on 2026-10-03 (major updates incompatible with Java 11 were blocked with reasons). In the second round the same day, the minor updates of biome and jest in js, which had been stuck at lint, were passed in #978. The sbt in js's mise.toml was removed in #984 because it was unused and `mise install` failed since conda-forge does not have 2.0.10. In the third round the same day, js's pnpm 12 was taken in with #982, and TypeScript 7 was blocked in #987 until ts-jest and ts-node support it directly. `@google-cloud/spanner` v9 was moved to peerDependencies (`^8.7.1 \|\| ^9.0.0`) by the owner's decision, because the public API receives the user's `Database` (#986) |

The blocked major updates were reviewed on 2026-10-03, after the migration to Gradle 9 (java #679, kotlin #807) and scala's JDK 25 (#848). In java #681 and kotlin #815, the blocks on Spotless 8 (for kotlin, including formatting with ktlint 1.8.0) and foojay 1.0 were lifted, and the JDK that runs Gradle was set to 25. Updates of the JDK for Gradle are allowed only for LTS. The major updates of JUnit 6 and of the JDK 11 for tests remain blocked as long as testing on Java 11 continues. scala's sbt 2 keeps being blocked, with the reason rewritten as waiting for plugin support and migration of the build definition (#850). The old-style rule that stopped scala's `sbt-ci-release` was deleted because it had no effect (#852).

The Snapshot workflows of java and kotlin, when CI succeeded on a PR's branch, also checked out that branch and published it to Sonatype (since 2023. On 2026-10-02, a Renovate branch was published and failed on checking out the branch that was gone after merging). On 2026-10-03, in java #682 and #684 and kotlin #817, #818, and #820, they were fixed to publish, by SHA, only a commit for which the CI of a push to main or of a scheduled run succeeded and which is the head of main both when the run starts and immediately before publishing, and we confirmed that publishing on main succeeds.

js's Snapshot workflow pushed a version-bumping commit to main before publishing (even if publishing failed only the version went up, every push made open PRs older than main, and provenance could not be attached). The same day, by the owner's decision, the version is decided only inside the job (`X.Y.Z-snapshot.<run_number>.<run_attempt>`) without pushing to main, and the conditions for publishing were aligned with java and kotlin (#985). We confirmed that it is published to the `snapshot` tag with provenance on main and that `latest` does not move.

js's npm publishing had been failing with `404 Not Found - PUT` when publishing with `NPM_TOKEN`, since the release of v3.1.1 on 2026-09-16. On 2026-10-03, by the owner's decision, it was switched to npm Trusted Publishing (OIDC). The workflow was prepared in #983 (`id-token: write`, the Snapshot's `--tag snapshot`, and an entry to manually re-publish an existing tag), and with the owner's approval `release.yml` and `snapshot.yml` were registered as trusted publishers with npm's CLI (`npm trust github`). v3.1.1 was re-published with OIDC, and 4.0.0, which includes the change that made spanner a peer dependency (#986), was released as a major by the owner's decision (a migration note was added in #989. `latest` is 4.0.0). Next, the owner deleted `NPM_TOKEN` and switched npm's Publishing access to a setting that does not allow tokens (`mfa=publish`). `NODE_AUTH_TOKEN` was also removed from the workflow (#991), and we confirmed that a Snapshot can be published with OIDC and provenance without a token on main (`4.0.1-snapshot.5405.1`).

For rs's publishing to crates.io, on 2026-10-03 the owner registered Trusted Publishing on crates.io, and in #239 it was moved to a form that uses the token that `rust-lang/crates-io-auth-action` obtains with OIDC. We started `lib-bump-version` manually to create v3.0.4 and confirmed that it can be published with OIDC (the crates.io version carries the issuer information of the GitHub run).

scala's publish was fixed on 2026-10-03 when the owner updated `SONATYPE_USERNAME` and `SONATYPE_PASSWORD` to Central Portal user tokens (the Snapshot of 12:27 UTC the same day succeeded in publishing 2.13 and 3). The release of tag `v1.0.338`, whose upload to Central Portal had failed with HTTP 401 before the update, was published to Maven Central by re-running the failed job. Also, the workflow that bumps the version every day was not counting commits with a scope such as `fix(ci):`, so no new version was created for about 300 commits from v1.0.337 (2025-04) to v1.0.338. It was fixed to the same condition as rs (#855), started manually the same day to create v1.0.339, and we confirmed that it is published to Maven Central.

js's Spanner emulator test (run optionally) was failing while waiting for startup because the latest emulator image has no shell. In the course of fixing it, we found a bug where the implementation did not roll back the transaction when a write was rejected, which was the cause of waiting forever on spanner v8, so we added the rollback and fixed it (#988. All cases pass on both v8 and v9).
