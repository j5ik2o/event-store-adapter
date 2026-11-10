---
status: proposed
---

# Java 非同期操作の実行資源の明示

## D0. 提案と決定の境界

[#139](https://github.com/j5ik2o/event-store-adapter/issues/139) の目的は、Java SQLite・Spanner・Bigtable の呼出 thread を操作の I/O で塞がず、既存 factory と保存順を維持することである。[英語草案](0010-explicit-execution-for-async-operations.md) を正本とし、本書は日本語補助とする。

明示的に作成する、容量上限付き単一 worker の実行資源と追加 factory を推奨する。以下の signature と挙動は未採用・未公開の提案である。独立レビューと PM 承認を経て API を採用し、その後に言語別実装 issue を作る。共通契約と conformance 1.4.0 は変更しない。

基準は [共通 main ea561f8](https://github.com/j5ik2o/event-store-adapter/tree/ea561f8d2a1d008a9196e8b189268741fbc0c9ff)。[ADR-0009](0009-bound-manual-spanner-aborted-retry-waits.md) は採用済みの待機設計であり、Java main の実装済み証拠ではない。Java #814/#817、JS #1127、Kotlin #906、Scala #918、公開設定・workflow・版・既存 ADR は本変更の対象外とする。

## D1. 観測した挙動と固定 source

本作業では [#114 の調査記録](https://github.com/j5ik2o/event-store-adapter/issues/114#issuecomment-6773418204)、現 #139 本文とコメント、以下の固定 source と Maven 公開物を再取得した。旧 report は出発点であり、本作業の確認の代用にはしていない。

| 固定対象 | 本作業で照合した source 事実 |
| --- | --- |
| [Java main d0237dd](https://github.com/j5ik2o/event-store-adapter-java/tree/d0237ddcd76149fae8296fedea1f4b1f1d281ae5) | 各保存先の `createAsync` は caller-thread 実行を記載している。`Async.complete` は Future を返す前に `action.get()` を呼ぶ。 |
| [公開 Java 5.2.0 SQLite source](https://repo.maven.apache.org/maven2/io/github/j5ik2o/event-store-adapter-java-sqlite/5.2.0/event-store-adapter-java-sqlite-5.2.0-sources.jar)、[Spanner source](https://repo.maven.apache.org/maven2/io/github/j5ik2o/event-store-adapter-java-spanner/5.2.0/event-store-adapter-java-spanner-5.2.0-sources.jar)、[Bigtable source](https://repo.maven.apache.org/maven2/io/github/j5ik2o/event-store-adapter-java-bigtable/5.2.0/event-store-adapter-java-bigtable-5.2.0-sources.jar) | 3 個の `*EventStore.java` は固定 main と bytes 一致。D8 は公開 binary を使用した。 |
| [公開 Java 5.1.0 一体版 source](https://repo.maven.apache.org/maven2/io/github/j5ik2o/event-store-adapter-java/5.1.0/event-store-adapter-java-5.1.0-sources.jar) | 同じ 3 ファイルは空白除去後に 5.2.0 と一致する。binary や依存全体の同等性は意味しない。 |
| [Kotlin main ab3e877](https://github.com/j5ik2o/event-store-adapter-kotlin/tree/ab3e877f55abab7a57383af50a749cf2a4591dec) | `build.gradle.kts` は Java 一体版 5.1.0。`JavaAsyncEventStoreAdapter` の全 4 操作は Java 呼出し後に `.await()` する。 |
| [Kotlin #906 head c7be242](https://github.com/j5ik2o/event-store-adapter-kotlin/tree/c7be2421c88f5aff2247abacb86fd3e03168eab8) | 未 merge の分割は Java 5.2.0 driver を使う。adapter の core 移動によって Java invocation 前の dispatch は追加されない。 |
| [Scala main dc358b4](https://github.com/j5ik2o/event-store-adapter-scala/tree/dc358b460123e6051375a7ab8ab743824c8011cb) | `project/Dependencies.scala` は Java 5.1.0。`JavaInterop.future` の by-name 引数は `Future.fromTry(attempt(call))` 内で評価される。 |
| [Scala #918 head 2a70891](https://github.com/j5ik2o/event-store-adapter-scala/tree/2a708919980550a14330b59e8e796ef25ede8d99) | 未 merge の分割は Java 5.2.0 driver を使い、同じ評価境界を保つ。 |

公開 POM の依存は、Java 5.1.0 が sqlite-jdbc 3.53.4.0・Spanner 6.124.0・Bigtable 2.85.0、Java 5.2.0 が順に 3.54.1.0・6.127.0・2.88.0 である。対応 SDK source も再取得した。Spanner `ReadContext` は `executeQuery` が先に返る場合でも `ResultSet.next()` で response を待ち得る。adapter は結果を消費する。Bigtable `readRow` と `checkAndMutateRow` は同期 SDK helper で待ち、`BigtableRows.readRange` は stream を消費する。SQLite 操作内では JDBC 呼出しと結果走査を行う。SDK transport thread の存在によって adapter の入口が早く返るわけではない。

既存 factory は storage/config を同期検証する。操作は検証・serialization・SQL/SDK・復元・hook・該当する retention を Future 返却前に実行する。`Async.complete` は `RuntimeException` を含む `Exception` を失敗 Future にする。`Error` は同期 throw し得る。storage open/initialize は別の同期操作である。既存 API は完了済み Future と thread affinity を含めて維持する。既存 factory の暗黙 `commonPool` 投入や wrapper の実行方針の無断置換は行わない。

SDK の一次 source は [Spanner 6.127.0](https://repo.maven.apache.org/maven2/com/google/cloud/google-cloud-spanner/6.127.0/google-cloud-spanner-6.127.0-sources.jar) と [Bigtable 2.88.0](https://repo.maven.apache.org/maven2/com/google/cloud/google-cloud-bigtable/2.88.0/google-cloud-bigtable-2.88.0-sources.jar) を参照する。

## D2. 具体的な 2 案

案 A は 3 保存先に次の overload を追加する。

```java
// Candidate A, not an existing API.
public static <P, A> AsyncEventStore<P, A> createAsync(
	SqliteStorage storage, EventStoreConfig<P, A> config, Executor executor);
public static <P, A> AsyncEventStore<P, A> createAsync(
	SpannerStorage storage, EventStoreConfig<P, A> config, Executor executor);
public static <P, A> AsyncEventStore<P, A> createAsync(
	BigtableStorage storage, EventStoreConfig<P, A> config, Executor executor);
```

案 B は実行資源と別名の factory を追加する。

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

両案とも 4 操作は既存 `AsyncEventStore` と同じ `persistEvent(EventEnvelope<P>)`、`persistEventAndSnapshot(EventEnvelope<P>, SnapshotEnvelope<A>)`、`getLatestSnapshotById(AggregateId)`、`getEventsByIdSinceSeqNr(AggregateId, long)` とする。返却型は順に `CompletableFuture<Void>`、`CompletableFuture<Void>`、`CompletableFuture<Optional<SnapshotReadResult<A>>>`、`CompletableFuture<List<EventEnvelope<P>>>` を維持する。

| 論点 | A: 任意 Executor の借用 | B: 明示的に作る library 管理資源、推奨 |
| --- | --- | --- |
| 所有者・寿命 | application が executor と storage を所有する。store は executor を shutdown しない。 | application が資源 handle と storage を所有する。資源が 1 worker と queue を所有し、store は handle を借用する。 |
| worker/queue 上限 | Executor 次第で不明。順序維持には別途 bounded FIFO sequencer が必要。 | worker は厳密に 1。正の Q を明示指定し pending queue を Q 件に制限する。受理は最大 Q+1 件。既定の共通 pool はない。 |
| 拒否 | 同期 `RejectedExecutionException` を失敗 Future にする。silent discard は操作を未完了のまま残し得る。 | 満杯・close 後は `RejectedExecutionException` の失敗 Future。空き待ち・破棄・inline fallback はない。 |
| caller | direct executor、blocking `execute`、`CallerRunsPolicy` は caller で実行・待機し得る。Executor 型だけで offload を証明できない。 | caller は受理 bookkeeping のみ行う。操作は worker 上で実行する。wait-free や返却時間上限の保証ではない。 |
| 順序 | 複数 worker では直列化が必要。executor shutdown と sequencer の競合で受理済み操作を残し得る。 | 接続した全 store の read・write・retention を 1 FIFO で実行する。 |
| close/drain/cancel | overload だけでは不足し、store ごとの受理/drain handle が別途必要。executor 終了だけでは識別できない。 | D5 で close・drain・取消しを独立に定義する。 |

offload 契約を定める入口には B を推奨する。同じ資源を共有する無関係な aggregate も遅い操作を待つというコストがある。所有範囲が独立した storage には別資源を作れる。将来の bounded multiworker/keyed 案は順序と資源予算の別レビューが必要である。SDK native async は transaction・取消しの再設計を要し、SQLite JDBC も解決しない。どちらも本提案には含めない。

## D3. 受理と実行単位

caller は Q を明示して資源を作る。例えば 64 は workload に応じた例であり測定からの推奨値ではない。作成時には thread の確保・起動と同期例外があり得る。factory は handle/storage/config の検証のみ行い、I/O や利用者 callback を呼ばない。null handle と不正 Q は同期 configuration error とする。

操作は入力参照を保持する command を受理する。caller 側は result 確保と bounded queue bookkeeping に限る。payload 検査・serialization・envelope 検証・SQLite lock 取得・hook は行わない。受理と close は共通の線形化点を持つ。close 済み・満杯なら失敗済み Future を返し、操作を実行しない。短い内部同期の待機はあり得る。厳密な nonblocking algorithm や返却 deadline は主張しない。

利用者は result 取消し後も、実操作が終了するまで入力を変更しない。caller 上の serializer で mutable payload を複製すると、この境界に違反する。thread-local は暗黙に複製しない。serializer/hook/listener の affinity 変更は追加 factory を選ぶ利用者だけに適用する。

worker が同期操作全体を実行する。検証・serialization・transaction 試行・retry 待機・read と結果走査・commit・復元・commit 後 tail 処理・retention・logging・listener を含む。transaction を worker 間で分割しない。SDK 内部 thread は SDK が管理する。単位全体の終了と資源解放の後に次の command を開始する。

Future 完了は利用者 continuation を完了 worker 上で inline 実行し得る。完了済みなら登録 caller 上で実行し得る。continuation は storage 操作外だが worker を止め得る。blocking continuation には別の明示 executor を使う。hook/serializer/listener/continuation は同じ資源の別 command や drain を同期的に待ってはならない。Q 内の再入受理は可能だが、その待機は deadlock する。任意の利用者コードの安全な終了を timeout で保証できない。

## D4. 順序と commit の維持

資源ごとの FIFO は受理順であり、event 時刻・seq_nr による整列や並行 thread 間の公平性ではない。同じ caller の連続した受理済み呼出しは呼出順に実行する。並行 caller 間では資源の受理順だけが定まる。queue 内取消しは順番を飛ばすことであり append 成功ではない。後続 seq_nr は楽観 lock に失敗し得る。並べ替え・採番変更はしない。資源・process・raw store・外部 writer を跨ぐ順序は保証しない。成功を条件に次へ進める場合は成功 result から連鎖する。

SQLite の同一 connection への alias を含む全アクセスは同じ資源へ統一するか、offload session の外で行う。内部 connection lock は FIFO 受理を保証しない。同じ connection を 2 資源へ接続せず、session 中は raw 同期アクセスを混ぜず、command が残る間は storage を close しない。採用時には attachment identity を強制するか利用条件にするか決める。それまでは本草案の順序保証は排他的利用を条件とする。

Spanner の手動 retry loop 全体は同じ worker に残す。同じ envelope・seq_nr、head 再照合、retry 上限、例外分類、hook を維持し、別 SDK runner で包まない。ADR-0009 の採用済み待機も、別途実装後はこの worker を占有する。queue 上限は SDK・retry の時間上限ではない。案 B の result 取消しは loop を interrupt しない。

Bigtable は、head 条件付き更新の前に直前の確定 head を journal に書き出す順序を維持する。head CAS が commit 点である。commit 後の新 tail 書出し・通知を retention より前に実行し、retention と listener まで同じ command に含める。read は取得した head の境界で journal と head tail を結合する。retention を独立 queue へ移さず、取消しで commit 後処理を飛ばさない。遅延コピーでも retired history marker を維持する。[Bigtable storage profile](../spec/storage/bigtable.md) を参照する。

SQLite/Spanner の database commit 点も維持する。commit response 消失や既存の commit 後 hook error の unknown 分類は unknown のままとする。wrapper は不確定な結果を既知の rollback に変えられない。unknown を自動 retry せず、既存 storage 規則で照合する。[S-4](../spec/core-contract.md) に従い、retention 失敗は確定 append 成功を変えず、別経路で報告する。listener 自身の失敗は既存実装どおり隔離する。戻らない listener は completion と drain を止め得る。

## D5. 寿命と取消し

資源状態は `OPEN`・`DRAINING`・`TERMINATED` とする。command は `QUEUED` から `RUNNING`、`FINISHED` へ進むか、queue 内取消しで `QUEUED` から `SKIPPED` へ進む。result 完了と command 完了は別状態である。result 取消し後にも commit し得る。

`close()` は冪等で、受理を閉じた後に返る。待機・interrupt はしない。受理済みは queue 内取消しを除いて FIFO で drain する。新しい操作は D3 の失敗になる。暗黙の shutdown-now・破棄・timeout はない。worker は non-daemon とし、application が必ず資源を close する。try-with-resources は受理を閉じるだけで、終了の証拠ではない。

`drained()` は読取り専用の終了 stage とする。受理済み command が終了または skip され、操作の cleanup と worker 上の完了 callback が戻り、worker が以後 command を実行しない状態になってから完了する。利用者が派生 stage を cancel/complete しても drain を取り消せない。個別 store は共有資源を所有・close しない。借用 store 全ての producer が停止してから close する。drain 後に application が SQLite storage を close し、SDK client は他の利用者も終了した後に close する。資源は storage/client を自動 close しない。

操作 Future の cancel は result の放棄要求とする。`RUNNING` 遷移より先に取消しが原子的に勝てば invocation 全体を飛ばす。worker が skip command を取り除くまで queue 枠を占有したままにし、Q 上限を維持する。`RUNNING` が勝てば `cancel(false)`/`cancel(true)` のどちらも result を取り消し得るが、command を停止・interrupt しない。検証・transaction 解決・commit 後処理・cleanup を完了する。result が cancelled という理由で lane や connection を解放したり drain を通知したりしない。

queue から実行への race は、非同期な `isCancelled()` 確認ではなく 1 個の線形化された状態遷移を必要とする。D8 の局所モデルは制御下のケースだけを試し、この race は証明していない。この取消し案は即時中止より順序と cleanup を優先する。SDK interruption/request cancel は将来の別設計とする。caller timeout 時の in-flight write は確定済みかもしれないものとして扱う。

## D6. 境界ごとのエラー

| 境界 | 案 B の提案挙動 |
| --- | --- |
| 資源/factory 作成 | 不正引数は同期 configuration `RuntimeException`。thread 起動失敗も同期 throw し得る。既存 factory は変更しない。 |
| 操作確保・受理 | 満杯/close 後は `RejectedExecutionException` の失敗 Future。確保失敗などの基盤 `Error` は同期 throw し得る。操作は未開始。 |
| worker 操作の `Exception` | 元の分類・cause で失敗完了する。取消し済み result は取消しのまま。内部管理は終了を別途観測する。 |
| worker 操作の `Error` | 失敗完了・cleanup を試みてから worker の uncaught handler へ再 throw する。fatal を通常 storage error に分類し直さない。worker 置換か明示的な異常終了が必要で、後続を黙って残さない。 |
| retention/tail 通知 | 既存の成功隔離・報告を維持する。汎用 worker error 処理で S-4 を上書きしない。 |

致命的 VM 障害では Future 完了・cleanup を保証できない。実装では制御した `AssertionError` に対する復旧を証明する。内部管理を解放し、worker を置換して受理済みを FIFO で drain する。これは最小モデルで実証済みの主張ではなく実装 gate である。未処理の受理済みを残して `drained()` を成功させてはならない。復旧不能なら診断可能な異常終了が必要である。caller-thread `Error` 挙動の維持は既存 factory に限る。offload を選ぶと error の配送 thread が変わる。

## D7. 現利用者の安全な呼出し境界

以下は現行 API を使い、application 所有の bounded blocking 資源が caller 実行ではなく拒否することを前提とする。実行の置き場所の例であり、新しい順序 wrapper ではない。並行投入には application 側の順序制御が必要である。blocking し得る storage open も UI thread の外に置く。

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

先に legacy 操作を評価してから `thenApplyAsync` を付けても continuation しか移動しない。外側 Future の cancel は worker 停止・資源安全性を意味しない。storage close 前には投入 task の実終了を追跡する。

```kotlin
// blockingDispatcher belongs to the application and has a bounded admission policy.
withContext(blockingDispatcher) {
	legacy.persistEvent(event) // Dispatch happens before Java invocation and await.
}
```

現 Kotlin wrapper は `suspend` と `await` だけで Java 呼出しを移さない。取消しは invocation 後の待機に作用し得るが、blocking Java invocation の終了・rollback・資源解放を保証しない。application が dispatcher 寿命を管理し、実操作終了を別途追跡する。既存 factory の dispatcher を本草案で暗黙置換しない。

```scala
// blockingEc and continuationEc are explicit application-owned ExecutionContexts.
// blockingEc must reject overload rather than execute on the submitting thread.
val invoked = scala.concurrent.Future {
	legacy.persistEvent(event) // The by-name body is evaluated on blockingEc.
}(blockingEc)
val result = invoked.flatMap(identity)(continuationEc)
```

ここで `legacy` は Scala Future を返す現 Scala wrapper とする。Java store なら `flatMap` 内で内側 CompletionStage を `asScala` 変換する。同期 scheduling rejection は application 境界で扱う。`JavaInterop.future(underlying.operation(...))` はこの例と違い、`attempt(call)` が invocation thread 上で by-name 引数を評価する。後段の `map`/`flatMap`/変換用 `ExecutionContext` は前段評価を dispatch しない。標準 Scala Future に操作取消し入口はない。

## D8. 証拠と後続実装の検証

本作業では OpenJDK 26.0.2.1 で `/tmp/pm-java-async-design/` の throwaway probe を実行した。監査資料であり commit しない。継承した probe source を読んで、新たに取得した jar に対して再実行した。compile と最終実行は全て exit 0。返却境界の検査であり性能 benchmark ではない。

| 本作業の実行証拠 | 証明する範囲と限界 |
| --- | --- |
| 公開 5.2.0 `BoundaryProbe` | 実 private Async に blocking proxy を注入し、3 保存先×4 操作を実行。同じ caller が fake に入り release 前に Future 未返却。RuntimeException は失敗 Future、AssertionError は同期 throw、完了後 cancel は false。実 Spanner/Bigtable SDK 実行ではない。 |
| 公開 5.2.0 `SqliteProbe` と sqlite-jdbc 3.54.1.0 | 実一時 DB、2 write・2 read・retention hook を通す。人工待機 hook ごとに caller が Future 返却前に待つ。確定 event 3 件を readback。 |
| `ExecutionModel` | 1 worker・queue 1 枠の最小案。fake が worker を塞いでいる間に未完了 Future を受け取る。満杯/close 後の拒否、in-flight result 取消し後も FIFO、close/drain、queue 内取消しの invocation skip を確認。direct executor の負例は inline 実行。 |

モデルは提案 public API や library patch ではない。簡略化のため `Throwable` を捕捉し、invocation 前に取消しを確認する。D5 の atomic race、D6 の fatal worker 方針、読取り専用 drain stage、attachment identity 強制は実装していない。成功しても製品の保証にはならない。公開 jar probe は既存挙動の証拠だけである。offload した実 SQLite 実装は試していない。

実装受入れ前に **3 保存先の全 4 操作** と snapshot write の retention について以下を必要とする。

| Gate | 必要な観測 |
| --- | --- |
| caller 境界 | validation/serializer/storage/hook/deserializer/retention/listener 内に latch を置く。release 前に caller が result を取得し、操作 callback は caller 外で実行する。飽和時も inline に戻らない。 |
| queue/順序 | Q 正数・不正値、最大 Q+1、拒否時コード未実行。同 caller の write と read を FIFO 維持。並行受理は 1 個の記録順を持つ。SQLite alias は同一資源。別資源は global order を主張しない。 |
| 寿命 | close/受理 race、複数 close、満杯時 close、queue 内/in-flight cancel、空 drain、listener 停止、callback 再入。result cancel でなく実終了まで drain が pending。 |
| 失敗 | transaction 前・commit 中・commit 後の RuntimeException と制御 Error。fatal worker 置換後も受理済みを drain。元の分類と S-4 を維持。 |
| 実 SQLite | 一時 DB の全 4 入口、連番 readback、保持 snapshot と marker、connection 直列化、失敗 append rollback、drain 後 close。 |
| Spanner SDK | fake backend と実 SDK の session 取得、query 消費、ABORTED retry と採用済み待機、hook 回数、commit response 消失、timeout/client close。5.1/5.2 の依存集合を分ける。 |
| Bigtable SDK | fake backend と実 SDK の head CAS、前 journal 書出し失敗、response 消失、tail 失敗、retention 後の遅延コピー、head 境界 stream read、timeout/close。commit 後失敗でも append 成功を維持。 |
| JVM wrapper | Kotlin/Scala 例の実行、単一 thread caller の応答、invocation 前 dispatch、bounded rejection、coroutine cancel race、queue 内/in-flight write、取消し後の資源 cleanup。main の Java 5.1 と分割 head の 5.2 を別々に検証。 |

実 Spanner/Bigtable SDK backend、wrapper runtime、JDK 11、長時間負荷、製品 offload 実装は未検証である。Future 型やモデル成功でこれらの gate を満たしたことにはならない。本草案のための cloud 操作・release・merge・言語の full suite 実行は行っていない。

## D9. レビューと後続

PM へ本草案を返し、単一 worker の待機コスト、SQLite attachment 条件、atomic cancel、fatal worker 復旧、drain 契約、正確な公開名の独立レビューを依頼する。本作業には独立 reviewer の verdict はない。API 採用と言語別実装 issue の新規作成はレビュー後の PM 判断に残す。判断まで #139 を open に保つ。draft PR 作成や推奨を採用済みと扱わない。
