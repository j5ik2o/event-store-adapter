# DynamoDB storage profile (finalized in v5)

Defines how to realize the [common contract](../core-contract.md) on DynamoDB. It covers the table layout, key derivation, attributes, transactions, reads, snapshot retention, and the change feed via Streams.

> This document consists of parts derived from the agreed items (P-1 to P-40, ADR-0001 to 0006), and the decisions D-1 to D-9 that became newly necessary in this document. D-1 to D-9 were agreed on 2026-10-02 (chapter 1). The keys were changed from logical shards to the aid string by P-29 (agreed 2026-10-03). P-17 to P-22, added following the review of PR #1, were agreed on 2026-10-03 ([the README's agreement status](../README.md#agreement-status)). A place marked "not agreed" has not been agreed yet. Changing it requires the owner's agreement.

## 1. Decisions made in this document

| # | Decision | Proposal in the draft | Main alternatives | Status |
|:--|:--|:--|:--|:--|
| D-1 | Where the configuration item is placed, and its shape | The initial proposal was to place one in the journal under a reserved key. The current layout, creation procedure, and permissions follow chapter 4 | Place it in the head table, or create a dedicated table | Agreed (2026-10-02). P-29 changed it so that only the layout version is recorded. P-40 added store_id and made it placed in all three tables |
| D-2 | Attributes of the head item | aid, type_name, seq_nr, events (a list) | Do not hold type_name, do not make events a list | Agreed (2026-10-02) |
| D-3 | The mechanism for excluding history waiting for TTL | A sparse KEYS_ONLY GSI that holds only history without a mark. The old snapshot `(aid, seq_nr)` GSI is abolished. Items with no expiry do not hold the `ttl` attribute (rs v3 put 0) | Exclude with a filter condition (FilterExpression) | Agreed (2026-10-02) |
| D-4 | Record format of Streams | `NEW_IMAGE` | `NEW_AND_OLD_IMAGES` | Agreed (2026-10-02) |
| D-5 | How to tell how W-8 was deviated from | On a failed condition, have the old item returned and compare it with the head's seq_nr | Re-read after the failure and compare | Agreed (2026-10-02) |
| D-6 | Classification of transaction conflicts | Optimistic lock | Storage | Agreed (2026-10-02) |
| D-7 | Classification of exceeding the item size limit | Check before writing, and treat as a contract violation | Storage (return DynamoDB's validation error as is) | Agreed (2026-10-02) |
| D-8 | The migration procedure from rs v3 | Rewrite into new tables via Scan. The head's seq_nr is derived from the journal's maximum | ― | Agreed (2026-10-02) |
| D-9 | When to run retention processing | Only after a write that wrote history (a write accompanied by a snapshot) | After every write, as in rs v3 and js | Agreed (2026-10-02) |

## 2. Table layout

There are three tables, and they are created outside the library. Table names and index names are given in the settings.

| Table | Partition key | Sort key | GSI | Streams |
|:--|:--|:--|:--|:--|
| journal | `aid` (S) | `seq_nr` (N) | None | Disabled |
| snapshot | `aid` (S) | `skey` (N) | `(aid, active_history_seq_nr)`, projection KEYS_ONLY (D-3, agreed 2026-10-02) | Disabled |
| head | `aid` (S) | None | None | Enabled (D-4, agreed 2026-10-02) |

- **MUST DY-2**: On the snapshot table, enable DynamoDB's TTL on the attribute `ttl` (when using TTL-style retention).
- **MUST DY-3**: Streams is enabled only on the head table. Streams of the journal does not guarantee ordering per aggregate, so it is not used as a source of the change feed ([ADR-0002](../../adr/0002-separate-aggregate-head-from-snapshot.md)).

- **MUST DY-18**: The precondition of this layout is that the three tables are in the same region and writes are also made only from that region. Reads of an aggregate are made with strong consistency (DY-8, DY-9, DY-11). Only the GSI read in retention processing is eventually consistent, but P-24 puts it on the safe side. Global tables (replicas in multiple regions) are out of scope. If writes are made from multiple regions, transactions are atomic only within a region, and writes from separate regions can both satisfy the head's condition, so H-1 and W-8 of the common contract do not hold (common contract SP-1) (agreed 2026-10-03, P-31).
- **MUST DY-19**: Writes, reads, and retention processing use only `GetItem`, `BatchGetItem`, `Query`, `TransactWriteItems`, `BatchWriteItem`, and `UpdateItem` narrowed to the aid of a single aggregate, and do not use Scan. Therefore they do not get slower as the number of aggregates grows. The whole table is read only in the migration from rs v3 (chapter 11) and the resynchronization of the change feed (DY-15). In these two, it may be read with a parallel Scan (`Segment`, `TotalSegments`), and may be replaced by an export to S3. An export does not consume read capacity, but take care in how the point in time is chosen. In migration, take it at a point after writes are stopped, and in resynchronization, take it at a point after the reading of Streams has resumed (agreed 2026-10-03, P-39).

DY-1 (the projection of the journal's GSI) has been deleted. This is because the journal's GSI was dropped (P-29).

## 3. Keys (P-29, agreed 2026-10-03)

- **MUST DY-16**: In all three tables, the partition key is the aid string itself (common contract T-1). Neither logical shards nor a hash is used ([ADR-0006](../../adr/0006-key-by-aggregate-id-instead-of-logical-shards.md)).
- **MUST DY-17**: The journal's sort key is seq_nr (a number). The snapshot's sort key `skey` (a number) is 0 for the current item, and the history's seq_nr for a history item. The head has no sort key.

An example for an aggregate with type name `UserAccount` and value `01H42K4ABWQ5V2XQEP3A48VE0Z`.

| Item | Partition key | Sort key |
|:--|:--|:--|
| Journal (seq_nr = 3) | `UserAccount-01H42K4ABWQ5V2XQEP3A48VE0Z` | `seq_nr` = 3 |
| Snapshot (current) | `UserAccount-01H42K4ABWQ5V2XQEP3A48VE0Z` | `skey` = 0 |
| Snapshot (history, seq_nr = 3) | `UserAccount-01H42K4ABWQ5V2XQEP3A48VE0Z` | `skey` = 3 |
| Head | `UserAccount-01H42K4ABWQ5V2XQEP3A48VE0Z` | None |

The items of an aggregate are read by an exact match on the partition key. Since prefix matching is not used, items of another aggregate never get mixed in.

DY-4 to DY-7 (shard numbers, the partition key `${type name}-${shard number}`, immutability of the shard count, and the ban on prefix matching of the sort key) have been deleted. This is because logical shards were dropped (P-29). Rule numbers are not reused.

## 4. Configuration item and check (D-1, agreed 2026-10-02. Extended to three tables by P-40)

A configuration item that records the store's identifier and the layout version is placed, one each, in all three tables. This is to confirm at every construction that the three tables belong to the same store (P-40, agreed 2026-10-03).

| Attribute | Value |
|:--|:--|
| aid | `__config__` |
| Sort key | For journal, `seq_nr` = 0; for snapshot, `skey` = 0. The head has no sort key |
| store_id (S) | The store's identifier. A random value (such as a UUID) that the library creates at the first construction |
| layout_version (N) | The layout version defined by this document. `1` in the first version |

Since an aid string always contains `-` (common contract T-1, T-11), it does not collide with this reserved value, which does not contain `-`. A seq_nr of 0 is not used for events either (common contract W-6). The snapshot's configuration item does not hold `active_history_seq_nr`, so it does not appear in the retention processing's GSI either. The shard count and hash method are not recorded because logical shards were dropped (P-29).

- **MUST DY-8**: When constructing the store, read the configuration items of the three tables with a strongly consistent read by `BatchGetItem`. Include all three in the first request, with `ConsistentRead = true` on each table. Accumulate the response's `Responses` by table name and key, and if there are `UnprocessedKeys`, re-request only those keys with exponential backoff. Keep the strongly consistent read in the re-request as well. Until there are no more unprocessed keys, do not judge an item absent from the response as "nonexistent", and do not proceed to the next step. If the configured upper limit of retry count or wait time is reached, return a storage error, not a configuration error. The [BatchGetItem specification](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_BatchGetItem.html) provides that even a successful response may leave some keys unprocessed.
  1. If none of the three exist, create a new store_id and write the three configuration items in one `TransactWriteItems`, each with the condition `attribute_not_exists(aid)`. If it fails because the condition does not hold, another construction wrote first, so discard the accumulated responses, re-read all three items by the above procedure with strong consistency, and then proceed to step 2. This is because, with an eventually consistent read, the configuration item written first by the other side may not be visible (P-19, agreed 2026-10-03). When the cancellation reason is `TransactionConflict` (another construction is in the middle of writing the same configuration item), re-read all three items with strong consistency and proceed to step 2, the same as when the condition did not hold. If none of the three exist even after re-reading, return a storage error without repeating the creation. The caller redoes the construction (agreed 2026-10-06, P-44).
  2. If all three exist, store_id and layout_version all match, and layout_version is the same as its own version, continue the construction.
  3. Otherwise (it exists in only some of the tables, store_id differs, layout_version differs), return a configuration error and stop the construction (common contract chapter 4). This is because combining the tables of different stores would advance the head of one store while appending to the journal of another (P-40, agreed 2026-10-03).

  Creating the tables is outside the library, but this write is done by the library. The IAM permissions for this construction procedure require `dynamodb:BatchGetItem` and `dynamodb:PutItem` on the three tables. `dynamodb:GetItem` alone cannot permit BatchGetItem. TransactWriteItems is an API name, and there is no IAM action of the same name. Grant the permissions corresponding to the operations inside the transaction. This procedure uses only conditional Puts, so it uses PutItem and does not require the permission for a standalone ConditionCheck. Permissions needed for other reads, writes, retention, and subscription are granted separately. The grounds are in the [list of DynamoDB IAM actions](https://docs.aws.amazon.com/service-authorization/latest/reference/list_dynamodb.html).

## 5. Item attributes

### 5.1 Journal item

| Attribute | Type | Content |
|:--|:--|:--|
| aid | S | The aid string. Partition key |
| seq_nr | N | The event's seq_nr. Sort key |
| occurred_at | N | Nanoseconds from the Unix epoch |
| manifest | S | The event's manifest (an empty string if omitted) |
| payload | B | The serialized payload |

### 5.2 Snapshot item

There is one current snapshot, and it is overwritten with each write. Only when a retention count is set does the history also increase by one with each write.

| Attribute | Type | Current | History | Content |
|:--|:--|:--|:--|:--|
| aid | S | ○ | ○ | The aid string. Partition key |
| skey | N | ○ | ○ | Sort key. 0 for the current one, and the history's seq_nr for history |
| seq_nr | N | ○ | ○ | The seq_nr up to which the snapshot has been applied |
| manifest | S | ○ | ○ | The snapshot's manifest (an empty string if omitted) |
| payload | B | ○ | ○ | The serialized aggregate state |
| last_updated_at | N | ○ | ○ | The occurred_at of the written event converted to milliseconds (reference information) |
| active_history_seq_nr | N | × | Only while unmarked | The history's seq_nr. The sort key of the sparse GSI (D-3, agreed 2026-10-02) |
| ttl | N | × | Only when marked | The expiry (epoch seconds). An item with no expiry does not hold the attribute itself |

### 5.3 Head item (D-2, agreed 2026-10-02)

| Attribute | Type | Content |
|:--|:--|:--|
| aid | S | The aid string. Partition key |
| type_name | S | The type name. Used by subscribers to narrow down by type |
| seq_nr | N | The seq_nr of the most recently appended event |
| events | L | The list of events appended by the immediately preceding write. Each element is an M holding seq_nr (N), occurred_at (N), manifest (S), and payload (B) |

By H-3 of the common contract, events currently has one element. It is made a list to prepare for batch appends in the future. type_name can also be obtained as everything up to the first `-` of the aid string (common contract T-11), but it is made an independent attribute so that subscribers can narrow down by type without decomposing the string.

## 6. Writes

### 6.1 Transaction composition

One write is done by one `TransactWriteItems`. The moment the transaction succeeds is the commit (common contract H-1).

| Action | Target | Condition | When included |
|:--|:--|:--|:--|
| Put | Journal item | `attribute_not_exists(aid)` | Always |
| Put | Head item | `attribute_not_exists(aid)` | New creation (seq_nr = 1) |
| Update | Head item | `seq_nr = :prev` (`:prev` is event.seq_nr − 1) | Update (seq_nr > 1) |
| Put | Current snapshot item | None (serialized by the head's condition) | When writing a snapshot |
| Put | History snapshot item | None | When writing a snapshot and a retention count is set |

On update, the head's Update overwrites `seq_nr` and `events`. There are at most four actions, which fit within the `TransactWriteItems` limit (100 actions, 4MB in total).

### 6.2 Classification of failures

| Failure | Classification |
|:--|:--|
| On new creation, the head's condition fails (already exists) | Optimistic lock (common contract W-3) |
| On update, the head's condition fails | Distinguished by comparing with the head's seq_nr (common contract W-8). If event.seq_nr is less than or equal to the head's, an optimistic lock; if the head's + 2 or more, a contract violation. The method of distinguishing is (D-5, agreed 2026-10-02) |
| The journal's condition fails | Optimistic lock (common contract W-7) |
| Concurrent transactions on the same item (`TransactionConflict`) | Optimistic lock (D-6, agreed 2026-10-02) |
| Exceeding the item size limit | Contract violation. Checked before writing (D-7, agreed 2026-10-02) |
| Throttling, communication failure, others | Storage |

The cancellation reasons (`CancellationReasons`) are returned one per item of the transaction. When a reason other than `None` is attached to two or more items, look in the following order and classify by the first one that matches (agreed 2026-10-06, P-43).

1. If any item has `TransactionConflict`, an optimistic lock (D-6).
2. A failed head condition. As in the table above, for new creation an optimistic lock (W-3), and for an update, distinguished by comparing with the head's seq_nr (W-8, D-5).
3. A failed journal condition. An optimistic lock (W-7).
4. Anything else. A storage error.

`TransactionConflict` is looked at first because another transaction is in progress on the same aggregate and it is resolved by re-reading. Another write to the same aggregate always touches the head too, so in practice a failed head condition and a `TransactionConflict` on another item are almost never returned at the same time. This also matches the description in the conformance test data (the statement in `conformance/README.md` that a `TransactionConflict` on any item is D-6).

Draft of D-5: attach `ReturnValuesOnConditionCheckFailure = ALL_OLD` to the head's Put / Update. When the transaction is cancelled, the old head item appears in the cancellation reason (the `Item` of the relevant element of `CancellationReasons`) ([API Reference: Update](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_Update.html), [CancellationReason](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_CancellationReason.html)), so compare its seq_nr with event.seq_nr. No additional read is needed, and the distinction can be made with the head at the time of the failure. If the head did not exist on an update (when no old item is returned), regard the head's seq_nr as 0. Since aggregates are not deleted, an append with seq_nr of 2 or more is a gap in numbering and becomes a contract violation.

Draft of D-6: `TransactionConflict` indicates that another write to the same aggregate was proceeding at the same time. It is resolved by re-reading and retrying, so it is classified as an optimistic lock.

Draft of D-7: A DynamoDB item has a limit of 400KB, and the event's payload is also carried in the head item. A write that exceeds the limit will not succeed no matter how many times it is tried, so to distinguish it from a transient failure, estimate the item size before writing and return a contract violation.

## 7. Reads

### 7.1 Latest snapshot

- **MUST DY-9**: Read the head item and the current snapshot item with one `BatchGetItem` using a strongly consistent read. If `UnprocessedKeys` are returned, re-request until it has been read through.
- **MUST DY-10**: If there is no head, return "none" (common contract R-1). If there is a head, return the pair of the snapshot envelope (none if absent) and the head's seq_nr (common contract R-2, R-3).

Reading the two items is not atomic. If another write is committed while the two are read, the snapshot's seq_nr may be above or below the head's seq_nr. In either case consistency does not break. If the caller numbers from an older state than the actual one, it becomes an optimistic lock by W-8, and if it numbers from a newer state, it can append correctly (common contract R-8). The method of reading atomically with `TransactGetItems` is not used. It doubles the read capacity, and when it overlaps with a write it fails with `TransactionConflict`, so a retry rule would also be needed (P-25, agreed 2026-10-03).

### 7.2 Events

- **MUST DY-11**: Run a Query on the journal with `aid = :aid AND seq_nr >= :seq_nr` using a strongly consistent read (`ConsistentRead = true`), and return in ascending order of seq_nr. While `LastEvaluatedKey` is returned, keep reading the continuation, and return after reading everything. Because it is a strongly consistent read, all events that were committed at the time the read started are included (common contract R-5) (P-29, agreed 2026-10-03, changed from reading the GSI to reading the base table).

DY-14 (read the head with strong consistency and re-read until the GSI results reach that seq_nr; P-26) has been deleted. This is because the journal can now be read with strong consistency from the base table, and it became unnecessary (P-29).

## 8. Snapshot retention (D-3, agreed 2026-10-02)

Only when a retention count n is set, retention processing is run after the commit of a write that wrote history (common contract S-1 to S-4) (D-9, agreed 2026-10-02). History without a mark appears only in the sparse GSI `(aid, active_history_seq_nr)` of the snapshot table. The current item and history marked for TTL do not appear.

1. Query the GSI with `aid = :aid` in descending order of seq_nr (`ScanIndexForward = false`), and read through the keys of unmarked history (reading the continuation if there is one). The projection is KEYS_ONLY, so it can be read small.
2. Add the history written by this write to the history that was read. This is because the reflection into the GSI may be delayed and not yet visible (do not duplicate it if already visible). Keep the first n items arranged in descending order, and select the history older than that as the target to be removed (common contract S-2).
3. For the delete style, delete the selected history with `BatchWriteItem`. One request can send at most 25 items, so send in batches of 25 (P-18, agreed 2026-10-03). Resend `UnprocessedItems`.
4. For the TTL style, update the selected history one at a time with `SET #ttl = :expires REMOVE active_history_seq_nr`, with the condition `attribute_exists(active_history_seq_nr)`. `TTL` is a reserved word in DynamoDB, so write the attribute name `ttl` with the alias `#ttl` of `ExpressionAttributeNames`. `:expires` is the Unix epoch seconds at the time of marking plus the grace period given in the settings. Both are the same as rs v3 (`delete_ttl`) (P-17, agreed 2026-10-03). Since it is removed from the GSI, it is not read from the next time on and is not selected again (common contract S-3). Even if two retention processes select the same history at the same time, the later update fails because of the condition. This failure is skipped as "already marked". This prevents the expiry from being reset.

Even if retention processing fails, the write is returned as a success, and the failure is reported through a log or a callback for notification (common contract S-4).

The method of counting and then selecting the excess is not used. The GSI is eventually consistent, so history just written is not counted and history that should be removed remains. Also, when two retention processes overlap, the excess decided with an old count may be applied after another process has removed history, and may remove even history within the newest n. What this procedure removes is only history for which n newer items are visible. Therefore, even if processes overlap or reflection is delayed, the newest n are not removed. What was not visible because of delayed reflection is left in excess and is cleaned up by the next retention processing (common contract S-4) (P-24, agreed 2026-10-03).

Reason for the draft of D-9: history increases only in a write accompanied by a snapshot, so running retention processing after an events-only write does not change what is to be removed. Running it every time adds one useless Query for each events-only write.

Reason for the draft of D-3: another way to exclude marked history is a filter condition (FilterExpression). However, filtering only discards after reading, so it consumes read capacity even for marked history. Snapshot payloads are often large. A sparse GSI that holds only keys can read just the unmarked history small. Since this GSI takes charge of retention processing, the `(aid, seq_nr)` GSI that rs v3's snapshot table had becomes unnecessary.

## 9. Change feed

- **MUST DY-12**: Enable Streams on the head table, with `StreamViewType` set to `NEW_IMAGE` (D-4, agreed 2026-10-02).
- **MUST DY-13**: Each INSERT and MODIFY record is one head transition. However, a record whose aid is `__config__` is the configuration item (chapter 4), so skip it. It flows once as an INSERT at the store's first construction. Assemble the head transition (common contract chapter 6) from the aid, seq_nr, and events of `NewImage`. The library does not delete heads, so no REMOVE records occur.

DynamoDB Streams delivers changes to the same item in the order they were made, and delivers each record exactly once. The head is one item per aggregate, and updates are serialized by the check in W-8, so the head transitions of the same aggregate arrive in order of seq_nr. A Lambda event source mapping keeps per-item ordering even if the parallelism (`ParallelizationFactor`) is raised.

However, in the following cases the subscriber's obligations (common contract F-3, F-4) actually come into effect.

- The retention period of Streams is 24 hours, and if the subscriber falls behind more than that, records disappear and become missing numbers.
- When reading via Kinesis Data Streams, reordering and duplicates can occur.

- **MUST DY-15** (obligation of the subscriber): When receiving a failure indicating that reading of Streams has exceeded the retention period (`TrimmedDataAccessException`), or when the last processed position is older than the retention period (24 hours), perform the resynchronization of common contract F-5 by the following procedure. First resume reading Streams, and keep processing the records that arrive. In parallel, Scan the head table with a strongly consistent read (`ConsistentRead = true`) and read through until `LastEvaluatedKey` is no longer returned (this may be replaced by a parallel Scan, or by an export at a point after the reading of Streams has resumed; DY-19). Compare each head's seq_nr with your own position (skip the configuration item whose aid is `__config__`), and for an aggregate whose own position is smaller, fill in from the journal with the operation in 3.5 of the common contract. Items that arrived from both Streams and the Scan have duplicates discarded by F-3 of the common contract. The head table holds the latest position of all aggregates, so it can also pick up aggregates that were updated only while the subscriber was stopped. If subscribing per type, narrowing down by the head's type_name is allowed (agreed 2026-10-03, P-27).
  `ExpiredIteratorException` only indicates that the shard iterator's expiry (15 minutes) has passed, and does not mean that records have disappeared. In this case, do not perform a full resynchronization; re-acquire the iterator from after the last processed sequence number (`AFTER_SEQUENCE_NUMBER`) and continue (agreed 2026-10-03, P-38).

Reason for the draft of D-4: what is needed to assemble a head transition is only the value after the update. With `NEW_AND_OLD_IMAGES`, every record would also carry the payload of the preceding event.

## 10. Limits

| Limit | Value | Effect |
|:--|:--|:--|
| Partition key | 2048 bytes | The aid string is at most 1024 bytes, so it fits (common contract T-12) |
| Item size | 400KB | The event's payload is carried in both the journal item and the head item. The snapshot's payload is carried in the snapshot item |
| Transaction | 100 actions, 4MB in total | One write is at most 4 actions |
| One response of Query | 1MB | Read through the continuation (DY-11, chapter 8) |
| Streams retention | 24 hours | Chapter 9 |

## 11. Migration from rs v3 (D-8, agreed 2026-10-02)

A full rewrite is required from the layout of rs v3. This is because the keys change from logical shards to the aid string (P-29), and a head table is added.

The target of this procedure is limited to rs v3's default key layout (when `KeyResolver` has not been replaced; pkey is `${type name}-${shard number}` and skey is `${type name}-${value}-${seq_nr}`). Cases using a custom `KeyResolver` are out of scope. If an item whose old pkey and old skey are not in this form is found in step 3, stop the migration (P-22, agreed 2026-10-03).

1. Create the three new tables and write the configuration items.
2. Stop writes to the old tables. This is because writes continuing during the rewrite would be missed.
3. Scan the old journal table and write each item to the new journal with the new key. The attributes are in the same form as v3, so only the key and the aid format (common contract T-1) change. The type name and the value are extracted by removing the trailing shard number from the old pkey and the trailing seq_nr from the old skey. rs v3 allowed `-` in type names, so an old type name containing `-` is replaced with a new type name by a mapping table that the user gives as input to the migration (common contract T-11). If an old type name containing `-` that is not in the mapping table is found, stop the migration (P-23, agreed 2026-10-03). Do the Scan with a strongly consistent read (`ConsistentRead = true`) after writes are stopped, and continue until `LastEvaluatedKey` is no longer returned (this may be replaced by a parallel Scan, or by an export at a point after writes are stopped; DY-19). This is because, with an eventually consistent read or a read of only one page, the old table would be discarded with events missed (P-20, agreed 2026-10-03). While scanning, tally the maximum seq_nr and the count for each aggregate.
4. For each aggregate, check that the seq_nr values line up from 1 to the maximum without gaps (that the count equals the maximum). If there is an aggregate with gaps, output the list and stop the migration. rs v3 did not verify continuity, so missing numbers are possible, but the new layout presupposes that there are no missing numbers (common contract W-8). Aggregates with missing numbers are fixed by the user before migrating again (agreed 2026-10-03, P-36).
5. For each aggregate, create the head item with the maximum seq_nr tallied in step 3. Do not re-read the newly written new journal to find the maximum. For events, read the event of that seq_nr from the new journal with a strongly consistent `GetItem` and put it in (agreed 2026-10-03, P-37). The seq_nr of rs v3's current item is the position of the snapshot, so it is not used for the head's seq_nr.
6. Scan the old snapshot table and write the current items and history with the new keys. The way of scanning is the same as in step 3 (P-20, agreed 2026-10-03). Discard the version attribute. Items whose `ttl` is 0 are given no attribute, and unmarked history is given `active_history_seq_nr`. rs v3's items have no manifest, so put an empty string (the value for omission in T-10 of the common contract) (P-21, agreed 2026-10-03).
7. Resume writes with a version of the library that uses the new tables.

Before writing to the new journal in step 3, you may read the old journal to the end and finish the check in step 4. In that case, read the old journal once more when writing. Since writes are stopped in step 2, the same content is read both times. When missing numbers or the like are found, it can be stopped before any data item is written to the new tables (agreed 2026-10-06, P-45).

The method of recomputing the old pkey is not used. This is because there is no guarantee that the toolchain's `DefaultHasher` at that time returns the same value as at write time ([ADR-0002](../../adr/0002-separate-aggregate-head-from-snapshot.md)).

Migration from the layouts of the old contracts of js, java, and go is outside the scope of this document.
