# Memory storage profile (finalized in v5)

Realizes the [common contract](../core-contract.md) in the memory of a single process. It separates the aggregate head from the snapshot, and checks appends by seq_nr.

> Created on 2026-10-05. MEM-D1 to MEM-D9, MEM-D11, and MEM-D12 in chapter 1 were agreed on the same day by adopting the proposals in the draft. MEM-D10 is on hold because MEM-D9 decided that the first version does not provide a change feed, and will be decided when it is provided. MEM-1 to MEM-13 in the body show the agreed content. MEM-14 and MEM-15 are candidates for when it is provided in the future, and are not agreed rules. IP-D4 of the [implementation plan](../../plan/implementation-plan.md) is the agreement on the policy of declaring conformance for memory as well. The implementation and conformance verification in each language will be done in the future. This is not an instruction to change the current implementations. Terminology follows [CONTEXT.md](../../../CONTEXT.md).

## 1. Agreed preconditions and capabilities

Except for MEM-D10, the proposals in the draft were adopted. The candidate for MEM-D10, and the alternatives, advantages, and disadvantages of each decision, are kept as a record of the decision process. The rules of the common contract themselves are not changed.

| Decision | Adopted proposal (MEM-D10 is a candidate) | Main alternatives | Status |
|:--|:--|:--|:--|
| MEM-D1 | Used in a single process, and all records are lost when the storage's lifetime ends. Does not persist | Same premise, and also provide an explicit clear-all during use | Agreed (2026-10-05) |
| MEM-D2 | A new construction is an independent storage. Only instances that explicitly share the same storage share records | Use with only one instance, and do not provide sharing to other instances | Agreed (2026-10-05) |
| MEM-D3 | Perform the check and all writes within store-wide mutual exclusion, and commit them together | With per-aggregate mutual exclusion, commit the check and all writes of the same aggregate together | Agreed (2026-10-05) |
| MEM-D4 | An event read obtains all items at the same point in time within the mutual exclusion | Secure the head h at the start and the immutable records, release the mutual exclusion, and then read through to h | Agreed (2026-10-05) |
| MEM-D5 | Atomically read the pair of the latest snapshot envelope and the head's seq_nr | Read the envelope and the head separately. Handle a mismatch in the pair according to R-8 | Agreed (2026-10-05) |
| MEM-D6 | After the commit, remove history within the same mutual exclusion as the write | After the commit, release the mutual exclusion and re-acquire it in a separate retention operation | Agreed (2026-10-05) |
| MEM-D7 | Report a retention failure by a log, and retry in the retention processing after the next append | Report by a callback for notification, and retry in the next retention processing | Agreed (2026-10-05) |
| MEM-D8 | The first version does not provide an expiry style | Provide a style that holds an expiry mark and a grace period, and removes expired history at each operation | Agreed (2026-10-05) |
| MEM-D9 | The first version does not provide a change feed | Provide an optional change feed, and include the head transition in the same commit as the append | Agreed (2026-10-05) |
| MEM-D10 | If a feed is provided, keep transitions indefinitely during the storage's lifetime, and hand them over preserving the order within an aggregate | Provide a finite retention period and a transport path in which the order can be swapped | On hold (because MEM-D9 does not provide it. To be decided when it is provided) |
| MEM-D11 | The storage holds immutable settings, and the instances that share it use those settings | Each instance receives its own settings, and checks them at construction against the shared storage's settings | Agreed (2026-10-05) |
| MEM-D12 | The implementation protects concurrent calls to the same storage. Use from multiple threads is also covered | Presuppose that the caller serializes all operations | Agreed (2026-10-05) |

MEM-D1, MEM-D2, and MEM-D12 define the preconditions of SP-1. MEM-D3 corresponds to H-1, MEM-D4 to R-5, and MEM-D5 to R-8. MEM-D6 to MEM-D8 correspond to S-3 and S-4, and MEM-D9 and MEM-D10 correspond to chapter 6, F-2, and F-5 of the common contract. MEM-D11 defines how to align the common contract's configuration errors with the settings of the sharing writers. MEM-D10 is decided when a change feed is provided, so it is on hold this time.

