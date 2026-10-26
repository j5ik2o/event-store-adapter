> この文書は [README.md](README.md) の日本語版です。英語版が正本で、食い違うときは英語版に従います。

# main の CI の失敗を issue で知らせるワークフロー

6 言語のリポジトリに同じ内容で写す、main の CI の失敗を知らせるワークフローの正本。

| ファイル | 役割 |
|---|---|
| `main-ci-failure.yml` | 各リポジトリの `.github/workflows/` に写すワークフロー |

## 何をするか

CI のワークフローが main で完了したとき（`workflow_run`）、元の実行のきっかけが `push` か `schedule`（定期実行）のものだけを扱う。

- 結論が `failure`・`timed_out`（時間切れ）・`startup_failure`（起動の失敗）: ラベル `ci-failure-on-main` の付いた開いている issue を探す。なければ issue を作り、あればその issue にコメントを足す。本文とコメントには、元の実行の URL、コミット、きっかけ、失敗したジョブの名前を書く。
- 結論が `success`: 開いている issue があれば、成功した実行の URL をコメントして閉じる。CI の実行は重なりうるので、issue に記録した最後の失敗より新しい成功でだけ閉じる。新しさは、CI のワークフローの実行番号（`run_number`）と試行の回数（`run_attempt`。流し直すと増える）で比べるので、失敗した実行を流し直して成功した場合も閉じる。
- ラベルがなければ作る。

同時に動く数は制限しない。制限すると、待っている知らせが後の知らせに置き換えられて消えることがあるからである。その代わり、2 つの失敗がほぼ同時に終わると、issue が 2 つできることがある。

`CI Success` の外の検査の失敗も、`CI Success` 自体の失敗も、CI のワークフローの失敗として同じように扱う。使うのは GitHub の issue とその通知だけで、外部への通知や Secret は使わない。権限は `issues: write` と `actions: read` だけ。

## 各リポジトリへの写し方

1. `main-ci-failure.yml` を、そのリポジトリの `.github/workflows/main-ci-failure.yml` に写す。
2. ファイルの `on.workflow_run.workflows` の 1 か所だけを、そのリポジトリの CI のワークフローの `name:` に合わせる。rs は `ci`、ほかの 5 つは `CI`（正本は `CI`）。ほかは替えない。

## 写した後の確かめ方

1. 写したワークフローを main に入れる。
2. Actions の `main-ci-failure` を `workflow_dispatch` で実行し、入力 `run_id` に、過去の失敗した main の CI の実行の ID（push か定期実行のもの）を渡す。
3. ラベル `ci-failure-on-main` の付いた issue ができたことを見る。
4. 確かめ終わったら、その issue を閉じる。

過去の成功した実行の ID を渡すと、開いている issue を閉じる処理も確かめられる。

## `CI Success` の依存に入れない

このワークフローは知らせるだけで、マージを止める仕組みではない。CI の `CI Success` の依存にも、ブランチ保護の必須の検査にも入れない。
