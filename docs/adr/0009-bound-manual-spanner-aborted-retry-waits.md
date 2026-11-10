---
status: proposed
---

# Proposal for bounded manual Spanner ABORTED retry waits

This is an unaccepted design draft for [#137](https://github.com/j5ik2o/event-store-adapter/issues/137), following the [PM decision](https://github.com/j5ik2o/event-store-adapter/issues/113#issuecomment-6773097308). It proposes implementation requirements for [Java #816](https://github.com/j5ik2o/event-store-adapter-java/issues/816) and [JS #1126](https://github.com/j5ik2o/event-store-adapter-js/issues/1126). Implementation, contract acceptance, merge, and release are separate work. The [Japanese companion](0009-bound-manual-spanner-aborted-retry-waits.ja.md) is supplementary. English is authoritative.

## D1. Scope and observed behavior

The goal is to reduce the risk that contention consumes the retry count immediately. This risk is an inference from the manual retry loops. No production improvement, success-rate change, or starvation has been measured.

[SPN-7](../spec/storage/spanner.md) remains accepted and unchanged. It specifies envelope reuse, seq_nr reuse, head checks, side effects, and exhaustion errors. It does not specify waits. This draft adds no requirement to Rust, Go, Kotlin, or Scala without their own audit and acceptance. Conformance data 1.4.0 is unchanged.

The following source snapshots were read directly and reacquired for this proposal.

| Snapshot | Entry and dependency |
| --- | --- |
| [Java main d0237ddcd76149fae8296fedea1f4b1f1d281ae5](https://github.com/j5ik2o/event-store-adapter-java/blob/d0237ddcd76149fae8296fedea1f4b1f1d281ae5/spanner/src/main/java/com/github/j5ik2o/event/store/adapter/java/spanner/SpannerTransactions.java) | `SpannerTransactions.runReadWrite` creates a `TransactionManager` for each attempt. Declared SDK is 6.127.0. |
| [Java published 5.2.0 sources](https://repo.maven.apache.org/maven2/io/github/j5ik2o/event-store-adapter-java-spanner/5.2.0/event-store-adapter-java-spanner-5.2.0-sources.jar) | The transaction entry is byte-identical to the fixed main entry. [Published POM](https://repo.maven.apache.org/maven2/io/github/j5ik2o/event-store-adapter-java-spanner/5.2.0/event-store-adapter-java-spanner-5.2.0.pom) declares SDK 6.127.0. Tag commit is 0ec46b15ba44b4dfb45b4261dfafd6af6d79efbc. |
| [JS main 4f4f5b800aea89b7e880a77cc90d76929dc889bc](https://github.com/j5ik2o/event-store-adapter-js/blob/4f4f5b800aea89b7e880a77cc90d76929dc889bc/packages/library/src/internal/spanner-read-write-transaction.ts) | `runSpannerReadWriteTransaction` calls `getTransaction` each time. Lockfile SDK is 9.1.0. Optional peer range is `^8.7.1 || ^9.0.0`, so users need not resolve 9.1.0. |

These entries do not invoke the SDK automatic transaction runners. They have no intentional ABORTED backoff. RPC retries, session acquisition, rollback, and close can still take time. This draft does not describe the proposed waits as implemented or released.

## D2. Attempt state and count

Keep the existing validated `transactionRetryLimit` L, excluding the initial attempt. Keep its public API and existing validation. The private state is `retriesStarted`, initially 0, and the last ABORTED failure. A delay decision has exactly three forms, `fallback`, `server`, or `stop`. A scheduled wait is a positive integer number of milliseconds. It is not a transaction attempt.

After failure and cleanup, first preserve the existing error classification. Only ABORTED from a retryable transaction attempt can reach the wait decision. If `retriesStarted >= L`, return the existing exhausted storage error with the failure as cause, without decoding hints, sampling randomness, or scheduling a wait. Otherwise set the next retry ordinal `k = retriesStarted + 1`, decide the delay, wait, then start the retry and increment `retriesStarted`. A stop decision never starts another attempt.

Measure the chosen wait from after cleanup with a monotonic clock. If a sleeper or timer resolves before d milliseconds have elapsed, wait for the rounded-up positive remainder before starting another attempt. Keep each timer argument within 1..60000ms. This prevents timer rounding from shortening a server hint. It does not impose a deadline on scheduler delays.

| L | Maximum total attempts | Maximum waits | All attempts abort |
| --- | --- | --- | --- |
| 0 | 1 | 0 | First ABORTED returns exhaustion. |
| 1 | 2 | 1 | Wait after attempt 1 only. Attempt 2 returns exhaustion. |
| 5 | 6 | 5 | Wait after attempts 1 through 5 only. Attempt 6 returns exhaustion. |

Success on attempt 1 has zero waits. If L=5 and attempt 3 succeeds, there are two waits and three attempts. No wait follows success.

## D3. Server hint decoding and safety

A valid server `google.rpc.RetryInfo.retry_delay` takes precedence over fallback. Do not add fallback jitter to it and do not cap it downward. Missing hint, missing `retry_delay`, decode failure, or an invalid duration uses fallback. Parsing failure must not replace the original ABORTED error.

Use the structured duration, not error-message text. Accept integer seconds `s` in 0..315576000000 and integer nanos `n` in 0..999999999. Both fields must be nonnegative. Zero is valid. Omitted scalar fields in a present protobuf duration mean zero. A missing duration message is different from a present empty duration. Reject negative, fractional, non-finite, non-integer, wrong-type, and out-of-protobuf-range components. A negative nanos field with positive seconds is invalid, not a request to normalize. These restrictions select nonnegative delays from the [protobuf Duration definition](https://protobuf.dev/reference/protobuf/google.protobuf/#duration).

For Java SDK 6.127.0, first inspect the public `SpannerException.getErrorDetails().getRetryInfo()`. If it yields no valid duration, inspect `google.rpc.retryinfo-bin` trailers through public gRPC metadata APIs on the exception and its cause chain. Visit each throwable at most once by identity. For repeated trailer values, inspect in wire order. The first valid duration in this precedence order wins, including a valid value above the safety ceiling. Do not skip a long valid hint to choose a shorter one. No reflection or SDK-private method is needed. SDK `getRetryDelayInMillis()` uses `Durations.toMillis`, which loses sub-millisecond precision, so do not use that scalar as the source of truth. Verify both structured-status and raw-trailer paths during implementation.

For JS, inspect `cause.metadata.get("google.rpc.retryinfo-bin")` in returned order. Decode binary entries with an adapter-owned private protobuf decoder for RetryInfo and Duration, generated from the descriptors in the fixed SDK's `build/protos/status.json`. Preserve the upstream license. Use a directly declared protobuf runtime if the generated decoder requires one. Do not resolve a transitive runtime by accident. The fixed SDK's `getRetryInfo()` is private and RetryInfo is absent from its spanner-api exports, so importing that helper or assuming a public RetryInfo export is not an implementation path. Use the first valid duration. Do not use the automatic runner's private `getNextDelay`. Accept protobuf seconds as an exact safe integer number, canonical decimal integer string, or the decoder's Long representation converted losslessly to an integer. Reject coercions of arbitrary objects. The valid protobuf seconds range fits within JS safe integers. Validate before multiplication and use integer arithmetic such as BigInt. Check metadata access and decoding against supported peer 8 and 9, including 8.7.1 and locked 9.1.0, before claiming compatibility.

For an accepted duration, compute `h = 1000*s + ceil(n/1000000)` with checked or exact integer arithmetic. If `h <= 60000`, schedule `d = max(1,h)` milliseconds. If `h > 60000`, stop immediately after cleanup with a storage error, retaining the ABORTED cause and identifying that the server delay exceeds the supported wait. Do not schedule a timer or retry. This is a new proposed stop condition within the existing storage error category, not exhaustion or an unknown commit outcome.

The 1ms scheduling floor prevents a tight loop for a valid zero hint. The 60000ms per-wait ceiling bounds requested waits without retrying earlier than the server asks. Both are design choices, not measured optima or SDK defaults. A long hint can therefore stop before L retries are used. Unbounded waits would preserve every hint but could block Java callers for hours. Clamping and retrying at 60 seconds would violate a longer hint. The stop choice trades availability for bounded scheduled waiting.

| Input hint | Decision |
| --- | --- |
| Absent, undecodable bytes, or missing duration | Fallback. |
| Present `{seconds:0,nanos:0}` | Server, 1ms. |
| `{seconds:0,nanos:1}` | Server, 1ms. |
| `{seconds:0,nanos:1000001}` | Server, 2ms. |
| `{seconds:1,nanos:1}` | Server, 1001ms. |
| `{seconds:60,nanos:0}` | Server, 60000ms. |
| `{seconds:60,nanos:1}` | Stop, no timer or retry. |
| `{seconds:315576000000,nanos:999999999}` | Valid but too long. Stop before converting to timer arguments. |
| `s=-1`, `n=-1`, `n=1000000000`, `s=315576000001`, NaN, Infinity, or fractional seconds | Invalid, fallback. |
| First valid entry 61s, second valid entry 10ms | Stop on 61s. |

## D4. Fallback and elapsed time

For next retry ordinal k starting at 1, use equal jitter in integer milliseconds. Let `C(k) = min(1000, 50 * 2^(k-1))`, `a = ceil(C/2)`, and `d = a + floor(u * (C-a+1))`, with an independent uniform `u` in [0,1). For k>=6, set C=1000 directly before exponentiation, so a large configured L cannot overflow. Randomness need not be cryptographic. Provide a private injectable random source and sleeper for deterministic verification, without a public configuration API.

| k | C in ms | Inclusive d range in ms |
| --- | --- | --- |
| 1 | 50 | 25..50 |
| 2 | 100 | 50..100 |
| 3 | 200 | 100..200 |
| 4 | 400 | 200..400 |
| 5 | 800 | 400..800 |
| 6 and later | 1000 | 500..1000 |

With L=5 and no hints, requested waits total 775..1550ms if all retry opportunities are used. With accepted server hints, at most `L * 60000` ms is requested, calculated without overflow for diagnostics. This is not a wall-clock deadline. RPCs, hooks, rollback, cleanup, scheduler delays, and a blocked event loop can add time. This proposal introduces no total operation deadline and never resets an SDK RPC deadline. The caller's existing client settings still govern SDK operations.

The 50ms initial cap gives a positive pause while limiting added latency for a transient abort. Doubling spreads later retries over a wider interval. The 1000ms cap limits fallback latency for high retry limits. Equal jitter retains a nonzero lower bound. These are policy judgments to review, not benchmark results or copies of either SDK's defaults.

## D5. Errors, ordering, and side effects

| Outcome | Wait and retry behavior |
| --- | --- |
| Eligible pre-commit ABORTED | Cleanup, limit check, delay decision, wait, next transaction. |
| Domain rejection or Java `EventStoreException` | Existing domain error, no wait or retry. |
| Non-ABORTED transaction failure | Existing storage error, no wait or retry. |
| ABORTED beyond L | Existing exhaustion storage error, no extra wait. |
| JS `getTransaction` failure, including code 10 | Existing transaction-start storage error, no wait or retry. |
| `afterCommit` failure, including an ABORTED-shaped failure | Existing unknown-outcome storage error, no wait or retry. |

Keep Java classification as ABORTED error code or `AbortedException`, after its domain-error catch. Keep JS classification as numeric code 10, after its committed and domain-rejection checks. This proposal does not expand retryable errors to INTERNAL, CANCELLED, or unknown outcomes.

For Java, keep the try-with-resources boundary. Each attempt runs `begin`, body, `beforeCommit`, and commit. Manager close, including any SDK rollback and session release, finishes before a wait or another manager is created. Retain Java's existing exception suppression and cleanup-error precedence. Do not reclassify an unrelated cleanup error as ABORTED. On success, close precedes `afterCommit`, as today.

For JS, an aborted attempt awaits best-effort rollback and executes `end()` in `finally` before the wait. Move the wait outside that `try/catch/finally`. Sleeping inside the catch would retain the transaction until the timer finishes. Keep the original failure if rollback fails. Keep existing behavior if `end()` itself throws. On success, `afterCommit` still runs after commit and before `end()`. Do not move it into the retry loop's failure path.

Reuse the exact input envelopes and seq_nr. Re-run the body and `beforeCommit` on each retry, including a fresh head check. Do not number events or send external notifications within them. If another append has advanced the head to at least the input seq_nr, return optimistic lock on re-execution. Run `afterCommit` and existing success-only effects once after confirmed commit. Existing retention failure reporting remains separate. Waiting changes none of these SPN-7 obligations.

## D6. Interruption and cancellation

Java checks `Thread.currentThread().isInterrupted()` before the initial attempt, before every retry attempt, before sleeping, and after sleeping. Use an interruptible sleep. If sleep throws `InterruptedException`, restore the interrupt flag and stop. If a check sees the flag, leave it set and stop. Return `StorageException` identifying interrupted transaction retry. Use the `InterruptedException` as cause when available and retain the last ABORTED as suppressed evidence. For a flag-only check, create an `InterruptedException` cause and retain the last ABORTED if present. No retry or hook runs after detection. If ABORTED is already exhausted, its exhaustion result takes precedence and no wait check is needed.

These checks do not cancel an active SDK call or roll back a successful commit. An interrupt during an attempt is handled by the SDK until control returns. Once commit succeeds, finish the existing success path, including `afterCommit`, even if a flag was set during that attempt. A race can set the flag immediately after a check. Do not promise instantaneous cancellation.

Java sleep blocks the calling thread. The fixed implementation of the asynchronous facade completes its action synchronously before returning a Future. `AsyncEventStore`'s returned `Future.cancel` has no guarantee of stopping this retry loop. This proposal does not add an executor or change that API.

JS awaits a referenced timer Promise. The event loop can run other work, but the operation remains pending and the timer can keep the process alive. Do not call `unref()`. There is no new AbortSignal API. Abandoning the Promise or racing it against a timeout does not stop retries. Existing SDK cancellation errors remain non-ABORTED failures. If an internal wait fails, return a storage error and do not retry. No cancellation or total-duration guarantee is added.

## D7. Alternatives and priority continuity

| Option | Recommendation and cost |
| --- | --- |
| Immediate retry | Reject. It retains the risk of consuming L without an intentional pause. |
| Fixed delay | Reject. It gives callers the same schedule. Jitter varies the schedule, though production benefit is unmeasured. |
| Full jitter from zero | Reject. It permits zero or near-zero repeated delays. |
| Equal jitter plus valid server hints and a long-hint stop | Adopt as this proposal. Adds latency and a storage-error stop before exhaustion. |
| Replace with SDK automatic runners | Defer. Require proof of one shared count, classification, and time budget before adoption. Do not nest the current loop around a runner. |
| Preserve prior transaction ID and session priority | Separate verification before adoption. Keep current fresh-manager and fresh-getTransaction lifecycle for this waiting change. |

The [fixed Java SDK 6.127.0 source](https://repo.maven.apache.org/maven2/com/google/cloud/google-cloud-spanner/6.127.0/google-cloud-spanner-6.127.0-sources.jar) says `resetForRetry()` retains the session and increases lock priority. `begin(AbortedException)` carries prior transaction information for multiplexed sessions. The [fixed Node SDK 9.1.0 package](https://registry.npmjs.org/@google-cloud/spanner/-/spanner-9.1.0.tgz) runner retains a session and forwards `multiplexedSessionPreviousTransactionId`. The current application entries do neither. General [Google transaction guidance](https://cloud.google.com/spanner/docs/transactions) also discusses retry priority. That guidance does not prove starvation in these applications.

Adopting continuity changes ownership and cleanup while sleeping. Verify normal and multiplexed sessions, ABORTED from reads and commit, released-session validity, prior ID propagation, and public peer APIs with a local fake backend before deciding a separate implementation. Do not copy Node private fields into the adapter. Waiting is not evidence that priority continuity has been solved.

The unused Java runner has a different time and count policy in `SpannerRetryHelper`, and the Node runner also retries selected INTERNAL errors and defaults to a one-hour loop budget. General [timeout guidance](https://cloud.google.com/spanner/docs/custom-timeout-and-retry) cannot establish equivalence with these manual paths. Runner replacement stays out until count, error, hook, cleanup, and time semantics have an executable equivalence test.

## D8. Implementation acceptance and evidence limits

Both implementation issues should use fake transactions, an injected sleeper or virtual timer, and controlled randomness. Required observations are the following.

| Check | Required observation |
| --- | --- |
| L=0,1,5, all ABORTED and later success | Exact attempt and wait counts from D2, no final wait. |
| Every D3 boundary and malformed binary metadata | Exact decision, ceiling before timer conversion, original cause retained. |
| Multiple hints and structured Java status versus trailers | D3 precedence, no short fallback for a long valid hint, missing versus zero distinguished. |
| k=1..6 and very large k, u=0 and u just below 1 | D4 inclusive endpoints, cap without exponent overflow, positive integer timer arguments. |
| Before timer resolution or after an early resolution | No next transaction or body call. After the monotonic duration elapses, exactly one next attempt. |
| Errors and hooks from D5 | Classification preserved, head rechecked, envelope and seq_nr identical, no duplicate success effect. |
| Cleanup failure and rollback failure | Existing precedence preserved, no transaction held during wait. |
| Java interrupted before initial call, before wait, during sleep, after sleep | StorageException, interrupt flag set, no next attempt, ABORTED retained when present. |
| Java interrupt during successful commit | Finish success path, no replay. Future cancellation is not asserted as retry cancellation. |
| JS abandoned Promise and external timeout race | No claim that either cancels a scheduled retry. |
| JS peer compatibility | Real RetryInfo encoding and decoding with SDK 8.7.1 and 9.1.0, including seconds representations and unknown protobuf fields. |

This design pass reacquired the fixed application entries, Java published source, and both fixed SDK packages. It matched their relevant bytes against inherited originals and verified all 55 inherited major-manifest hashes. It read the actual manual lifecycle and SDK hint paths. Pure local boundary calculations verify the tables, not adapter behavior. Earlier stub and virtual-timer experiments are inherited evidence only and were not rerun here.

No adapter implementation, real SDK backend integration, wall-clock retry benchmark, cloud operation, or full application suite was run for this document change. The JS peer matrix and Java encoded metadata integration remain implementation gates. PM owns independent review and acceptance of the proposed constants, long-hint stop, and interruption behavior. No independent reviewer ran in this design task.