| Decision | Proposal | Advantage | Disadvantage |
|:--|:--|:--|:--|
| MEM-D1 | Lose all records at the end of the lifetime | No need to handle clear-all during reads and writes | To return to empty in tests and the like, a new storage is needed |
| MEM-D1 | Also provide an explicit clear-all | The same storage can be returned to empty | A procedure is needed to stop all operations and invalidate the old instances and subscription positions |
| MEM-D2 | Explicitly share the storage | Multiple users can check appends to the same aggregate | An operation is needed to distinguish sharing from independent construction |
| MEM-D2 | Do not share between instances | The owner of the records is clear | Users have to pass around and use the same instance |
| MEM-D3 | Mutual exclusion for the whole store | The boundary between commits and reads is simple | Operations on unrelated aggregates also wait for each other |
| MEM-D3 | Mutual exclusion per aggregate | Different aggregates can be handled concurrently | A separate consistent boundary is needed for the settings and the full resynchronization |
| MEM-D4 | Obtain all items at the same point in time | There is no doubt about whether appends during the read are included, and completeness is easy to confirm | With many items, the time under mutual exclusion gets long |
| MEM-D4 | Secure immutable records up to h | The result can be assembled outside the mutual exclusion | It must be guaranteed that records at or below h are not missing and do not change during acquisition |
| MEM-D5 | Atomically read the pair | The envelope's seq_nr does not exceed the head | The two values must be placed at the same read boundary |
| MEM-D5 | Read separately | Individual records can be read independently | Users must handle the case where the envelope is newer than the head |
| MEM-D6 | Retain under the same mutual exclusion after the commit | It can be returned to the normal retention count before the next operation | With a lot of history, the wait time of the write gets longer |
| MEM-D6 | Re-acquire mutual exclusion in a separate retention operation | The mutual exclusion for the append can be released early | The latest count must be re-read, including history that increased in the meantime |
| MEM-D7 | Report by log | The return value of the append and the notification are easy to separate | To tally retention failures, users need to monitor logs |
| MEM-D7 | Report by callback | Users can handle notifications directly | Failures and re-entry of the notification must be separated from the append |
| MEM-D8 | Do not provide an expiry style | The management of clocks and expiry becomes unnecessary | The behavior of lazy deletion cannot be tested in this storage |
| MEM-D8 | Check expiry at each operation and remove | Retention with a grace period can be handled | Clock management increases, and physical deletion does not progress without operations |
| MEM-D9 | Do not provide a feed | No need to manage the transport path and subscription positions | Users who use the change feed cannot test it in this storage |
| MEM-D9 | Provide an optional feed | Subscriptions following the common contract can also be tested | The implementation of saving transitions at commit time and resynchronization increases |
| MEM-D10 | Indefinite retention during the lifetime and order preservation | Loss of transitions due to a stopped period can be avoided | The retained amount of transitions keeps growing |
| MEM-D10 | Allow finite retention and swapped order | The retained amount is kept down, and the transport path can be configured independently | In addition to duplicate and missing-number handling, detecting the exceeded period and a full resynchronization are needed |
| MEM-D11 | Share the storage's immutable settings | No mismatch of settings between writers is created | To change settings, a new storage is needed |
| MEM-D11 | Check each instance's settings | A mismatch with the settings the user requests can be detected | The same check items and rules must be kept in all instances |
| MEM-D12 | The implementation protects concurrent calls | Users do not need to prepare separate mutual exclusion | The synchronization and the behavior under contention must be implemented and verified |
| MEM-D12 | The caller serializes | The synchronization in the implementation can be reduced | Users must also put the reads and retention of all sharing instances under the same control |

## 2. Check the storage's lifetime, sharing, and settings

