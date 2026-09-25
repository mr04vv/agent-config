---
name: diff-explain
description: >-
  Generate an annotated diff-EXPLANATION page in the browser: changes are
  grouped into semantic "change groups" (across files), each with an intent
  explanation, a risk level (要注意/注意/低リスク), tags, and per-hunk /
  per-line explanations (意図・コード解説・解説) — but NO review findings.
  The page also has per-line & multi-line human comment boxes and (branch
  diffs) GitHub PR comment submission for the human's own comments. Use this
  skill when the user wants to UNDERSTAND a diff, not have it critiqued:
  "差分を解説して", "explain the diff", "何を変えたか説明して",
  "このブランチで何を変えたか", "変更内容をまとめて", "diffをブラウザで見たい",
  "レビュー前に変更を整理して" (understanding sense). Do NOT use for reviewing a remote PR by URL, or for one-line diff
  questions answerable inline in chat.
---

# Diff Explain

Build a self-contained **explanation** page for a diff, organized the way a
reader thinks — not file by file, but as **semantic change groups**. Each
group carries an intent (意図), a risk level, tags, and annotated hunks
explaining *what* changed and *why*. This skill is the **explanation-only**
variant: it does **not** emit review findings (指摘) or 要改善. Humans can
still add per-line / multi-line comments and, on a branch diff, send those
comments to the GitHub PR.

解説専用で、findings/unclear は一切出さない（`render --no-review`）。

Division of labor: `scripts/build_diff_page.py` does everything deterministic
— diff extraction, parsing, hunk ids, intraline highlighting, HTML rendering,
state persistence. Your job: read the diff and write `explanations.json` with
the explanatory annotations. Do not hand-write the HTML or re-parse the diff.

## Workflow

### 1. Extract the diff

```bash
python <skill-path>/scripts/build_diff_page.py extract [--mode MODE]
```

Modes:

- `branch` (default) — current branch vs base (`merge-base..HEAD`). Base
  auto-detects via `origin/HEAD` then `main`/`master`/`develop`; pass
  `--base <branch>` if named. PR コメント送信は branch モードのみ。
- `unstaged` — working tree vs index.
- `staged` — index vs HEAD.
- `worktree` — working tree vs HEAD (staged + unstaged).

Add `--workdir <dir>` to reuse a directory.

**解説量 `--detail {small|medium|large}`** (default `medium`): 生成する解説
（意図・コード解説・解説）の分量レベル。ユーザーが「軽く/ざっくり」「詳しく/
しっかり」等と言ったら選ぶ。extract 時に保存され、ページヘッダーにも表示。

The script prints the workdir and a **hunk index**: files, hunks, and their
global ids (`h001`, …) — the ids you assign to groups. lockfile・生成物には
**`(generated — 解説不要)`** マークが付く。It also writes `raw.diff` and
`diff_data.json`. If it exits with "No differences", report and stop.

### 2. Read the diff and plan the groups

Read `<workdir>/raw.diff` and decide change groups by the *logical structure*
of the change (a group can span files). Aim for 3–8 groups. Typical shapes:
新しい基盤・共通化 / 使う側の機械的な置き換え / テスト・docs・生成物. Order
core first, mechanical/low-risk later. Unassigned hunks land in an automatic
「その他の変更」 group.

For large diffs, triage: read the hunk index, read meaningful files fully,
skim mechanical mass-changes. If ±3 lines of context isn't enough, read the
actual file — guessed explanations are worse than short ones.

### 3. Write explanations.json

Write `<workdir>/explanations.json`. **解説専用なので findings / unclear は
書かない**（書いても `--no-review` で無視される）。

```json
{
  "title": "app/system URL整理の差分解説",
  "groups": [
    {
      "name": "URL・ホスト判定の共通基盤",
      "risk": "high",
      "tags": ["core"],
      "description": "一覧に出す60字程度の要約(省略時はintent先頭を使用)",
      "intent": "従来はcontroller・view・batchの三箇所でURLを個別に組み立てており、deployment modeを追加するたびに分岐が増え不整合の温床になっていた。本グループではURL生成とhost判定を`UrlResolver`一か所へ集約し、legacy-path方式とsubdomain方式をmodeフラグで切り替える形に再設計する。呼び出し側は`resolver.url_for(...)`を呼ぶだけになり、影響範囲は三モジュールに広がるが判定ロジックの重複は解消される。",
      "hunks": ["h079", "h080", "h081"],
      "hunk_intents": {
        "h080": "このハンク固有の意図(紫)。グループ全体のintentとは別に、この差分片の目的を一言で。"
      },
      "code_notes": {
        "h080:142": "コード解説(緑)。142行目: `resolver.url_for`はmode→builder関数の辞書を引き、該当がなければlegacy builderにfallbackして絶対URLを返す。(行キーなのでこの行の直下にインライン表示)"
      },
      "hunk_notes": {
        "h080": "解説(青)。なぜこう変えたか・非自明な点。modeフラグの判定を一度だけ行いキャッシュしている理由など。"
      }
    },
    {
      "name": "設計文書と移行計画の更新",
      "risk": "low",
      "tags": ["docs"],
      "intent": "architectureとmigration planを現在の責務分離へ更新。",
      "hunks": ["h101", "h102"]
    }
  ]
}
```

