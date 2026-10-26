---
status: accepted
---

<a id="論理シャードをやめ集約-id-をキーにする"></a>
# Drop logical shards and key by aggregate ID

In ADR-0002, after comparing it with the option of "using aggregate_id as the partition key as it is," we adopted the same logical shards as the journal (`${型名}-${シャード番号}` (type name and shard number)) for the head's key, in order to align with the design principle shared with pekko-persistence-dynamodb. Later, we decided to prioritize a design that does not break on storage backends other than DynamoDB (Spanner, Bigtable, SQLite), and since breaking changes were allowed, we revised this decision. In DynamoDB, all three tables use the aid string as the partition key, and the journal's sort key is seq_nr (a number). Logical shards and the shard count are removed from the specification (agreed with the owner on 2026-10-03, P-29).

The technique of increasing the variety of key values to spread writes (write sharding) is meant for keys with few distinct values. Aggregate IDs differ for each aggregate, so as they are they spread best. Logical shards, conversely, reduced the variety of keys to "number of types × shard count" and gathered multiple aggregates into one key.

## Considered Options

- **Keep logical shards (the decision of ADR-0002)**: It aligns with pekko-persistence-dynamodb, and aggregates can be enumerated per type by querying `型名-0` to `型名-N` (type name). However, the partition key is not determined per aggregate, so a GSI on aid (projection ALL) is needed to read the journal per aggregate. A GSI cannot be read with strong consistency, so it misses the event confirmed just before, and a re-read rule (P-26) was required. Writing to the GSI also roughly doubles the cost. The risk also remains that changing the shard count loses the head and causes double creation. We do not adopt it.
- **Keep logical shards only for DynamoDB**: The way of thinking would split per storage backend, and the drawbacks above would remain in DynamoDB. We do not adopt it.

## Consequences

- The journal can be queried from the base table with strong consistency, so core contract R-5 (return all events that were confirmed at the time the read started) is satisfied as it is. P-26's re-read (DY-14) is no longer needed.
- The journal's GSI, and the recording and checking of the shard count and hash method, are no longer needed. Only the layout version remains in the settings.
- Because reads use an exact match on the partition key, the problem of items of other aggregates being mixed in by prefix matching (the former DY-7) does not occur.
- Enumerating aggregates per type requires a table Scan. If it becomes necessary, a GSI on type_name can be added to the head table to bring it back.
- Spanner and Bigtable use the FNV-1a 64 of the aid string, without dividing, as the key prefix, to avoid hotspots caused by monotonically increasing keys ([hash](../spec/storage/hash.md)). Since there is no shard count, there is also no losing keys by changing it.
- The key design no longer aligns with pekko-persistence-dynamodb.