- **MUST MEM-1**: Use only the memory of a single process. Saving to files, recovery after a restart, and sharing between processes are out of scope. When the storage's lifetime ends, the journal, head, snapshot, and settings are lost. A configuration outside the scope that can be detected is made a configuration error (SP-1). An explicit clear-all during use is not provided (MEM-D1).
- **MUST MEM-2**: Constructing a new storage yields an empty, independent store. Instances that explicitly share the same storage share all records, settings, and mutual exclusion. A storage is not shared merely because the names are the same. The sharing scope follows MEM-D2.
- **MUST MEM-3**: At construction, check settings such as the retention count. A retention count of 0, and a setting that requests an expiry style or change feed that is not provided, are configuration errors. The settings are placed in the storage, and the sharing instances are not given different settings. They are not changed during use. The handling of settings follows MEM-D8, MEM-D9, and MEM-D11. The classification of making an invalid setting value a configuration error follows chapter 4 and S-1 of the common contract.
- **MUST MEM-4**: The implementation protects concurrent calls of reads, writes, and retention to the same storage. Even if called simultaneously from multiple threads, intermediate states before the commit cannot be read. The protection of concurrent calls follows MEM-D12. No synchronization means of a particular language is specified.
  - Note for js (decided by the owner on 2026-10-06): In JavaScript, ordinary objects cannot be shared across threads (Workers). Therefore, js's storage is shared only within one thread. The js implementation satisfies MEM-4 by not letting intermediate states before the commit be read even when asynchronous calls overlap within the same thread. A storage that can be shared across threads is not built.

In the alternative of MEM-D11 that was not adopted, the retention count, retention style, the presence of a feed, and the grace period and retention period of the capabilities provided are checked at construction. If the storage's settings are missing or do not match, it is a configuration error, and they are not overwritten automatically.

## 3. Separate records by exact match on aid and by seq_nr

| Record | Values used for identification | Content |
|:--|:--|:--|
| Journal | aid string, seq_nr | Event envelope |
| Aggregate head | aid string | The latest seq_nr and the event envelope at that position |
| Latest snapshot | aid string | Snapshot envelope. May be absent |
| Snapshot history | aid string, seq_nr | The envelopes when a retention count is set |
| Settings | Storage | The retention count and the settings of the capabilities provided |

- **MUST MEM-5**: Assemble the aid string according to T-1, and compare by exact match. Treat aid and seq_nr as separate values. Do not use the hash value alone for identification, and do not select records of another aggregate by prefix match (SP-2). Check the type name, byte length, integers, and the range of time as in the common contract.
- **MUST MEM-6**: Hold metadata and payload separately. Make sure that changes by the user after writing, and changes to the retrieved result, do not change the stored values. No requirement of its own beyond T-6 is imposed on the payload type. A method such as holding the serialized payload and restoring it on retrieval can be used. The concrete storage format is left to each language's implementation.

## 4. Commit the check and the write within the same mutual exclusion

- **MUST MEM-7**: Finish the input checks and the preparation of the payload, which can fail. After that, perform the following processing within store-wide mutual exclusion. The commit method and the scope of mutual exclusion follow MEM-D3.

```text
排他制御を始める
  ヘッドを aid の完全一致で読む
  新規作成ならヘッドの不在を確認し、更新なら W-8 を照合する
  イベント封筒、ヘッド、任意のスナップショットと履歴の変更を準備する
  準備した変更をまとめて公開する（ここで確定）
  必要な保持処理を行う（失敗しても確定を取り消さない）
排他制御を解く
保持の失敗があれば別経路で知らせる
書き込みの成功を返す
```

"Publish together" means that no intermediate state is visible from other operations. On a failure during preparation, the records to be published are not changed. A method that returns a failure while leaving a partial change is not used. The aggregate head, the journal, and the snapshot follow the same commit (H-1).

The check is performed only against the head's seq_nr (H-2). An events-only append with seq_nr = 1 can also create a new aggregate (W-3). An update with no head is regarded as position 0 and rejected as a gap in W-8. A mismatch between snapshot.seq_nr and event.seq_nr is a contract violation of W-9. The error classification and messages follow chapter 4 of the common contract.

## 5. Return values at the same point in time for each read

- **MUST MEM-8**: The latest snapshot envelope and the head's seq_nr are read atomically within the same mutual exclusion. If there is no head, return "none". If there is a head, return the pair even if there is no envelope (R-1 to R-3, R-8). The reading of the pair follows MEM-D5.
- **MUST MEM-9**: An event read obtains all matching items within the same mutual exclusion. The start point is the moment when the mutual exclusion is acquired and the reference to the records begins. It includes all events committed at that point, and returns the envelopes whose seq_nr is at least the specified value in ascending order (R-4 to R-6). The read boundary follows MEM-D4.

Reads are strongly consistent, and do not need a re-read for eventual consistency. This consistency is based on the agreement of MEM-D4 and MEM-D5 (SP-1). Even if two public operations are called one after another, there is no guarantee that both operations read the same point in time.

