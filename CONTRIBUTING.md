# Contributing to the hub

This repository is the hub of the event-store-adapter group (rs, js, java, kotlin, scala, go). It holds the shared specification, the design decisions, the glossary, the conformance test data, and the shared tools. This guide points to where each of them is and how to check your changes locally. It only states what can be confirmed from the existing files and the current scripts.

## Language of documents

For developer-facing documents, the English `X.md` is the source of truth, and the Japanese `X.ja.md` is an aid. When the two differ, the English one wins. The documents marked `English and Japanese` in the table below follow this rule.

Some documents are currently written in Japanese only: the specification in `docs/spec/`, the operations policy `docs/operations/repository-policy.md`, and the plans in `docs/plan/`. `conformance/README.md` and `conformance/COVERAGE.md` are part of the distributed conformance data (see below), and they are kept in Japanese as distributed. The workflow parts under `tools/takt/facets/` are written in Japanese because the workflows run in Japanese.

## Where to find things

| What you need | Where | Language |
|:--|:--|:--|
| Shared specification (core contract, storage profiles, hash) | [docs/spec/README.md](docs/spec/README.md) | Japanese only |
| Design decisions | [docs/adr/](docs/adr/) (see the list below) | English and Japanese |
| Glossary of shared concepts | [CONTEXT.md](CONTEXT.md) ([Japanese](CONTEXT.ja.md)) | English and Japanese |
| Conformance test data: developer guide | [docs/conformance-guide.md](docs/conformance-guide.md) ([Japanese](docs/conformance-guide.ja.md)) | English and Japanese |
| Conformance test data: distributed README and coverage table | [conformance/README.md](conformance/README.md), [conformance/COVERAGE.md](conformance/COVERAGE.md) | Japanese (fixed distributed data) |
| Public API shape and its check | [api-surface/README.md](api-surface/README.md) ([Japanese](api-surface/README.ja.md)) | English and Japanese |
| Template for user-facing documents | [user-docs/README.md](user-docs/README.md) ([Japanese](user-docs/README.ja.md)), checked by [tools/user-docs/README.md](tools/user-docs/README.md) ([Japanese](tools/user-docs/README.ja.md)) | English and Japanese |
| Operations policy (CI, branch protection, merging, review, dependency updates, agent operation) | [docs/operations/repository-policy.md](docs/operations/repository-policy.md) | Japanese only |
| Implementation plan for each language | [docs/plan/implementation-plan.md](docs/plan/implementation-plan.md) | Japanese only |
| Instructions for the coordinator agent | [CLAUDE.md](CLAUDE.md) ([Japanese](CLAUDE.ja.md)) | English and Japanese |

### Design decisions

- [ADR-0001: language-neutral specification based on the envelope model](docs/adr/0001-language-neutral-spec-based-on-envelope-model.md) ([Japanese](docs/adr/0001-language-neutral-spec-based-on-envelope-model.ja.md))
- [ADR-0002: separate the aggregate head from the snapshot](docs/adr/0002-separate-aggregate-head-from-snapshot.md) ([Japanese](docs/adr/0002-separate-aggregate-head-from-snapshot.ja.md))
- [ADR-0003: fix the representation of stored values](docs/adr/0003-fix-storage-value-representations.md) ([Japanese](docs/adr/0003-fix-storage-value-representations.ja.md))
- [ADR-0004: use seq_nr for the optimistic lock](docs/adr/0004-use-seq-nr-for-optimistic-locking.md) ([Japanese](docs/adr/0004-use-seq-nr-for-optimistic-locking.ja.md))
- [ADR-0005: define append atomicity by observable confirmation](docs/adr/0005-define-append-atomicity-by-observable-commit.md) ([Japanese](docs/adr/0005-define-append-atomicity-by-observable-commit.ja.md))
- [ADR-0006: key by aggregate ID instead of logical shards](docs/adr/0006-key-by-aggregate-id-instead-of-logical-shards.md) ([Japanese](docs/adr/0006-key-by-aggregate-id-instead-of-logical-shards.ja.md))
- [ADR-0007: store Bigtable snapshot history with the events](docs/adr/0007-store-bigtable-snapshot-history-with-events.md) ([Japanese](docs/adr/0007-store-bigtable-snapshot-history-with-events.ja.md))
- [ADR-0008: fix the Bigtable envelope binary format](docs/adr/0008-fix-bigtable-envelope-binary-format.md) ([Japanese](docs/adr/0008-fix-bigtable-envelope-binary-format.ja.md))

### Tools

- Notification of main CI failures: [tools/ci-failure-notice/README.md](tools/ci-failure-notice/README.md) ([Japanese](tools/ci-failure-notice/README.ja.md))
- Release notes scripts: [tools/release-notes/README.md](tools/release-notes/README.md) ([Japanese](tools/release-notes/README.ja.md))
- Interoperability check across the 6 languages: [tools/interop/USAGE.md](tools/interop/USAGE.md) ([Japanese](tools/interop/USAGE.ja.md))
- DynamoDB test environment comparison: [tools/spikes/dynamodb-emulators/README.md](tools/spikes/dynamodb-emulators/README.md) ([Japanese](tools/spikes/dynamodb-emulators/README.ja.md))

## Conformance data

The directory `conformance/` is distributed as is to each language's repository, pinned by the SHA-256 values in `conformance/manifest.json`. Do not edit its files by hand, and do not convert their line endings. The normative documents are those in `docs/spec/`, and the data adds no rules. `conformance/COVERAGE.md` is generated fixed data. The developer guide for the data is [docs/conformance-guide.md](docs/conformance-guide.md).

The rule definition lines in the specification are written in the Japanese classification (`必須`, `推奨`, `任意`) or in the English MUST / SHOULD / MAY. The guide explains both forms.

## Public API shape

`api-surface/surface.json` describes the shape that the core contract requires of each language's public API, and each language checks it in CI. See [api-surface/README.md](api-surface/README.md), including the procedure for raising the version.

## Local checks

Run these from the repository root. Each command is taken from the documents listed above.

```sh
# Check the conformance data against its manifest (Python 3 standard library only)
python3 tools/conformance/manifest.py verify

# Check Schemas, rule numbers, references, IDs, the coverage table, and the reference model
# (needs Python 3.11 or later and uv)
uv run --project tools/conformance --locked python tools/conformance/validate.py

# Unit tests of the conformance tools
uv run --project tools/conformance --locked python -m unittest discover -s tools/conformance -p 'test_*.py'

# Unit tests of the user-docs checker
python3 -m unittest discover -s tools/user-docs -p 'test_*.py'

# Unit tests of the release notes scripts
python3 -B -m unittest discover -s tools/release-notes -p 'test_*.py' -v
```

When you change the conformance data, regenerate and check it in the order given in [docs/conformance-guide.md](docs/conformance-guide.md). The interoperability check in `tools/interop/` and the test environment comparison in `tools/spikes/dynamodb-emulators/` need Docker and other tools, and are described in their own guides.

## Changing documents

- Do not edit `AGENTS.md`. It is designated as editable by humans only, and that applies even to link-only fixes (see [CLAUDE.md](CLAUDE.md)).
- When you change an English `X.md` that has a Japanese `X.ja.md`, change both in the same change. The first line of a Japanese version links to its English original.
- Changing the specification or the operations policy requires the repository owner's agreement, as stated in those documents.
