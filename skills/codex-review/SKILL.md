---
name: codex-review
description: |
  codex review コマンドを使ってコードレビューを非インタラクティブに実行するスキル。
  トリガー: "codex-review", "codexでレビュー", "codex reviewして"
  使用場面: 未コミット変更・特定ブランチ差分・特定コミットのレビュー
allowed-tools: Bash(codex review*)
---

# codex-review

`codex review` コマンドを使ってコードレビューを実行し、結果をそのまま返すスキル。
tmuxのやり取りは不要。コマンドを実行して結果を受け取るだけ。

## コマンド形式

```bash
# 未コミットの変更をレビュー
codex review --uncommitted

# 特定ブランチとの差分をレビュー
codex review --base <branch>

# 特定コミットをレビュー
codex review --commit <SHA>

# カスタム指示を追加する場合
codex review --uncommitted "日本語で指摘してください"
```

## 実行手順

1. ユーザーの意図を確認してモードを選ぶ
   - 未コミット変更 → `--uncommitted`
   - ブランチ差分 → `--base <branch>`
   - コミット指定 → `--commit <SHA>`
2. カレントディレクトリがプロジェクトルートか確認する（必要なら `-C <dir>` を使う）
3. `codex review` を実行して結果を受け取る
4. 結果をユーザーに報告する
