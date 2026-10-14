# 公開 API の形（試験中）

共通契約 v5 が各言語の公開 API に求める「形」を、言語に依存しない JSON で書いたものです。各言語は、自分の公開 API がこの形を満たしているかを CI で照合します。

**状態: 6 言語で照合を入れた（0.1.0、2026-10-14）。** 2026-10-14 に go で照合を試作し、ずれを検出できることを確かめた（[ハブの PR #28](https://github.com/j5ik2o/event-store-adapter/pull/28)）。オーナーは段階的な採用を決め、同じ日に 6 言語の CI に照合が入った（下の「各言語の照合の方式」）。まだ受け入れ条件ではない（[実装計画](../docs/plan/implementation-plan.md) の 5 章は変えていない）。受け入れ条件に入れるかは、オーナーが決める。

## 何を書くか、何を書かないか

書くのは、仕様が言語に関係なく決めていることだけです。

- 2 つの封筒の要素と、構築時に必須の要素（1.2・1.4、T-2・T-10）
- 最新のスナップショットの読み取りが返す組（3.4、R-2）
- ストアの 4 つの操作の入力と出力（3 章）
- エラーの 5 つの分類（4 章、E-1）

書かないのは、仕様が言語に任せていることです。

- 名前の綴り（`persist_event` / `persistEvent` / `PersistEvent`）
- 失敗の返し方（`Result`、例外、`error` の値）と、非同期かどうか
- 組の表し方（構造体、タプルなど）、「なし」の表し方（`Option`、`null`、`undefined`、ポインタ）
- 言語の作法で足す引数（go の `context.Context` など）

振る舞い（照合、保持、エラーの分類の条件など）は、この形では表せません。振る舞いは [適合テストデータ](../conformance/README.md) で確かめます。

## 書き方

| 書き方 | 意味 |
|:--|:--|
| `P`・`A` | 利用者が決める型（イベントのペイロード、集約の状態）。言語の型の引数で表す |
| `aggregate_id`・`seq_nr`・`timestamp`・`string` | 値の種類。意味は `value_types` に書いた |
| `optional<T>` | `T` があるか、ないか |
| `list<T>` | `T` の列（順序あり） |
| `none` | 成功のときに返す値がない |
| `required: true` | 構築時に必ず与える要素。`required: false` は省略でき、省略時は `default` の値になる |

## 各言語での照合

各言語のリポジトリは、次の 2 つを持ちます。

1. この `surface.json` の写し（`api-surface/surface.json`）。CI で、下の SHA-256 と一致することを確かめる（適合テストデータと同じ配り方）。
2. 名前の対応表（`api-surface/<言語>.json` など）。共通の名前（`event_envelope`、`occurred_at` など）を、その言語の公開 API の名前と型に対応させる。対応表は各言語のリポジトリだけに置き、ハブは持たない。

照合の試験は、少なくとも次を確かめます。

- 各型と、その要素を読む手段（フィールド、取得の関数など）がある。要素の型が、値の種類と合う。
- 構築の手段（関数、ビルダーなど）が、`required: true` の要素を必ず受け取り、`required: false` の要素を省略できる。
- ストアの 4 つの操作があり、入力と出力が合う（失敗の返し方と非同期の包み方は、言語の対応表が決める）。
- エラーの 5 つの分類を、呼び出し側が型か値で区別できる。

照合の試験は、形をわざとずらしたとき（要素を消す、名前を変える、型を変える、分類を消すなど）に、それを報告できることも試験で示します。

## 各言語の照合の方式

| 言語 | 公開 API の読み方 | 否定の試験で確かめたずれ | PR |
|:--|:--|:--|:--|
| go | `go/types`（ソースを読む importer） | 要素の欠落・名前の変更・型の変更、構築の関数の必須の引数の欠落、操作の戻り値、エラーの分類の欠落、型の引数の制約、対応表の抜け | [go #438](https://github.com/j5ik2o/event-store-adapter-go/pull/438) |
| java | リフレクション（ビルダーは実際に呼んで必須の要素を確かめる） | 要素の欠落・名前の変更・型の変更、必須の要素の省略、ビルダーの引数の型、操作の戻り値、型の引数の制約、同期・非同期のストアの対応の抜け | [java #740](https://github.com/j5ik2o/event-store-adapter-java/pull/740) |
| js | TypeScript のコンパイラ API（型を当てはめる試しのファイルを作る） | 要素の欠落・名前の変更・型の変更、省略できる要素の誤り、操作の戻り値、エラーの分類の欠落、型の引数の制約、型を公開しなくなったこと | [js #1058](https://github.com/j5ik2o/event-store-adapter-js/pull/1058) |
| rs | 日付を固定した nightly の rustdoc の JSON（`rustdoc-types`） | 要素の欠落・名前の変更・型の変更、構築の関数の必須の引数の欠落、操作の戻り値（`async_trait` の書き換えの中まで。`Future` が `Send` を持つことも）、エラーの分類の欠落、型の引数の制約、対応表の抜け | [rs #298](https://github.com/j5ik2o/event-store-adapter-rs/pull/298) |
| kotlin | `kotlin-reflect` | 操作の欠落と戻り値、`suspend` でない非同期の操作、なしを表せない戻り値、型の引数の制約、同期・`suspend` のストアや例外の基底の対応の抜け | [kotlin #857](https://github.com/j5ik2o/event-store-adapter-kotlin/pull/857) |
| scala | Java のリフレクション（総称型の情報を含む） | 操作の戻り値（`Try`・`Future`・`Option` の包み方）、`SnapshotReadResult` の要素の欠落、型の引数の制約、ストア・要素・例外のクラスの対応の抜け | [scala #879](https://github.com/j5ik2o/event-store-adapter-scala/pull/879) |

kotlin と scala は java の封筒と例外をそのまま使うので、封筒の要素と例外の分類の形は java の照合に任せ、クラスが解決できることだけを確かめる。kotlin は自分のストアの操作（`SnapshotReadResult` も java のもの）、scala は自分のストアと `SnapshotReadResult` を照合する。各言語で確かめられないこと（scala の `implicit` の印や `AnyRef` の上限など）は、各言語の `api-surface/README.md` に書いた。

## 版と SHA-256

| 版 | `surface.json` の SHA-256 |
|:--|:--|
| 0.1.0 | `37c91f8f94e10c73513a9c1deef990ea4deea96d5001ae700d6bf799658d0e32` |
