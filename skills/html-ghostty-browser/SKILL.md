---
name: html-ghostty-browser
description: HTML の説明ドキュメントを作成し、ghostty-browser コマンドで Ghostty の新規タブに表示する（試験的）。「html-ghostty-browser」「ghostty で解説を開いて」などと指示された場合に使う。macOS + Ghostty 専用。
---

# HTML を作って ghostty-browser で開く（試験的）

`html` スキルで HTML の説明ドキュメントを作り、生成物を `ghostty-browser`
コマンドで Ghostty の新規タブに表示する。`html` スキルとの違いは表示手順を
持つ点だけで、HTML そのものの作り方は `html` スキルに完全に従う。

`ghostty-browser` は Ghostty の新規タブを（herdr の外側に）開き、そこで
terminal-browser に URL を読み込ませる。herdr-browser plugin が不安定なため
の代替手段で、herdr のグラフィックスパイプラインを経由しない。

## 手順

1. **HTML を作る** — `html` スキルの規則（成果物・デザインシステム・構成・図・
   コード・数式）にそのまま従う。デザインシステムのアセット（`document.css`、
   `math-copy.js` など）は `html` スキル配下の `design-system/` を参照する。
2. **ghostty-browser で開く** — 保存した HTML の**絶対パス**を `file://` URL に
   して渡す。

```bash
ghostty-browser "file:///absolute/path/to/output.html"
```

> ⚠️ **必ず絶対パスを渡す。** `ghostty-browser` は新しいタブを開いてそこで
> コマンドを実行するため、カレントディレクトリが変わる。`./report.html` の
> ような相対パスは解決できない。`file:///Users/.../report.html` のように
> ルートから書くこと。

## 条件とフォールバック

- macOS + Ghostty 1.3 以上でのみ動作する。`ghostty-browser` が見つからない
  （`command -v ghostty-browser` が失敗する）場合は表示をスキップし、保存先の
  絶対パスをユーザーに伝えるにとどめる。
- パス内スペースにも注意する。同じファイルを更新した場合も同手順で開き直して
  よい（新しいタブが開く）。
- 初回実行時に Ghostty の Automation（オートメーション）権限を求められることが
  ある。コマンドが失敗した場合はエラーを握り潰さず報告し、保存先パスの提示に
  フォールバックする。