In the alternative of MEM-D4 that was not adopted, the head h and the immutable records up to h are secured at the start. Even after the mutual exclusion is released, the items from the specified value up to h are returned without gaps. In the alternative of MEM-D5, each value is read from the committed state, but the pair is not atomic. A case where the envelope's seq_nr exceeds the head is also within the scope of R-8.

## 6. Separate the retention failure from the result of the append

- **MUST MEM-10**: If there is no retention count, keep only the current snapshot. If a count n is set, keep the newest n and remove the excess from the oldest (S-1, S-2). Retention is performed after the commit of the append, within the same mutual exclusion. Even for an events-only append, it cleans up history left behind last time. The timing of retention follows MEM-D6. The journal and the aggregate head are not removed by retention processing.
- **MUST MEM-11**: A retention failure does not change the success of the write. The failure is reported by a log after the mutual exclusion is released. In the retention processing after the next append, the current history is re-read and the leftovers are cleaned up (S-4). The notification and retry follow MEM-D7. A failure of the notification also does not change the result of the committed append.

In the alternative of MEM-D6 that was not adopted, the commit of the append is also separated from the success of retention. The excess is selected from the oldest, from the history at the time the mutual exclusion is re-acquired. A proposal to cancel the append because of a retention failure goes against S-4, so it is not included among the candidates.

- **MUST MEM-12**: The first version does not provide the expiry style of S-3 (MEM-D8). A setting that requests it is a configuration error of MEM-3.

In the alternative of MEM-D8 that was not adopted, the grace period is a positive integer number of seconds in the settings. The store's time at the moment of marking plus the grace period is stored as an expiry in seconds. occurred_at is not used as the expiry clock. The mark is applied only once, marked history is not counted in the count, is not selected again, and its expiry is not extended. Since expiry is checked and removed at each operation, there is no upper bound on the delay of deletion. The current snapshot is not made to expire. This is a record of the alternative, and is not an agreed rule.

## 7. The first version does not provide a change feed

- **MUST MEM-13**: The first version does not provide a change feed (MEM-D9). A setting that requests it is a configuration error of MEM-3.

### Candidates for when it is provided in the future

MEM-D10 was put on hold because MEM-D9 decided that the first version does not provide it. The following are candidates for when a change feed is provided in the future, and are not agreed rules. The properties of retention and the transport path, and the resynchronization procedure, will be confirmed when it is decided to provide it.

In the proposal to provide it, the head transitions of all committed appends are included in the same commit as the journal and head. Uncommitted transitions are not delivered (H-1, F-1). The user's notification processing is not made a condition of the commit.

- **Candidate MEM-14** (if provided in the future): Generate the transitions of the same aggregate in ascending order of seq_nr, and the transport path also preserves that order. Duplicates are possible. The subscriber discards duplicates and fills in missing numbers from the journal according to F-3 and F-4. Transitions are kept indefinitely during the storage's lifetime (the candidate of MEM-D10).
- **Candidate MEM-15** (if provided in the future): Tie the subscription position to the identity of the storage, and do not reuse a position of a different storage. For a first subscription or when the position is lost, obtain, within the mutual exclusion, the current seq_nr of all aggregates and the boundary of transitions up to that point. While keeping the transitions after the boundary, compare the subscriber's position with each aggregate. Fill in the shortfall from the journal, and then subscribe from after the boundary (F-5; a candidate accompanying the hold of MEM-D10).

Even in the candidate that adopts indefinite retention, the resynchronization procedure is not omitted. When the storage's lifetime ends, not only the transitions but also the journal is lost. There is no guarantee that old records can be supplemented from the new storage. Do not mix with the old position, and treat it as a new storage.

In the alternative of MEM-D10, the retention period is a positive integer number of seconds in the settings, and it is stated that the transport path may swap the order. Compare the oldest retained position with the subscription position, and if an exceeded period is detected, perform the full resynchronization of MEM-15. If the transitions after the boundary needed during resynchronization cannot be retained, end that attempt and start over from a new boundary. Aggregates that stopped after an update are also included in the full comparison. This alternative is also not an agreed rule.

## 8. Differences from the current memory implementations

On 2026-10-05, the following files of `origin/main` in each repository were checked with `git show`. Files in progress and the implementations of other storages are not covered by this comparison.

