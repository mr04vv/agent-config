# Vendored skills

`skills/` 以下には、外部リポジトリから取り込んだ（vendoring した）スキルが含まれる。
このファイルはその出所と更新手順の記録。デプロイ対象外（`skills/` の外に置いてある）。
上流のライセンス本文は `licenses/` に置いている（ponytail 含め MIT、herdr のみ Apache-2.0）。

## mathbullet/skills

- Upstream: https://github.com/mathbullet/skills
- License: MIT (Copyright (c) 2026 mathbullet)
- 取り込み時点のコミット: `fe96c626b39abba47fad2d4a4ef738e8a27602b1` (2026-08-02)

| スキル | 上流パス | 取り込み理由 |
| --- | --- | --- |
| `paper-details` | `plugins/paper-details/skills/paper-details` | 依頼された本体 |
| `html` | `plugins/html/skills/html` | 依頼された本体 |
| `documenting-with-sources` | `plugins/documenting-with-sources/skills/documenting-with-sources` | `paper-details` の必須依存 |
| `writing-quotation` | `plugins/writing-quotation/skills/writing-quotation` | `paper-details` の必須依存 |
| `explain` | `plugins/explain/skills/explain` | `html` の推奨併用スキル |

### 実行時の外部依存

- `paper-details/scripts/extract_images.py` — PEP 723 のインラインメタデータで
  `pymupdf` を宣言しており、`uv run` で実行する。`uv` は別途インストールしておく。
- `html/render-pdf.sh` — `/Applications/` 配下の Google Chrome / Chromium を headless で使う。
  PDF 化をユーザーが明示的に依頼したときだけ実行される。

### 更新手順

上流の当該ディレクトリを再取得してファイルを差し替え、上の「取り込み時点のコミット」を更新する。

```bash
# リポジトリのルートで実行
B=repos/mathbullet/skills/contents/plugins
for s in paper-details html documenting-with-sources writing-quotation explain; do
  gh api "$B/$s/skills/$s/SKILL.md" -H "Accept: application/vnd.github.raw" \
    > skills/$s/SKILL.md
done
# 付随ファイル（scripts/, design-system/, render-pdf.sh）は個別に取得する
```

## mattpocock/skills

- Upstream: https://github.com/mattpocock/skills
- 取り込み元: Claude Code のスキルインストーラで `~/.claude/skills/` に入っていたものを
  そのまま取り込んだ。各 `SKILL.md` の frontmatter に `metadata.github-ref` /
  `github-tree-sha` が埋まっており、それが取り込み時点のピンになっている。

| スキル | 上流パス | ピン |
| --- | --- | --- |
| `grilling` | `skills/productivity/grilling` | `refs/tags/v1.1.0` |

**注意**: `grilling` は上流 main が v1.1.0 から文言変更されている
（対象が "plan" → "plan, decision, or idea"、探索先が "codebase" → "environment"
などに一般化）。ここでは v1.1.0 の文言を維持しているため、更新時は挙動の変化を確認すること。

### 更新手順（mattpocock）

```bash
# リポジトリのルートで実行
gh api "repos/mattpocock/skills/contents/skills/productivity/<skill>/SKILL.md" \
  -H "Accept: application/vnd.github.raw" > skills/<skill>/SKILL.md
```

上流のファイルには `metadata:` ブロックが無いので、差し替えたらこの表のピンを更新する。

## ツール同梱のスキル（herdr）

- `skills/herdr/SKILL.md` — [herdr](https://github.com/herdrdev/herdr)（Apache-2.0） のパッケージ同梱ファイル
  （`share/herdr/skills/herdr/SKILL.md`）のコピー。

ツールを更新したら、パッケージ内のファイルで差し替える。

## humanlayer/skills

- Upstream: https://github.com/humanlayer/skills
- License: MIT (Copyright (c) 2026 HumanLayer)
- 取り込み元: スキルインストーラで `~/.claude/skills/` に入っていたものをそのまま取り込んだ。
  frontmatter の `metadata.github-tree-sha`（`0bdb821a21e793a4f6f82a7078c052154447e5cc`）が取り込み時点のピン。

| スキル | 上流パス |
| --- | --- |
| `show-me` | `plugins/show-me/skills/show-me` |

更新するときは `gh api "repos/humanlayer/skills/contents/plugins/show-me/skills/show-me/SKILL.md" -H "Accept: application/vnd.github.raw" > skills/show-me/SKILL.md`。

## nicobailon/visual-explainer

- Upstream: https://github.com/nicobailon/visual-explainer
- License: MIT (Copyright (c) 2025 Nico Bailon)
- 取り込み時点のコミット: `5f378868e0ea745a6284b51e710c390f0c76f72c` (2026-10-19, v0.14.0)

| 取り込み先 | 上流パス |
| --- | --- |
| `skills/visual-explainer/` | `plugins/visual-explainer/`（`commands/`, `mcp/`, `extension.ts` を除く） |
| `claude/commands/*.md`（9個） | `plugins/visual-explainer/commands/` |

`kit/render.mjs` の実行に `node` が必要。動画・PPTX 出力は追加の依存がある（`video/`, `pptx/README.md`）。
Codex にはスキルのみ配備（commands は Claude のみ）。更新するときは上流の `plugins/visual-explainer/` で差し替え、上のコミットを更新する。

## nanaism/yomiyasu

- Upstream: https://github.com/nanaism/yomiyasu
- License: MIT (Copyright (c) 2026 nanaism)。スキル同梱の `UNICODE-LICENSE.txt` はそのまま残している
- 取り込み時点のコミット: `8be3ef6e0e668f14cae30c3da6b0c20b95b2179f` (2026-10-19, v2.1.0)

| 取り込み先 | 上流パス |
| --- | --- |
| `skills/yomiyasu/` | `skills/yomiyasu/`（`.codex-plugin/` を除く） |

スクリプトは Python 標準ライブラリのみで動く（`python3` が必要）。`yomiyasu_check.py` は検査記録（原文と最終稿の全文）を
git ルートの `.yomiyasu/` に書く。任意のフック `scripts/yomiyasu_hook.py` は設定に登録していない。
Codex にも配備する。更新するときは上流の `skills/yomiyasu/` で差し替え、上のコミットを更新する。
