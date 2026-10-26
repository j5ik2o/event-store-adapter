# Spanner storage profile (finalized)

Realizes the [common contract](../core-contract.md) with transactions within the same Spanner database. It separates the journal, head, current snapshot, and history, and decouples the commit of an append from failures of snapshot retention.

> Created on 2026-10-04. It presupposes the agreements of P-1 to P-40 and ADR-0001 to 0006. The main decisions in chapter 1 (SPN-D1a, SPN-D1b, SPN-D2 to D7) were agreed on the same day, and the draft rules were finalized on 2026-10-16 (P-57). The first version does not provide a change feed (SPN-D8, P-58). SPN-15 is finalized when a change feed is provided. Verification in each language's implementation remains (the re-release of js is [js#1067](https://github.com/j5ik2o/event-store-adapter-js/issues/1067)). Implementers check the layout and the commit procedure in chapters 1 to 5, and refer to the relevant chapters for retention, subscription, and migration. Terminology follows [CONTEXT.md](../../../CONTEXT.md).

## 1. Agreed layout and capabilities

| Decision | Adopted proposal | Main alternatives | Status |
|:--|:--|:--|:--|
| SPN-D1a | The first version targets only the GoogleSQL dialect | Target only the PostgreSQL dialect, or target both | Agreed (2026-10-04) |
| SPN-D1b | Derive the five tables from the same database and the same name prefix | Configure individual table names | Agreed (2026-10-04) |
| SPN-D2 | Appends and retention processing use SERIALIZABLE read-write transactions, and restoration uses strongly consistent read-only transactions | Keep reads strongly consistent, and design the necessary checks and conflict detection for REPEATABLE_READ writes | Agreed (2026-10-04) |
| SPN-D3 | Provide both a style that deletes old snapshot history immediately and a style that marks it and then removes it with Spanner TTL, selected per store | Provide only immediate deletion | Agreed (2026-10-04) |
| SPN-D4 | Optionally provide a head-only Change Stream. The capture type is NEW_ROW | Do not provide a change feed | Agreed (2026-10-04). Kept as the decision for when it is provided (SPN-D8) |
| SPN-D5 | Creation of tables, the configuration item, and the Change Stream to be used is done by an external initialization procedure. At store construction, check, and make missing or mismatched items a configuration error | Execute DDL at store construction | Agreed (2026-10-04) |
| SPN-D6 | Align the retention count of snapshot history per store, and have all clients check it against the configuration item. Setting changes are made with appends and maintenance processing stopped | Design a method that manages the retention count per aggregate | Agreed (2026-10-04) |
| SPN-D7 | Make an API that specifies the TTL grace period as a positive integer number of days, and check the configuration item against the DDL value | Specify with a Duration type, and make values that do not fit in days a configuration error | Agreed (2026-10-04) |
| SPN-D8 | The first version does not provide a change feed. A setting that requests it is a configuration error. Keep change_feed_enabled in config and fix it to false | Provide it from the first version as in SPN-D4 | Agreed (2026-10-16) |

SPN-D1 was split into SPN-D1a and SPN-D1b in order to confirm the supported SQL dialect and the way of specifying table names independently.

SPN-D6 and D7 give numbers to the handling of the retention count and the TTL grace period API that had been left in chapter 10 of the draft.

SPN-D8 was added following the owner's decision on 2026-10-15 not to include the change feed in the version being re-released. It takes the same form as the SQLite (SQ-D8) and Bigtable (BT-D8) profiles. The `change_feed_enabled` column of config is kept and fixed to false in the first version. This is so that `layout_version` need not be raised when a change feed is added later. SPN-D4, SPN-14, and SPN-15 are kept as decisions and rules for when a change feed is provided. The Spanner emulator supports reading Change Streams, so it can be tested locally when it is provided.

