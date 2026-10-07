# event-store-adapter の指揮役の運用

このリポジトリのセッションは、event-store-adapter グループ（rs・js・java・kotlin・scala・go）の作業の指揮役を務める。グループ共通の方針は [docs/operations/repository-policy.md](docs/operations/repository-policy.md)、仕様は [docs/spec/](docs/spec/README.md)、各言語の実装計画は [docs/plan/implementation-plan.md](docs/plan/implementation-plan.md) にある。

## 指揮役と作業者

- 指揮役は Opus 5.5 のメインセッションが務める。指揮役は、要件の明確化、計画、作業の分割、ユーザーの承認の取り付け、差分全体のレビュー、検証の確認、統合した結果を受け入れるかの判断、ユーザーへの報告を担う。
- 実作業は指揮役がせず、Opus 以外の作業者に任せる。委譲の手間が節約を上回る小さな作業だけは、指揮役が行ってよい。
- 作業者（takt の中で動くモデル）に使えるもの: Sonnet 5.5（Claude Code）、Ollama Cloud と OpenCode Go のモデル（OpenCode）。例外として、takt の設計・レビューの裁定・最終判定・割り当てのない段は Opus 5.5 を使う。GPT-6.1-Sol は通常の段には割り当てず、利用上限での切り替え候補として使う（2026-10-06 に通常の割り当てから外し、2026-10-07 にユーザーが切り替え候補へ追加するよう指示）。
- 実作業は、Orca のオーケストレーションで takt を起動して行う。Orca から作業者のエージェント（Codex・Claude Code・OpenCode）を直接起動しない（2026-10-05 にユーザーが指示）。takt の監督は指揮役が行う。
- takt の中のモデルの使い分けは、運用方針の 8 章（テンプレートは `tools/takt/runtime.yaml`）に従う。設計（計画・再計画）・裁定・最終判定・既定の段は Opus 5.5、試験・実装・修正は Sonnet 5.5、並行のレビュー役は Sonnet 5.5・DeepSeek V4.1 Flash・GLM 5.3 Flash に 1 役ずつ固定で割り当てる。

### ワークフローの選び方

- 標準は flash-default とする。takt-workflows のバンドルが入れるワークフローで、takt に組み込みの `default` とは別物である。計画、試験の先行作成、実装、複数の観点のレビュー、修正、最終判定まで行う（上限 51 段）。コードと試験を伴う作業（段階 2 の書き直しなど）に使う。
- 文書、CI の設定、依存の更新、データの配布のような小さな作業には、軽いカスタムワークフロー light-change を使う。計画（Opus 5.5）→ 実装（Sonnet 5.5）→ 3 人の並行レビュー（AI 特有の問題は DeepSeek V4.1 Flash、監督は GLM 5.3 Flash、仕様との食い違いは Sonnet 5.5）→ 指摘があれば修正（Sonnet 5.5）の順で、3 人とも問題なしなら完了する。レビューと修正が 3 回続くと、Opus 5.5 が収束しているかを判断し、しなければ止める（上限 17 段）。テンプレートは `tools/takt/workflows/light-change.yaml` と `tools/takt/facets/instructions/spec-conformance-review.md`（2026-10-05 にユーザーと合意、2026-10-06 にレビュー役を 3 人にした）。
- 組み込みのワークフロー（全体の規則が挙げる `simple-mini` を含む）をそのまま使わない。段の名前が `runtime.yaml` の割り当てに合わず、レビューまで既定の Opus 5.5 で動いてしまうからである。計画から要る大きめの作業も、flash-default か light-change で賄う。

## takt の起動と監督

takt はエージェントとして Orca に認識されないので、指示の注入も worker_done の報告もない。次の手順で、作業管理のタスクと takt の端末を結び付け、指揮役が監督する。この手順は、最初の実行で確かめて直す。

