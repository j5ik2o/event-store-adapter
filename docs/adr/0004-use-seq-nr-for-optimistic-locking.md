---
status: accepted
---

<a id="version-を廃止し楽観ロックは-seq_nr-で照合する"></a>
# Abolish version and check the optimistic lock against seq_nr

rs v3 used version, which increases by 1 on every write, for the optimistic lock, and the write operation accepted `expected_version`. The core contract decided to enforce the continuity of seq_nr at write time (W-8) and to append only one event per write (H-3). With these two together, version and seq_nr always match. Version became redundant.

So we abolish version, and the optimistic lock is checked against the aggregate head's seq_nr. An event with seq_nr n can be appended only when the head's seq_nr is n−1. Because the expected value for the check is determined from the event's seq_nr, the write operation does not take an `expectedVersion` argument. Reading the latest snapshot returns the head's latest seq_nr instead of version. pekko-persistence also checks against sequenceNr alone in the same way.

## Considered Options

- **Keep version**: The rs v3 API could be kept as it is. There was also a view that it would be needed as a "write count" when multiple events are appended together in the future. However, even when appending together, the check can be done with "head's seq_nr == first event's seq_nr − 1," so version is not needed. We would keep checking a value that always matches seq_nr, so we do not adopt it.

## Consequences

- rs v3's `expected_version` argument is removed as a breaking change. The "explicit expected value" that ADR-0001 listed as a strength of rs v3 changes into the form "make the write position explicit by the event's seq_nr."
- By comparing the head's seq_nr returned on read with the last seq_nr obtained by replay, the caller can detect the lag of an eventually consistent read (core contract R-7).
- If seq_nr is exposed as is as the token for optimistic locking in an external API, the number of events of the aggregate becomes known. This was the same with version. If it needs to be hidden, the application should use something like an HMAC with a secret key to turn it into an opaque token. Because seq_nr is a small integer, a hash without a key can be brute-forced back to the original value.
