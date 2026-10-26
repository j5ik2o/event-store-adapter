---
status: accepted
---

<a id="仕様は言語中立に本リポジトリで管理し意味論は-rs-v3-の封筒モデルを基準にする"></a>
# Keep the specification language-neutral in this repository, with the semantics based on rs v3's envelope model

As of 2026-10-02, the implementations are split into two lines. event-store-adapter-rs v3.0.2 abandoned the Event / Aggregate traits and moved to the event envelope and the snapshot envelope. js (3.1.2-snapshot.0), java, kotlin, scala, and go remain on the older contract, in which the event itself carries the metadata and `isCreated`. The storage formats also differ from one implementation to another, for example with four different partition-key hashes, so sharing a table does not give interoperability.

Therefore, the specification is placed in this repository's `docs/spec/` as language-neutral documents, and each implementation conforms to it. We adopt rs v3's envelope model as the basis for the semantics. We judged it better than the older contract on five points: it does not require the library's trait on domain types; it makes `expected_version` explicit; reading the latest snapshot returns seq_nr and version; it decides new creation by `seq_nr == 1 ⇔ expected_version == 0`; and it makes violations of the calling convention an independent error category. Of these, version and `expected_version` were later replaced by checking against seq_nr in ADR-0004.

However, what we take as the basis is rs v3's **model**, not rs's code. rs v3 has defects that must not enter the specification (it uses `DefaultHasher` for hashing, the retention policy deletes newer history, and journal reads do not advance through pages). These are corrected with the good parts of the other implementations, and rs itself is also changed to match the specification.

## Considered Options

- **Use the older contract as the basis**: 5 of the 6 implementations already follow it, so the migration is small. However, it would fix structural problems such as forcing `isCreated` and holding metadata twice into every language, so we do not adopt it.
- **Use rs's code as it is as the reference implementation**: It saves the effort of writing documents, but rs-specific defects and Rust-specific idioms (`usize`, `&mut self`, `with_*` builders) would become the standard, so we do not adopt it.

## Consequences

- The specification consists of three layers: the core contract, independent of the storage backend; a storage profile for each storage backend; and language-independent conformance test data. How errors are returned (Result or exceptions) and how types are expressed are left to each language, and the specification decides only the categories and the ranges of values.
- Every implementation that follows the older contract (js, java, kotlin, scala, go, and php, swift, and dotnet, which are listed in the README) will have a breaking change.
- rs also cannot avoid a breaking change (ADR-0002, ADR-0003).