By the agreement of SPN-D1a, the first version targets only databases of the GoogleSQL dialect. [Spanner offers both GoogleSQL and PostgreSQL](https://docs.cloud.google.com/spanner/docs/choose-googlesql-or-postgres), but translating to the PostgreSQL dialect's types, DDL, and error codes is not included in the scope of this version. If support is added, it will be agreed separately, with the layout and conformance verification prepared. The dialect is aligned per database ([database specification](https://docs.cloud.google.com/spanner/docs/databases)).

## 2. Presuppose a configuration that keeps strong consistency

- **MUST SPN-1**: Place all tables in the same database. Explicitly specify SERIALIZABLE for writes. For reads, use the strong timestamp bound, and do not specify an old point in time. No additional restriction is placed on Spanner's region configuration. Use a configuration in which transactions and strongly consistent reads of the same database hold (common contract SP-1). The grounds are [Transactions](https://cloud.google.com/spanner/docs/transactions) and [External consistency](https://cloud.google.com/spanner/docs/true-time-external-consistency) (agreed 2026-10-16, P-57).
- **MUST SPN-2**: At store construction, check the layout version, configuration item, required columns and primary keys, and the retention style. If a change feed is used, also check the Change Stream's targets, capture type, and retention period. A shortage or mismatch is a configuration error. Do not execute DDL at construction, or fill in missing settings automatically (agreed 2026-10-04, SPN-D5). The storage format and fields to be checked are as in the paragraph below (agreed 2026-10-16, P-57).

DDL changes during reads or operation, and data changes that do not go through the adapter, are out of scope.

The configuration item's `store_id` is a lowercase UUID string, and `layout_version` is the INT64 value 1. `keep_snapshot_count INT64` is NULL for none, and a positive integer when set. `retention_mode STRING(8)` is `delete` or `ttl`, and `ttl_grace_days INT64` is a positive number of days only when TTL is used, and NULL otherwise. `change_feed_enabled BOOL` records the presence of the capability, and is fixed to false in the first version (SPN-D8, SPN-17). It is also checked that the setting values fit in the integer range of the column.

By the agreement of SPN-D1b, all table names are derived together from the same database and a common prefix, and individual table names are not accepted. This makes it impossible to create a setting that combines only the head of a different store. The prefix and each table name after generation are checked as SQL identifiers, and value conditions are passed as parameters.

Table names are `<prefix>_<logical name>`. If the prefix is `esa`, `esa_journal`, `esa_head`, `esa_snapshot_current`, `esa_snapshot_history`, and `esa_config` of the same database are used. The alternative of specifying individual names would be easier to fit into existing naming conventions, but it was not adopted because a method to confirm that the five tables belong to the same store would be needed.

By the agreement of SPN-D5, initialization is done by an external procedure when there are no writers. Writers are started after the five tables and the configuration item, the Change Stream if used, and the row deletion policy for the TTL style are in place. The initialization procedure confirms the completion of DDL and that each table is empty, and then writes one configuration item. The ordinary store construction only checks, and does not fill in missing tables or configuration items automatically.

By the agreement of SPN-D6, the retention count of snapshot history is aligned per store. One entry is recorded in config, and all clients check it against their own settings. A mismatch is a configuration error. If none, no new history is left in snapshot_history, and when set it is an integer of 1 or more (S-1). A change of the retention count is made externally after organizing the existing history by the setting change procedure in chapter 6, and checked at reconstruction. Writers with different retention counts are not run at the same time. The alternative of specifying it per aggregate was not adopted in this version because it requires adding a place to store the setting and a checking procedure.

### Consistency agreed in SPN-D2

By the agreement of SPN-D2, SERIALIZABLE is explicitly specified for appends and retention processing, and a strong read-only transaction is used for restoration. After the append is committed, retention processing is done in a separate transaction. A failure of retention processing does not affect the committed append. In [Spanner's isolation levels](https://docs.cloud.google.com/spanner/docs/isolation-levels), SERIALIZABLE guarantees the same result as serial execution. Upon contention, an abort and re-execution may be needed.

The considered REPEATABLE_READ detects write conflicts on the same data, but for writes that depend on the condition that was read, consistency can break. To keep the relationship between the condition read and the write by the isolation level, this version adopted SERIALIZABLE. If REPEATABLE_READ is added in the future, it will be agreed separately, and the verification needed for the head check and the selection of retention targets will be designed. Performance improvement is decided by measuring on the target workload.

For reads, the head and the latest snapshot, or the head and the event sequence, are each obtained in the same strong read-only transaction. This returns a pair at the same point in time and includes events committed before the read started (R-5, R-8, [read-only transactions](https://docs.cloud.google.com/spanner/docs/transactions#read-only_transactions)). Reads that specify an old point in time alone cannot satisfy R-5, so they are not a standalone alternative.

## 3. Align keys and integers across languages

`H(aid)` is the output of [FNV-1a 64](hash.md) as an 8-byte big-endian value. No reinterpretation as a signed integer and no remainder by a shard count is used.

| Logical table name | Primary key | Other columns |
|:--|:--|:--|
| journal | `(hash_prefix BYTES(8), aid STRING(1024), seq_nr INT64)` | `occurred_at_ns INT64`, `manifest STRING(MAX)`, `payload BYTES(MAX)` |
| head | `(hash_prefix BYTES(8), aid STRING(1024))` | `type_name STRING(1024)`, `seq_nr INT64`, `event_occurred_at_ns INT64`, `event_manifest STRING(MAX)`, `event_payload BYTES(MAX)` |
| snapshot_current | `(hash_prefix BYTES(8), aid STRING(1024))` | `seq_nr INT64`, `manifest STRING(MAX)`, `payload BYTES(MAX)` |
| snapshot_history | `(hash_prefix BYTES(8), aid STRING(1024), seq_nr INT64)` | `manifest STRING(MAX)`, `payload BYTES(MAX)`, `expired_at TIMESTAMP` (nullable) |
| config | `singleton INT64` (the value is 1) | `store_id STRING(36)` and the settings for layout, retention, and feed |

- **MUST SPN-3**: The `seq_nr` of events and snapshots is 1 to 2^53−1. `occurred_at_ns` stores signed 64-bit nanoseconds from the Unix epoch. It is not replaced with a TIMESTAMP column. The TTL mark is a separate operational time, and is not used for the event's occurrence time (T-3, T-13) (agreed 2026-10-16, P-57).
- **MUST SPN-4**: The library checks that aid is at most 1024 bytes in UTF-8. It does not leave this to the STRING length specification alone. Keys are compared by exact match on a typed tuple, and prefix match on aid is not used (SP-2). Even if hashes collide, different aids give different primary keys (agreed 2026-10-16, P-57).
- **MUST SPN-5**: SDK INT64 values are converted losslessly, especially in JavaScript, from decimal strings or BigInt. Do not convert `occurred_at_ns` via number. Payload serialization is applied only to the payload, and manifest and time are handled as columns (T-7) (agreed 2026-10-16, P-57).

Column and commit size limits follow [Spanner's quotas](https://cloud.google.com/spanner/quotas). Range and serialization checks are done before writing. Rejection due to capacity limits, communication failures, and commit failures are storage errors, and the SDK's raw errors are not included in the optimistic lock message.

## 4. Put the head check and all writes in the same transaction

- **MUST SPN-6**: After finishing event checks and serialization, run the following SERIALIZABLE read-write transaction. The commit point is the success of the commit (H-1; the isolation level was agreed in SPN-D2) (agreed 2026-10-16, P-57).

1. Read the head of `(H(aid), aid)`.
2. If seq_nr is 1, continue only if there is no head. If it exists, it is an optimistic lock. If it is 2 or more, apply W-8, regarding it as 0 when there is no head. A gap is a contract violation, and a position at or below the existing one is an optimistic lock.
3. INSERT the event into journal. Do not overwrite an existing row.
4. Create or update the head, and write the seq_nr and all metadata and payload of that event. The target of the check is the head's seq_nr (H-2, H-4).
5. If accompanied by a snapshot, create or update snapshot_current. If a retention count is set, INSERT the same envelope into snapshot_history and set `expired_at = NULL`. snapshot.seq_nr matches event.seq_nr (W-9).
6. Commit. The processing that ages, deletes, or marks history is not put in this transaction.

A new creation with events only is also possible. If there is no snapshot, no row is created in snapshot_current (W-3, R-3).

- **MUST SPN-7**: Even when the SDK receives ABORTED and re-executes the transaction, the head is checked with the same event envelope and the same seq_nr. Within the callback, no external notification and no new numbering is done. If an append with the same aid and a seq_nr at least the input's has been committed first, it becomes an optimistic lock on re-execution. An ABORTED that exceeds the re-execution limit is a storage error. Whether to have a default for the limit, and what it is, is left to each language's implementation (agreed 2026-10-16, P-57).
- **MUST SPN-8**: If the commit response is lost, treat it as a storage error of unknown outcome. Do not assert that it was not committed and perform a compensating write. If the same seq_nr is resent in another call, and it has already been committed, it becomes an optimistic lock by W-7 (agreed 2026-10-16, P-57).

A primary key duplicate is mapped to an optimistic lock only when it can be confirmed to be a duplicate of journal's `(aid, seq_nr)` or of a new head. Other constraint, schema, and SDK failures are not collectively made optimistic locks.

## 5. Restore at the same strongly consistent read point

- **MUST SPN-9**: In the retrieval of the latest snapshot, read head and snapshot_current in one strong read-only transaction. Do not combine two independent strong reads. This makes the pair of R-2 read atomically, and snapshot.seq_nr is at most head.seq_nr (R-8). If there is no head, return "none", and if there is only a head, return "no snapshot" and the head position (agreed 2026-10-16, P-57).
- **MUST SPN-10**: Event retrieval is also done in a strong read-only transaction. First fix the head's h, read journal for `max(1, seqNr) <= seq_nr <= h` by a primary key range, and return in ascending order. If seqNr is 0, start from 1, and if it is greater than h, it is an empty sequence (agreed 2026-10-16, P-57).

Do not return a success on result splitting, premature stream termination, or the SDK's page limit. Read to the end, and for an existing aggregate confirm that the seq_nr values in the target range are not missing. Resumption of a read is done in the same read-only transaction, and if it is lost, discard the accumulated results and redo the whole operation. A gap in the range is a storage error (R-5, R-6).

## 6. Organize history after the commit

By the agreement of SPN-D3, both styles are provided: immediate deletion of old snapshot history, and TTL. The style to use is aligned per store. TTL marking is done only once, and marked history is not counted in the retention count and not selected again as a marking target (S-3). This treatment is maintained while waiting for physical deletion. The TTL grace period uses the days API agreed in SPN-D7.

- **MUST SPN-11**: After an append accompanied by a snapshot is committed, in a separate SERIALIZABLE read-write transaction, read that aid's unmarked history in descending order of seq_nr. Keep the newest n, and process only the older rows. Confirm the existence of the newest n and the selection of candidates in the same transaction. On re-execution, reselect (the isolation level and the separation from the append were agreed in SPN-D2) (agreed 2026-10-16, P-57).
- **MUST SPN-12**: In immediate deletion, DELETE only the target snapshot_history rows. Do not delete snapshot_current, head, or journal. In the TTL style, set `CURRENT_TIMESTAMP()` only once on candidates with `expired_at IS NULL`. Marked rows are not counted in the retention count and are not selected again (S-3) (agreed 2026-10-16, P-57).

TTL is set only on snapshot_history. By the agreement of SPN-D7, a store that uses TTL receives the grace period as a positive integer number of days. [GoogleSQL's row deletion policy](https://docs.cloud.google.com/spanner/docs/reference/standard-sql/data-definition-language#create_table) specifies the period with `INTERVAL num_days DAY`. As an example, for a grace period of 7 days, the following row deletion policy is used.

```sql
ROW DELETION POLICY (OLDER_THAN(expired_at, INTERVAL 7 DAY))
```

This 7 days is an example, not a default. The considered Duration-type alternative would also require a check that the value is at least 1 day and a whole multiple of one day, so this version made it an API that specifies days directly.

- **MUST SPN-16**: The TTL grace period is a store-wide positive integer number of days, and the client's specified value, the configuration item, and the days of snapshot_history's row deletion policy are checked against each other. Zero or less, fractions, values that do not fit in the integer range of the setting column, and mismatches are configuration errors. The grace period is not rounded up or down (agreed 2026-10-04, SPN-D7).

`expired_at` is the time at which the mark was applied. Unmarked NULL rows are not targets of TTL. Actual deletion is delayed even after the expiry has passed, so marked rows are not included in the application's retention count. An operation that extends the grace period later and postpones the expiry of existing marks is out of scope. [Spanner TTL](https://cloud.google.com/spanner/docs/ttl) provides per-table policies and asynchronous deletion.

- **MUST SPN-13**: Even if the organizing transaction fails, the already committed append is returned as a success. Record it in a separate notification path, and re-execute at the next snapshot write or in explicit maintenance processing (S-4). Large organization work is done by splitting the candidates, and in each split it is confirmed that the newest n are not removed (agreed 2026-10-16, P-57).

### A change to the retention count setting is reflected after organizing the existing history

This is done by an external management procedure. Unlike ordinary per-aid operations, it enumerates all aggregates in snapshot_history.

1. Stop all clients that use the store, and confirm that the appends, reads, retention, and subscriptions in progress have ended. Save the setting before the change, the target setting, and the progress of the processing in a management record that can be used for resuming.
2. For each aid, in a SERIALIZABLE read-write transaction, read the unmarked history in descending order of seq_nr. If the target is n, keep the newest n, and if it is none, target all unmarked history. For immediate deletion, DELETE by SPN-12, and for the TTL style, set `CURRENT_TIMESTAMP()` only on candidates with `expired_at IS NULL`. Rows already marked and their times are not changed. Split large organization work, and reselect in each transaction. Do not change journal, head, or snapshot_current.
3. After the organization of all aggregates is complete, update config's retention count. In the TTL style, the completion of the necessary marking is the condition, and physical deletion is not waited for. Reconstruct all clients to check the settings, and resume processing.

If it fails midway, keep it stopped and re-run to the same target in the management record. Deleted rows and already marked rows are not reprocessed, and the expiry is not postponed. A rollback of the whole store is not presupposed. When the count is increased, or when a count is set from none, past history that was deleted, marked, or not retained is not revived or fabricated. The new setting is applied from subsequent snapshot writes. This is a management procedure during a stop, and the guarantee of S-4 that does not change the success of a committed append does not change.

## 7. Build transitions from the head's Change Stream

The only rule that applies to the first version is the following SPN-17 (SPN-D8).

- **MUST SPN-17**: The first version does not provide a change feed (SPN-D8). The operation of constructing a store with a setting that requests the feed, and the operation of constructing a store whose config's change_feed_enabled is true, are configuration errors. The initialization procedure of the first version records change_feed_enabled as false (agreed 2026-10-16, P-58).

The following are decisions and rules limited to versions that provide a change feed. By the agreement of SPN-D4, the change feed is provided as an optional capability. In a store that uses it, a head-only Change Stream is enabled, and committed head transitions are restored from NEW_ROW. A store that does not use it is not required to create a Change Stream. The subscriber saves its position, removes duplicates, and fills in missing numbers from the journal. If it stops beyond the retention period, it resynchronizes by comparing against the current positions of all aggregates (F-3 to F-5).

- **MUST SPN-14** (if used): Track the head's key and all non-key columns, and use `value_capture_type = 'NEW_ROW'`. Do not exclude INSERT and UPDATE. Do not use the setting that excludes the adapter's transactions from delivery either. Start the writers after confirming the completion of DDL (agreed 2026-10-04, SPN-D4).

```sql
CREATE CHANGE STREAM esa_head_changes
FOR esa_head
OPTIONS (value_capture_type = 'NEW_ROW', retention_period = '7d');
```

NEW_ROW returns the tracked row including the columns that were not updated. The default OLD_AND_NEW_VALUES has only the changed columns, so it is not used for envelope restoration when the same payload or manifest continues. The grounds are in the [capture types](https://cloud.google.com/spanner/docs/change-streams/use-dataflow).

Build the aid, seq_nr, and event envelope from each mod. Do not substitute by re-reading the current head after the record. This is because a subsequent write would overwrite it and intermediate transitions would be lost.

- **Draft, MUST SPN-15**: Process all split results, multiple mods, and child partitions. The generation order is the head's seq_nr order, but do not depend on the receiving order from multiple partitions. The subscriber discards duplicates and fills in missing numbers from the journal according to F-3 and F-4.

SPN-15 is finalized when a change feed is provided (SPN-D8).

The retention period is obtained from the configuration and saved together with the subscription position. In the [management specification](https://cloud.google.com/spanner/docs/change-streams/manage) checked on 2026-10-04, the default is 7 days and the maximum is 30 days. Do not determine expiry by assuming it is fixed at 7 days.

### A subscription beyond the retention period is resynchronized by comparison with the current positions

1. From an ordinary strong read of config, obtain the read time T returned by the service. Do not substitute the special read time returned by a Change Stream query. Start a new subscription from T, so that the subsequent records of all partitions can be retained. Do not decide T by the client's clock alone.
2. Read all heads in a strong read-only transaction, and note the position h for each aid. Ordinary aggregate operations read only a primary key range. This full read is for resynchronization.
3. Fill in from the subscriber's position to each h with the journal, and perform the duplicate removal of F-3. Events after the target of supplementation are not mixed into the supplementation at this stage.
4. Process the transitions received after T. Discard duplicates with the supplementation, and continue the partition splits and successor subscriptions.

For an aggregate created after T, the creation transition flows into the new subscription. Therefore, creations in parallel with the full read are not missed either. Do not start the full read before the subscription is prepared (F-5).

## 8. Rewrite into the new layout from the current implementation

The investigated target is [js's Spanner implementation (a443ef9)](https://github.com/j5ik2o/event-store-adapter-js/blob/a443ef990e75bbbf2809c8dce49f0d42f5fa5b0d/packages/library/src/internal/spanner-event-store.ts). The current one uses the journal and snapshot layout, a check by the snapshot's version, and a TIMESTAMP occurred_at. It is not compatible with this profile's dedicated head and nanosecond INT64.

Migration is done by stopping the writers and moving to tables with a new prefix. The restoration of the type name and value from old keys, the event's manifest, and the conversion of the occurrence time are decided by checking the old implementation's contract. Lost nanosecond precision is not treated as having been supplemented. Custom key resolution, and data that lacks information required for events, are not guessed and moved automatically.

After confirming that the seq_nr of each aggregate runs from 1 to the maximum without gaps or duplicates, create the new head with the event envelope corresponding to that maximum. Also confirm that the snapshot's seq_nr is at most the maximum. When an old type name contains `-`, replace it with the mapping table that the user gives, and check for collisions of new aids and exceeding 1024 bytes. Compare the read-back after migration, and if a Change Stream is used, finish the new subscription and the rebuild of the read model before switching over.

## 9. Cases to look at in conformance verification

| Case | Expected result | Rules |
|:--|:--|:--|
| Append seq_nr=1 to the same aid concurrently | Only one is committed, and the other is an optimistic lock | SPN-6, SPN-7, W-3, W-7 |
| The transaction is re-executed because of an earlier write | Re-checks the head with the same envelope, and does not renumber | SPN-7, H-2, W-8 |
| New creation with events only | Can be read as an existing aggregate without a snapshot | SPN-6, R-1 to R-3 |
| Failure after the journal write and before the commit | No uncommitted update is visible in any of head, snapshot, or journal | SPN-6, H-1 |
| The response is lost after the commit succeeds | A storage error of unknown outcome. No compensating write. Resending the same seq_nr is an optimistic lock | SPN-8, W-7 |
| A head read and a snapshot update conflict | Returns a pair at the same read point | SPN-9, R-8 |
| The result is split into multiple responses | Reads through to h without gaps | SPN-10, R-5 |
| A retention failure or a duplicated organization | The append success does not change, and the newest n are not removed | SPN-11, SPN-13, S-2, S-4 |
| The same payload and manifest continue (when a change feed is provided) | The complete envelope can be restored from each NEW_ROW transition | SPN-14, F-1 |
| Subscription expiry, and aggregate creation during resynchronization (when a change feed is provided) | Filled in by the comparison of all heads and the subscription after T | SPN-15, F-5 |
| In the first version, construct a store with a setting that requests the feed, or with a config whose change_feed_enabled is true | Configuration error | SPN-17 |

Tests are done on the Spanner emulator (chapter 5 of the [implementation plan](../../plan/implementation-plan.md)). The emulator supports the explicit SERIALIZABLE, strong read-only transactions, and reading out the row deletion policy and Change Stream settings from the information schema (the checks of SPN-2 and SPN-16).

Concurrent-execution cases can be reproduced on the emulator. However, the emulator makes an overlapping second read-write transaction ABORTED even without a conflict. Therefore, tests are wrapped in the re-execution of SPN-7. Passing on the emulator does not prove the service side's conflict detection.

What cannot be reproduced on the emulator, and how to verify it, are as follows. The rules do not change.

- The loss of the commit response of SPN-8 is verified in each language's tests. Place an injection inside the library that discards the response after the commit succeeds.
- For the service-side limits on mutation and commit size, verify only the check the library does before writing.
- Physical deletion by the row deletion policy is the service's job and is outside the scope of tests. The library does not count marked rows in the retention count (S-3), so it does not rely on physical deletion.

The table is the acceptance criteria for conformance tests at implementation time, not completed test results.

## 10. Agreement status

SPN-D1a, SPN-D1b, and SPN-D2 to D7 were agreed on 2026-10-04, and SPN-D8 on 2026-10-16. No unagreed decisions remain in chapter 1. The draft rules were finalized on 2026-10-16 (P-57). Only SPN-15 remains a draft, and it is finalized when a change feed is provided (P-58). This finalization includes the way of verifying in line with the principle of testing on the emulator (chapter 9). It does not declare the conformance of implementations, and verification in each language's implementation remains (the re-release of js is [js#1067](https://github.com/j5ik2o/event-store-adapter-js/issues/1067)). The agreed rules of the common contract have not been changed. The entry point for comparing the capabilities with Bigtable and SQLite is placed in the [specification README](../README.md).
