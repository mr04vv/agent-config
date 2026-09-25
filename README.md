# agent-config

Claude Code と Codex の設定・スキル・コマンド。`install.sh` が `~/.claude` と `~/.codex` に symlink を張るので、このリポジトリのファイルを直接編集すればそのまま反映される。

## セットアップ

```sh
ghq get mr04vv/agent-config
"$(ghq root)/github.com/mr04vv/agent-config/install.sh"
```

- 何度実行してもよい。既存の実ファイルは `~/.agent-config-backup/<日時>/` に退避してから symlink に置き換える
- ファイルやスキルを**追加**したとき、`codex/config.base.toml` を編集したときは再実行する

## 構成

| パス | 配置先 |
| --- | --- |
| `claude/` | `~/.claude/`（ファイル単位で symlink。管理外のファイルには触れない） |
| `skills/` | `~/.claude/skills/<name>`。一部は `~/.codex/skills/` にも（`install.sh` の `CODEX_SKILLS`） |
| `ponytail/` | `~/.claude/ponytail`（hooks）。commands も展開。skill 本体は `skills/ponytail*`（[UPSTREAM.md](ponytail/UPSTREAM.md)） |
| `codex/` | `~/.codex/`。`config.toml` だけは `config.base.toml` から生成する |

`codex/config.toml` を symlink にしないのは、codex が project の trust や hook の trust hash などの端末固有の状態を同じファイルに書き込むため。`install.sh` は base の内容で上書きし、base に無いキー・テーブルはそのまま残す。

## 管理していないもの

- `~/.claude/statusline.py` — 自己更新するため。新しい端末では [usedhonda/statusline](https://github.com/usedhonda/statusline) から `~/.claude/statusline.py` に置く
- `settings.json` の hook が呼ぶ外部コマンド（`herdr`, `node`, macOS の `Notifier.app` / `afplay` など）

外部から取り込んだスキルの出所とライセンスは [VENDORED-SKILLS.md](VENDORED-SKILLS.md) と `licenses/` を参照。
