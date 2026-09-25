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

## yasunori0418/skills

- Upstream: https://github.com/yasunori0418/skills
- 取り込み元: 同上（`~/.claude/skills/` の実体をそのまま）。
  取り込み時点で上流 main と本文は一致していた。

| スキル | 上流パス |
| --- | --- |
| `quizzing` | `skills/learning/quizzing` |
| `tutoring` | `skills/learning/tutoring` |

2 つとも `disable-model-invocation: true`（明示呼び出し専用）。

### 更新手順（mattpocock / yasunori0418 共通）

```bash
# リポジトリのルートで実行
gh api "repos/mattpocock/skills/contents/skills/productivity/<skill>/SKILL.md" \
  -H "Accept: application/vnd.github.raw" > skills/<skill>/SKILL.md
gh api "repos/yasunori0418/skills/contents/skills/learning/<skill>/SKILL.md" \
  -H "Accept: application/vnd.github.raw" > skills/<skill>/SKILL.md
```

上流のファイルには `metadata:` ブロックが無いので、差し替えたらこの表のピンを更新する。

## ツール同梱のスキル（herdr / terminal-browser）

- `skills/herdr/SKILL.md` — [herdr](https://github.com/herdrdev/herdr)（Apache-2.0） のパッケージ同梱ファイル
  （`share/herdr/skills/herdr/SKILL.md`）のコピー。
- `skills/terminal-browser/SKILL.md` — [terminal-browser](https://github.com/zenbu-labs/terminal-browser)（MIT）のパッケージ同梱ファイル
  （`share/terminal-browser/SKILL.md`）のコピー。

ツールを更新したら、パッケージ内のファイルで差し替える。
