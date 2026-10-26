<a id="event-store-adapter-の指揮役の運用"></a>
# Operating the coordinator for event-store-adapter

The session in this repository acts as the coordinator for work across the event-store-adapter group (rs, js, java, kotlin, scala, go). The group-wide policy is in [docs/operations/repository-policy.md](docs/operations/repository-policy.md), the specification is in [docs/spec/](docs/spec/README.md), and the implementation plan for each language is in [docs/plan/implementation-plan.md](docs/plan/implementation-plan.md).

## Protected file: AGENTS.md

`AGENTS.md` is designated as editable by humans only. Agents must not add, change, or delete it, and must not touch it even for a link-only fix. This direct instruction takes precedence over the general permission to fix links in a document. (Recorded here because the instruction "This file can only be edited by humans. AI must not edit it." was given directly by the current user.)

<a id="指揮役と作業者"></a>
## Coordinator and workers

- The coordinator is the Opus 5.5 main session. The coordinator is responsible for clarifying requirements, planning, splitting work, obtaining the user's approval, reviewing the whole diff, confirming verification, deciding whether to accept the integrated result, and reporting to the user.
- The coordinator does not do the actual work, and delegates it to workers other than Opus. Only small tasks, where the effort of delegating exceeds the savings, may be done by the coordinator.
- Models available as workers (models running inside takt): Sonnet 5.5 (Claude Code), and models on Ollama Cloud and OpenCode Go (OpenCode). As an exception, takt's design, review arbitration, final judgment, and any step without an assignment use Opus 5.5. GPT-6.1-Sol is not assigned to regular steps and is used as a fallback candidate when a usage limit is reached (it was removed from the regular assignment on 2026-10-06, and the user instructed on 2026-10-07 that it be added as a fallback candidate).
- The actual work is done by launching takt through Orca orchestration. Do not launch the worker agents (Codex, Claude Code, OpenCode) directly from Orca (the user instructed this on 2026-10-05). The coordinator supervises takt.
- The use of models inside takt follows chapter 8 of the operations policy (the template is `tools/takt/runtime.yaml`). Design (planning and re-planning), arbitration, final judgment, and the default steps use Opus 5.5; tests, implementation, and fixes use Sonnet 5.5; and the parallel reviewers are fixed, one role each, to Sonnet 5.5, DeepSeek V4.1 Flash, and GLM 5.3 Flash.

<a id="ワークフローの選び方"></a>
### Choosing a workflow

