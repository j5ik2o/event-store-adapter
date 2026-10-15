# 段階 4 の準備状況

各言語の最初のメジャーについて、[実装計画](implementation-plan.md) 5 章の受け入れ条件 1〜6 を満たしているかを確かめた記録である。メジャーを出すかは、言語ごとにオーナーが承認する（4 章の段階 4）。

## 確かめ方（2026-10-13）

各リポジトリの origin/main を読み、CI の実行記録と成果物を見た。ローカルでのビルドや試験はしていない。調べは Sonnet 5.5 の作業者が言語ごとに行い、コーディネーターが結果を確かめた。

| 言語 | 確かめたコミット |
|:--|:--|
| rs | `d442caa` |
| js | `c4e794a` |
| java | `96689fb` |
| kotlin | `0a57b83` |
| scala | `719a491` |
| go | `e80385d` |

## 結果

次の表は、直す前（2026-10-13 の確かめた時点）の判定である。直した後の状態は「対応の結果（2026-10-13）」にあり、6 言語とも受け入れ条件 1〜6 を満たしている。

| 言語 | 1. 適合テストデータ | 2. 項目の形 | 3. CI | 4. 公開 API の設計 | 5. 文書 | 6. 移行の案内 |
|:--|:--|:--|:--|:--|:--|:--|
| rs | 満たさない | 一部 | 満たす | 満たす | 一部 | 満たす |
| js | 一部 | 満たす | 満たす | 満たす | 一部 | 満たす |
| java | 満たす | 満たす | 満たす | 満たす | 一部 | 満たす |
| kotlin | 一部 | 満たす | 満たす | 満たす | 一部 | 満たす |
| scala | 一部 | 満たす | 満たす | 満たす | 一部 | 満たす |
| go | 満たす | 満たす | 満たす | 満たす | 一部 | 満たす |

条件 5 の「一部」には、共通契約の版の呼び名（P-46 の共通契約の版の名前）がそろっていないことを含む。kotlin と go は、それ以外の不足がない。

### 適合テストデータの件数

全言語で、写した適合テストデータのハッシュは v1.0.0 の値と一致し、CI で照合している。DynamoDB Local は digest で固定している（rs は固定する処理がコードにあるが、CI の DynamoDB の枠では DynamoDB Local を起動していない）。FNV-1a 64 の 4 件（hash.md の K-1）は、全言語で理由を付けて対象外にしている。

| 言語 | メモリ（成功・失敗・対象外・未検証） | DynamoDB（成功・失敗・対象外・未検証） | 規則番号ごとの報告 |
|:--|:--|:--|:--|
| rs | 58・0・58・0 | 9・0・14・93 | CI の成果物にある |
| js | 60・0・56・0 | 104・0・12・0 | レポートの JSON にあるが、CI は保存していない |
| java | 60・0・56・0 | 104・0・12・0 | CI の成果物にある |
| kotlin | 60・0・56・0 | 104・0・12・0 | `report.json` にあるが、CI は保存していない |
| scala | 60・0・56・0 | 104・0・12・0 | `report.json` にあるが、CI は保存していない |
| go | 60・0・56・0 | 104・0・12・0 | CI の成果物にある |

