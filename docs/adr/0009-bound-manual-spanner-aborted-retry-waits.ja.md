---
status: accepted
---

# Spanner 手動 ABORTED 再試行の待機

これは PM が 2026-11-11 JST に [#137](https://github.com/j5ik2o/event-store-adapter/issues/137) で採用した待機設計である。[採用記録](https://github.com/j5ik2o/event-store-adapter/issues/137#issuecomment-6773771824) は [最初の PM 判断](https://github.com/j5ik2o/event-store-adapter/issues/113#issuecomment-6773097308) に続く。[英語正本](0009-bound-manual-spanner-aborted-retry-waits.md) を優先し、本書は日本語補助とする。[Java #816](https://github.com/j5ik2o/event-store-adapter-java/issues/816) と [JS #1126](https://github.com/j5ik2o/event-store-adapter-js/issues/1126) の実装要件を定める。実装・結合検証・merge・公開は別作業として残る。

## D1. 適用範囲と観測した現状

競合時に再試行回数を即座に消費するリスクを減らすことが目的である。リスクは手動 loop からの推論であり、本番改善・成功率変化・飢餓を実測していない。

確定済み [SPN-7](../spec/storage/spanner.ja.md) は変更しない。同じ封筒・seq_nr、head 再照合、副作用、上限時のエラーを維持する。SPN-7 は待機を未規定としている。他の Rust・Go・Kotlin・Scala を監査と承認なしに新要件の対象にしない。conformance 1.4.0 も変更しない。

| 自分で読取り・再取得した固定対象 | 入口と依存 |
| --- | --- |
| [Java main d0237ddcd76149fae8296fedea1f4b1f1d281ae5](https://github.com/j5ik2o/event-store-adapter-java/blob/d0237ddcd76149fae8296fedea1f4b1f1d281ae5/spanner/src/main/java/com/github/j5ik2o/event/store/adapter/java/spanner/SpannerTransactions.java) | `SpannerTransactions.runReadWrite` が毎回 `TransactionManager` を生成する。宣言 SDK は 6.127.0。 |
| [Java 公開 5.2.0 sources](https://repo.maven.apache.org/maven2/io/github/j5ik2o/event-store-adapter-java-spanner/5.2.0/event-store-adapter-java-spanner-5.2.0-sources.jar) | 入口は固定 main と bytes 一致。[公開 POM](https://repo.maven.apache.org/maven2/io/github/j5ik2o/event-store-adapter-java-spanner/5.2.0/event-store-adapter-java-spanner-5.2.0.pom) も SDK 6.127.0。tag commit は 0ec46b15ba44b4dfb45b4261dfafd6af6d79efbc。 |
| [JS main 4f4f5b800aea89b7e880a77cc90d76929dc889bc](https://github.com/j5ik2o/event-store-adapter-js/blob/4f4f5b800aea89b7e880a77cc90d76929dc889bc/packages/library/src/internal/spanner-read-write-transaction.ts) | 毎回 `getTransaction` を呼ぶ。lock は 9.1.0、optional peer は `^8.7.1 \|\| ^9.0.0`。利用者の版は一意ではない。 |

どちらも SDK 自動 transaction runner の retry loop を通らず、意図的な ABORTED backoff がない。RPC・session 取得・rollback・close の待ちは別に存在し得る。以下の本設計の挙動は実装済み・公開済みではない。

## D2. 試行状態と回数

既存の検証済み `transactionRetryLimit` を L とし、初回を含めない意味と公開 API・入力検証を維持する。内部状態は初期値 0 の `retriesStarted` と直前の ABORTED。待機判断は `fallback`・`server`・`stop` の三種類。待機値は正の整数 ms であり、待機そのものを試行回数に数えない。

失敗と解放の後、既存のエラー分類を先に行う。再試行可能な ABORTED だけを待機判断に進める。`retriesStarted >= L` なら従来の上限超過 storage エラーを返す。hint decode・乱数・timer は不要。それ以外は `k = retriesStarted + 1` を次の再試行番号として判断・待機する。次の試行を開始するときにだけ `retriesStarted` を増やす。stop は次の試行を開始しない。

選んだ待機時間は解放後から monotonic clock で測る。sleeper・timer が d ms より早く解決したら、正の残時間を ms 切上げで追加待機してから次の試行を始める。timer 引数は毎回 1..60000ms に収める。server hint を timer の丸めで短縮しないためであり、scheduler 遅延への deadline ではない。

| L | 最大試行数 | 最大待機数 | 全試行 ABORTED の場合 |
| --- | --- | --- | --- |
| 0 | 1 | 0 | 初回で上限超過。 |
| 1 | 2 | 1 | 初回後だけ待つ。2 回目で上限超過。 |
| 5 | 6 | 5 | 1〜5 回目後だけ待つ。6 回目で上限超過。 |

初回成功なら待機は 0 回。L=5 で 3 回目成功なら 2 回待機・3 回試行。成功後には待たない。

## D3. Server hint の decode と安全な範囲

正当な `google.rpc.RetryInfo.retry_delay` を fallback より優先する。fallback jitter を加算せず、下向きに制限しない。欠落・duration message 欠落・decode 失敗・不正値は fallback。decode エラーで元の ABORTED を置き換えない。エラーメッセージ文字列を解析しない。

[protobuf Duration](https://protobuf.dev/reference/protobuf/google.protobuf/#duration) のうち、整数秒 s が 0..315576000000、整数 nanos n が 0..999999999 の非負 duration を受理する。0 は正当。存在する duration 内の省略 scalar は 0。duration message 自体の欠落とは区別する。負値・小数・非有限値・異なる型・protobuf 範囲外は不正。正の秒と負の nanos を正規化して受理しない。

Java SDK 6.127.0 では公開 `SpannerException.getErrorDetails().getRetryInfo()` を先に読む。正当な duration がなければ、公開 gRPC metadata API で例外と cause chain の `google.rpc.retryinfo-bin` trailers を調べる。throwable は identity ごとに一度だけ訪問し、複数 trailer は wire 順で調べる。この優先順で最初の正当な値を使う。長すぎても正当なら、後の短い値を探さない。reflection・SDK private API は使わない。`getRetryDelayInMillis()` は `Durations.toMillis` でサブ ms を失うので正本として使わない。実装時は structured status と raw trailer の双方を検証する。

JS は `cause.metadata.get("google.rpc.retryinfo-bin")` の順に binary を adapter 所有の内部 protobuf decoder で decode し、最初の正当な duration を使う。固定 SDK の build/protos/status.json の RetryInfo・Duration descriptor から生成し、上流 license を保持する。必要な protobuf runtime は直接依存に宣言し、推移依存を偶然解決する構成にしない。固定 SDK の getRetryInfo() は private で、spanner-api は RetryInfo を公開していないため、その内部 helper の import や公開 RetryInfo 型の仮定は採用しない。private `getNextDelay` を使わない。seconds は正確な safe integer number・正規の十進整数字列・decoder の Long から lossless に変換した整数を受理する。任意 object の強制変換は禁止。protobuf 秒範囲は JS safe integer に収まる。乗算前に検証し、BigInt 等の整数演算を使う。peer 8・9、特に 8.7.1 と lock 9.1.0 の metadata 取得・decode を実装時に検証する。

`h = 1000*s + ceil(n/1000000)` を checked または正確な整数演算で求める。h<=60000 なら `d=max(1,h)` ms を待つ。h>60000 なら解放後に storage エラーで停止し、元 ABORTED を cause に保持する。server delay が対応待機範囲を超えたことを示す。timer も再試行も行わない。これは既存 storage 分類内の新しい停止条件であり、回数超過や commit outcome unknown ではない。

1ms の下限は正当なゼロ hint でも tight loop を避ける設計選択。60000ms の各待機上限も性能測定値・SDK 既定値ではない。長い hint は残り回数があっても停止する。無制限待機は Java 呼出しを何時間も塞ぎ得る。60 秒へ切り下げて再試行すると server の要求より早くなる。この案は待機予約の有限性と引換えに早期 storage エラーを認める。

| Hint | 判断 |
| --- | --- |
| 欠落・decode 不能・duration 欠落 | fallback。 |
| `{seconds:0,nanos:0}` | server、1ms。 |
| `{seconds:0,nanos:1}` | server、1ms。 |
| `{seconds:0,nanos:1000001}` | server、2ms。 |
| `{seconds:1,nanos:1}` | server、1001ms。 |
| `{seconds:60,nanos:0}` | server、60000ms。 |
| `{seconds:60,nanos:1}` | stop、timer・再試行なし。 |
| `{seconds:315576000000,nanos:999999999}` | 正当だが長すぎる。timer 引数へ変換する前に stop。 |
| s=-1、n=-1、n=1000000000、s=315576000001、NaN、Infinity、小数秒 | 不正、fallback。 |
| 最初の正当値が 61s、次が 10ms | 61s で stop。 |

## D4. Fallback と総時間

次の再試行番号 k は 1 から始める。`C(k)=min(1000,50*2^(k-1))`、`a=ceil(C/2)`、`d=a+floor(u*(C-a+1))` ms とする。u は毎回独立な [0,1) の一様乱数。k>=6 なら累乗前に C=1000 とし、大きい L でも overflow させない。暗号学的乱数は不要。内部注入可能な乱数・sleeper で検証し、公開設定は追加しない。

| k | C の ms | d の整数 ms 範囲、両端含む |
| --- | --- | --- |
| 1 | 50 | 25..50 |
| 2 | 100 | 50..100 |
| 3 | 200 | 100..200 |
| 4 | 400 | 200..400 |
| 5 | 800 | 400..800 |
| 6 以降 | 1000 | 500..1000 |

L=5、hint なし、全再試行使用なら選択した再試行待機時間の合計は 775..1550ms。受理した hint なら合計は最大 L*60000ms。診断用の乗算も overflow させない。各待機時間を一度ずつ数えた合計であり、早期 wake 後の timer 再予約を含む予約時間の合計はこれより大きくなり得る。これは wall-clock deadline ではない。RPC・hook・rollback・解放・scheduler・event loop 停滞の時間は別に加わる。総時間 deadline は追加せず、SDK RPC deadline もリセットしない。既存 client 設定が SDK 動作を制御する。

初回 cap 50ms は一時的 abort の追加遅延を抑えつつ正の休止を与える選択。倍増は後の試行を広く分散する。cap 1000ms は大きな L の fallback 遅延を制限する。equal jitter は正の下限を保つ。いずれも設計判断であり、SDK 値のコピーや測定結果ではない。

## D5. エラー、順序、副作用

| 結果 | 待機・再試行 |
| --- | --- |
| commit 前の再試行可能な ABORTED | 解放、回数判定、待機判断、待機、次の transaction。 |
| domain rejection・Java EventStoreException | 既存 domain エラー。待機・再試行なし。 |
| Java の非 ABORTED SpannerException、または JS の一般 transaction エラー分岐に到達する失敗 | 既存 storage エラー。待機・再試行なし。 |
| try-with-resources の試行から伝播する、それ以外の Java RuntimeException | 既存の伝播と suppression を維持。新たな storage 変換・再試行なし。 |
| L 超過の ABORTED | 既存上限超過 storage エラー。追加待機なし。 |
| JS getTransaction 失敗、code 10 含む | 既存開始失敗 storage エラー。待機・再試行なし。 |
| afterCommit 失敗、ABORTED 形状含む | 既存 outcome unknown storage エラー。待機・再試行なし。 |

Java は domain catch の後で ABORTED code または AbortedException を判定する。JS は committed と domain rejection の後で数値 code 10 を判定する。INTERNAL・CANCELLED・成否不明へ再試行対象を広げない。

Java は try-with-resources を維持する。begin、body、beforeCommit、commit の後、close と SDK rollback・session 解放が完了してから待つ。例外 suppression と解放エラーの既存優先順位を維持する。主例外の RuntimeException が EventStoreException でも SpannerException でもなければ、StorageException へ包まず既存通り伝播させる。body・beforeCommit・close の失敗も含む。afterCommit は別の outcome unknown 分類を維持する。無関係な解放失敗を ABORTED に変えない。成功時は従来通り close の後で afterCommit。

JS は ABORTED の best-effort rollback を await し、finally の end() を実行した後に待つ。待機を try/catch/finally の外に置く。catch 内で待つと timer 終了まで transaction を保持してしまう。rollback 失敗時は元失敗を保持し、end() 自体の throw は既存挙動を維持する。成功時は commit、afterCommit、end() の順序を変えない。

同一入力封筒・seq_nr を再利用する。各再試行で body・beforeCommit と head 再照合をやり直す。内部で採番や外部通知をしない。他 append が入力以上の seq_nr を確定していたら再実行時に optimistic lock とする。afterCommit と成功後の副作用は確定後に一度だけ実行する。retention 失敗の別経路通知も変えない。

## D6. 割込みと取消し

Java は初回前・各再試行前・sleep 前・sleep 後に `Thread.currentThread().isInterrupted()` を確認する。interruptible sleep を使う。InterruptedException 時はフラグを復元して停止する。フラグ検出時も消さずに停止する。割込みによる transaction retry 停止を示す StorageException とし、可能なら InterruptedException を cause、直前 ABORTED を suppressed に保持する。フラグだけの検出時も InterruptedException cause を作る。検出後は次の試行・hook を実行しない。既に回数上限に達した ABORTED は上限超過を優先し、待機判定をしない。

この確認は進行中 SDK 呼出しを cancel せず、成功済み commit も戻さない。試行中の割込みは制御が戻るまで SDK が扱う。commit 成功後は試行中にフラグが立っていても afterCommit を含む既存成功経路を終える。確認直後に割込みが入る race は残り、即時取消しを保証しない。

sleep は Java 呼出スレッドを塞ぐ。固定実装の非同期 facade は Future を返す前に action を同期実行する。AsyncEventStore の返却 Future.cancel がこの retry loop を止める保証はない。executor や API の変更は加えない。

JS は参照を保持する timer Promise を await する。event loop は他の処理を進められるが、操作は pending で timer が process を維持し得る。unref() はしない。AbortSignal API は追加しない。Promise の放棄や timeout race では retry 停止を保証しない。既存 SDK の cancellation エラーは非 ABORTED として扱う。内部待機が失敗したら storage エラーで停止し、再試行しない。取消しや総時間の新保証はない。

## D7. 代案と優先度引継ぎ

| 候補 | 推奨と代償 |
| --- | --- |
| 即時 retry | 見送り。意図的休止なしで L を消費するリスクが残る。 |
| 固定待機 | 見送り。同じ schedule になる。jitter は schedule を変えるが本番効果は未測定。 |
| 0 からの full jitter | 見送り。0 または極小待機の連続を許す。 |
| equal jitter・正当 hint 優先・長い hint で停止 | 採用。遅延と上限前の storage エラーが増える。 |
| SDK 自動 runner 置換 | 別途検証。回数・分類・時間予算を一つにできる証明まで採用しない。外側 loop と入れ子にしない。 |
| 前回 transaction ID・session 優先度の引継ぎ | 別途検証後に判断。今回は毎回新 manager・getTransaction を維持する。 |

[固定 Java SDK 6.127.0](https://repo.maven.apache.org/maven2/com/google/cloud/google-cloud-spanner/6.127.0/google-cloud-spanner-6.127.0-sources.jar) は resetForRetry による session 継続・優先度上昇と、multiplexed session の begin(AbortedException) を説明する。[固定 Node SDK 9.1.0](https://registry.npmjs.org/@google-cloud/spanner/-/spanner-9.1.0.tgz) runner は session と multiplexedSessionPreviousTransactionId を保持する。現アプリ入口にはこの引継ぎがない。[Google 一般文書](https://cloud.google.com/spanner/docs/transactions) の優先度説明から現アプリの飢餓を断定しない。

引継ぎは待機中の所有権・解放を変える。通常・multiplexed session、read・commit 時 ABORTED、解放済み session の有効性、前回 ID、公開 peer API を局所 fake backend で検証して別実装を判断する。Node private field を adapter へコピーしない。backoff だけで優先度問題を解決したとは扱わない。

未使用 Java runner の SpannerRetryHelper は回数・時間方針が異なる。Node runner は一部 INTERNAL も再試行し、既定 loop 予算は 1 時間。[一般 timeout 文書](https://cloud.google.com/spanner/docs/custom-timeout-and-retry) から手動入口との同等性を導かない。回数・エラー・hook・解放・時間の実行可能な同等性検証まで runner 置換を見送る。

## D8. 実装受入れ条件と今回の証拠限界

両実装で fake transaction、注入 sleeper・仮想 timer、制御乱数を使い、以下を観測する。

| 検証 | 必要な観測 |
| --- | --- |
| L=0・1・5、全 abort と途中成功 | D2 の回数一致、最終待機なし。 |
| D3 全境界、不正 binary metadata | 判断一致、timer 変換前の ceiling、元 cause 保持。 |
| 複数 hint、Java status と trailers | D3 の優先順、長い正当 hint を短い fallback にしない。欠落と 0 を区別。 |
| k=1..6・巨大 k、u=0 と 1 直前 | D4 両端、累乗 overflow なし、正整数 timer。 |
| timer 解決前・早すぎる解決・仮想時間経過後 | 解決前に次 transaction・body なし。monotonic 時間経過後に一回進む。 |
| D5 エラー・hook | 分類維持、head 再照合、同一封筒・seq_nr、副作用重複なし。 |
| 解放失敗・rollback 失敗 | 既存優先順、待機中 transaction 保持なし。 |
| Java 初回前・待機前・sleep 中・sleep 後の割込み | StorageException、フラグ保持、次試行なし、直前 ABORTED 保持。 |
| Java commit 成功中の割込み | 成功経路完了、再実行なし。Future.cancel の停止保証を主張しない。 |
| JS Promise 放棄・外部 timeout race | retry が cancel されるとは主張しない。 |
| JS peer 互換性 | SDK 8.7.1 と 9.1.0 の実 RetryInfo encode・decode、seconds 表現・未知 protobuf field。 |

今回は固定アプリ入口、Java 公開 source、両固定 SDK package を再取得した。主要 source bytes を継承原本と比較し、継承 major-manifest 55 件の hash も全件照合した。実際の手動 lifecycle と SDK hint 経路を読んだ。純粋な局所境界計算は表の検証であり、adapter 動作の証明ではない。既存 stub・仮想 timer 実験は継承証拠であり、今回は再実行していない。

新しい待機の実装・実 SDK backend 結合・実時間 benchmark・クラウド操作・全アプリ suite は実行していない。peer matrix と Java encoded metadata 結合は後続実装の検証条件。[修正済み契約の独立 review](https://github.com/j5ik2o/event-store-adapter/pull/138#issuecomment-6773696853) を経て、PM は定数・長い hint の停止・割込み挙動・adapter 所有 JS decoder 方針を採用した。実装検証と公開承認は別の条件として残る。
