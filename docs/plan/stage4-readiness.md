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

| 言語 | 1. 適合テストデータ | 2. 項目の形 | 3. CI | 4. 公開 API の設計 | 5. 文書 | 6. 移行の案内 |
|:--|:--|:--|:--|:--|:--|:--|
| rs | 満たさない | 一部 | 満たす | 満たす | 一部 | 満たす |
| js | 一部 | 満たす | 満たす | 満たす | 一部 | 満たす |
| java | 満たす | 満たす | 満たす | 満たす | 一部 | 満たす |
| kotlin | 一部 | 満たす | 満たす | 満たす | 一部 | 満たす |
| scala | 一部 | 満たす | 満たす | 満たす | 一部 | 満たす |
| go | 満たす | 満たす | 満たす | 満たす | 一部 | 満たす |

条件 5 の「一部」には、共通契約の版の呼び名（P-46 の「共通契約 v4」）がそろっていないことを含む。kotlin と go は、それ以外の不足がない。

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

## メジャーを出すときにやること

- 順番は 4 章のとおり、java を先に出し、kotlin・scala は java への依存を `2.0.0-SNAPSHOT` から正式版に替えてから出す。
- 版上げの workflow は、`level` を major にして起動する。js は `feat!:` の件名がないので、`auto` では minor になりうる。
- rs は、CHANGELOG の `[Unreleased]` を版の見出しに替える。
- java・kotlin・scala は、README などにある Snapshot の版の記述と、Snapshot 用のリポジトリの案内を直す。kotlin・scala の README は、導入の版がまだ仮の記述である。
- java の版上げと Maven Central への公開は、2.0.0 で初めて通る。

## 気づき（範囲外）

- scala の CI には毎時の定期実行がある（2023-09-12 のコミット `eb6b383` で入った）。CI の成功のたびに Snapshot を公開する。
- go の版上げの workflow は、版を上げるコミットを main に push する。2026-10-05 の v1.0.197 でも、この形で main に push できている（コミット `1054cf2`）。
- go・java・kotlin・scala には CHANGELOG がない。リリースノートは版上げの workflow が作る。
