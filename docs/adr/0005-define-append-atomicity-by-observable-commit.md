---
status: accepted
---

<a id="追記の原子性を物理的な書き方ではなく観測できる確定で定める"></a>
# Define append atomicity by observable confirmation, not by the physical way of writing

The core contract's H-1 originally prescribed a physical way of writing: "do the append to the journal and the update of the aggregate head in one atomic write." DynamoDB, Spanner, and SQLite can satisfy this with transactions. However, Bigtable can write atomically only within a single row, so the only way to satisfy it is to put the whole journal of an aggregate into one row, and the row would grow without bound (limit 256MB). So we revised H-1 into a property observable from the outside: "the confirmation of an append is decided by one atomic operation; a confirmed append appears in all of the head, event reads, and the change feed, and an append that was not confirmed appears in none of them." The confirmation mechanism is defined by the storage profile (agreed with the owner on 2026-10-03, P-28).

## Considered Options

- **Keep the current wording and put the aggregate in one row in Bigtable**: The core contract would not need to change. However, a long-lived aggregate will eventually hit the row limit, and large rows also worsen compression and read latency. We do not adopt it.
- **Exclude Bigtable from the scope**: rs has a Bigtable implementation, and it would cut off its users. We do not adopt it.

## Consequences

- The Bigtable profile can take the approach of making the conditional update of the head row (CheckAndMutateRow) the confirmation point, and writing out the journal row idempotently after confirmation. Even if the write-out fails, the next writer or reader fills it in from the event envelope held by the head. For this reason, the head holding the confirmed event envelope was made mandatory as H-4.
- The snapshot also follows confirmation. In Bigtable, if it is placed in the same row as the head, it can be written atomically at the same time as confirmation.
- DynamoDB, Spanner, and SQLite can keep writing in one transaction as before, and no change is needed.
- "Advances in the same atomic write as the append" in ADR-0002 is to be read in the sense of confirmation in this ADR.
