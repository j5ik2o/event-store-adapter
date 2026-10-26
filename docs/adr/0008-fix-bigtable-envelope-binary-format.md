---
status: accepted
---

<a id="bigtable-の封筒を版番号付きの固定バイナリ形式で保存する"></a>
# Store Bigtable envelopes in a fixed binary format with a version number

Bigtable's event envelope and snapshot envelope are stored in the fixed binary format of [chapter 4 of the profile](../spec/storage/bigtable.md#4-封筒と履歴の削除状態を固定する) (2026-10-04, agreed with the owner, BT-D6a). The first byte identifies the format version, and the item order, the integer widths and big-endian, and the UTF-8 strings and payload byte lengths are made the same in every language.

The domain serializer handles only the payload. The envelope's metadata is assembled by the library. Nanosecond timestamps are stored as signed 64-bit integers as they are, so they do not pass through conversion to floating point.

<a id="検討した代案"></a>
## Considered Options

- **JSON**: The metadata is easy to check by eye, but nanosecond integers would have to be stored as strings and binary payloads as Base64. The storage size also increases.
- **Protocol Buffers**: Items are easy to extend, and code for each language can be generated from a shared schema, but code generation and dependency management become necessary.

<a id="影響"></a>
## Consequences

Prepare the same encoding and decoding processing and input/output verification in each language. Changes to the format are managed by the version number. Because it gets burned into existing data, changing to another format requires read support or migration.

This agreement covers the storage format of the envelope. The size limit was agreed separately in BT-D6b as a store-level setting with a default of 1MiB and a maximum of 8MiB.
