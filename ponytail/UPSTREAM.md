# ponytail (vendored)

`ponytail/` は [ponytail](https://github.com/DietrichGebert/ponytail)
を vendoring したもの。上流は Claude Code の plugin として配布されるが、この repo
では `/plugin install` を使わず手動で取り込み、`install.sh` の symlink で配置している。

- Upstream: https://github.com/DietrichGebert/ponytail
- 取り込み時点: version `4.8.4`, commit `16f29800fd2681bdf24f3eb4ccffe38be3baec6b`

## 何をする plugin か

「一番ラクなシニア開発者のように考える」= 書かずに済むコードは書かない、を強制する
ruleset。YAGNI → stdlib → native → 既存依存 → ワンライナー → 最小実装、の順で
「本当に書く必要があるか」を毎回問う。mode は `off`/`lite`/`full`/`ultra` の4段階。

## 構成と配置（`install.sh` が symlink を張る）

| 上流 | 取り込み先 | デプロイ先 | 役割 |
| --- | --- | --- | --- |
| `skills/*/SKILL.md` (6個) | `ponytail/skills/` | `~/.claude/skills/<name>/` | skill 本体。手動 skill 呼び出し用 |
| `commands/*.toml` (6個) | `ponytail/commands/*.md` | `~/.claude/commands/*.md` | `/ponytail*` slash command |
| `hooks/*.js` ほか | `ponytail/hooks/` | `~/.claude/ponytail/hooks/` | **主機能**。毎セッション ruleset を注入 |
| `hooks/claude-codex-hooks.json` | `ponytail/hooks/` | 同上（参照用に保持） | 上流の hook 定義。配線は settings.json 側 |

### 手を加えた点（上流との差分）

1. **commands を `.toml` → `.md` に変換**。`~/.claude/commands/` 直置きは `.md` 形式
   しか確実にサポートされないため。`{{args}}` は Claude Code の `$ARGUMENTS` に置換した。
   本文（prompt）と description は上流のまま。
2. **hooks の配線は `settings.json` に手書き**。上流は `plugin.json` の
   `"hooks": "./hooks/claude-codex-hooks.json"` と `${CLAUDE_PLUGIN_ROOT}` で自動配線されるが、
   plugin として入れないので `settings.json` の `SessionStart`/`SubagentStart`/`UserPromptSubmit`
   に `node ~/.claude/ponytail/hooks/*.js` を直接記述した。
   hooks の Node コードは `CLAUDE_PLUGIN_ROOT` に依存せず `os.homedir()` ベースで動くので、
   plugin 外配置でも全機能動作する。

### 実行時依存

- `node` — 別途インストールしておく。hooks は純粋な Node.js。
- mode のデフォルトは `full`（上流既定）。変更するなら環境変数 `PONYTAIL_DEFAULT_MODE`
  (`off`/`lite`/`full`/`ultra`) か `~/.config/ponytail/config.json` の `{"defaultMode": ...}`。
- statusline バッジ（`[PONYTAIL]` 表示）は未配線。この repo は独自の `statusline.py` を
  使っているため。必要なら `ponytail/hooks/ponytail-statusline.sh` を組み込む。

## 更新手順

```bash
# リポジトリのルートで実行
DEST=ponytail
for f in ponytail-activate.js ponytail-config.js ponytail-instructions.js \
         ponytail-mode-tracker.js ponytail-runtime.js ponytail-subagent.js \
         ponytail-statusline.sh claude-codex-hooks.json; do
  gh api "repos/DietrichGebert/ponytail/contents/hooks/$f" \
    -H "Accept: application/vnd.github.raw" > "$DEST/hooks/$f"
done
for s in ponytail ponytail-review ponytail-audit ponytail-debt ponytail-gain ponytail-help; do
  gh api "repos/DietrichGebert/ponytail/contents/skills/$s/SKILL.md" \
    -H "Accept: application/vnd.github.raw" > "$DEST/skills/$s/SKILL.md"
done
gh api repos/DietrichGebert/ponytail/commits/HEAD --jq '.sha' > "$DEST/.upstream-commit"
```

commands は上流 `.toml` を再取得して `.md` に変換し直す（`{{args}}` → `$ARGUMENTS`、
`description`/`prompt` を frontmatter + 本文へ）。取り込み後は上の version/commit を更新し、
hook の JSON 仕様（SessionStart 等の matcher）が変わっていないか `claude-codex-hooks.json`
と `settings.json` を突き合わせて確認する。
