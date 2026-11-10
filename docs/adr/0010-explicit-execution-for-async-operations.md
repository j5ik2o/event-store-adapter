---
status: accepted
---

# Explicit execution for Java asynchronous operations

## D0. Adopted implementation target and decision boundary

The goal of [#139](https://github.com/j5ik2o/event-store-adapter/issues/139) is to protect Java SQLite, Spanner, and Bigtable callers from operation I/O on their calling thread while preserving existing factories and storage order. This English ADR is authoritative. The [Japanese companion](0010-explicit-execution-for-async-operations.ja.md) is explanatory.

PM [adopted candidate B as the implementation target](https://github.com/j5ik2o/event-store-adapter/issues/139#issuecomment-6776831524) after the [independent PASS+NOTES on draft head 51bf027](https://github.com/j5ik2o/event-store-adapter/pull/144#issuecomment-6776410540). The adopted target is an explicitly created, bounded, single-worker resource with additional factories. Accepted status records that design decision only. It does not mean the APIs are implemented or published, D8 runtime gates have passed, CI is green, or release is approved. The adoption update still requires independent confirmation at its latest head and merge before implementation starts. This ADR changes neither the common contract nor conformance 1.4.0.

The baseline is [common main ea561f8](https://github.com/j5ik2o/event-store-adapter/tree/ea561f8d2a1d008a9196e8b189268741fbc0c9ff). [ADR-0009](0009-bound-manual-spanner-aborted-retry-waits.md) is accepted waiting design, not evidence that Java main implements it. Java #814/#817, JS #1127, Kotlin #906, Scala #918, release settings, workflows, versions, and existing ADRs remain outside this change.

## D1. Observed behavior and fixed sources

The original draft pass reacquired [#114's investigation record](https://github.com/j5ik2o/event-store-adapter/issues/114#issuecomment-6773418204), the current #139 body and comments, the following source snapshots, and public Maven artifacts. The earlier report was a starting point, not a substitute for the original draft checks.

| Fixed target | Source facts checked in the original draft pass |
| --- | --- |
| [Java main d0237dd](https://github.com/j5ik2o/event-store-adapter-java/tree/d0237ddcd76149fae8296fedea1f4b1f1d281ae5) | Each backend's `createAsync` documents caller-thread execution. Its `Async.complete` calls `action.get()` before returning the Future. |
| [Published Java 5.2.0 SQLite sources](https://repo.maven.apache.org/maven2/io/github/j5ik2o/event-store-adapter-java-sqlite/5.2.0/event-store-adapter-java-sqlite-5.2.0-sources.jar), [Spanner sources](https://repo.maven.apache.org/maven2/io/github/j5ik2o/event-store-adapter-java-spanner/5.2.0/event-store-adapter-java-spanner-5.2.0-sources.jar), [Bigtable sources](https://repo.maven.apache.org/maven2/io/github/j5ik2o/event-store-adapter-java-bigtable/5.2.0/event-store-adapter-java-bigtable-5.2.0-sources.jar) | The three `*EventStore.java` files match fixed main byte for byte. Their public binaries were used in D8. |
| [Published Java 5.1.0 monolithic sources](https://repo.maven.apache.org/maven2/io/github/j5ik2o/event-store-adapter-java/5.1.0/event-store-adapter-java-5.1.0-sources.jar) | The same three files match 5.2.0 after whitespace removal. This does not establish binary or full dependency equivalence. |
| [Kotlin main ab3e877](https://github.com/j5ik2o/event-store-adapter-kotlin/tree/ab3e877f55abab7a57383af50a749cf2a4591dec) | `build.gradle.kts` uses monolithic Java 5.1.0. `JavaAsyncEventStoreAdapter` invokes Java before `.await()` in all four methods. |
| [Kotlin #906 head c7be242](https://github.com/j5ik2o/event-store-adapter-kotlin/tree/c7be2421c88f5aff2247abacb86fd3e03168eab8) | Unmerged module split uses Java 5.2.0 drivers. Moving the adapter into core does not add dispatch before Java invocation. |
| [Scala main dc358b4](https://github.com/j5ik2o/event-store-adapter-scala/tree/dc358b460123e6051375a7ab8ab743824c8011cb) | `project/Dependencies.scala` uses Java 5.1.0. `JavaInterop.future` takes a by-name call but evaluates it in `Future.fromTry(attempt(call))`. |
| [Scala #918 head 2a70891](https://github.com/j5ik2o/event-store-adapter-scala/tree/2a708919980550a14330b59e8e796ef25ede8d99) | Unmerged split uses Java 5.2.0 drivers and retains the same evaluation boundary. |

The public POMs separate the dependency sets: Java 5.1.0 uses sqlite-jdbc 3.53.4.0, Spanner 6.124.0, and Bigtable 2.85.0. Java 5.2.0 uses 3.54.1.0, 6.127.0, and 2.88.0 respectively. The matching SDK sources were reacquired. Spanner `ReadContext` permits response waiting at `ResultSet.next()` even when `executeQuery` returns earlier. The adapter consumes that result set. Bigtable `readRow` and `checkAndMutateRow` wait through synchronous SDK helpers, and `BigtableRows.readRange` consumes the returned stream. JDBC calls and result traversal occur inside SQLite operations. SDK transport threads do not make these adapter entry points return early.

Existing factories validate storage and configuration synchronously. Operations run validation, serialization, SQL or SDK calls, deserialization, hooks, and applicable retention before returning. `Exception`, including `RuntimeException`, becomes a failed Future in `Async.complete`. `Error` can escape synchronously. Storage open and initialize are separate synchronous operations. Preserve these facts for existing APIs, including completed-Future behavior and thread affinity. Do not silently submit an existing factory to `commonPool` or replace a wrapper's execution policy.

Primary SDK references are the [Spanner 6.127.0 sources](https://repo.maven.apache.org/maven2/com/google/cloud/google-cloud-spanner/6.127.0/google-cloud-spanner-6.127.0-sources.jar) and [Bigtable 2.88.0 sources](https://repo.maven.apache.org/maven2/com/google/cloud/google-cloud-bigtable/2.88.0/google-cloud-bigtable-2.88.0-sources.jar).

## D2. Adopted B API and rejected A comparison

Candidate A was rejected because an arbitrary Executor cannot guarantee offload under inline execution or saturation, or define the required ownership contract. Retain its overloads for comparison only:

```java
// Candidate A, not an existing API.
public static <P, A> AsyncEventStore<P, A> createAsync(
	SqliteStorage storage, EventStoreConfig<P, A> config, Executor executor);
public static <P, A> AsyncEventStore<P, A> createAsync(
	SpannerStorage storage, EventStoreConfig<P, A> config, Executor executor);
public static <P, A> AsyncEventStore<P, A> createAsync(
	BigtableStorage storage, EventStoreConfig<P, A> config, Executor executor);
```

Candidate B is the adopted implementation target. Its fixed names and signatures are below. `BlockingExecution` belongs in Java core without SDK dependencies. Each backend supplies its own `createOffloaded` factory. The code block comments retain the original proposal wording for traceability. None of these additions is implemented or published by this ADR:

```java
// Candidate B, proposed names and signatures only.
public final class BlockingExecution implements AutoCloseable {
	public static BlockingExecution singleWorker(int queueCapacity);
	public void close();
	public CompletionStage<Void> drained();
}
public static <P, A> AsyncEventStore<P, A> createOffloaded(
	SqliteStorage storage, EventStoreConfig<P, A> config, BlockingExecution execution);
public static <P, A> AsyncEventStore<P, A> createOffloaded(
	SpannerStorage storage, EventStoreConfig<P, A> config, BlockingExecution execution);
public static <P, A> AsyncEventStore<P, A> createOffloaded(
	BigtableStorage storage, EventStoreConfig<P, A> config, BlockingExecution execution);
```

In each candidate, the four operation signatures remain those of `AsyncEventStore`: `persistEvent(EventEnvelope<P>)`, `persistEventAndSnapshot(EventEnvelope<P>, SnapshotEnvelope<A>)`, `getLatestSnapshotById(AggregateId)`, and `getEventsByIdSinceSeqNr(AggregateId, long)`. Their respective results remain `CompletableFuture<Void>`, `CompletableFuture<Void>`, `CompletableFuture<Optional<SnapshotReadResult<A>>>`, and `CompletableFuture<List<EventEnvelope<P>>>`.

| Concern | A: borrowed arbitrary Executor | B: explicit library-created resource, adopted target |
| --- | --- | --- |
| Owner and lifetime | Application owns executor and storage. Store must never shut down the executor. | Application owns resource handle and storage. Resource owns one worker and its queue. Stores borrow the handle. |
| Worker and queue bounds | Executor supplies unknown bounds. A bounded FIFO sequencer is also required to preserve order. | Exactly one worker and a FIFO queue of Q pending operations, Q supplied explicitly and positive. At most Q+1 admitted operations. No default global pool. |
| Rejection | Catch synchronous `RejectedExecutionException` and return a failed Future. Silent-discard executors can strand operations. | Full queue or closed resource returns a failed Future with `RejectedExecutionException`. No waiting for space, dropping tasks, or inline fallback. |
| Calling thread | Direct executors, blocking `execute`, and `CallerRunsPolicy` can execute or wait on the caller. Executor type alone cannot certify offload. | Only admission bookkeeping runs on caller. Operation code runs on resource worker. This is offload, not a wait-free or latency-bound API. |
| Order | Multiple workers need serial sequencing. Executor shutdown can race the sequencer and strand accepted work. | One FIFO sequence covers all attached stores, reads, writes, and retention. |
| Close, drain, cancel | Requires an additional store admission/drain handle beyond the overloads. Executor termination alone cannot identify each store's operations. | D5 defines close, drain, and cancellation independently. |

Adopt B for an entry point with a defined offload contract. Its cost is head-of-line waiting, including between unrelated aggregates sharing a resource. Applications can create independent resources for independent storage ownership domains. A later bounded multiworker or keyed design needs a separate ordering and resource-budget review. Native SDK async would need transaction and cancellation redesign and would not solve SQLite JDBC. Neither alternative is part of this adopted target.

## D3. Admission and execution unit

The caller creates the resource explicitly, with Q such as 64 chosen for its workload. Q=64 is an example, not a measured capacity recommendation. Creation may allocate and start a thread and can throw synchronously. Factory calls perform only handle, storage, and configuration checks, without I/O or user callbacks. Null handles and invalid Q remain synchronous configuration errors.

An operation admits a command that retains its input references. Caller-side work is limited to allocating its result and bounded queue bookkeeping. Do not inspect payloads, serialize, validate envelopes, acquire a SQLite connection lock, or invoke hooks there. Resource admission has a linearization point shared with close. Closed or full admission returns an already failed Future and runs no operation code. A short internal synchronization wait is possible. No claim of strictly nonblocking algorithms or hard return deadlines is made.

Inputs must remain unchanged until the actual operation ends, including after result cancellation. Snapshotting mutable payloads with a serializer on the caller would violate this boundary. Thread-local state is not copied implicitly. Serializer, hook, and listener thread affinity changes only for users choosing the new factories.

One worker executes the entire synchronous operation: validation, serialization, transaction attempts, retry waits, reads and result traversal, commit, deserialization, post-commit tail work, retention, logging, and listeners. It does not split a transaction between workers. Internal SDK threads remain SDK-owned. The next command starts only after this entire unit exits and its resources are cleaned up.

Ordinary Future completion can run user continuations inline on the completing worker, or on the attaching caller if already complete. Those continuations are outside the storage operation and can stall a worker. Use an explicit separate executor for blocking continuations. A hook, serializer, listener, or continuation must not synchronously wait for another command on the same resource or for its drain. Reentrant admission is allowed within Q but such waiting deadlocks. No timeout can make arbitrary user code terminate safely.

## D4. Preserve ordering and commit semantics

For one resource, FIFO means accepted admission order, not event timestamp, seq_nr sorting, or fairness between concurrent threads. Consecutive accepted calls by one caller execute in call order. Concurrent callers have only the resource's admission order. A cancelled queued operation is a skipped position, not a successful append. A later seq_nr can then fail optimistic locking. Do not reorder or renumber it. No order is promised across resources, processes, raw stores, or external writers. Applications needing conditional progress chain from a successful result.

The adopted SQLite precondition requires all offloaded accesses to one connection, including storage aliases, to use the same resource. Until actual operation termination, do not mix raw APIs, use another resource for that connection, or close storage. A connection lock protects internal access but does not supply FIFO admission. This is an explicit use condition, not a guarantee of complete detection through a global identity registry or of external raw JDBC use. D8 requires both compliant use and negative controls that do not misrepresent violations as safe. The order guarantee is conditional on this exclusive use.

For Spanner, keep the complete manual retry loop on the worker. Preserve the same envelopes, seq_nr, fresh head checks, retry limits, exception classification, and hooks. Do not wrap it in another SDK transaction runner. ADR-0009's accepted waits, once implemented separately, occupy this worker too. Queue bounds do not bound SDK duration or retry duration. Cancellation of a result does not interrupt this loop under candidate B.

For Bigtable, preserve the mandatory journal write-out of the previous committed head before the conditional head advance. The head compare-and-set remains the commit point. Keep post-commit new-tail write-out and its notification before retention, and keep retention and its listener within the same command. Reads continue combining the fetched head tail with journal rows at that head's bound. Do not move retention to an independent queue or let cancellation skip required post-commit work. Preserve retired history markers when delayed copies run. See the [Bigtable storage profile](../spec/storage/bigtable.md).

SQLite and Spanner retain their database transaction commit points. A lost commit response, or existing post-commit hook error classified as unknown, stays an unknown outcome. An execution wrapper cannot turn an uncertain operation into a known rollback. Do not automatically retry an unknown result. Reconcile using existing storage rules. [S-4](../spec/core-contract.md) still requires retention failure to preserve committed append success and report separately. A listener that fails remains isolated as in the underlying implementation. A listener that never returns can still prevent completion and drain.

## D5. Lifecycle and cancellation

The resource state is `OPEN`, `DRAINING`, or `TERMINATED`. Commands move from `QUEUED` to `RUNNING` to `FINISHED`, or from `QUEUED` to `SKIPPED` on cancellation. Result completion and command completion are separate state. Result cancellation can precede a later commit.

`close()` is idempotent and returns after closing admission. It neither waits nor interrupts. Already accepted commands drain in FIFO order, except cancelled queued commands. New calls fail as in D3. There is no implicit shutdown-now, drop, or timeout. The worker is non-daemon, so an application must close the resource. Try-with-resources closes admission but does not prove termination.

`drained()` exposes a read-only termination stage. It completes only after all accepted commands have finished or been skipped, all operation cleanup and worker-run completion callbacks have returned, and the worker can no longer execute commands. Cancelling or externally completing a consumer's derived stage cannot cancel drain. No individual store owns or closes the shared resource. Close it only after every borrowing store's producer has stopped. After drain, the application closes SQLite storage and then any application-owned SDK clients when their other users have also finished. This resource does not close either automatically.

Cancellation of a returned operation Future is a request to abandon its result. If cancellation wins the atomic transition before `RUNNING`, skip invocation entirely. Keep the queue slot charged until the worker removes the skipped command, so Q remains an honest bound. If `RUNNING` wins, both `cancel(false)` and `cancel(true)` can mark the result cancelled but do not interrupt or stop the command. Finish validation, transaction resolution, post-commit work, and cleanup. Never release a lane, reuse a connection, or signal drain merely because its result is cancelled.

The queue-to-running race requires one linearized state transition, not an unsynchronized `isCancelled()` check. The local sketch in D8 exercises controlled cases only and does not prove this race. This adopted cancellation rule prioritizes order and cleanup over prompt abort. Actual SDK interruption or request cancellation needs a future separate design. A timed-out caller must treat an in-flight write as possibly committed.

## D6. Errors at each boundary

| Boundary | Adopted B target behavior |
| --- | --- |
| Resource or factory construction | Synchronous configuration `RuntimeException` for invalid arguments. Thread-start failure can throw synchronously. Existing factories remain unchanged. |
| Operation allocation or admission | Full/closed becomes a failed Future with `RejectedExecutionException`. Infrastructure `Error` such as allocation failure may escape synchronously. No operation has started. |
| Worker operation `Exception` | Complete result exceptionally with the same underlying classification and cause. A cancelled result stays cancelled. Internal bookkeeping still observes completion. |
| Worker operation `Error` | Attempt exceptional completion and cleanup, then rethrow to the worker's uncaught handler. Never relabel fatal errors as ordinary storage failures. Later accepted commands require worker replacement or explicit failed termination, never silent stranding. |
| Retention or tail notification | Preserve existing success isolation and reporting. Generic worker error handling must not override S-4. |

Fatal VM failure cannot guarantee Future completion or cleanup. An implementation must prove recovery for a controlled `AssertionError`: release internal accounting, replace the failed worker while draining accepted work, and keep FIFO. This is an implementation gate, not a claim established by the minimal model. `drained()` must never report successful termination with stranded accepted commands. Exceptional termination needs a diagnostic failure if recovery is impossible. Existing caller-thread `Error` behavior is preserved only for existing factories; choosing offload deliberately changes the error delivery thread.

## D7. Safe invocation boundaries for current users

These examples use current APIs and assume application-owned bounded blocking resources with rejection rather than caller execution. They illustrate placement, not a new ordering wrapper. Concurrent submissions still need application sequencing. Opening storage must also occur away from a UI thread when it can block.

```java
// blockingPool is bounded, application-owned, and uses AbortPolicy.
// Invoke the existing factory's operation inside the worker lambda.
CompletableFuture<Void> result;
try {
	result = CompletableFuture.runAsync(() -> legacy.persistEvent(event).join(), blockingPool);
} catch (RejectedExecutionException rejected) {
	result = new CompletableFuture<>();
	result.completeExceptionally(rejected);
}
// Do not evaluate legacy.persistEvent(event) before submission.
```

`thenApplyAsync` after an eagerly invoked legacy operation moves only the continuation. Cancelling the outer Future does not stop the worker or prove resource safety. Track actual submitted task termination before closing storage.

```kotlin
// blockingDispatcher belongs to the application and has a bounded admission policy.
withContext(blockingDispatcher) {
	legacy.persistEvent(event) // Dispatch happens before Java invocation and await.
}
```

For the current Kotlin wrapper, `suspend` and `await` alone do not move the Java call. Cancellation may affect waiting after invocation returns, but does not guarantee that blocking Java invocation ends, rolls back, or releases resources. The application controls dispatcher lifetime and must track actual operation completion separately. This ADR does not silently replace existing factories' dispatchers.

```scala
// blockingEc and continuationEc are explicit application-owned ExecutionContexts.
// blockingEc must reject overload rather than execute on the submitting thread.
val invoked = scala.concurrent.Future {
	legacy.persistEvent(event) // The by-name body is evaluated on blockingEc.
}(blockingEc)
val result = invoked.flatMap(identity)(continuationEc)
```

Here `legacy` is the current Scala wrapper, returning a Scala Future. For a Java store, convert the inner CompletionStage with `asScala` in `flatMap` instead. Handle synchronous scheduling rejection at the application boundary. `JavaInterop.future(underlying.operation(...))` is not equivalent to this example: its by-name argument is evaluated in `attempt(call)` on the invoking thread. An `ExecutionContext` used for later `map`, `flatMap`, or conversion does not dispatch that earlier evaluation. Standard Scala Future supplies no operation cancellation entry point.

## D8. Evidence and required implementation verification

The original draft pass ran the following throwaway probes under `/tmp/pm-java-async-design/`, on OpenJDK 26.0.2.1. These files are audit artifacts and are not committed. The inherited probe source was inspected and rerun against newly downloaded jars. All compiles and final probe runs exited 0. These are boundary checks, not performance benchmarks.

| Evidence obtained in the original draft pass | What it establishes and what it does not |
| --- | --- |
| Public 5.2.0 `BoundaryProbe` | Blocking proxy injected into each actual private Async class, three backends times four operations. Same caller enters the fake, no Future returned until release. RuntimeException fails the result, AssertionError escapes, completed cancel returns false. No real Spanner or Bigtable SDK execution. |
| Public 5.2.0 `SqliteProbe` with sqlite-jdbc 3.54.1.0 | Real temporary DB, both writes, both reads, and retention hook. Each controlled hook blocks the caller before Future return. Three committed events read back. Hook delays are artificial. |
| `ExecutionModel` | Throwaway one-worker, one-queue-slot sketch returns a pending Future while fake blocks on worker. Full and closed reject, FIFO survives in-flight result cancellation, close waits for work through drain, queued cancellation skips invocation. A direct-executor negative control runs inline. |

The model is not the proposed public API or a library patch. It catches `Throwable` for convenience and polls cancellation before invocation. It does not implement D5's atomic cancellation race, D6's fatal worker policy, a read-only drain stage, or attachment identity enforcement. Its success cannot establish production guarantees. The published-jar probes demonstrate existing behavior only. No offloaded real SQLite implementation was tested.

The independent reviewer subsequently reran the public-jar, SQLite, and model probes and added isolated controls for saturation, reentrant waiting, read-only stages, controlled Error replacement, the Java D7 example, and small Kotlin/Scala invocation examples. The [review record](https://github.com/j5ik2o/event-store-adapter/pull/144#issuecomment-6776410540) limits PASS+NOTES to the document and design at 51bf027. Isolated controls do not prove the library contract or full wrapper runtime. This adoption edit inherits those results only within their stated scope. It does not rerun jars, SDKs, wrappers, JDK 11, or full language suites, and is not a new independent PASS. Its new checks cover bilingual D0-D9, unchanged API/example code blocks, links, the two-file scope, and unchanged historical evidence tables.

Before implementation acceptance, require this matrix for **all four operations** on **all three backends**, plus the retention path of snapshot writes:

| Gate | Required observations |
| --- | --- |
| Caller boundary | Latches inside validation, serializer, storage, hooks, deserializer, retention, and listener. Caller receives result before release, all operation callbacks run off caller, no inline fallback under saturation. |
| Queue and order | Q positive and invalid values, Q+1 maximum, rejection runs no code. Same-caller writes and interleaved reads retain FIFO. Concurrent admission has one recorded order. SQLite aliases share one resource. Independent resources do not claim global order. |
| Lifecycle | Close/admit races, repeated close, full queue at close, queued and in-flight cancellation, empty drain, listener stall, and callback reentrancy. Drain remains pending until actual exit, not result cancellation. |
| Failure | RuntimeException and controlled Error before transaction, during commit, and after commit. Fatal worker replacement drains accepted tasks. Underlying classifications and S-4 remain intact. |
| Real SQLite | Temporary DB with all four entry points, ordered sequence readback, retained snapshots and markers, connection serialization, failed append rollback, close only after drain. |
| Spanner SDK | Fake backend plus actual SDK session acquisition, query traversal, ABORTED retries and accepted waits, hook counts, commit-response loss, SDK timeouts and client close. Keep fixed 5.1 and 5.2 dependency sets separate. |
| Bigtable SDK | Fake backend plus actual SDK head CAS, previous journal write-out failure, lost response, tail failure, delayed copy after retention, head-bound stream reads, timeout and close. Preserve append success after post-commit failure. |
| JVM wrappers | Execute Kotlin and Scala examples, single-thread caller responsiveness, dispatch before invocation, bounded rejection, coroutine cancellation races, queued versus in-flight writes, and resource cleanup after cancellation. Verify main's Java 5.1 and split heads' 5.2 separately. |

Atomic queued cancellation, controlled Error recovery or diagnostic failed termination, read-only library drain, compliant SQLite attachment and violation controls, offloaded real SQLite, real Spanner/Bigtable SDK backends, full wrapper runtime across all four operations, JDK 11, long-running load, and a production offload implementation remain unverified. Neither a future-shaped result nor the model establishes these gates. No cloud operation, release, merge, or full language suite ran for this ADR.

## D9. Review and follow-up

The original draft pass had no independent reviewer verdict. The later [independent PASS+NOTES](https://github.com/j5ik2o/event-store-adapter/pull/144#issuecomment-6776410540) applies to 51bf027 and the document/design scope only. PM then [adopted B](https://github.com/j5ik2o/event-store-adapter/issues/139#issuecomment-6776831524), including the fixed Java names, explicit SQLite use condition, and controlled Error recovery target. Independent confirmation of the latest adoption head remains pending. Keep #139 open until that confirmation and merge. PR readiness is a document handoff, not implementation or release approval.

Duplicate searches found no equivalent follow-up issues. Track the remaining work separately:

- [Java #818](https://github.com/j5ik2o/event-store-adapter-java/issues/818) covers the SDK-free core resource, three backend opt-in factories, existing API/order/S-4/dependency preservation, and the full D8 matrix.
- [Kotlin #907](https://github.com/j5ik2o/event-store-adapter-kotlin/issues/907) and [Scala #919](https://github.com/j5ik2o/event-store-adapter-scala/issues/919) cover current wrappers' four operations, dispatch, rejection, cancellation, drain, and dependency boundaries after the corresponding new Java artifact is available. Any needed wrapper entry requires a separately defined signature while preserving existing public APIs. This ADR invents no wrapper API.

Implementation is on hold until latest-head independent confirmation and ADR merge. Creating tracking issues is not completing implementation. Product runtime verification, CI, design adoption, and publication approval are separate decisions. Snapshot and formal publication require separate owner approval. No new release version or milestone is selected. Keep these changes separate from Java #814/#817, Kotlin #906, and Scala #918.
