# event-store-adapter

A glossary of the concepts shared by the event-store-adapter implementations in each language. The specification itself is in `docs/spec/`, and design decisions are in `docs/adr/`.

## Language

<a id="書き込みと記録"></a>
### Writing and recording

**Journal**:
A record that only appends each aggregate's events in seq_nr order. It is the single source of truth for aggregate state, and replay is performed from it.
_Avoid_: event log (イベントログ), event table (イベントテーブル)

**Event envelope**:
The container that carries one event. It keeps the metadata (aggregate_id, seq_nr, occurred_at, manifest) and the payload separately.
_Avoid_: event (when referring to the whole envelope; イベント), event record (イベントレコード)

**Payload**:
The domain content that the envelope carries. The library does not interpret it, and no metadata is embedded in it.
_Avoid_: event body (イベント本体), data (データ)

**manifest**:
A free-form string that the user attaches to identify the type or schema version of a payload or of the aggregate state in a snapshot. The library does not interpret the value.
_Avoid_: type name (タイプ名), event kind (イベント種別)

**seq_nr**:
A serial number, starting at 1, assigned to events within an aggregate. The domain side assigns it, not the store. It is also used for the optimistic-locking check.
_Avoid_: sequence number (シーケンス番号), offset (オフセット), version (as a number used for the check; version（照合用の番号として）)

<a id="集約の現在位置"></a>
### Current position of an aggregate

**Confirmation** (確定):
An append becoming established as a record of the aggregate. Only confirmed appends appear in the aggregate head, in event reads, and in the change feed; an append that was not confirmed appears nowhere.
_Avoid_: commit (コミット; easily confused with the storage transaction's meaning), persistence (永続化)

**Aggregate head**:
The record of the latest write position, of which there is exactly one per aggregate. It is created by the first append and does not exist before that. It holds the latest seq_nr and the event envelope confirmed at that seq_nr, and it advances at the same time as an append is confirmed. It is the check point for optimistic locking and also the unit of the change feed.
_Avoid_: current snapshot (current スナップショット), header (ヘッダ), leading item (先頭項目)

**Head transition**:
The pair of one change in which the aggregate head's seq_nr advances from n−1 to n, and the event envelope appended at that time.
_Avoid_: update event (更新イベント), change record (変更レコード)

<a id="状態の再構築"></a>
### Rebuilding state

**Snapshot**:
A cache that stores the aggregate state at a certain seq_nr. It may be older than the head, and it may be absent. It is not used for the optimistic-locking check.
_Avoid_: aggregate state (when referring to the stored object; 集約状態（保存物を指す場合）)

**Snapshot envelope**:
The container that carries one snapshot. It holds the aggregate state, the seq_nr it already reflects, and the manifest, and the same type is used for writing and reading.
_Avoid_: AggregateResult

**Replay**:
Obtaining the latest state by applying, in order, the events after the snapshot's seq_nr to the aggregate state in the snapshot.
_Avoid_: playback (再生), restoration (復元)

<a id="外部への配信"></a>
### Delivery to the outside

**Change feed**:
The sequence of head transitions arranged in seq_nr order for each aggregate. Downstream consumers such as read-model updates subscribe to this, not to the journal.
_Avoid_: CDC stream (CDC ストリーム), event stream (as a general term; イベントストリーム（汎用語として）)

<a id="仕様の構成"></a>
### Structure of the specification

**Core contract**:
The semantics, independent of the storage backend, that every implementation must satisfy.
_Avoid_: core API (コア API), interface definition (インターフェイス定義)

**Storage profile**:
The specification that defines how the core contract is realized on a particular storage backend (such as DynamoDB). It includes the physical layout, key derivation, and storage format.
_Avoid_: backend implementation (バックエンド実装), adapter specification (アダプタ仕様)
