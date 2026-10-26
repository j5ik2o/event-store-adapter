---
status: accepted
---

<a id="bigtable-のスナップショット履歴を対応するイベントと同じ行に置く"></a>
# Place Bigtable's snapshot history in the same row as the corresponding event

Bigtable's snapshot history is stored in the same journal row as the corresponding event (2026-10-04, agreed with the owner, BT-D2).

Only the payload of old history is removed. Events are not deleted. A deletion marker is also kept. Even if a delayed write-out arrives later, if the event's cell already exists, the condition for initial creation cannot be satisfied, so the deleted history cannot be revived.

The head holds the tail event and the current snapshot, and does not hold past history. With the approach of writing out the confirmed tail and then advancing the head (ADR-0005), the necessary history is also saved atomically in the same row. This prevents the problem in which only the copy of the history fails while the head's only copy is replaced.

<a id="検討した代案"></a>
## Considered Options

- **Place fixed slots for the latest n entries in the head**: The head and the history can be updated at once, but the product of the retained count and the snapshot size must fit within the row size limit. We do not adopt the idea of adding a row-size-derived limit to the retained count.
- **Copy to a separate row dedicated to history**: A range of history can be read efficiently, but recovery from a failed copy across rows and prevention of revival after deletion need additional design. We do not adopt it for the initial layout.

<a id="影響"></a>
## Consequences

- The size of the head is not proportional to the number n of history entries retained.
- When tidying history, the history markers are searched for in the aggregate's journal range. The amount read is affected by the length of the journal. This cost is also included in the agreement.
- Deleted-history markers are kept together with the events that are not deleted. The payload of the history is removed.
- The concrete key and envelope formats, table initialization, cluster configuration, expiration method, change feed, and envelope limit are confirmed in the individual decisions of the [Bigtable profile](../spec/storage/bigtable.md).
