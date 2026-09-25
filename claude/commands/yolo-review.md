---
description: "yoloラベル付きPRを自動レビューし、問題なければapprove・問題があればコメントを残す"
allowed-tools: ["Bash", "Read", "Grep"]
---

## YOLO Review Command

gh-review-watcher の `on_poll` hook から `yolo` ラベル付きPRに対して自動実行される、
完全自動のPRレビューコマンド。人間の介在なしにレビューとアクションまで完結する。

引数: **$ARGUMENTS**（`{number} {repo}` の形式。例: `123 owner/repo`）

## 前提

- 対話的なプロンプトは一切出さない（非対話・全自動で完結すること）
- PR単位でこのコマンドが繰り返し呼ばれる可能性があるため、既に自分のレビューを
  投稿済みのPRには重複してアクションしないこと

## 実行手順

### 1. 引数のパース
- `$ARGUMENTS` を空白で分割し、1つ目を PR番号 (`NUMBER`)、2つ目を リポジトリ (`REPO`, `owner/repo` 形式) として扱う
- どちらかが欠けている場合は、その旨を出力して終了する

### 2. 重複チェック（冪等性の担保）
- `gh pr view "$NUMBER" -R "$REPO" --json reviews,state,isDraft` でPRの状態を取得
- 以下のいずれかに該当する場合は、理由を出力してアクションせず終了する:
  - PRが既に `MERGED` / `CLOSED` である
  - PRがdraftである
  - 自分（現在の gh 認証ユーザー、`gh api user --jq .login` で取得）による
    レビューが既に存在する

### 3. レビューの実行
- 組み込みの `/review` コマンド（`/review <PR URL>`）でPRをレビューする
- PR URL は `gh pr view "$NUMBER" -R "$REPO" --json url --jq .url` で取得する
- レビュー結果から、マージをブロックすべき問題（バグ・セキュリティ・破壊的変更等）が
  あるかどうかを判定する

### 4. 判定に応じたアクション（全自動）
- **問題なし（approve相当）**の場合:
  - `gh pr review "$NUMBER" -R "$REPO" --approve --body "<レビュー要約> (Auto-reviewed by Claude Code)"`
- **懸念あり（コメント/修正要求相当）**の場合:
  - `gh pr review "$NUMBER" -R "$REPO" --comment --body "<懸念事項の要約>"`
  - 重大なブロッカーがある場合のみ `--request-changes` を使う（安全側に倒し、
    確信が持てない場合は `--comment` にとどめる）

### 5. 実行ログ
- 何をしたか（レビュー結果の要約・実行したアクション・スキップ理由）を標準出力に
  簡潔に出す。この出力は `/tmp/gh-review-watcher-hooks.log` に追記される

## 注意

- ハードコードされた秘密情報やトークンを出力しないこと
- `gh` / `claude` 以外の外部サービスへ情報を送信しないこと
- 判定に迷う場合は破壊的なアクション（approve / request-changes）を避け、
  `--comment` で所見を残すにとどめること
