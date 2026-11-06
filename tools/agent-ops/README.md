# Agent operation checks

Two small checks for the coordinator's operating loop. They use only the Python
standard library and do not launch anything.

## Dispatch plan and claims

`dispatch.py plan PLAN.json` checks a dispatch plan. Every track must have its own
worktree, a write scope that does not overlap another track's, and a verification
command that no other track runs. The check rejects duplicate ids, duplicate
worktrees, overlapping scopes, and duplicate verification commands.

`dispatch.py claims CLAIMS.json --from-orca` checks the terminals a report claims
against `orca terminal list --json`. Every claim must name a handle that Orca
lists, in the named worktree, with the named title. Use `--terminals FILE`
instead of `--from-orca` to check a saved copy. If the terminal list is
truncated, the check refuses to judge instead of calling a real terminal
missing; `--from-orca` requests the full list, and `--terminals` must be a full
capture.

Plan shape:

```json
{
  "goal": "one line",
  "tracks": [
    {
      "id": "diagnose",
      "phase": "implement",
      "worktree": "agent-ops-diagnose",
      "scope": ["tools/agent-ops/diagnose.py"],
      "verification": "python3 -m unittest discover -s tools/agent-ops -p 'test_diagnose.py'"
    }
  ]
}
```

Claims shape:

```json
{
  "claims": [
    {
      "track": "diagnose",
      "terminal": "term_...",
      "worktree": "/Users/.../agent-ops-diagnose",
      "title": "agent-ops diagnose.py の判定ロジック"
    }
  ]
}
```

Run from the repository root:

```sh
python3 tools/agent-ops/dispatch.py plan <plan.json>
python3 tools/agent-ops/dispatch.py claims <claims.json> --from-orca
```

## Tool availability diagnosis

`diagnose.py TOOL` observes a tool through separate signals and prints a verdict.
It records the host, the surface (`ORCA_TERMINAL_HANDLE` when the observation runs
in an Orca terminal, otherwise `local-shell`), the PATH lookup, the resolved
entity, every running process and the executable it runs, and the version output.
Run it in the terminal that reported the error.

```sh
python3 tools/agent-ops/diagnose.py ollama --json
```

The verdict is `not-installed` only when the PATH lookup, the known paths, and the
process list agree that nothing exists. `binary-missing-process-running` means a
running process points at a deleted executable. `path-resolution-failure` means
the PATH lookup misses an executable that exists at a known path. Both are launch
problems to fix, not proof that the tool is absent. `--from-json OBS.json` replays
a saved observation without touching the OS.

## Test

```sh
python3 -m unittest discover -s tools/agent-ops -p 'test_*.py'
```

The tests replay the recorded incidents. `past-ollama-deleted-binary.json` must
not produce `not-installed`, and `past-path-only.json` must produce
`path-resolution-failure`. `past-duplicate-verification.json` must fail the plan
check, and `past-claim-with-terminal.json` must fail the claims check. The correct
fixtures pass. The same command runs in CI (`.github/workflows/agent-ops.yml`).
