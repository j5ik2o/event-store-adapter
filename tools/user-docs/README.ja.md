> この文書は [README.md](README.md) の日本語版です。英語版が正本で、食い違うときは英語版に従います。

# 利用者向けの文書の照合の道具

`check.py` は、リポジトリの利用者向けの文書が [`user-docs/`](../../user-docs/README.ja.md) の型に従っているかを照合する。Python 3.11 以上で動き、標準ライブラリだけを使う。ネットワークには接続しない。

## 動かし方

リポジトリのルートで実行する。

```sh
python3 tools/user-docs/check.py
```

`user-docs/template.json`（写した型）と `user-docs/repo.json`（リポジトリの設定）を読む。別の場所を照合するときは、そのルートを渡す。

```sh
python3 tools/user-docs/check.py --root DIR
```

誤りはすべて集めて、ファイルのパスと行番号を付けて標準エラーに出し、終了コードは 1 になる。誤りがなければ、照合した文書の数を出して 0 で終わる。

照合するのは、型が求める文書が英語と日本語の両方にあること、H1 と H2（と「Storages」の下の H3）、H3 の数が英語と日本語で等しいこと、日本語の文書の先頭の一行、相対リンク、型の外の文書、移ったことを示すファイル、`docs/` の直下の `.md` がすべて説明のつくものであること、である。文章の中身は照合しない。

## 試験の動かし方

```sh
python3 -m unittest discover -s tools/user-docs -p 'test_*.py'
```

試験は、一時ディレクトリに小さな文書の木を作り、照合の道具を実行して確かめる。

## 各リポジトリへの写し方

1. `user-docs/template.json` と `tools/user-docs/check.py` を、同じ内容で写す。
2. `user-docs/repo.json` を書く（[`user-docs/README.ja.md`](../../user-docs/README.ja.md) を参照）。
3. CI の `CI Success` が依存するジョブで、`sha256sum -c` により写しを SHA-256 の固定値と照合し、続けて `python3 tools/user-docs/check.py` を実行する。

ハブで型や照合の道具を変えたときは、2 つのファイルを写し直し、SHA-256 の固定値を更新する。
