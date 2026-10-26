# SQLite storage profile (finalized)

Realizes the [common contract](../core-contract.md) with the transactions of a single local database file. The head is placed in a dedicated table, and appends are checked by seq_nr even with multiple connections opening the same file and multiple processes on the same host.

> Created on 2026-10-04. The main decisions SQ-D1a, SQ-D1b, SQ-D2a, SQ-D2b, SQ-D3, SQ-D4, SQ-D5a, SQ-D5b, SQ-D6, and SQ-D7 in chapter 1 were agreed on the same day, and the concrete realization of the SQ rules that had been drafts was finalized on 2026-10-16 (P-53). The first version does not provide a change feed (SQ-D8, P-54). SQ-13 stays a draft and is finalized when a change feed is provided. Implementers check the layout, connections, and commit in chapters 1 to 5, and refer to the relevant chapters for retention, subscription, and migration. Terminology follows [CONTEXT.md](../../../CONTEXT.md).

## 1. Agreed layout and capabilities

| Decision | Adopted proposal | Main alternatives | Status |
|:--|:--|:--|:--|
| SQ-D1a | Target a local file on the same host, and handle use from multiple connections and multiple processes | Limit to a single connection to a local file, or also support in-memory databases | Agreed (2026-10-04) |
| SQ-D1b | Local files use WAL and synchronous=FULL | Use rollback journal DELETE and synchronous=EXTRA, or make both methods selectable by a setting | Agreed (2026-10-04) |
| SQ-D2a | Target SQLite 3.51.3 or later | In addition to 3.51.3 or later, also target the patched older versions 3.44.6 and 3.50.7 | Agreed (2026-10-04) |
| SQ-D2b | Make all tables STRICT, including config and the optional transition table | Use ordinary tables and leave checks of types and ranges to the library | Agreed (2026-10-04) |
| SQ-D3 | Appends use BEGIN IMMEDIATE, and each read operation is done in the same explicit read transaction | Appends use BEGIN DEFERRED and re-execution of the whole operation upon contention at the move to writing, with reads in the same explicit transaction | Agreed (2026-10-04) |
| SQ-D4 | Delete old snapshot history in a separate transaction after the commit of the append. The first version does not provide an expiry style | Provide an expiry column and an independent lazy-deletion process | Agreed (2026-10-04) |
| SQ-D5a | Provide an optional change feed, and commit the transition table in the same transaction as the events | The first version does not provide a change feed | Agreed (2026-10-04). Kept as the decision for when it is provided (SQ-D8) |
| SQ-D5b | The feed's transition table is kept indefinitely in the first version that provides a change feed, and the adapter does not delete old transitions | Design deletion with a retention period, and detection of expiry and resynchronization | Agreed (2026-10-04). Kept as the decision for when it is provided (SQ-D8) |
| SQ-D6 | Separate the explicit initialization of an uninitialized empty DB from the operation of opening an existing store | Automatically create missing tables at construction | Agreed (2026-10-04) |
| SQ-D7 | Align the retention count and the feed settings per store, and have all clients check them. When changing, stop appends, maintenance, and subscriptions, and reconstruct after the change | Design a method that manages the retention count per aggregate. The feed settings are aligned across the whole store | Agreed (2026-10-04) |
| SQ-D8 | The first version does not provide a change feed. A setting that requests it is a configuration error. Keep change_feed_enabled in config and fix it to 0, and do not create head_transition | Provide it from the first version as in SQ-D5a | Agreed (2026-10-16) |

SQ-D1 was split into SQ-D1a and SQ-D1b in order to confirm the supported environment and the storage method independently. SQ-D2 was split into SQ-D2a and SQ-D2b in order to confirm the minimum SQLite version and the adoption of STRICT tables independently. SQ-D7 gives a number to the handling of retention and feed settings that had been left in chapter 10 of the draft.

SQ-D5 was split into SQ-D5a and SQ-D5b in order to confirm the provision of the change feed and the retention period of the transition table independently.