| Implementation | Version and file checked | Current state and the difference from this profile |
|:--|:--|:--|
| [rs](https://github.com/j5ik2o/event-store-adapter-rs/blob/535be125c0168425cd55a4ef377c0ac8432b84ff/lib/src/event_store_for_memory.rs) | `lib/src/event_store_for_memory.rs` at `535be125`. For the new-creation and retention paths, `lib/src/generic_event_store.rs` and `lib/src/event_store_backend.rs` of the same version were also checked | Has event envelopes and mutual exclusion, and cloned instances share the storage. The check depends on the version of the snapshot envelope, and there is no independent head. Rejects an events-only new creation. Imposes a copy requirement on the payload and the aggregate state. Has retention count and expiry settings, but the memory processing does not thin out history or process expiry |
| [js](https://github.com/j5ik2o/event-store-adapter-js/blob/377603d01c26b9ce6d9e89930cb2b65c0a53d214/packages/library/src/internal/memory-event-store.ts) | `packages/library/src/internal/memory-event-store.ts` and `packages/library/src/memory-event-store-input.ts` at `377603d0` | An independent storage that receives initial values. Stores domain events and aggregate state, and checks by the aggregate state's version. Does not return the pair of envelope and head, and cannot do an events-only new creation. Since references to events are shared, the immutability of stored values also needs review |
| [go](https://github.com/j5ik2o/event-store-adapter-go/blob/b0c598d13ba953e1ff5a8e52b1b29b45f4748797/pkg/event_store_on_memory.go) | `pkg/event_store_on_memory.go` at `b0c598d1` | Stores domain events and aggregate state, and checks by the aggregate state's version. Has no independent head or internal mutual exclusion. An events-only new creation stops, and duplicates of new creation are not checked. An update to a nonexistent aggregate also needs handling that returns it in the common contract's classification |

None of the three implementations has a change feed in the memory processing that was checked. MEM-D9 also agreed that the first version does not provide it. This does not mean that the current implementations conform to this profile or the common contract. Memory has no persisted old records, so what is checked at the implementation stage is the handling of the public operations and of the running storage, not a migration of the storage format.

## 9. Cases to look at in conformance verification

These are cases to be checked in an implementation of the agreed profile.

1. Independently constructed storages do not get mixed, and explicitly shared storages see the same records and settings.
2. When the same seq_nr is appended to the same aggregate concurrently, only one is committed. A gap in numbering is a contract violation.
3. A new aggregate can be created without a snapshot. An aggregate without an envelope also returns the head's seq_nr.
4. If a failure is injected before the commit, no change appears in any of the head, the journal, or the snapshot.
5. Even if reads and appends overlap, the retrieval of events is returned without gaps up to the start point. The envelope's seq_nr does not exceed the head of the atomically read pair.
6. Even if a retention failure is injected, the committed append is returned as a success. It is notified through another path, and is cleaned up from the oldest history in the next retention processing.
7. A retention count of 0 and a request for a capability that is not provided become configuration errors. The history of other aggregates is not deleted.
8. Even if the input of a write or the retrieved result is changed, the stored envelope and payload do not change.

If a change feed is provided in the future, a candidate for verification is that appends made even during resynchronization do not cause transitions after the boundary to be missing. If finite retention is adopted, confirm that aggregates that stopped after an update are also filled in by resynchronization. These are not included in the conformance verification of the first version.

## 10. Agreement status and items to confirm before implementation

On 2026-10-05, MEM-D1 to MEM-D9, MEM-D11, and MEM-D12 were agreed by adopting the proposals in the draft. The first version does not provide the expiry style or the change feed. MEM-D10 is on hold because no change feed is provided, and will be decided when it is decided to provide it. MEM-14 and MEM-15 in chapter 7 are kept as candidates for that time.

The implementation in each language's adapter, and the conformance verification by the cases in chapter 9, remain. This agreement does not declare the conformance of the current implementations. The agreed rules of the common contract have not been changed.

The following two options are the way forward.

1. **Recommended**: Proceed with the implementation and conformance verification in each language in line with the agreed content of the first version, and keep MEM-D10 on hold.
2. If considering a version that provides a change feed, decide the policy to provide it first, and then confirm MEM-D10 and the candidates in chapter 7.
