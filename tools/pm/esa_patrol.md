# Run the ESA patrol on Spark

The patrol automation "ESA 見回り" runs `esa_patrol.py` on Spark (pi with DeepSeek V4.1 Flash on DGX) every 30 minutes. The DGX Spark rules (2026-11-12) put the patrol and the cleanup on Spark so that they use no cloud quota. The coordinator is woken only when there is something to report.

```sh
python3 tools/pm/esa_patrol.py --run <run_id> --automation <patrol_automation_id> \
  --coordinator-terminal <coordinator_terminal_handle> --apply
```

Each run:

1. Runs the cleanup of `orca_cleanup.py` (see `orca_cleanup.md`). The coordinator's terminal is passed with `--coordinator-terminal`, because the patrol runs in its own terminal.
2. Lists the open PRs of the ESA repositories and the issues opened since the previous patrol.
3. Writes to the Run inbox only when something was removed or released, something needs a judgement, an error occurred, a PR was opened or closed, or an issue was opened. A quiet patrol sends nothing.

The previous PR set and time are kept in `~/.local/state/esa-orca-cleanup/patrol.json`. The first run only records them. When the report cannot be sent, the state is not advanced, so the next patrol reports the same changes again. The cleanup log line also carries the patrol's PRs, issues and report.

`--no-send` prints the report without sending it or advancing the state.

```sh
python3 -m unittest discover -s tools/pm -p 'test_esa_patrol.py'
```