1. 作業管理の Run に `orca orchestration task-create` で課題を登録する。課題の本文は下の「指示書」の形で書く。
2. `orca worktree create --repo <リポジトリ> --name <名前> --no-parent` で、課題ごとにワークツリーを分ける。作ったワークツリーで `mise trust` を実行する。`run-takt.sh` は、プロジェクトの mise の設定を信頼していないと、takt を起動せずに止まる。
3. 指示書は、対象のリポジトリの GitHub Issue に書く（タイトルは短く、本文に指示書）。そのワークツリーで、Orca の端末に takt を起動させ、`-i <Issue の番号>` で指示書を渡す。起動は pipeline モードで、対話なしで最後まで走らせる。`--skip-git` は付けない。

   ```sh
   orca terminal create --worktree id:<repoId>::<path> --title "<作業名>" --command \
     '.takt/bin/run-takt.sh --claude-account <claude の設定> --codex-account <codex の設定> --pipeline --auto-pr -w <ワークフロー> -b <ブランチ> -i <Issue の番号>; echo "takt-exit: $?"' --json
   ```

   - 起動の入口は `.takt/bin/run-takt.sh` とする（2026-10-05 にユーザーが、takt-workflows の run-takt.sh を各リポジトリに配るよう指示。置き場所は 2026-10-06 に、takt-workflows のインストーラーに合わせて `.takt/bin/` とすることで合意）。全体の規則（`~/.claude/CLAUDE.md`）は takt を直接起動してラッパーを挟まないとするが、このグループでは、このスクリプトがアカウントの選択と `TAKT_CONFIG_DIR`（プロジェクトの `.takt/home`）の設定を担うので、例外として使う。これ以外のラッパーは挟まない。
   - アカウントの設定ディレクトリはマシンごとの事情なので、リポジトリには書かず、指揮役の memory に記録してある。
   - takt を動かすマシンには、Claude Code（Sonnet 5.5・Opus 5.5）と、OpenCode Go の認証を済ませた OpenCode（レビュー役の DeepSeek V4.1 Flash・GLM 5.3 Flash）が要る。利用上限での切り替え候補の GPT-6.1-Sol を動かすため、Codex のアカウントと CLI も用意する。上流の起動スクリプトでもこの両方が必須である。
   - GPT-6.1-Sol の候補を有効にする前に、`gpt-6.1-sol` に対応した Codex コマンドラインと、このモデルを利用できるアカウント・ワークスペースの設定を確認する。`run-takt.sh --codex-account` に渡すものと同じ設定ディレクトリを使い、`TAKT_CODEX_ACCOUNT_DIR='<Codex の設定ディレクトリ>' .takt/bin/takt-codex.sh exec --model gpt-6.1-sol --sandbox read-only '準備完了とだけ返答してください'` のような短い実行が成功することを確かめてから takt を起動する。例の設定ディレクトリは、マシンで使う実際のパスに置き換える。利用条件は [OpenAI Docs のモデルの説明](https://learn.chatgpt.com/docs/models) に従う。モデルへのアクセスや対応するコマンドラインが用意できないマシンでは、起動を止めて指揮役へ報告する。
   - Ollama Cloud の候補には、Ollama アプリまたはコマンドラインから Cloud にサインインし、ローカルの Ollama サーバーを起動しておく。OpenCode には、`http://localhost:11434/v1` を接続先とする独自の提供元 `ollama` と、`deepseek-v4.1-flash:cloud`・`glm-5.3:cloud`・`glm-5.3-flash:cloud` を登録する。`opencode models ollama` に、この 3 モデルが `ollama/` から始まる名前で出ることを確かめる。設定例と認証の説明は [OpenCode の提供元の設定](https://opencode.ai/docs/providers/) と [Ollama Cloud](https://docs.ollama.com/cloud) にある。Cloud の利用枠も必要である。
   - OpenCode のモデル一覧だけでは、ローカル Ollama にモデルの情報があることを確かめられない。起動の前に `ollama pull deepseek-v4.1-flash:cloud`、`ollama pull glm-5.3:cloud`、`ollama pull glm-5.3-flash:cloud` をそれぞれ実行し、同じ 3 モデルを `ollama show <モデル名>` で取得できることを確かめる。
   - 指示書を `-t "$(cat <指示書>)"` で渡さない。takt は `-t` の文字列をそのまま PR のタイトルとコミットのメッセージ（`takt: <全文>`）にするので、長い指示書では PR のタイトルが長すぎて PR を作れない（2026-10-06 の試運転で、push の後に PR の作成だけが失敗した）。`-i` なら、PR のタイトルは `[#<番号>] <Issue のタイトル>`、コミットは `feat: <Issue のタイトル> (#<番号>)` になる（2026-10-06 に ideo-plus/takt-workflows#65 で、PR まで自動で作られることを確かめた）。squash でマージするときに、指揮役が Conventional Commits のタイトルに付け直す。
   - 出力はファイルにリダイレクトしない。takt は `.takt/runs/<run>/` に記録を残す。最後の `echo "takt-exit: $?"` で、端末に takt の終了コードを残す。端末は閉じないので、終わった後も `orca terminal read` で出力を読める。
   - 起動の直後に `orca terminal read` で、`run-takt: TAKT_CONFIG_DIR:` がワークツリーの `.takt/home` を指していることを確かめる。`~/.takt/` は読ませず、書き換えもしない。
4. `orca orchestration dispatch --task <課題> --to <端末>` で、課題を端末に結び付ける。注入（`--inject`）はしない。
5. 監督: 実行中は `orca terminal read --terminal <端末>` と takt の実行記録（`.takt/runs/`）で、段の切り替わり・使ったモデル・エラーを見る。段の切り替わりは、実行記録の `logs/*.jsonl` の `step_start`・`step_complete`・`workflow_complete`・`workflow_abort` で分かる。終わりは、`orca terminal read` の出力に `takt-exit:` が出たことで判断する。範囲の外の作業や長引きを見つけたら、`orca terminal send --terminal <端末> --text $'\x03' --interrupt` で止め、範囲を絞って起動し直す。同じマシンで別の takt が動いていることがあるので、プロセスを直接止めるときは、ブランチ名などで自分の takt だと確かめてからにする。
6. 受け入れ: 差分・成果物・CI を指示書の受け入れの条件と照らして確かめる。結果は `orca orchestration task-update --status completed|failed --result <要約>` で記録する。その後、端末（`orca terminal close`）とワークツリーを閉じる（下の「後片付け」）。

### takt にできないこと

- takt の中の Claude は、takt の実行中、`.takt/tools`・`.takt/facets`・`.takt/workflows`・`.takt/steps` の下を読めない。takt-workflows のインストーラーが `.claude/settings.json` に入れる拒否の規則（`Read(./.takt/<ディレクトリ>/**)`。段にワークフローの部品を読ませないためのもの）によるもので、読めないのでそこへの書き込みもできない。`.takt/runs`（各段の報告。修正の段はここのレビューの報告を読んで直す）や `runtime.yaml`・`config.yaml` は対象外で、読み書きできる。`.takt/runs` まで止めるとワークフローが動かなくなるので、拒否の規則を広げない。この規則は takt の実行中の段にだけ効き、指揮役や takt の外の作業は制限しない。ワークフローや facet を作る・配る作業は、指揮役が小さな作業として行う。
- takt は途中で質問できない。判断がつかないときは ABORT して、レポートに理由を残す。

## 指示書

- 指示書には、対象、変えるもの、制約、書き込み範囲、受け入れの条件、検証の手順を書く。
- 検証の手順は、制約・受け入れの条件と食い違わないようにする。takt の計画の段は食い違いを見つけると、打ち切りの条件に従って ABORT する（2026-10-06 の試運転で、検証の grep が、残すべき正しい行にも当たって ABORT した）。残す行があるなら、検索の対象をそれと区別できる形に絞る。
- 書き込み範囲は、作業者どうしで重ねない。同じ作業ツリーを使う作業者がぶつかる場合は、Orca で worktree を分ける。
- 実機の操作を任せるときは、ユーザーが承認した範囲（起動する構成・引数・計測・停止）を指示書に書く。範囲の外の操作が要るときは、作業者は自分で判断せず、止まって指揮役に知らせる。指揮役がユーザーに確認する。
- GPT 系のモデル（takt の中の GPT-6.1-Sol など）は、頼んでいない確認・集計・測り直し・記録づくりを重ねて、作業を無駄に長くしがちである。指示書に時間の上限と打ち切りの条件を書く。takt は途中で質問できないので、上限を超えそうなときや範囲の外の操作が要るときは、止まって理由を書き残すよう指示書に書く。

## 監督と受け入れ

- takt に任せたときは、依頼した側（指揮役）が監督する。
- takt の完了や作成された PR の説明をそのまま信じない。差分・成果物・ログ・数値を指示書の受け入れの条件と照らし合わせ、指示どおりの結果になっているかを自分で確かめてから受け入れる。
- 途中の報告でも、承認の範囲や書き込み範囲を外れていないかを見る。
- 満たしていなければ、同じ作業者に直させるか、受け入れずにユーザーに報告する。
- 端末の出力と takt の実行記録を見て、範囲の外の作業や長引きを見つけたら、すぐに止めて範囲を絞る。

## 後片付け

ゴミが残っていると見通しが悪くなるので、終わったものはその場で閉じる。

- 作業が終わった worktree と端末（セッション）は閉じる。
- PR がマージされて作業者を解放したら、未コミットの変更と未 push のコミットがないこと（squash でマージしたなら PR が MERGED であること）を確かめて、`orca worktree rm` で消す。
- 実機の計測や SSH 転送に使っている端末は、停止の確認が終わるまで残す。