**解説量レベル (`--detail`)**:

- **small** — 要点のみ。`intent` 1〜2 文、hunk 解説は本当に非自明な箇所だけ。
- **medium**（既定）— `intent` 3〜5 文、非自明な hunk に 2〜4 文。自明は省略。
- **large** — 手厚く。設計判断・境界条件・代替案・影響範囲まで。ただし自明な
  hunk を無理に膨らませない（水増しは全レベルで avoid）。

**生成物・lock ファイルは解説しない** — `(generated — 解説不要)` の hunk には
注釈を付けない。低リスクグループ（`tags: ["deps"]` 等）にまとめ `intent` に
一言添えれば十分。判定は extract のマークに従う。

Field guidance:

- **risk**: `high`=挙動変更・境界・並行・移行、`medium`=広いが機械的、
  `low`=docs・生成物・rename。誤りの結果の重大さで判断する（行数ではない）。
- **tags**: 1–2 語 (`core`, `refactor`, `docs`, `test`, `deps`, `config`).
- **intent**: なぜこの変更か・設計判断・影響範囲。分量は `--detail` に従い (1) 問題・背景
  (2) アプローチと理由 (3) 影響範囲 (4) 代替案/トレードオフ。憶測は明示する。
- **ハンク単位の解説は3種**（同じハンクに複数可、役割で書き分け重複させない。
  表示順 意図 → コード解説 → 解説）:
  - **hunk_intents** (意図, purple) — そのハンク固有の変更意図を 1〜2 文。
  - **code_notes** (コード解説, green) — 変更後コードが何をしているか（処理の
    流れ・データの動き・戻り値）。
  - **hunk_notes** (解説, blue) — why と非自明な点を 2〜4 文。
  自明なハンク（rename・import 追加・フォーマットのみ）には付けない。
- **注釈は行単位・範囲でも付けられる**。3 種すべてキーは `"h012"`（ハンク
  全体）/ `"h012:58"`（特定行、58 = 新側 RIGHT 行番号）/ `"h012:58-63"`
  （複数行の範囲、両端とも新側 RIGHT 行）の 3 形式。行/範囲キーは終了行の
  直下にインライン表示。「どこの話か」が明確になるので可能な限り行/範囲キーで。
  行番号は extract に実在する新側行のみ、範囲は両端とも実在すること（無ければ
  ハンク単位にフォールバック+警告）。
- **Display order is risk order**（high → medium → low で安定ソート）。
- **Language**: match the user's language (ほぼ日本語).

### 4. Render and open

```bash
python <skill-path>/scripts/build_diff_page.py render --workdir <workdir> --no-review
```

**必ず `--no-review` を付ける**（このスキルの肝）。findings/unclear を描画
せず、指摘/要改善のカウント・バッジ・AI 送信チェックボックスも出さない。解説
系・人間コメント欄・PR 送信は残る。

It prints the path to `diff_review.html`. Open it:

- macOS: `open <path>` / Linux with display: `xdg-open <path>`
- No display / Claude.ai container: present the HTML file to the user
  directly and mention it works offline.

Then give a short recap in chat (2–4 sentences): the shape of the change and
where to start reading.

### 5. 人間コメントを GitHub PR に送る（branch モードのみ、任意）

解説ページでも人間が行/範囲/ハンクにコメントを残せる。それを PR に送りたいと
言われたら、ページの「PR送信用にコピー」でコピーされた JSON（解説専用なので
`author` は human のみ）を使って送る:

```bash
gh pr view <head-branch> --json number -q '.number'
gh api repos/{owner}/{repo}/pulls/<pr-number>/reviews \
  --method POST --input <(jq 'del(._context) | .comments |= map(del(.author))' review.json)
```

**送信は破壊的で外向きの操作**。件数と event を要約しユーザーの承認を得てから
叩く。行/範囲コメントはその行/範囲、ハンクコメントは代表行にアンカーされる。

## The generated page

A sticky header shows a DIFF REVIEW label, the title, `N files / M hunks
+A −D`, an approval progress bar, a まとめをコピー button, a PR送信用にコピー
button (branch mode), and a "?" legend. Section 01 lists groups in risk
order; a meta line shows 対象範囲・生成日時・解説量レベル. Section 02 has
detail cards with the risk badge, 意図, a 確認して承認 checkbox, and the
hunks. Annotation boxes: 意図 (purple), コード解説 (green), 解説 (blue) —
行キーの注釈は該当行の直下にインライン表示。**指摘 (red)・要改善 (amber) は
このスキルでは出ない。**

**行コメント・範囲コメント**: 各行（RIGHT 側）にホバーで「＋」、または **行
番号列をドラッグ**で複数行を範囲選択してコメントできる。1 行/範囲に複数コメ
ント可、localStorage に保存・復元。範囲は `start_line`〜`line` で PR 送信。

The **まとめをコピー** button assembles a Markdown summary of the human's
comments and unapproved groups. State persists in localStorage, keyed by
title + merge-base.

## Iterating

Edit `explanations.json` in the same workdir and re-run `render --no-review`
— no need to re-extract unless the code changed. Regrouping resets saved
approval checkboxes.
