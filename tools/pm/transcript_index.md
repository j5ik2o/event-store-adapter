# Create a bounded manual transcript index

Use `transcript_index.py` with Python 3.9 or newer. It reads one Codex JSONL rollout and writes one JSON manifest to stdout. Save stdout to a private file. The manifest contains excerpts and paths that can be sensitive. Commit only synthetic fixtures.

Specify an inclusive range of physical JSONL event numbers, a total UTF-8 output byte budget, and a per-event UTF-8 excerpt byte budget. A newline counts toward the output budget. The CLI never labels an index as review complete. Exit 0 means that it produced a valid bounded index. Exit 2 means blocked, with no manifest on stdout.

## Run the synthetic example

From the repository root, run these commands. The example has five events and establishes no live or historical execution evidence.

```sh
python3 tools/pm/transcript_index.py index \
  --mode fixture --source tools/pm/transcript_index_example.jsonl \
  --start 1 --end 5 --byte-budget 4096 --excerpt-budget 80 \
  --reviewed 1:3 --prior-conclusion 'Synthetic old review, not execution evidence' \
  --new-action 'Inspect synthetic user prompt and tool result' > /tmp/synthetic-index.json
```

Copy `source_sha256` from that manifest. Retrieve event 4 with the same identity and explicit budgets.

```sh
python3 tools/pm/transcript_index.py event \
  --mode fixture --source tools/pm/transcript_index_example.jsonl \
  --start 4 --end 4 --source-sha256 SHA256_FROM_MANIFEST \
  --byte-budget 4096 --excerpt-budget 256 \
  --prior-conclusion 'Synthetic old review, not execution evidence' \
  --new-action 'Retrieve synthetic event 4' > /tmp/synthetic-event.json
```

The event command returns a bounded excerpt and its original event pointer. It does not dump an unlimited event. Increase both budgets explicitly when the required text remains truncated. For fields classified as opaque, inspect the original event through an authorized source reader. Do not infer that an opaque argument is plaintext or that an unavailable field was inspected.

## Select a live rollout

Pass `--mode live --state-db /absolute/current/state.sqlite --thread-id EXPLICIT_ID --workspace /absolute/worktree` instead of the fixture identity options. Resolve the current state DB in your runtime first. Do not choose a remembered thread ID or search session filenames. The CLI queries only the specified ID in `threads` through a read-only SQLite connection. It does not list other threads.

The selected rollout must start with `session_meta`. Its ID must match, and its cwd must be a repository root or worktree root with the same Git common directory as `--workspace`. A missing or ambiguous row, a wrong ID, or an unrelated cwd blocks the command. The CLI checks the selected identity again after acquisition. Explicit fixture mode has no live authenticity claim, even if a fixture resembles a real session.

Use the same mandatory range, budget, prior-conclusion, and new-action options as in the synthetic example. A range refers to a captured source, not a timestamp or a semantic checkpoint detector. Determine the checkpoint boundaries manually. `--reviewed START:END` is repeatable and marks prior coverage. The prior conclusion and new action are operator declarations. Neither proves that a command ran.

## Inspect omissions before review

Read these manifest fields before using its excerpts as evidence.

- `source_path` and `source_sha256` identify the whole original byte sequence. Each retained entry has a one-based event number, zero-based byte offset, original byte length, and SHA256 of its full JSONL line, including its newline. `reacquire` lists the event command inputs.
- `selected_events` and `selected_source_bytes` describe the requested range. `source_events` counts the whole validated source. Events outside the range have no excerpts.
- `omitted_events` and `omitted_event_bytes` count selected events removed entirely to fit the total budget. Retained entries form a prefix of the selected range. Retrieve omitted event numbers explicitly.
- `excerpt_omitted_bytes` counts known plaintext bytes excluded by either excerpt truncation or event omission. `excerpt_omitted_lines` counts entirely absent plaintext lines. A partially retained line is indicated by `line_truncated`, which also covers multiline excerpt truncation. These counters exclude opaque content.
- `source_bytes_not_reproduced` is selected raw JSONL bytes minus retained excerpt bytes. It includes JSON syntax, metadata, opaque fields, and omitted text. It is not a count of missing semantic evidence.
- `kind` is the only per-entry field outside `excerpt` that copies source content, and it is not limited by `--excerpt-budget` or counted in `excerpt_omitted_*`. Known user prompts and tool events have the derived kinds `user_prompt`, `tool_call`, and `tool_result`. Other events copy the `payload.type` string, or the top-level `type` string when the payload has no `type`, only when it is at most 64 UTF-8 bytes. A longer string becomes `type_too_long`. A missing or non-string `type` (number, boolean, null, array, or object), or a non-object payload, becomes `unknown`. A source `type` whose value is literally `unknown` or `type_too_long` is indistinguishable from these fixed values. In live mode, `provenance.session_cwd` also comes from the source. It is the resolved `session_meta` cwd, which the CLI first verifies as a root of a worktree that shares the Git common directory of `--workspace`.
- `reviewed_ranges`, `already_reviewed`, and `prior_conclusion_is_execution_evidence` distinguish declared prior coverage from the new range. Assistant conclusions are opaque. The tool does not recognize execution from prose.

Retrieve every source event required by the review and record that acquisition separately. A small manifest can still omit necessary evidence. `MANUAL_SOURCE_ACQUISITION_REQUIRED` remains set even when no entries were dropped. Hash equality proves source identity, not command success, truthful output, or historical recovery.

## Handle blocked inputs

The CLI validates every line, including lines outside the requested range. It rejects malformed JSON, duplicate keys at any depth, non-JSON `NaN` and `Infinity` tokens, non-object events, partial final lines, empty sources, reversed or out-of-source ranges, and source changes during acquisition. An overflowing number such as `1e999` is accepted. The manifest does not reproduce it, because excerpts copy only string fields and a non-string `type` becomes the fixed `kind` value `unknown`. Missing budgets or identity arguments also block use. A budget too small for the manifest fails rather than silently dropping its required fields.

A live append changes the whole-source hash. Capture a new bounded index instead of reusing an old hash. The CLI reads the source and database without modifying either. It parses one event at a time, so a giant event can require memory proportional to that event. It hashes the whole source and validates all events, even for a narrow range. It does not support compressed rollouts, decrypt runtime fields, redact secrets, scan other projects, or automatically integrate with reviewers.

The checkpoint120 report described an approximately 9MB unlimited export. This fixture and the tests reproduce that size problem synthetically. Independent review confirmed that the current parent rollout and a surviving export are accessible, and that the export matches its saved manifest hash. Exact agreement with the rollout snapshot at checkpoint120 remains unproven because its original byte count and hash were not recorded. Current indexing and synthetic examples do not establish that historical equivalence or review completeness. See the [independent evidence and remaining acceptance gap](https://github.com/j5ik2o/event-store-adapter/pull/154#issuecomment-6781885739).

## Run behavior tests

```sh
python3 -m unittest discover -s tools/pm -p test_transcript_index.py
```

The tests invoke the actual CLI. They check byte limits, Unicode, a giant event, exact original event pointers, changed source rejection, malformed inputs, opaque fields, `kind` values from non-string and overlong types, omission accounting, and read-only database identity selection.
