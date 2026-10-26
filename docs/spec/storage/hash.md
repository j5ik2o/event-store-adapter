# Hash used for key prefixes (common to storage profiles, finalized in v5)

This document is finalized in v5 (P-49 of the [README](../README.md)). The storages of the first major version (DynamoDB and memory) do not use this hash. When Spanner, Bigtable, and other storages that use a hash are released, they will use this hash unchanged.

A storage profile that uses a hash in the key (Spanner, Bigtable, and others) uses the hash below. The purpose is to avoid new creations concentrating at the end of the key space (a hotspot) when the aid string increases monotonically, as in `type name-ULID`. DynamoDB hashes the partition key internally, so it does not use this hash ([ADR-0006](../../adr/0006-key-by-aggregate-id-instead-of-logical-shards.md)).

- **MUST K-1**: The hash is FNV-1a 64. The input is the UTF-8 byte sequence of the aid string (common contract T-1), and the output is an unsigned 64-bit integer ([ADR-0003](../../adr/0003-fix-storage-value-representations.md)).
- **MUST K-2**: Do not divide the hash value by a shard count. Since there is no setting called a shard count, there is no case of losing keys by changing that value (P-29). How to embed it in the key (as a sequence of digits or as a fixed-width hexadecimal number) is defined by each profile.

```
h = 0xcbf29ce484222325
for b in utf8(input):
    h = (h XOR b) * 0x100000001b3   (mod 2^64)
```

In a language that has only signed 64-bit integers (such as Java's `long`), the multiplication can simply be computed with overflow. When comparing the value or representing it in decimal, treat it as unsigned (`Long.toUnsignedString` and the like).

| Input | FNV-1a 64 |
|:--|:--|
| `a` | `0xaf63dc4c8601ec8c` |
| `01H42K4ABWQ5V2XQEP3A48VE0Z` | `0xadb103af5fe2a91a` |
| `01H42KBHCW1BZG504J4ZXKA2F2` | `0x0aa990285e0388ca` |
| `ユーザー` | `0x309f20171820053e` |

The values in this table were confirmed to match between Go's `hash/fnv` and a custom Python implementation. They are included in the conformance test data.
