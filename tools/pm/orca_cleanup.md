# Clean up the ESA line's Orca worktrees and worker terminals

`orca_cleanup.py` takes stock of the Orca worktrees of the ESA repositories (the umbrella repository, the six `event-store-adapter-*` repositories and the seven `cqrs-es-example*` repositories) and of the workers of the coordinator's Runs. It removes only what passes mechanical safety checks. Anything it cannot check is kept and listed with the reason. A person's "probably fine" is never a condition.

The ESA coordinator runs it each time the patrol automation ("ESA 見回り", every 30 minutes) wakes it:

```sh
python3 tools/pm/orca_cleanup.py --run <run_id> --apply
```

Without `--apply` it changes nothing and prints what it would do. Each run appends one JSON line to `~/.local/state/esa-orca-cleanup/log.jsonl` with what was removed, what was kept and why. It exits 1 when part of the inventory could not be observed. In that case the affected items are kept.

## Worktree removal: all three facts must be observed

1. The branch has a merged PR (`gh pr list --head <branch> --state merged`).
2. The worktree is clean: `git status --porcelain --untracked-files=all` prints nothing.
3. No commit is unpushed: `git rev-list HEAD --not --remotes` prints nothing, or HEAD is the head commit of a merged PR, which keeps the commits on GitHub after the remote branch is deleted.

These are always kept:

- The main worktree of each repository (the ghq checkout) and the coordinator's seat.
- A worktree that a live worker of any Run, or any terminal, is still attached to. If attachment cannot be observed, the worktree is kept too.
- A worktree whose Orca comment contains `parallel` or `並列`. Such a worktree was created in advance as an exception. Even when it passes the three checks, it is only listed, and its cleanup follows the owner and timing recorded when it was created.

Removal uses `orca worktree rm --worktree id:<id> --delete-branch`. Child worktrees should be removed when their delegation completes, so this cleanup only catches the ones that were missed.

## Worker terminal release

A worker of the given Runs is released (`orca orchestration worker-release`) only when its task is settled and either its process has exited, or `worker-show` reports it `live` and `idle` with `waitingOnHuman` `no`. A worker waiting for input is kept and reported as stalled. `waitingOnHuman: unknown` or `liveness: unverifiable` counts as not observable, so the worker is kept. The coordinator's own terminal is never touched. Terminals in ESA worktrees that do not belong to a worker of these Runs are listed but never closed, because their task cannot be identified.

## Report

The patrol reports to the contact point in one line, and only when something was removed or something needs a judgement (`summary.needs_judgement`).

```sh
python3 -m unittest discover -s tools/pm -p 'test_orca_cleanup.py'
```