SQ-D8 was added following the owner's decision on 2026-10-15 not to include the change feed in the version being re-released (the change feed is ultimately needed, but its priority is low). It takes the same form as MEM-D9 and MEM-13 of the memory profile, and a setting that requests a feed is a configuration error. The `change_feed_enabled` column of config is kept and recorded fixed to 0 in the first version. This is so that `layout_version` need not be raised when the feed is added later. SQ-D5a and SQ-D5b, and the rules concerning the feed (SQ-12, SQ-13, SQ-18, SQ-19), are kept as decisions and rules for when it is provided.

By the agreement of SQ-D1a, the case of using a local file on the same host from multiple connections and multiple processes is also covered. The check of writers is performed by database transactions. Network file systems and a memory-only layout are outside the scope of this version. The proposal to limit to a single connection was not adopted because it could not handle use from other connections and other processes.

A known bug at WAL reset was fixed in [3.51.3](https://www.sqlite.org/releaselog/3_51_3.html). By the agreement of SQ-D2a, the supported SQLite itself is limited to 3.51.3 or later. According to the [SQLite explanation](https://www.sqlite.org/wal.html#walresetbug), the fix has also been incorporated into the older series [3.44.6](https://sqlite.org/src/info/863c171b76cd36e0) and [3.50.7](https://sqlite.org/src/info/c7facf7ac58d2cda), but this version does not allow them because it would increase individual support decisions and acceptance checks.

## 2. Check the file, connections, and settings

- **MUST SQ-1**: Use SQLite 3.51.3 or later, and set and confirm `locking_mode=NORMAL`, `journal_mode=WAL`, and `synchronous=FULL` on all connections. Do not use shared cache, and set `read_uncommitted=OFF`. The busy wait time is given by a setting. Whether to have a default for the wait time, and what it is, is left to each language's implementation. The file is placed on the local file system of the same host. Network file systems, layouts split across multiple files by ATTACH, and memory-only layouts are out of scope (SP-1) (agreed 2026-10-16, P-53).

The wait time of SQ-1 is the time that SQLite waits until the transaction of another connection releases the write lock, of which it has only one per database file. The lock is one for the whole file, so appends to different aggregates also wait their turn. An append holds this lock only for the short time from BEGIN IMMEDIATE to COMMIT, and does not hold it while the user re-reads events and creates the next event. The concurrency control seen by the user is the optimistic lock check by seq_nr (W-8), which is separate from this wait time. If the wait time is exceeded, it is a storage error, not an optimistic lock (SQ-7).

The concurrent operation of WAL readers and writers and the same-host premise are based on [WAL](https://www.sqlite.org/wal.html), and synchronization at commit is based on [PRAGMA synchronous](https://www.sqlite.org/pragma.html#pragma_synchronous). It is also a premise that the file's storage honors the synchronization requests.

To preserve use from multiple connections and multiple processes, set locking_mode to NORMAL before enabling WAL. This is because with EXCLUSIVE a connection keeps holding the file lock ([PRAGMA locking_mode](https://www.sqlite.org/pragma.html#pragma_locking_mode)).

By the agreement of SQ-D1b, it is fixed to WAL and synchronous=FULL. WAL allows reads and writes to proceed concurrently, and FULL synchronizes the WAL at each commit. The considered rollback journal DELETE and synchronous=EXTRA is a method that also synchronizes the directory from which the journal was deleted at commit. The proposal to make both methods selectable was not adopted in this version because it would require checking settings and verification for each mode.

- **MUST SQ-14**: Set and confirm `journal_mode=WAL` and `synchronous=FULL` on all connections used by the store. Do not continue reads and writes with values different from the settings; make it a configuration error. Use FULL on all connections, and do not switch the strength of synchronization per call (agreed 2026-10-04, SQ-D1b).

- **MUST SQ-15**: From the connection that opens the store, obtain the version of the SQLite actually used, and confirm that it is 3.51.3 or later. If it is lower, make it a configuration error. Compare versions by treating each part as an integer (agreed 2026-10-04, SQ-D2a).

- **MUST SQ-2**: At construction, confirm config's store_id, layout version, retention count, presence of the feed, table definitions, and primary keys. A missing or mismatched configuration item or required definition is a configuration error. A nonexistent store is not automatically initialized by the ordinary "open" operation. Initialization is an explicit operation targeting only an uninitialized empty DB, and performs the DDL and the INSERT of the configuration in one transaction (agreed 2026-10-04, SQ-D6). The concrete storage format and fields to be checked are as in the layout of chapter 3 and the shape of config below (agreed 2026-10-16, P-53).

By the agreement of SQ-D6, the explicit initialization and the operation of opening an existing store are separated. Initialization targets, while the store is not running, only a new file or an uninitialized database that has no application tables, indexes, views, or triggers. After confirming the SQLite version and WAL and FULL, confirm within BEGIN IMMEDIATE that the target is uninitialized, and commit the necessary DDL and the INSERT of config together.

The WAL setting is made before starting this initialization transaction. This is because journal_mode cannot be changed during a transaction ([PRAGMA journal_mode](https://www.sqlite.org/pragma.html#pragma_journal_mode)). The ordinary "open" targets an existing file, and makes a missing or mismatched configuration item or required definition a configuration error. Missing definitions are not filled in automatically. The alternative of auto-initializing at construction was not adopted in this version because it requires additionally designing contention in simultaneous initialization and recovery from partial creation failures.

config's `store_id` is a lowercase UUID string, and `layout_version INTEGER` is 1. `keep_snapshot_count INTEGER` is NULL for none, and a positive integer when set. `retention_mode TEXT` is limited to `delete`, and `change_feed_enabled INTEGER` to 0 or 1. It is also checked that the setting values fit in SQLite's signed 64-bit integer.

By the agreement of SQ-D7, the retention count and the feed settings are recorded per store, and all clients check them against their own settings. The alternative of specifying the retention count per aggregate was not adopted in this version because it would require adding a place to store the setting and a procedure by which all writers and maintenance processes use the same count. In an enabled store, a transition is saved on every append (SQ-D5a).

- **MUST SQ-19**: Align the retention count and the feed settings per store, and have all clients check them against the configuration item. A mismatch is a configuration error. Change the settings with the operations of all clients stopped, and reconstruct and check the store after the change. When changing the retention count, organize the existing history by the setting change procedure in chapter 6 before updating the setting. When enabling or re-enabling the feed, align the necessary transition table, and start subscribing by the procedure in chapter 7 that aligns the boundary of restoration and subscription (agreed 2026-10-04, SQ-D7).

For backup and restore, use SQLite's backup means, and do not copy only the main file of a store running under WAL.

## 3. Use aid and integers as the primary keys, without a hash

SQLite does not distribute in this profile, so it has no hash prefix. It uses exact match on aid and integer comparison of seq_nr (SP-2).

| Table | Primary key | Other columns |
|:--|:--|:--|
| journal | `(aid TEXT COLLATE BINARY, seq_nr INTEGER)` | `occurred_at_ns INTEGER`, `manifest TEXT`, `payload BLOB` |
| head | `aid TEXT COLLATE BINARY` | `type_name TEXT`, `seq_nr INTEGER`, `event_occurred_at_ns INTEGER`, `event_manifest TEXT`, `event_payload BLOB` |
| snapshot_current | `aid TEXT COLLATE BINARY` | `seq_nr INTEGER`, `manifest TEXT`, `payload BLOB` |
| snapshot_history | `(aid TEXT COLLATE BINARY, seq_nr INTEGER)` | `manifest TEXT`, `payload BLOB` |
| config | `singleton INTEGER` (the value is 1) | `store_id TEXT`, `layout_version INTEGER` (1 in the first version), retention and feed settings |
| head_transition (optional) | `transition_id INTEGER PRIMARY KEY AUTOINCREMENT` | `aid TEXT`, `seq_nr INTEGER`, `occurred_at_ns INTEGER`, `manifest TEXT`, `payload BLOB`, `UNIQUE(aid, seq_nr)` |

The required columns of keys and envelopes are NOT NULL, and seq_nr has `CHECK(seq_nr BETWEEN 1 AND 9007199254740991)`. All tables are STRICT, which preserves the storage format of INTEGER and BLOB. The type checking of STRICT follows the [SQLite specification](https://www.sqlite.org/stricttables.html).

By the agreement of SQ-D2b, journal, head, snapshot_current, snapshot_history, config, and head_transition when enabled are all STRICT. Values that cannot be converted losslessly to the specified type are rejected by the database too. Even with STRICT, lossless type conversion is performed, so the library's input checks and the CHECK on the seq_nr range are maintained.

- **MUST SQ-16**: Create all tables of the store as STRICT, and check the declarations at construction. This includes config, and head_transition when enabled. A layout mixing ordinary tables is a configuration error (agreed 2026-10-04, SQ-D2b).

- **MUST SQ-3**: The library first checks the aid's type name, UTF-8 byte length, and the integer ranges. Bind `occurred_at_ns` as a signed 64-bit integer, and do not use REAL. Also retrieve it as an integer on read. In JavaScript, use a lossless SDK path such as BigInt (T-3, T-9, T-13) (agreed 2026-10-16, P-53).
- **MUST SQ-4**: Store the manifest and payload of events and snapshots in separate columns. Bind aid as a parameter, and do not make it a prefix match by LIKE or a delimiter. Do not include `-` in the type name, and compare strings without normalizing them (T-1, T-7, T-11) (agreed 2026-10-16, P-53).

The upper limits on value size for SQLite connections and builds follow [SQLite limits](https://www.sqlite.org/limits.html). A serialization failure is a serialization error, and exceeding the size or running out of capacity returned by the storage is a storage error.

## 4. Check writers within BEGIN IMMEDIATE

- **MUST SQ-5**: After finishing the input checks and serialization, perform the following processing in one transaction on one connection. Do not hand the same connection to another operation at the same time (agreed 2026-10-16, P-53).

```text
BEGIN IMMEDIATE
  ヘッドを aid の完全一致で読む
  新規作成ならヘッドの不在を確認し、更新なら W-8 を照合する
  journal にイベントを INSERT する
  head に最新 seq_nr とイベント封筒を作成・更新する
  スナップショットを伴うなら current を作成・更新する
  スナップショットを伴い、保持件数を設定していれば history に同じスナップショットを INSERT する
  フィードを利用するストアなら head_transition に同じイベントを INSERT する
COMMIT
```

An update with no head is regarded as position 0, and a seq_nr of 2 or more is a gap and becomes a contract violation. If an earlier write puts the seq_nr at or below the existing position, it is an optimistic lock. A new creation can also be done without a snapshot. A mismatch between snapshot.seq_nr and event.seq_nr is made a contract violation before starting the transaction.

Because BEGIN IMMEDIATE serializes the writers of the same file, appends from the old state of another process can be checked even without an in-process Mutex. It is premised on [SQLite isolation](https://www.sqlite.org/isolation.html).

By the agreement of SQ-D3, a write transaction is secured with BEGIN IMMEDIATE before the head check begins. Since the head is read and checked after waiting for the lock, a procedure that keeps using an old read point on the way from reading to writing can be avoided. The retrieval of the latest snapshot and the retrieval of events are each done in the explicit read transaction of chapter 5.

The considered BEGIN DEFERRED, if a read is done first, may conflict with another connection's update at the move to writing and result in SQLITE_BUSY or SQLITE_BUSY_SNAPSHOT. It would require a procedure to end that transaction and re-execute from the head check with the same input, so it was not adopted in this version ([transaction specification](https://www.sqlite.org/lang_transaction.html)). An in-process Mutex alone cannot arbitrate other processes, and a set of independent SELECTs can have shifted read points, so it is not a standalone alternative.

- **MUST SQ-17**: An append starts BEGIN IMMEDIATE before the head check and commits in the transaction on the same connection. The retrieval of the latest snapshot reads head and snapshot_current, and the retrieval of events reads head and journal, each in the same explicit read transaction. A connection in the middle of an operation is not shared with another operation (agreed 2026-10-04, SQ-D3).

- **MUST SQ-6**: The success of COMMIT is the commit point. An error midway is ROLLBACKed, and a partial journal, head, snapshot, or transition is not published. On an error in COMMIT, check the state of the transaction and clean up, and if success or failure cannot be confirmed, make it a storage error. Do not assume it was not committed and renumber with a different seq_nr (agreed 2026-10-16, P-53).
- **MUST SQ-7**: SQLITE_BUSY, SQLITE_LOCKED, and wait-time overruns are storage errors. Do not confuse lock waits with optimistic locks. Re-execution is done for the whole operation with the same input, and only the INSERT of the journal is not resent (agreed 2026-10-16, P-53).

If it can be confirmed to be a primary key duplicate in journal or in a new head, it is an optimistic lock. Other violations of CHECK, NOT NULL, type, and feed constraints are not collectively mapped to an optimistic lock. A primary key duplicate after passing the head check occurs only when the journal and head are inconsistent. In that case too, it is an optimistic lock, aligned with W-7 of the common contract and 6.2 of the DynamoDB profile (a failed journal condition is an optimistic lock).

## 5. Put multiple SELECTs in the same read transaction

- **MUST SQ-8**: In the retrieval of the latest snapshot, read head and snapshot_current on the same connection from BEGIN to COMMIT. The read point is fixed at the first SELECT. The pair of R-2 is atomic, and snapshot.seq_nr is at most h (R-8). If there is no head, return "none", and if there is only a head, return h and "no snapshot" (agreed 2026-10-16, P-53).
- **MUST SQ-9**: In event retrieval, read head and journal in one explicit read transaction. First read the head's h, then read journal with `aid = :aid AND seq_nr >= :start AND seq_nr <= :h ORDER BY seq_nr`. Let `:start = max(1, seqNr)`. Process the cursor to the end, and do not close the read transaction midway (R-4 to R-6) (agreed 2026-10-16, P-53).

Even when a large result is divided into pages, the same read point is used. If the connection is lost, discard the result and re-execute the whole. A missing number in the target range or a missing required column is a storage error, and a short result is not returned as a success.

Even if the latest write is added immediately after a read, in the next write W-8 is checked against the current head.

## 6. Take history deletion out of the append transaction

By the agreement of SQ-D4, snapshot history older than the retention count is deleted in a separate transaction after the commit of the append. Even if the deletion fails, the committed append is returned as a success (S-4). The first version does not provide an expiry style. The alternative of adding an expiry column and independent lazy deletion was not adopted in this version because it requires additionally designing the marking, the determination of the count, the re-execution of the deletion process, and operations.

- **MUST SQ-10**: After an append accompanied by a snapshot is committed, in a separate BEGIN IMMEDIATE, read that aid's history in descending order of seq_nr. Keep the newest n, and DELETE only the older ones and COMMIT. Do not delete current, head, journal, or transition (agreed 2026-10-16, P-53).
- **MUST SQ-11**: Notify of busy, disk, and SQL failures in retention processing, and do not change the success of the append. Retry at the next snapshot write or explicit maintenance (S-4). The expiry style S-3 is not provided, and a setting that requests TTL is a configuration error (agreed 2026-10-04, SQ-D4).

Reclaiming free space remaining in the SQLite file and logical history deletion are separate processes. VACUUM is not included in the success conditions of an append.

### A change to the retention count setting is reflected after organizing the existing history

This is done by an external management procedure. Unlike ordinary per-aid operations, it enumerates all aggregates in snapshot_history.

1. Stop all clients that use the store, and confirm that the appends, reads, retention, and subscriptions in progress have ended. Save the setting before the change, the target setting, and the progress of the processing in a management record that can be used for resuming.
2. For each aid, read the history in descending order of seq_nr with BEGIN IMMEDIATE. If the target is n, keep the newest n, and if it is none, DELETE all history, and COMMIT. Split large organization work, and reselect in each transaction. Do not change journal, head, snapshot_current, or head_transition.
3. After the organization of all aggregates is complete, update config's retention count in a separate BEGIN IMMEDIATE and COMMIT. Reconstruct all clients to check the settings, and resume processing.

If it fails midway, keep it stopped and re-run to the same target in the management record. The failure of each transaction can be rolled back, but history already deleted by a previous transaction cannot be restored, so a rollback of the whole store is not presupposed. When the count is increased, or when a count is set from none, past history that was already deleted or was not retained is not fabricated. The new setting is applied from subsequent snapshot writes. This is a management procedure during a stop, and the guarantee of S-4 that does not change the success of a committed append does not change.

## 7. The optional change feed writes the transition table in the same commit

By the agreement of SQ-D5a, the change feed is provided as an optional capability. In a store that uses it, event envelopes are appended to head_transition and committed in the same transaction as head and journal. A store that does not use it is not required to save transitions. The subscriber re-reads from the saved position, removes duplicates, and fills in missing numbers from journal (F-1 to F-4). The retention period of the transition table is confirmed separately in SQ-D5b. However, the first version does not provide a change feed (SQ-D8).

- **MUST SQ-20**: The first version does not provide a change feed (SQ-D8). Initialization with a setting that requests the feed, and the operation of opening a store whose config's change_feed_enabled is 1, are configuration errors. In the first version, change_feed_enabled is recorded as 0, and head_transition is not created (agreed 2026-10-16, P-54).

- **MUST SQ-12** (if used): Include head_transition in the append transaction and commit it together with the event. Do not make only in-process notification such as sqlite3_update_hook the source of truth of the feed. Make it possible to re-read unprocessed transitions from the table even after the process exits or reconnects (F-1, agreed 2026-10-04, SQ-D5a).
- **Draft, MUST SQ-13**: Subscription repeats `transition_id > :cursor ORDER BY transition_id LIMIT :page_size`. After the processing of the returned transitions is complete, make the last transition_id the processed subscription position. Do not regard gaps in IDs as missing events. Missing events are determined by seq_nr per aid, and F-3 and F-4 are performed.

SQ-13 is finalized when a change feed is provided (SQ-D8).

transition_id uses the range of SQLite's 64-bit rowid. It is separate from the range of the event's seq_nr, and the subscription position is treated as an opaque decimal string or the like. The prevention of reuse by AUTOINCREMENT follows the [SQLite explanation](https://www.sqlite.org/autoinc.html).

By the agreement of SQ-D5b, in the first version that provides a change feed, the transition table is kept indefinitely, and the adapter does not delete old transitions. A stopped subscription resumes from after the saved ID. In a store that uses the feed, transition rows increase with every append, so an increase in capacity is anticipated. Deletion with a retention period was not adopted because it requires additionally designing a record of the deleted boundary, detection of subscription expiry, and resynchronization comparing against the current positions of all aggregates (F-5).

- **MUST SQ-18** (when using the feed): In the first version that provides a change feed, the transitions of head_transition are kept indefinitely. A failure of INSERT due to insufficient capacity or the ID limit is treated as a storage error, and the append transaction is rolled back. Only the event is not committed (agreed 2026-10-04, SQ-D5b).

### When rebuilding a read model, also align the boundary of restoration and subscription

1. In one read transaction, read the maximum transition_id m (0 if empty) and the positions h of all heads.
2. From the journal at that read point, apply the events up to each h. If moving to another read to avoid a long transaction, apply with the noted h as the upper limit.
3. When the restoration of the read model is complete, subscribe from after m. Maintain the duplicate removal of F-3.

This initialization is provided even with indefinite retention. If feed deletion is added in the future, agree together on a method that records the deleted boundary and detects subscription expiry, and on the resynchronization of F-5.

## 8. Migrate to a separate file from the current rs

The investigated target is [rs's SQLite implementation (7c6528c)](https://github.com/j5ik2o/event-store-adapter-rs/blob/7c6528c60acb787166431563f6148de5980a1667/lib/src/event_store_for_sqlite.rs). The current one has two tables, journal and snapshot, checks the snapshot's version, and shares the connection with an in-process Mutex. Its layout differs from this profile, which has a dedicated head, STRICT types, and an optional transition table.

Stop the writers, read the old file, and move to a new file. Do not infer the type name and value from the old pkey/skey or Display; make explicit the restoration corresponding to the old KeyResolver. Confirm the continuity, duplicates, and maximum of seq_nr per aggregate, and create the new head from the envelope of the maximum. When an old type name contains `-`, replace it with the mapping table that the user gives, and check for collisions of new aids and exceeding 1024 bytes. Maintain the occurrence time as a nanosecond value, and confirm how to handle the case where the old data has no manifest. Also verify the position of snapshots.

Do not treat the counts alone as completion; compare the envelope sequence per aid with the new read results before switching over. In a migration that uses the change feed, decide beforehand whether to create all past transitions at migration time or to initialize the read model from the maximum position.

## 9. Cases to look at in conformance verification

| Case | Expected result | Common rules |
|:--|:--|:--|
| Append the same next seq_nr from another connection or process | Only one is committed. A later one that reached the head check is an optimistic lock, and one that exceeds the wait limit is a storage error | H-2, W-8, SQ-7 |
| First event without a snapshot | The head exists, and there is no snapshot | W-3, R-3 |
| Fail after writing the journal and before COMMIT | All items and transitions are rolled back | H-1, F-1 |
| Another connection writes between the SELECTs of head and snapshot | Returns a pair at the same read point | R-8 |
| The lock wait time runs out | A storage error. Not an optimistic lock | E-1 |
| History deletion fails | Keeps the append success and re-executes in the next maintenance | S-4 |
| A subscription stops and resumes (when a change feed is provided) | Re-reads durable transitions from after the ID | F-1 to F-4 |
| -1ns, both ends of 64 bits, 2^53−1 | Values are preserved without conversion to REAL | T-3, T-9, T-13 |
| In the first version, initialize with a setting that requests the feed, or open a store whose change_feed_enabled is 1 | Configuration error | SQ-20 |

At the time of drafting, an SQL prototype was run on a temporary file with SQLite 3.53.1, and the following were confirmed: the STRICT layout, both ends of the signed 64-bit range, an append without a snapshot, a read point fixed against writes from another connection, the writer's lock wait, rollback before commit, a retention failure after the commit, retention of the newest n, and the transition table and the restoration boundary. It was not tried on the minimum version 3.51.3 itself.

This small-scale check does not prove the conformance of each language's adapter. Storage that honors fsync, forced process termination, power loss, and long multi-process tests are unverified.

## 10. Agreement status and remaining checks

All the main decisions in chapter 1 were agreed on 2026-10-04. Not providing a change feed in the first version (SQ-D8) was agreed on 2026-10-16. The rules that had been drafts, SQ-1 and SQ-3 to SQ-10, and the layout in chapter 3 and the shape of config in chapter 2, were finalized on 2026-10-16 (P-53, P-54). SQ-13 stays a draft and is finalized when a change feed is provided.

Verification in each language's adapter remains (the re-release of rs is [rs#309](https://github.com/j5ik2o/event-store-adapter-rs/issues/309)). Tests for forced process termination, power loss, and long multi-process runs also remain, and this document does not declare the conformance of implementations. Tests are done on local files (chapter 5 of the [implementation plan](../../plan/implementation-plan.md)). When providing a change feed, transitions are recorded on all writes, and an increase in capacity from indefinite retention is anticipated. The agreed rules of the common contract have not been changed.
