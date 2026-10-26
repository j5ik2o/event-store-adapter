# Common contract (finalized in v5)

This document defines the semantics, independent of any storage, that all implementations satisfy. This document is common contract v5 (P-46 and P-47 of the [README](README.md)). The v5 documents can be pinned and referenced with this repository's tag `contract-v5` (P-50). How each storage realizes it is written in the storage profiles. For the notation of rules, see the [README](README.md).

> The agreement status of the rules in this document is in the [README's agreement status](README.md#agreement-status). A rule marked "not agreed" has not been agreed yet. Changing it requires the owner's agreement.

## 1. Values and types

### 1.1 Aggregate ID

An aggregate ID consists of two strings: a type name and a value.

- **MUST T-1**: The aggregate ID string used for storage and comparison (hereafter the aid string) is `${type name}-${value}`, assembled by the library. It does not depend on the user's stringification (`Display`, `asString()`, and so on) ([ADR-0003](../adr/0003-fix-storage-value-representations.md)).
- **MUST T-11**: The type name does not contain `-`. The value may contain `-`. Since everything up to the first `-` of the aid string is the type name, different aggregate IDs never become the same aid string. The library checks the type name when assembling the aid string, and returns a contract violation error if it contains `-`. If both the type name and the value were allowed to contain `-`, type name `order-item` with value `1` and type name `order` with value `item-1` would both become `order-item-1`, and items of different aggregates would get mixed in the storage (agreed 2026-10-03, P-23).
- **MUST T-12**: The aid string is at most 1024 bytes in UTF-8. For an aggregate ID that exceeds this, the library returns a contract violation error when assembling the aid string. This is so that it fits within the key length limit of any storage (DynamoDB's partition key is 2048 bytes, Bigtable's row key is 4KiB, Spanner's primary key is 8KiB) (agreed 2026-10-03, P-35).

### 1.2 Event envelope

An event envelope carries one event.

| Element | Content |
|:--|:--|
| aggregate_id | The aggregate ID |
| seq_nr | An integer of 1 or more. Numbered by the domain |
| occurred_at | The occurrence time given by the domain. Nanosecond precision |
| manifest | A free-form string attached by the user. An empty string if omitted |
| payload | The domain's content |

- **MUST T-2**: aggregate_id, seq_nr, occurred_at, and payload must always be given at construction. Only manifest can be omitted. Trying to construct an envelope without them, or calling an operation with an envelope lacking them, returns a contract violation error. If the language's type cannot express the absence, that check is not needed (the same treatment as the exemption in T-9; agreed 2026-10-06, P-42).
- **MUST T-3**: The library does not replace occurred_at with the store's time. The stored value is returned unchanged on read. However, if the language's standard time type cannot express nanoseconds, it may be rounded to the precision of that type (js's `Date` is in milliseconds).
- **MUST T-13**: occurred_at is within the range in which nanoseconds from the Unix epoch fit in a signed 64-bit integer (from 1677-09-21T00:12:43.145224192Z to 2262-04-11T23:47:16.854775807Z). Trying to write an envelope whose occurred_at is out of range returns a contract violation error. This is so that every language can read and write the same values even though the ranges of the standard time types differ by language (Java's `Instant` goes to a billion years, JavaScript's `Date` to about 270,000 years, and Go's nanosecond representation of `time.Time` to exactly this range) (agreed 2026-10-03, P-34).
- **MUST T-4**: The library does not interpret manifest and payload. The same applies to the snapshot's manifest (1.4).
- **SHOULD T-5**: Envelopes are immutable, and are exposed in a form where adding elements does not break existing user code. The same applies to the snapshot envelope (1.4). When metadata is added in the future, it is added as an element of the envelope.

### 1.3 Payload

- **MUST T-6**: The library requires nothing of the payload type beyond being serializable by the serializer. It does not require domain types to implement the library's interfaces or traits.
- **MUST T-7**: What the serializer serializes is only the payload. Metadata such as aggregate_id, seq_nr, and manifest is not embedded in the payload.
- **SHOULD T-8**: The default serializer is JSON.

### 1.4 Snapshot envelope

A snapshot envelope carries one snapshot. Like the event envelope, the same type is used for writes and reads.

| Element | Content |
|:--|:--|
| aggregate | The aggregate state of the snapshot |
| seq_nr | The seq_nr of the event up to which this snapshot has been applied. The starting point of replay |
| manifest | A free-form string attached by the user that indicates the type or schema version of the aggregate state. An empty string if omitted |

The head's seq_nr is not included in the envelope. This is because it is information of the aggregate head, not of the snapshot ([ADR-0002](../adr/0002-separate-aggregate-head-from-snapshot.md)). On a read, it is returned separately from the envelope (3.4).

- **MUST T-10**: aggregate and seq_nr must always be given at construction. Only manifest can be omitted. The handling of absence is the same as T-2 (agreed 2026-10-06, P-42).

### 1.5 Integer range

- **MUST T-9**: seq_nr is an integer from 0 to 2^53−1 inclusive ([ADR-0003](../adr/0003-fix-storage-value-representations.md)). Calling an operation with an out-of-range seq_nr returns a contract violation error. If the language's type cannot express out-of-range values (for example, negative values in an unsigned type), the check for those values is not needed (agreed 2026-10-05, P-41).

## 2. Aggregate head

There is one aggregate head per aggregate, and it holds the latest seq_nr and the event envelope appended by the immediately preceding write. The head is created by the first append (seq_nr = 1), and does not exist until then (W-3, R-1) ([ADR-0002](../adr/0002-separate-aggregate-head-from-snapshot.md)). The head's seq_nr is used for the optimistic lock check ([ADR-0004](../adr/0004-use-seq-nr-for-optimistic-locking.md)).

- **MUST H-1**: The commit of an append is decided by a single atomic operation. A committed append appears in all of the aggregate head, the event reads in 3.5, and the change feed (chapter 6, if provided), and an append that was not committed appears in none of them. In a write accompanied by a snapshot, the snapshot also follows the same commit, and the snapshot of a write that was not committed does not appear in the read in 3.4. The commit mechanism (whether the journal, head, and snapshot are written in one transaction, or the conditional update of the head is the commit point and the journal is written out afterwards) is defined by the storage profile ([ADR-0005](../adr/0005-define-append-atomicity-by-observable-commit.md), agreed 2026-10-03, P-28).
- **MUST H-2**: The optimistic lock check is performed against the head's seq_nr. The snapshot is not used for the check.
- **MUST H-3**: The number of events appended by one write is one.
- **MUST H-4**: The aggregate head holds the latest seq_nr and the event envelope committed at that seq_nr. A profile that writes the journal out after the commit point supplements events not yet written to the journal from the envelope held by the head (agreed 2026-10-03, P-28).

## 3. Operations

The names in each language may follow the language's conventions (`persist_event` / `persistEvent`, and so on).

The expected value for the check is determined from the seq_nr of the event envelope. An event whose seq_nr is n can be appended only when the head's seq_nr is n−1. If the seq_nr is 1, it can be appended only when the head does not yet exist. Therefore, the write operations take no argument for the expected value ([ADR-0004](../adr/0004-use-seq-nr-for-optimistic-locking.md)).

### 3.1 persistEvent(event)

Appends only the event. It does not write a snapshot.

### 3.2 persistEventAndSnapshot(event, snapshot)

Appends the event and writes the snapshot at the same time. event is an event envelope, and snapshot is a snapshot envelope.

- **MUST W-9**: If `snapshot.seq_nr != event.seq_nr`, return a contract violation error. This is because the snapshot is the state after applying that event.

### 3.3 Rules common to both operations

- **MUST W-3**: If `event.seq_nr == 1`, treat it as a new creation and create the journal and the head (in 3.2, also create the snapshot). If the head already exists, return an optimistic lock error.
- **MUST W-4**: If `event.seq_nr > 1`, treat it as an update and perform the check of W-8.
- **MUST W-6**: If `event.seq_nr == 0`, return a contract violation error.
- **MUST W-7**: Two events with the same seq_nr cannot be written to the same aggregate. The second one becomes an optimistic lock error.
- **MUST W-8**: An update writes only when `event.seq_nr == head's seq_nr + 1`. This is the optimistic lock check. The error when it does not match depends on how it deviates. If `event.seq_nr` is less than or equal to the head's seq_nr, return an optimistic lock error. This is the case where another write was committed first, or where replay under an eventually consistent read returned an old state and numbering was done from that old state, and it is fixed by re-reading. If it is the head's seq_nr + 2 or more, it is a gap in numbering, so return a contract violation error. This prevents missing numbers in the change feed. An update to an aggregate that has no head (`event.seq_nr` is 2 or more) applies the same rule, regarding the head's seq_nr as 0. Since aggregates are not deleted, this is a gap in numbering, and a contract violation error is returned (agreed 2026-10-03, P-32). This reverses the policy of rs v3, "do not verify continuity" (agreed 2026-10-02).

W-1, W-2, and W-5 have been deleted. W-2 and W-5 are due to the removal of version (ADR-0004), and W-1 is due to making the snapshot optional (R-3). To keep the correspondence with the conformance test data, the numbers are not reused.

### 3.4 getLatestSnapshotById(aggregateId)

- **MUST R-1**: If there is no aggregate head, regard the aggregate as non-existent and return "none". It is not an error. The presence or absence of a snapshot is unrelated to the existence of the aggregate (R-3).
- **MUST R-2**: If it exists, return a pair of the snapshot envelope (which may be absent) and the head's seq_nr at the time of the read. The representation of the pair (struct, tuple, and so on) is left to the language.
- **MUST R-3**: The snapshot may be absent. The snapshot is a cache of the aggregate state, and the aggregate can be read even if it is missing. When it is absent, the caller replays from seq_nr 1 of the journal (agreed 2026-10-02).
- **SHOULD R-7**: The caller checks whether the last seq_nr obtained by replay has reached the head's seq_nr received in R-2. If it has not, the eventually consistent read is lagging, so it re-reads.

Since a snapshot may be older than the head, the envelope's seq_nr can be below the head's seq_nr.

- **MUST R-8**: The storage profile states whether it reads the pair of R-2 atomically. In a storage that does not read atomically, when a read overlaps with a write, the snapshot envelope's seq_nr may exceed the head's seq_nr. In that case the snapshot is newer, and the caller may replay from the snapshot's seq_nr + 1 and number from there. If numbering was done from an old state, it becomes an optimistic lock by W-8, so consistency does not break whichever way it deviates (agreed 2026-10-03, P-25).

### 3.5 getEventsByIdSinceSeqNr(aggregateId, seqNr)

- **MUST R-4**: Return the event envelopes whose seq_nr is **greater than or equal to** seqNr, in ascending order of seq_nr. A caller replaying from a snapshot passes the snapshot envelope's seq_nr + 1. If there is no snapshot, it passes 1.
- **MUST R-5**: Return **all** the events that match the condition. If the storage has an upper limit on the amount returned in one response, read through the continuation before returning. "All" includes the events that were committed at the time the read started. For a storage that has only eventually consistent reads, the storage profile defines how to satisfy this (agreed 2026-10-03, P-26).
- **MUST R-6**: What is returned is envelopes, not a sequence of payloads alone.

## 4. Error classification

How errors are returned (Result type, exception, error value) is left to the language. What the specification defines is the classification.

| Classification | Situations in which it occurs |
|:--|:--|
| Optimistic lock | Creating an already existing aggregate, a duplicate seq_nr, appending with a seq_nr less than or equal to the head's seq_nr (W-8) |
| Contract violation | Calls that violate T-2, T-10 (absence of required elements), W-6, W-9, T-9, T-11, T-12, T-13, and a gap in numbering under W-8 |
| Serialization | Failure to serialize or restore the payload |
| Configuration | An invalid setting value at construction (for example, a retention count of 0), a mismatch with the settings recorded in the storage |
| Storage | Communication with the storage, a failure returned by the storage, missing data that was read |

- **MUST E-1**: The caller can distinguish the classification by type (or by a distinguishable value).
- **MUST E-2**: The message of an optimistic lock contains only the aid string, the seq_nr that was attempted to be appended, and (if known) the head's seq_nr. It does not contain connection strings, credentials, or the raw error text of the storage SDK.
- **MUST E-3**: The message of a contract violation contains the number of the rule that was violated and, if there is a relevant seq_nr, its value. When there is no relevant seq_nr, as when the seq_nr itself is missing (T-2, T-10), the rule number alone suffices (agreed 2026-10-06, P-42).

## 5. Snapshot retention

By default, only the current snapshot is kept. If a retention count is set, the snapshot history is also kept with each write.

- **MUST S-1**: The retention count is set as "none" or an integer of 1 or more. 0 is a configuration error.
- **MUST S-2**: History exceeding the retention count n is removed **from the oldest**, and the newest n are kept.
- **MAY S-3**: Instead of removing, a style can be chosen in which history is removed later by the storage's expiry mechanism. In this style, history marked as expired is not counted in the retention count, and is not selected as the next target for marking. The mark is applied only once per history item, and the expiry is not postponed (agreed 2026-10-02). The expiry mechanism (per-item expiry, rules at the level of tables or column families, and so on), where the grace period is placed (in the library's settings or in the storage's definition) and its precision, and the delay until removal are defined by the storage profile. The profile of a storage with no such mechanism need not provide this style (agreed 2026-10-03, P-30).
- **MUST S-4**: A failure of retention processing does not change the result of the append. Even if retention processing fails, if the append is committed, the write is returned as a success (when and in which operation retention processing is performed is defined by the storage profile; agreed 2026-10-03, P-30). A retention failure is reported through another path, such as a log or a callback for notification. History left behind is cleaned up the next time retention processing runs. The current rs and js return it as a write failure, and a retry by the caller then becomes an optimistic lock error, so this is changed (agreed 2026-10-02).

## 6. Change feed (optional capability)

A change feed is a sequence of head transitions ordered by seq_nr for each aggregate. Each storage profile states whether it provides this capability, and the properties of the transport path.

A head transition consists of the aggregate ID, the seq_nr after the transition, and the sequence of event envelopes appended by that write.

- **MUST F-1** (if provided): Every committed append appears as a head transition.
- **MUST F-2** (if provided): The head transitions of the same aggregate are generated in ascending order of seq_nr. If the transport path may reorder them, the profile says so.
- **MUST F-3** (obligation of the subscriber): The subscriber discards duplicates by (aid string, seq_nr).
- **MUST F-4** (obligation of the subscriber): If the received seq_nr is not the previous one + 1, the subscriber regards it as a missing number and fills it in from the journal with the operation in 3.5.
- **MUST F-5** (obligation of the subscriber): If the subscription stops beyond the retention period of the transport path, a miss of an aggregate that was updated in the meantime and has not been updated since cannot be detected by F-4. In this case, the subscriber compares the current seq_nr of all aggregates with its own position by the resynchronization procedure defined by the storage profile, and fills in the missing part with the operation in 3.5. Each storage profile, if it provides a change feed, defines this procedure (agreed 2026-10-03, P-27).

## 7. Requirements on storage profiles

Each storage profile defines how it satisfies the common contract in its storage. The following two are required of every profile.

- **MUST SP-1**: The profile states the preconditions under which its rules hold. It writes at least the kind of read consistency and the composition of the write path (a single region, routing to a single cluster, and so on). A configuration that deviates from the preconditions is out of scope, and if it can be detected, it is rejected with a configuration error (agreed 2026-10-03, P-31).
- **MUST SP-2**: The profile's key construction is injective. A read or retention processing of one aggregate must not hit the items of another aggregate. If a prefix-match range read is used, it defines an encoding in which the range boundaries do not overlap with another aggregate (agreed 2026-10-03, P-33).

In other chapters, the following are delegated to the profile.

| What is delegated | Rule |
|:--|:--|
| The commit mechanism | H-1 |
| How to return all committed events when only eventually consistent reads exist | R-5 |
| Whether to read the pair of the latest snapshot and the head atomically | R-8 |
| Whether to provide a change feed, the ordering properties of the transport path, and resynchronization when the retention period is exceeded | chapter 6, F-2, F-5 |
| The mechanism, grace period, and delay of the expire-and-remove style, and when retention processing is performed | S-3, S-4 |

## 8. What is left to the language

The following are not defined by the specification.

- The names of operations, types, and errors, and how errors are returned
- How to construct envelopes (constructor, builder, factory, and so on)
- The expression of asynchrony (async/await, Future, callbacks, and so on)
- The language-level types for integers and time (it suffices to satisfy the ranges of T-3 and T-9)

## 9. Open items

None (as of 2026-10-03).