- The standard is flash-default. It is a workflow installed by the takt-workflows bundle and is distinct from takt's built-in `default`. It covers planning, writing tests first, implementation, review from multiple perspectives, fixes, and final judgment (up to 51 steps). Use it for work that involves code and tests (such as the stage 2 rewrite).
- For small tasks such as documentation, CI configuration, dependency updates, and data distribution, use the lightweight custom workflow light-change. Its order is: plan (Opus 5.5) → implementation (Sonnet 5.5) → three parallel reviewers (DeepSeek V4.1 Flash for AI-specific problems, GLM 5.3 Flash for supervision, Sonnet 5.5 for discrepancies with the specification) → fix if there are findings (Sonnet 5.5); it finishes when all three find no problems. If review and fix repeat three times, Opus 5.5 judges whether the work is converging, and stops it if not (up to 17 steps). The templates are `tools/takt/workflows/light-change.yaml` and `tools/takt/facets/instructions/spec-conformance-review.md` (agreed with the user on 2026-10-05; the reviewers were made three on 2026-10-06).
- Because flash-default has a step that writes tests first, work that mainly changes CI configuration may end up creating tests that read and inspect the CI configuration files (in rs#292 on 2026-10-13, a 365-line test with hand-written YAML parsing was produced, and the coordinator removed it). At acceptance, check whether tests that the work order did not ask for have been added.
- Do not use the built-in workflows as they are (including `simple-mini`, which the global rules mention). Their step names do not match the assignments in `runtime.yaml`, so even the review would run on the default Opus 5.5. Larger tasks that need planning from the start are also handled with flash-default or light-change.

<a id="takt-の起動と監督"></a>
## Launching and supervising takt

Because takt is not recognized by Orca as an agent, there is no instruction injection and no worker_done report. The coordinator links the work-management task to the takt terminal and supervises with the following steps. These steps are to be confirmed and corrected in the first run.

1. Register an issue in the work-management Run with `orca orchestration task-create`. Write the body of the issue in the form of the "Work order" below.
2. Separate a worktree for each issue with `orca worktree create --repo <リポジトリ> --name <名前> --no-parent` (`<リポジトリ>` is the repository and `<名前>` is the name). Run `mise trust` in the created worktree. If the project's mise configuration is not trusted, `run-takt.sh` stops without launching takt.
3. Write the work order in a GitHub Issue of the target repository (a short title, with the work order in the body). In that worktree, have an Orca terminal launch takt, and pass the work order with `-i <Issue の番号>`. Launch in pipeline mode and run to the end without interaction. Do not add `--skip-git`.

   ```sh
   orca terminal create --worktree id:<repoId>::<path> --title "<作業名>" --command \
     '.takt/bin/run-takt.sh --claude-account <claude の設定> --codex-account <codex の設定> --pipeline --auto-pr -w <ワークフロー> -b <ブランチ> -i <Issue の番号>; echo "takt-exit: $?"' --json
   ```

   - The entry point for launching is `.takt/bin/run-takt.sh` (on 2026-10-05 the user instructed that takt-workflows' run-takt.sh be distributed to each repository; the location was agreed on 2026-10-06 to be `.takt/bin/`, to match the takt-workflows installer). The global rules (`~/.claude/CLAUDE.md`) say to launch takt directly without a wrapper in between, but in this group this script is responsible for selecting the account and setting `TAKT_CONFIG_DIR` (the project's `.takt/home`), so it is used as an exception. No other wrapper is placed in between.
   - The account configuration directories are specific to each machine, so they are not written in the repository and are recorded in the coordinator's memory.
   - The machine that runs takt needs Claude Code (Sonnet 5.5 and Opus 5.5) and OpenCode with OpenCode Go authentication completed (reviewers DeepSeek V4.1 Flash and GLM 5.3 Flash). To run GPT-6.1-Sol, the fallback candidate for usage limits, also prepare a Codex account and CLI. The upstream launch script requires both as well.
   - Before enabling the GPT-6.1-Sol candidate, confirm the Codex command line that supports `gpt-6.1-sol` and the settings of the account and workspace that can use this model. Use the same configuration directory as the one passed to `run-takt.sh --codex-account`, and confirm that a short run such as `TAKT_CODEX_ACCOUNT_DIR='<Codex の設定ディレクトリ>' .takt/bin/takt-codex.sh exec --model gpt-6.1-sol --sandbox read-only '準備完了とだけ返答してください'` succeeds before launching takt. Replace the example configuration directory with the actual path used on the machine. Follow [the model description in OpenAI Docs](https://learn.chatgpt.com/docs/models) for the terms of use. On a machine where access to the model or a compatible command line cannot be prepared, stop the launch and report to the coordinator.
   - For the Ollama Cloud candidates, sign in to Cloud from the Ollama app or the command line, and start the local Ollama server. In OpenCode, register a custom provider `ollama` whose endpoint is `http://localhost:11434/v1`, together with `deepseek-v4.1-flash:cloud`, `glm-5.3:cloud`, and `glm-5.3-flash:cloud`. Confirm that `opencode models ollama` lists these three models under names starting with `ollama/`. Configuration examples and an explanation of authentication are in [OpenCode's provider configuration](https://opencode.ai/docs/providers/) and [Ollama Cloud](https://docs.ollama.com/cloud). A Cloud usage allowance is also required.
   - The OpenCode model list alone cannot confirm that the local Ollama has the model information. Before launching, run `ollama pull deepseek-v4.1-flash:cloud`, `ollama pull glm-5.3:cloud`, and `ollama pull glm-5.3-flash:cloud` one by one, and confirm that the same three models can be retrieved with `ollama show <モデル名>`.
   - At the first environment setup, or when the OpenCode connection settings are changed, after retrieving the model information, confirm that a short response succeeds with `opencode run --model ollama/deepseek-v4.1-flash:cloud 'ツールを使わず準備完了とだけ返答してください'`. Change the `--model` value to `ollama/glm-5.3:cloud` and `ollama/glm-5.3-flash:cloud`, and confirm the remaining two models in the same way. Confirm that all three models can respond with the signed-in account through the endpoint registered in OpenCode before launching takt. If any model cannot be confirmed, stop the launch and report to the coordinator.
   - Do not pass the work order with `-t "$(cat <指示書>)"`. takt uses the string given to `-t` as is for the PR title and the commit message (`takt: <全文>`), so with a long work order the PR title is too long and the PR cannot be created (in the trial run on 2026-10-06, only the PR creation failed after the push). With `-i`, the PR title becomes `[#<番号>] <Issue のタイトル>` and the commit becomes `feat: <Issue のタイトル> (#<番号>)` (it was confirmed on 2026-10-06 in ideo-plus/takt-workflows#65 that even the PR is created automatically). When merging by squash, the coordinator re-titles it as a Conventional Commits title.
   - Do not redirect the output to a file. takt leaves its records in `.takt/runs/<run>/`. The final `echo "takt-exit: $?"` leaves takt's exit code in the terminal. The terminal is not closed, so the output can be read with `orca terminal read` even after the run ends.
   - Immediately after launch, confirm with `orca terminal read` that `run-takt: TAKT_CONFIG_DIR:` points to the worktree's `.takt/home`. Do not have it read `~/.takt/`, and do not rewrite it.
4. Link the issue to the terminal with `orca orchestration dispatch --task <課題> --to <端末>`. Do not inject (`--inject`).
5. Supervision: while the run is in progress, use `orca terminal read --terminal <端末>` and takt's run records (`.takt/runs/`) to watch the step transitions, the models used, and errors. The step transitions can be seen from `step_start`, `step_complete`, `workflow_complete`, and `workflow_abort` in the run record's `logs/*.jsonl`. The end is judged by `takt-exit:` appearing in the output of `orca terminal read`. If you find work outside the scope or a prolonged run, stop it with `orca terminal send --terminal <端末> --text $'\x03' --interrupt`, narrow the scope, and launch again. Other takt runs may be running on the same machine, so when stopping a process directly, first confirm by branch name or similar that it is your own takt.
6. Acceptance: check the diff, deliverables, and CI against the acceptance conditions in the work order. Record the result with `orca orchestration task-update --id <課題> --status completed|failed --result <要約>`. After that, close the terminal (`orca terminal close`) and the worktree (see "Cleanup" below).

<a id="takt-にできないこと"></a>
### What takt cannot do

- Claude inside takt cannot read anything under `.takt/tools`, `.takt/facets`, `.takt/workflows`, and `.takt/steps` while takt is running. This is due to the deny rules (`Read(./.takt/<ディレクトリ>/**)`, which keep the steps from reading the workflow's parts) that the takt-workflows installer puts in `.claude/settings.json`; since it cannot read them, it cannot write to them either. `.takt/runs` (the reports of each step; the fix step reads the review reports there and fixes accordingly), `runtime.yaml`, and `config.yaml` are excluded and can be read and written. Stopping even `.takt/runs` would make the workflow stop working, so do not widen the deny rules. These rules apply only to steps running inside takt, and do not restrict the coordinator or work outside takt. Creating and distributing workflows and facets is done by the coordinator as a small task.
- takt cannot ask questions midway. When it cannot decide, it must ABORT and leave the reason in the report.

<a id="指示書"></a>
## Work order

- A work order contains the target, what to change, constraints, the write scope, the acceptance conditions, and the verification procedure.
- The verification procedure must not contradict the constraints and acceptance conditions. When takt's planning step finds a contradiction, it ABORTs according to the abort conditions (in the trial run on 2026-10-06, the verification grep also matched a correct line that should have been kept, and it aborted). If there are lines to be kept, narrow the search target to a form that can be distinguished from them.
- Write scopes must not overlap between workers. If workers using the same working tree would collide, separate the worktrees with Orca.
- When delegating operations on real hardware, write the range the user approved (the configuration to start, the arguments, the measurements, and the stop) in the work order. When an operation outside the range is needed, the worker must not decide by itself, and must stop and notify the coordinator. The coordinator asks the user.
- GPT-family models (such as GPT-6.1-Sol inside takt) tend to pile on confirmations, aggregations, re-measurements, and record-making that were not requested, and make the work needlessly long. Write a time limit and abort conditions in the work order. Because takt cannot ask questions midway, write in the work order that when the limit is likely to be exceeded or an operation outside the scope is needed, it must stop and leave the reason.

<a id="監督と受け入れ"></a>
## Supervision and acceptance

- When work is delegated to takt, the requester (the coordinator) supervises it.
- Do not simply trust takt's completion or the description of the PR it created. Compare the diff, deliverables, logs, and numbers against the acceptance conditions in the work order, and confirm yourself that the result is as instructed before accepting.
- Even for interim reports, check whether they stay within the approved range and the write scope.
- If the conditions are not met, either have the same worker fix it, or do not accept it and report to the user.
- If you find work outside the scope or a prolonged run in the terminal output and takt's run records, stop it immediately and narrow the scope.

<a id="後片付け"></a>
## Cleanup

Leftover clutter makes things hard to see, so close finished things on the spot.

- Close the worktree and the terminal (session) of finished work.
- When a PR has been merged and the worker is released, confirm that there are no uncommitted changes and no unpushed commits (if merged by squash, that the PR is MERGED), and then remove it with `orca worktree rm`.
- Keep terminals used for measurements on real hardware or SSH forwarding until the stop has been confirmed.
