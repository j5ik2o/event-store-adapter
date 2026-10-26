---
status: accepted
---

<a id="保存される値の表現を言語に依存しない形で固定する"></a>
# Fix the representation of stored values in a language-independent form

The details of the storage format differ from one implementation to another, so the values written for the same aggregate change depending on the language. The differences as of 2026-10-02 are as follows.

- Partition-key hash: rs uses `DefaultHasher`, js applies a hashCode-style function to `asString()`, java uses `Math.abs(hashCode)`, and go uses FNV-1a 64
- Unit of occurred_at: rs uses nanoseconds, js and java use milliseconds, and go uses the integer the user passed, as it is
- The string in the aid column: it is left to the user's `Display` / `asString()` implementation. rs's sample returns only the value, while rs's documentation gives `user-account-<値>` as an example, so even within the same repository they disagree

All of these get burned into data once written, and changing them later requires rewriting every record. So we fix the following four points.

1. **The hash used for the key prefix is FNV-1a 64** (revised on 2026-10-03). The input is the UTF-8 byte sequence of the whole aid string, and the output is an unsigned 64-bit integer. Because logical shards were dropped, it is not divided by the shard count. It is used for the prefix in profiles that use a hash in the key, and is not used in DynamoDB ([ADR-0006](0006-key-by-aggregate-id-instead-of-logical-shards.md), [hash](../spec/storage/hash.md)). js implements it with BigInt.
2. **seq_nr is an integer from 0 to 2^53−1 inclusive** (version was originally also covered, but version was abolished in ADR-0004). This is the upper limit that a js number can handle without error, and in practice no aggregate is expected to exceed this range. Each language's type (`u64`, `long`, and so on) only needs to be able to represent this range.
3. **occurred_at is stored as nanoseconds from the Unix epoch**. rs, java, and go can keep nanoseconds through a round trip. js's `Date` can only hold milliseconds, so the specification states explicitly that sub-millisecond values are lost on reading. Because nanosecond values exceed 2^53, js uses BigInt for the conversion on storing and reading.
4. **The string in the aid column is `${型名}-${値}`** (type name and value), and the library assembles it from the type name and the value. It does not depend on the user's `Display` / `asString()`. The type name must not contain `-`, and the type name is everything up to the first `-` (added on 2026-10-03. If both the type name and the value were allowed to contain `-`, different aggregate IDs would become the same string. Values such as UUIDs often contain `-`, so the restriction is placed on the type name).

## Considered Options

- **Use java-compatible hashCode for the hash**: It would be compatible with the existing data of java, kotlin, and scala. However, `Math.abs(Integer.MIN_VALUE)` stays negative, so there is a defect in which a negative shard number is returned unless the shard count is a power of 2. We do not adopt it.
- **Align occurred_at to milliseconds**: It matches the existing data of js and java, and the implementation becomes simple in every language. However, it discards the nanosecond precision that rs v3 already has, and the order of occurrence of events within the same millisecond could no longer be distinguished. We do not adopt it.
- **Make the aid column only the value**: It becomes shorter, but when values collide between aggregates of different types, they cannot be distinguished on the GSI. We do not adopt it.
- **Prefix the aid column with the length of the type name, or escape `-` in the type name** (considered on 2026-10-03): It could be made unique without restricting the type name. However, a prefix makes the aid harder to read, and escaping increases the burden of implementing the same processing correctly in every language. We do not adopt it.

## Consequences

- The partition key changes in every implementation. Existing data must be rewritten in full (see ADR-0002 for the migration method).
- In profiles that use a hash in the key, the same aid hash is used for the journal and the aggregate head. If the hash implementation is wrong, the head is lost, so the input/output table is verified in every language. Not using the input aid and the remainder follows ADR-0006, K-1, and K-2.