rs の DynamoDB の未検証の 93 件は、CI が実行器を DynamoDB の機能なしで動かしているためである。`--require-all` もないので、CI は緑になる。rs の DynamoDB の動きは [PR #19](https://github.com/j5ik2o/event-store-adapter/pull/19) の相互運用の試験で確かめているが、適合テストデータでは確かめていない。

## 不足と対応

| 言語 | 不足 | 対応 |
|:--|:--|:--|
| rs | 適合試験の DynamoDB の枠を CI で実行していない。実行器と移行の実行ファイルの試験も CI で動いていない | [rs#289](https://github.com/j5ik2o/event-store-adapter-rs/issues/289) |
| rs | `AGENTS.md` が旧構成のまま。v3 の移行ガイドに旧版向けの注記がない。設計文書に移行モジュールがない | [rs#290](https://github.com/j5ik2o/event-store-adapter-rs/issues/290) |
| js | 規則番号ごとの報告が CI から見えない。移行ガイドに作業指示の文が残っている。旧版向けの移行ガイドに注記がない。Issue #1017 が開いたまま | [js#1049](https://github.com/j5ik2o/event-store-adapter-js/issues/1049) |
| java | 設計文書の未解決の問い Q7（SDK の `ExecutionInterceptor` の順序と、要求の観測との対応付け）が、実装後も未解決のまま。設計時点の記述「現行の試験は LocalStack を使う」が残っている | [java#730](https://github.com/j5ik2o/event-store-adapter-java/issues/730) |
| kotlin | 規則番号ごとの報告が CI から見えない | [kotlin#846](https://github.com/j5ik2o/event-store-adapter-kotlin/issues/846) |
| scala | 規則番号ごとの報告が CI から見えない | [scala#871](https://github.com/j5ik2o/event-store-adapter-scala/issues/871) |
| go | staticcheck を CI で実行していない（8 章で、現行メジャーの警告を新しいメジャーで解消するとした） | [go#431](https://github.com/j5ik2o/event-store-adapter-go/issues/431) |

共通契約の版の呼び名の統一は、各言語の上の対応に含めた。

## 対応の結果（2026-10-13）

上の不足は、takt（Orca から起動）で直し、コーディネーターが差分・CI・成果物を確かめてマージした。マージ後の main の `CI Success` は、6 言語とも成功している。

| 言語 | PR | 結果 |
|:--|:--|:--|
| rs | [rs#292](https://github.com/j5ik2o/event-store-adapter-rs/pull/292) | 適合試験の DynamoDB の枠を、DynamoDB の機能付きで DynamoDB Local に対して実行し、両方の枠に `--require-all` を付けた。DynamoDB は 116 件のうち成功 102・失敗 0・対象外 14・未検証 0、メモリは成功 58・失敗 0・対象外 58・未検証 0。実行器と移行の実行ファイルの試験も CI で実行する |
| rs | [rs#291](https://github.com/j5ik2o/event-store-adapter-rs/pull/291) | `AGENTS.md` を今の構成に書き直し、v3 の移行ガイドに旧版向けの注記、設計文書に移行の公開名を足した |
| js | [js#1050](https://github.com/j5ik2o/event-store-adapter-js/pull/1050) | 適合試験のレポートを CI の成果物に残し、規則番号ごとの表をジョブの要約に書く。移行ガイドの作業指示の文を消し、旧版向けの移行ガイドに注記を足した。Issue #1017 の 5 件は、対応する適合ケースが通っていることを確かめて閉じた |
| java | [java#732](https://github.com/j5ik2o/event-store-adapter-java/pull/732) | 設計文書の Q7（SDK の割り込み処理の順序と要求の観測の対応付け）を、実装と試験の根拠付きで解決済みにした。LocalStack の記述を DynamoDB Local に直した |
| kotlin | [kotlin#847](https://github.com/j5ik2o/event-store-adapter-kotlin/pull/847) | 適合試験のレポートを JDK ごとに CI の成果物に残し、規則番号ごとの表をジョブの要約に書く |
| scala | [scala#872](https://github.com/j5ik2o/event-store-adapter-scala/pull/872) | 適合試験のレポートを JDK と Scala の版ごとに CI の成果物に残し、規則番号ごとの表をジョブの要約に書く |
| go | [go#432](https://github.com/j5ik2o/event-store-adapter-go/pull/432) | staticcheck を版を固定して CI に足し、警告 1 件を直した |

js・kotlin・scala がジョブの要約に書く規則番号ごとの表は、すべての状態（成功・失敗・対象外・未検証・表せない値）を列に出し、対象外と表せない値の理由を添える。FNV-1a 64 の 4 件（K-1）は、理由付きの対象外として表に出る。rs・go・java は、もとから規則番号ごとの結果を CI の成果物のレポートに残している。共通契約の版の呼び名は、6 言語とも「共通契約 v4」（英語は common contract v4）にそろえ、ハブの仕様へリンクした。この後、契約の名前を v5 に改め、各言語の版を 5.0.0 にそろえることにした（P-46・P-48）。

これで、6 言語とも受け入れ条件 1〜6 を満たした。ただし、その後に契約の名前を v5 に改めたので（P-46）、各言語の文書が「共通契約 v5」に直るまで、条件 5 は満たしていない。直す作業は、5.0.0 を出す準備の PR（版上げの workflow に入力 `version` を足す作業と同じ PR）で行い、下の「公開の結果」のとおり 6 言語とも済んだ。

## 公開の結果（2026-10-13）

オーナーの承認を得て、6 言語の最初のメジャーを 5.0.0 で出した（P-48）。各言語で、版上げの workflow に入力 `version` を足す準備の PR をマージしてから、`version=5.0.0` で起動した。java を先に出し、Maven Central への反映を確かめてから、kotlin・scala の java への依存を 5.0.0 に替えて出した。

| 言語 | 準備の PR | 公開先 | 確かめたこと |
|:--|:--|:--|:--|
| java | [java#735](https://github.com/j5ik2o/event-store-adapter-java/pull/735) | Maven Central | `event-store-adapter-java` 5.0.0 の pom を取得できる。main は `5.0.1-SNAPSHOT` |
| rs | [rs#294](https://github.com/j5ik2o/event-store-adapter-rs/pull/294) | crates.io | 最新の版が 5.0.0 |
| js | [js#1052](https://github.com/j5ik2o/event-store-adapter-js/pull/1052) | npm | `latest` が 5.0.0 |
| go | [go#434](https://github.com/j5ik2o/event-store-adapter-go/pull/434) | Go のプロキシ | module のパスを `/v5` にした。`v5.0.0` の情報を取得できる |
| kotlin | [kotlin#851](https://github.com/j5ik2o/event-store-adapter-kotlin/pull/851)、[kotlin#853](https://github.com/j5ik2o/event-store-adapter-kotlin/pull/853)（java 5.0.0 への依存） | Maven Central | `event-store-adapter-kotlin` 5.0.0 の pom を取得できる |
| scala | [scala#874](https://github.com/j5ik2o/event-store-adapter-scala/pull/874)、[scala#875](https://github.com/j5ik2o/event-store-adapter-scala/pull/875)（java 5.0.0 への依存） | Maven Central | Scala 2.13 用と 3 用の 5.0.0 の pom を取得できる |

6 言語とも GitHub に v5.0.0 のリリースがある。java の 2.0.0 は、版をそろえる決定の前に出した版で、中身は 5.0.0 と同じである。README と 2.0.0 の GitHub のリリースの説明で、5.0.0 を使うよう案内している。

## 適合テストデータの外の規則の確認と 5.0.1（2026-10-13）

5.0.0 を出した後に、v5 の仕様が定める 71 の規則のうち、適合テストデータ 1.0.0 が扱っていない 25 の規則を、6 言語の v5.0.0 のコードと試験で確かめた（読み取りだけ）。kotlin・scala は java の実装に任せているので java と合わせて見た。

71 は、共通契約の 45、DynamoDB の 13、メモリの 13 の規則である。2026-10-14 にキーに使うハッシュの K-1・K-2 も v5 で確定したので（[仕様](../spec/README.md) の P-49）、v5 の規則は 73 になった。2 つとも、ハッシュを使う保存先を持たない最初のメジャーでは対象外である。K-1 は適合テストデータの 4 件が扱い、6 言語とも対象外と報告している。K-2（ハッシュの値をシャード数で割らない）は、適合テストデータが扱わない。この確認は P-49 より前に行ったので、K-1・K-2 を数に入れていない。

| 言語 | 満たす（試験あり） | 満たす（コードのみ） | 一部 | 満たさない | 対象外 |
|:--|--:|--:|--:|--:|--:|
| rs | 10 | 4 | 3 | 0 | 8 |
| js | 13 | 1 | 3 | 0 | 8 |
| java（kotlin・scala を含む） | 13 | 3 | 1 | 0 | 8 |
| go | 13 | 2 | 2 | 0 | 8 |

対象外の 8 つは、最初のメジャーで提供しない変更フィードと Streams に関する規則（F-1〜F-5 のヘッド遷移の生成と購読側の義務、DY-13 の Streams のレコードの読み方、DY-15 の再同期）と、プロファイルに前提を書くという仕様の側の義務（SP-1）である。見つけた不足を、オーナーの承認を得て 5.0.1 で直した。

| 不足 | 直したこと | PR |
|:--|:--|:--|
| rs のメモリが、保持件数なしの TTL を設定エラーにしない（MEM-3・MEM-12 との食い違い） | TTL の指定はすべて設定エラー。理由に `MemoryTtlUnsupported` を足した | [rs#296](https://github.com/j5ik2o/event-store-adapter-rs/pull/296) |
| js のメモリが、登録されていない保存先と想定外の設定を生成時に設定エラーにしない（MEM-1・MEM-3） | 生成時に設定エラー | [js#1054](https://github.com/j5ik2o/event-store-adapter-js/pull/1054) |
| go のメモリが、不明な保持方式の値を受け付ける（MEM-3）。`-race` を実行していない | 設定エラーにした。CI の試験を `-race` 付きにした | [go#436](https://github.com/j5ik2o/event-store-adapter-go/pull/436) |
| java のメモリが、null の保存先で `NullPointerException` を投げる | `ConfigurationException` にした。値の書き換え（JSON のペイロード）と非同期のストアの並行呼び出しの試験を足した | [java#737](https://github.com/j5ik2o/event-store-adapter-java/pull/737) |
| 6 言語とも、単一リージョンの前提（DY-18）と単一プロセスの前提（MEM-1）を文書に書いていない | 6 言語で同じ文言を README とスキーマ文書に足した | 上の 4 つと [kotlin#854](https://github.com/j5ik2o/event-store-adapter-kotlin/pull/854)・[scala#876](https://github.com/j5ik2o/event-store-adapter-scala/pull/876) |

6 言語とも 5.0.1 を出した（kotlin・scala は java 5.0.1 に依存）。DY-19（Scan を使わず、1 つの集約に絞った要求だけを使う）は 6 言語とも実装は満たしているが、直接確かめる試験がないので、適合テストデータの拡張（1.1.0）で扱う。1.1.0 は 2026-10-14 にハブに置いた（実装計画 6 章）。

## メジャーを出すときにやること

- 順番は 4 章のとおり、java を先に出し、kotlin・scala は java への依存を `2.0.0-SNAPSHOT` から正式版の java 5.0.0 に替えてから出す（P-48）。
- 版上げの workflow は、入力 `version` に 5.0.0 を指定して起動する（P-48。実装計画 3 章）。
- rs は、CHANGELOG の `[Unreleased]` を版の見出しに替える（5.0.0 のときの手順。2026-10-15 から CHANGELOG は更新せず、変更の記録はリリースノートだけにした。運用方針 1 章の「リリースノート」）。
- java・kotlin・scala は、README などにある Snapshot の版の記述と、Snapshot 用のリポジトリの案内を直す。kotlin・scala の README は、導入の版がまだ仮の記述である。
- java の版上げと Maven Central への公開は、2.0.0 で初めて通る。

## 気づき（範囲外）

- scala の CI には毎時の定期実行がある（2023-09-12 のコミット `eb6b383` で入った）。CI の成功のたびに Snapshot を公開する。
- go の版上げの workflow は、版を上げるコミットを main に push する。2026-10-05 の v1.0.197 でも、この形で main に push できている（コミット `1054cf2`）。
- js・go・java・kotlin・scala には CHANGELOG がない。リリースノートは版上げの workflow が作る。rs も 5.0.2 から CHANGELOG を更新しない（運用方針 1 章の「リリースノート」）。
