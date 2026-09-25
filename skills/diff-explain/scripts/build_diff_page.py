#!/usr/bin/env python3
"""build_diff_page.py — annotated diff review page builder.

Two subcommands:

  extract   Compute a diff (branch vs base, or unstaged/staged/worktree),
            parse it, assign global hunk ids (h001, h002, ...), and write
            diff_data.json + raw.diff into a workdir. Prints an index of
            files/hunks so the caller (Claude) knows what to annotate.

  render    Combine diff_data.json with explanations.json (written by
            Claude: change groups, intents, risks, notes, findings) into a
            single self-contained review HTML with per-group approval
            checkboxes. No CDN, no network needed to view.

Usage:
  python build_diff_page.py extract [--mode branch|unstaged|staged|worktree]
                                    [--base BRANCH] [--head REF]
                                    [--workdir DIR]
  python build_diff_page.py render  --workdir DIR [--out FILE]
"""

import argparse
import datetime
import html
import json
import os
import re
import subprocess
import sys
import tempfile

# ---------------------------------------------------------------- git helpers


def run_git(args, check=True):
    result = subprocess.run(["git"] + args, capture_output=True, text=True)
    if check and result.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result.stdout.strip()


def detect_base_branch():
    out = subprocess.run(
        ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
        capture_output=True, text=True,
    )
    if out.returncode == 0:
        return out.stdout.strip().replace("refs/remotes/", "", 1)
    for cand in ("origin/main", "origin/master", "main", "master",
                 "origin/develop", "develop"):
        ok = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", cand],
            capture_output=True, text=True,
        )
        if ok.returncode == 0:
            return cand
    sys.exit("Could not detect a base branch. Pass one with --base.")


# ---------------------------------------------------------------- diff parser

DIFF_HEADER = re.compile(r"^diff --git (?:a/|\")?(.*?)(?:\"|) (?:b/|\")?(.*?)(?:\"|)$")
HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")


def parse_diff(raw):
    files = []
    cur = None
    hunk = None
    old_no = new_no = 0

    def close_file():
        nonlocal cur, hunk
        if cur is not None:
            files.append(cur)
        cur = None
        hunk = None

    for line in raw.split("\n"):
        m = DIFF_HEADER.match(line)
        if m:
            close_file()
            cur = {"path": m.group(2), "old_path": None, "status": "modified",
                   "binary": False, "additions": 0, "deletions": 0,
                   "hunks": []}
            continue
        if cur is None:
            continue
        if line.startswith("new file mode"):
            cur["status"] = "added"
            continue
        if line.startswith("deleted file mode"):
            cur["status"] = "deleted"
            continue
        if line.startswith("rename from "):
            cur["old_path"] = line[len("rename from "):]
            cur["status"] = "renamed"
            continue
        if line.startswith("rename to "):
            cur["path"] = line[len("rename to "):]
            continue
        if line.startswith("Binary files "):
            cur["binary"] = True
            continue
        if line.startswith("--- "):
            p = line[4:]
            if p != "/dev/null" and cur["old_path"] is None:
                cur["old_path"] = re.sub(r"^a/", "", p)
            continue
        if line.startswith("+++ "):
            p = line[4:]
            if p != "/dev/null":
                cur["path"] = re.sub(r"^b/", "", p)
            continue
        m = HUNK_HEADER.match(line)
        if m:
            old_no = int(m.group(1))
            new_no = int(m.group(3))
            hunk = {"header": line, "lines": []}
            cur["hunks"].append(hunk)
            continue
        if hunk is None:
            continue
        if line.startswith("+"):
            hunk["lines"].append({"t": "add", "old": None, "new": new_no,
                                  "s": line[1:]})
            new_no += 1
            cur["additions"] += 1
        elif line.startswith("-"):
            hunk["lines"].append({"t": "del", "old": old_no, "new": None,
                                  "s": line[1:]})
            old_no += 1
            cur["deletions"] += 1
        elif line.startswith(" ") or line == "":
            hunk["lines"].append({"t": "ctx", "old": old_no, "new": new_no,
                                  "s": line[1:] if line else ""})
            old_no += 1
            new_no += 1
        elif line.startswith("\\"):
            hunk["lines"].append({"t": "meta", "old": None, "new": None,
                                  "s": line})
    close_file()
    for f in files:
        if f["old_path"] == f["path"]:
            f["old_path"] = None
    return files


# ------------------------------------------------------- intraline highlight


def mark_intraline(lines):
    """For paired del/add runs of equal length, compute a changed-span
    highlight (common prefix/suffix trim). Stores (start, end) on the line
    dict as 'hl'. Skips pairs where nearly the whole line changed."""
    i = 0
    n = len(lines)
    while i < n:
        if lines[i]["t"] != "del":
            i += 1
            continue
        j = i
        while j < n and lines[j]["t"] == "del":
            j += 1
        k = j
        while k < n and lines[k]["t"] == "add":
            k += 1
        dels, adds = lines[i:j], lines[j:k]
        if dels and adds:
            for d, a in zip(dels, adds):
                sa, sb = d["s"], a["s"]
                p = 0
                while p < len(sa) and p < len(sb) and sa[p] == sb[p]:
                    p += 1
                q = 0
                while (q < len(sa) - p and q < len(sb) - p
                       and sa[len(sa) - 1 - q] == sb[len(sb) - 1 - q]):
                    q += 1
                for s, ln in ((sa, d), (sb, a)):
                    mid = len(s) - p - q
                    if 0 < mid and (p + q) >= max(4, len(s) // 5):
                        ln["hl"] = (p, len(s) - q)
        i = k


# ------------------------------------------------------------------- extract


# files whose diffs almost never need prose explanation: dependency lockfiles,
# vendored deps, build output, minified/generated bundles, snapshots, etc.
GENERATED_PATTERNS = [
    # lockfiles (deps are decided elsewhere; the lock is a mechanical result)
    r"(^|/)package-lock\.json$", r"(^|/)pnpm-lock\.yaml$",
    r"(^|/)yarn\.lock$", r"(^|/)npm-shrinkwrap\.json$",
    r"(^|/)Cargo\.lock$", r"(^|/)poetry\.lock$", r"(^|/)Pipfile\.lock$",
    r"(^|/)composer\.lock$", r"(^|/)Gemfile\.lock$", r"(^|/)flake\.lock$",
    r"(^|/)go\.sum$", r"(^|/)pubspec\.lock$", r"(^|/)uv\.lock$",
    r"(^|/)mix\.lock$", r"(^|/)packages\.lock\.json$",
    r"(^|/)Podfile\.lock$", r"(^|/)deno\.lock$",
    # vendored / installed deps
    r"(^|/)node_modules/", r"(^|/)vendor/", r"(^|/)Pods/",
    # build output / generated bundles
    r"(^|/)dist/", r"(^|/)build/", r"(^|/)out/", r"(^|/)\.next/",
    r"\.min\.(js|css)$", r"\.bundle\.js$",
    r"(^|/)__snapshots__/", r"\.snap$",
    # common "do not edit" generated code
    r"\.pb\.go$", r"_pb2\.py$", r"\.g\.dart$", r"\.freezed\.dart$",
    r"\.generated\.(ts|js|tsx)$", r"(^|/)generated/",
]
_GENERATED_RE = re.compile("|".join(GENERATED_PATTERNS))


def is_generated_path(path):
    """Heuristic: does this path look like a lockfile / vendored dep /
    build artifact / generated code — i.e. a diff that needs no prose?"""
    return bool(_GENERATED_RE.search(path or ""))


def cmd_extract(args):
    run_git(["rev-parse", "--show-toplevel"])  # fail early outside a repo
    mode = args.mode
    label = {"branch": None, "unstaged": "unstaged changes",
             "staged": "staged changes", "worktree": "worktree vs HEAD"}
    if mode == "branch":
        head = args.head or "HEAD"
        head_name = run_git(["rev-parse", "--abbrev-ref", head])
        base = args.base or detect_base_branch()
        merge_base = run_git(["merge-base", base, head])
        diff_args = [merge_base, head]
        source = {"mode": "branch", "base_branch": base, "head": head_name,
                  "merge_base": merge_base}
    else:
        head_name = run_git(["rev-parse", "--abbrev-ref", "HEAD"])
        diff_args = {"unstaged": [], "staged": ["--cached"],
                     "worktree": ["HEAD"]}[mode]
        source = {"mode": mode, "head": head_name, "label": label[mode]}

    raw = subprocess.run(
        ["git", "diff", "--no-color", "--find-renames", "-U3"] + diff_args,
        capture_output=True, text=True,
    ).stdout

    if not raw.strip():
        sys.exit("No differences found for the requested mode.")

    files = parse_diff(raw)

    # assign global hunk ids and intraline highlights; flag generated files
    counter = 0
    for f in files:
        f["generated"] = is_generated_path(f["path"]) or (
            f["old_path"] is not None and is_generated_path(f["old_path"]))
        for h in f["hunks"]:
            counter += 1
            h["id"] = f"h{counter:03d}"
            mark_intraline(h["lines"])

    workdir = args.workdir or tempfile.mkdtemp(prefix="diff-review-")
    os.makedirs(workdir, exist_ok=True)
    data = {
        "source": source,
        "detail": args.detail,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "files": files,
    }
    with open(os.path.join(workdir, "diff_data.json"), "w") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=1)
    with open(os.path.join(workdir, "raw.diff"), "w") as fp:
        fp.write(raw)

    total_add = sum(f["additions"] for f in files)
    total_del = sum(f["deletions"] for f in files)
    print(f"workdir: {workdir}")
    if mode == "branch":
        print(f"base: {source['base_branch']}  head: {source['head']}  "
              f"merge-base: {source['merge_base'][:12]}")
    else:
        print(f"mode: {mode} ({label[mode]})  branch: {head_name}")
    n_generated = sum(1 for f in files if f["generated"])
    print(f"{len(files)} files, {counter} hunks, +{total_add} -{total_del}"
          + (f"  ({n_generated} generated/lock files)" if n_generated else ""))
    print(f"detail level: {args.detail}")
    print()
    print("Hunk index (assign these ids to groups in explanations.json):")
    for f in files:
        lab = f["path"]
        if f["old_path"]:
            lab = f"{f['old_path']} -> {f['path']}"
        print(f"  {lab}  [{f['status']}] +{f['additions']} -{f['deletions']}"
              + ("  (binary)" if f["binary"] else "")
              + ("  (generated — 解説不要)" if f["generated"] else ""))
        for h in f["hunks"]:
            print(f"    {h['id']}: {h['header'][:100]}")


# ------------------------------------------------------- markdown-mini render


def md_to_html(text):
    out = []
    lines = text.split("\n")
    i = 0
    in_ul = False

    def close_ul():
        nonlocal in_ul
        if in_ul:
            out.append("</ul>")
            in_ul = False

    def inline(s):
        s = html.escape(s)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        return s

    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            close_ul()
            block = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            out.append("<pre><code>" + html.escape("\n".join(block))
                       + "</code></pre>")
            i += 1
            continue
        if re.match(r"^\s*[-*] ", line):
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append("<li>" + inline(re.sub(r"^\s*[-*] ", "", line))
                       + "</li>")
            i += 1
            continue
        close_ul()
        if line.strip():
            para = [line]
            while (i + 1 < len(lines) and lines[i + 1].strip()
                   and not re.match(r"^\s*[-*] ", lines[i + 1])
                   and not lines[i + 1].strip().startswith("```")):
                i += 1
                para.append(lines[i])
            out.append("<p>" + inline(" ".join(para)) + "</p>")
        i += 1
    close_ul()
    return "\n".join(out)


# -------------------------------------------------------------------- render

RISK = {
    "high":   {"cls": "high",   "label": "要注意"},
    "medium": {"cls": "medium", "label": "注意"},
    "low":    {"cls": "low",    "label": "低リスク"},
}


def esc(s):
    return html.escape(s, quote=False)


def code_html(ln):
    s = ln["s"]
    hl = ln.get("hl")
    if not hl:
        return esc(s)
    a, b = hl
    return (esc(s[:a]) + '<span class="hl">' + esc(s[a:b]) + "</span>"
            + esc(s[b:]))


def render_hunk(hunk, file_path, line_annots=None, generated=False):
    """Render a hunk's diff table. `line_annots` maps a new-side line number
    to a list of (kind, text, sendable) tuples; each is emitted as a
    full-width annotation row directly under that line — this is how AI
    findings/notes anchored to a specific line show up inline. `generated`
    tags the hunk header when the file is a lockfile/build artifact."""
    line_annots = line_annots or {}
    rows = []
    for ln in hunk["lines"]:
        t = ln["t"]
        if t == "meta":
            rows.append('<tr class="meta"><td class="ln"></td>'
                        '<td class="ln"></td>'
                        f'<td class="code">{esc(ln["s"])}</td></tr>')
            continue
        old = "" if ln["old"] is None else ln["old"]
        new = "" if ln["new"] is None else ln["new"]
        sign = {"add": "+", "del": "-", "ctx": " "}[t]
        # RIGHT-side lines (add/ctx) can carry an inline line comment.
        addable = t in ("add", "ctx") and ln["new"] is not None
        if addable:
            attrs = (f' data-cpath="{html.escape(file_path, quote=True)}"'
                     f' data-cline="{ln["new"]}" data-cside="RIGHT"')
            btn = ('<button class="addcmt" title="この行にコメント" '
                   'onclick="toggleLineComment(this)">+</button>')
            # the new-side line-number cell is a drag handle for range select
            new_ln_cell = (f'<td class="ln lnum" data-lnum="{ln["new"]}">'
                           f'{new}</td>')
        else:
            attrs = ""
            btn = ""
            new_ln_cell = f'<td class="ln">{new}</td>'
        rows.append(
            f'<tr class="{t}"{attrs}><td class="ln">{old}</td>'
            f'{new_ln_cell}'
            f'<td class="code">{btn}<span class="sign">{sign}</span>'
            f'{code_html(ln)}</td></tr>'
        )
        # inline annotations anchored to this new-side line
        if ln["new"] is not None and ln["new"] in line_annots:
            for kind, text, sendable in line_annots[ln["new"]]:
                rows.append(
                    '<tr class="annot-row"><td class="ln"></td>'
                    '<td class="ln"></td><td class="code annot-cell">'
                    f'{note_html(text, kind, sendable=sendable)}</td></tr>')
    header = hunk["header"]
    m = HUNK_HEADER.match(header)
    rng = f"@@ -{m.group(1)},{m.group(2) or 1} +{m.group(3)},{m.group(4) or 1}" \
        if m else header
    gen_badge = ('<span class="genbadge" title="自動生成/lock: 解説対象外">'
                 'generated</span>' if generated else "")
    return f"""
<div class="hunk" id="{hunk["id"]}">
  <div class="hunk-head">
    <span class="hid">{hunk["id"]}</span>
    <span class="hpath">{esc(file_path)}</span>
    <span class="hrange">{esc(rng)}</span>
    {gen_badge}
  </div>
  <table class="diff">{"".join(rows)}</table>
</div>"""


ANNOT_KINDS = {
    "hintent": ("意図", "hintent"),
    "note":    ("解説", "note"),
    "code":    ("コード解説", "code"),
    "finding": ("指摘", "finding"),
    "unclear": ("要改善", "unclear"),
}


def note_html(text, kind="note", sendable=None):
    """Render an annotation box. When `sendable` is given (a dict with hid,
    path, line, side), the box gets a "send to PR" checkbox so the human can
    include or drop this AI comment; picked ones go into the review payload
    as author=ai line comments."""
    label, cls = ANNOT_KINDS[kind]
    check = ""
    if sendable:
        # key must be unique per (hid, kind, scope, start-line) so line-level
        # annotations on the same hunk+kind don't collide in the send-toggle
        # store. hunk-level sends carry scope="whole" to stay distinct from a
        # line-level send that happens to share the representative line.
        scope = sendable.get("scope", "line")
        start = sendable.get("start_line")
        span = f"{start}-{sendable['line']}" if start is not None \
            else str(sendable["line"])
        ck = f"ai:{sendable['hid']}:{kind}:{scope}:{span}"
        start_attrs = (f' data-cstart="{start}"'
                       f' data-cstartside="{sendable.get("start_side", "RIGHT")}"'
                       if start is not None else "")
        check = (
            f'<label class="ai-send" title="このAIコメントをPRに送る">'
            f'<input type="checkbox" class="ai-send-cb" checked'
            f' data-key="{esc(ck)}"'
            f' data-cpath="{html.escape(sendable["path"], quote=True)}"'
            f' data-cline="{sendable["line"]}"'
            f' data-cside="{sendable["side"]}"'
            f'{start_attrs}'
            f' data-kind="{ANNOT_KINDS[kind][0]}"'
            f' data-body="{html.escape(text, quote=True)}"> PRに送る</label>')
    return (f'<div class="annot {cls}"><span class="annot-label">{label}'
            f'</span><div class="annot-body">{md_to_html(text)}{check}</div>'
            f'</div>')


def hunk_comment_anchor(hunk):
    """Pick the line a GitHub PR review comment should attach to for this
    hunk. GitHub anchors a comment to a single line of the diff; prefer the
    last added line (new side, RIGHT), else the last context line (RIGHT),
    else the last deleted line (old side, LEFT). Returns {line, side} or None
    when the hunk has no anchorable line."""
    add = ctx = dele = None
    for ln in hunk["lines"]:
        if ln["t"] == "add" and ln["new"] is not None:
            add = {"line": ln["new"], "side": "RIGHT"}
        elif ln["t"] == "ctx" and ln["new"] is not None:
            ctx = {"line": ln["new"], "side": "RIGHT"}
        elif ln["t"] == "del" and ln["old"] is not None:
            dele = {"line": ln["old"], "side": "LEFT"}
    return add or ctx or dele


def hunk_new_lines(hunk):
    """Set of new-side (RIGHT) line numbers present in a hunk — the lines an
    annotation or comment may legitimately anchor to."""
    return {ln["new"] for ln in hunk["lines"] if ln["new"] is not None}


def split_annot_key(key):
    """An annotation key is one of:
      "h012"        → bare hunk id
      "h012:58"     → a single line
      "h012:58-63"  → a line range (start-end, new-side)
    Returns (hid, line_or_None, start_or_None) where `line` is the end line
    (the anchor) and `start` is the range start (None for a single line)."""
    if ":" in key:
        hid, _, spec = key.rpartition(":")
        if "-" in spec:
            a, _, b = spec.partition("-")
            if a.isdigit() and b.isdigit():
                lo, hi = sorted((int(a), int(b)))
                return hid, hi, lo
        elif spec.isdigit():
            return hid, int(spec), None
    return key, None, None


def cmd_render(args):
    workdir = args.workdir
    # "review-less" mode: drop AI findings/unclear entirely, keeping only the
    # explanatory annotations (意図/コード解説/解説), human comments and PR
    # submission. Set via --no-review.
    no_review = getattr(args, "no_review", False)
    with open(os.path.join(workdir, "diff_data.json")) as fp:
        data = json.load(fp)
    expl = {"title": "", "groups": []}
    expl_path = os.path.join(workdir, "explanations.json")
    if os.path.exists(expl_path):
        with open(expl_path) as fp:
            expl.update(json.load(fp))

    files = data["files"]
    src = data["source"]
    is_branch = src["mode"] == "branch"

    # hunk lookup: id -> (hunk, file)
    hmap = {}
    for f in files:
        for h in f["hunks"]:
            hmap[h["id"]] = (h, f)

    groups = list(expl.get("groups", []))
    used = set()
    for g in groups:
        used.update(g.get("hunks", []))
    leftover = [hid for hid in hmap if hid not in used]
    if leftover:
        groups.append({"name": "その他の変更", "risk": "low",
                       "intent": "上記グループに含まれない残りの変更です。",
                       "hunks": leftover})

    # display order is risk order (stable: author order kept within a level)
    risk_order = {"high": 0, "medium": 1, "low": 2}
    groups.sort(key=lambda g: risk_order.get(g.get("risk", "low"), 2))

    total_add = sum(f["additions"] for f in files)
    total_del = sum(f["deletions"] for f in files)
    n_hunks = len(hmap)
    if no_review:
        n_findings_total = n_unclear_total = 0
    else:
        n_findings_total = sum(len(g.get("findings", {}) or {}) for g in groups)
        n_unclear_total = sum(len(g.get("unclear", {}) or {}) for g in groups)

    if src["mode"] == "branch":
        default_title = f'{src["head"]} の差分レビュー'
        src_line = (f'<code>{esc(src["base_branch"])}</code> ⟵ '
                    f'<code>{esc(src["head"])}</code> · merge-base '
                    f'<code>{esc(src["merge_base"][:12])}</code>')
    else:
        jp = {"unstaged": "未ステージ差分", "staged": "ステージ済み差分",
              "worktree": "作業ツリー差分 (HEAD比較)"}[src["mode"]]
        default_title = f'{jp}レビュー'
        src_line = (f'{jp} · ブランチ <code>{esc(src["head"])}</code>')
    title = expl.get("title") or default_title

    # ---- overview list
    ov_items = []
    for gi, g in enumerate(groups):
        risk = RISK.get(g.get("risk", "low"), RISK["low"])
        nf = 0 if no_review else len(g.get("findings", {}) or {})
        nu = 0 if no_review else len(g.get("unclear", {}) or {})
        tags = "".join(f'<span class="pill">{esc(t)}</span>'
                       for t in g.get("tags", []))
        desc = g.get("description") or g.get("intent", "")
        if len(desc) > 60:
            desc = desc[:60] + "…"
        find_badge = (f'<span class="findct">指摘 {nf}</span>' if nf else "") \
            + (f'<span class="unclct">要改善 {nu}</span>' if nu else "")
        ov_items.append(f"""
<a class="ov risk-{risk["cls"]}" href="#group-{gi}">
  <div class="ov-main">
    <div class="ov-name">{esc(g.get("name", "(無題)"))}</div>
    <div class="ov-desc">{esc(desc)}</div>
  </div>
  <div class="ov-side">
    {find_badge}{tags}
    <span class="hunkct">{len(g.get("hunks", []))} hunks</span>
    <span class="badge {risk["cls"]}">{risk["label"]}</span>
  </div>
</a>""")

    # ---- group detail sections
    sections = []
    copy_items = []   # LLM annotations for the copy-back summary
    group_meta = []   # gid-indexed names for JS
    key_warnings = []  # annotation keys whose line doesn't exist in the hunk
    # annotation types, in the display order shown under each line/hunk.
    # In no-review mode the AI findings/unclear are dropped entirely.
    ANNOT_FIELDS = [
        ("hunk_intents", "hintent"), ("code_notes", "code"),
        ("findings", "finding"), ("unclear", "unclear"),
        ("hunk_notes", "note"),
    ]
    if no_review:
        ANNOT_FIELDS = [(f, k) for f, k in ANNOT_FIELDS
                        if f not in ("findings", "unclear")]
    SENDABLE_KINDS = {"finding", "unclear"}  # only these go to a PR
    for gi, g in enumerate(groups):
        risk = RISK.get(g.get("risk", "low"), RISK["low"])
        group_meta.append({"name": g.get("name", "(無題)")})

        # organize this group's annotations per hunk into line-level and
        # hunk-level buckets. Keys are "h012", "h012:58" or "h012:58-63".
        hunk_line = {}   # hid -> {end_line -> [(kind, text, start_or_None)]}
        hunk_whole = {}  # hid -> [(kind, text)]
        for field, kind in ANNOT_FIELDS:
            for key, text in (g.get(field, {}) or {}).items():
                hid, line, start = split_annot_key(key)
                if hid not in hmap:
                    continue
                h, _f = hmap[hid]
                if line is not None:
                    lines = hunk_new_lines(h)
                    # both ends of a range must exist in the hunk
                    ok = line in lines and (start is None or start in lines)
                    if not ok:
                        key_warnings.append(key)
                        hunk_whole.setdefault(hid, []).append((kind, text))
                    else:
                        hunk_line.setdefault(hid, {}).setdefault(
                            line, []).append((kind, text, start))
                else:
                    hunk_whole.setdefault(hid, []).append((kind, text))

        hunks_html = []
        for hid in g.get("hunks", []):
            if hid not in hmap:
                continue
            h, f = hmap[hid]
            # build inline (line-level) annotations, attaching send checkboxes
            line_annots = {}
            for line, items in hunk_line.get(hid, {}).items():
                out = []
                for kind, text, start in items:
                    sendable = None
                    if is_branch and kind in SENDABLE_KINDS:
                        sendable = {"hid": hid, "path": f["path"],
                                    "line": line, "side": "RIGHT"}
                        if start is not None:
                            sendable["start_line"] = start
                            sendable["start_side"] = "RIGHT"
                    out.append((kind, text, sendable))
                    if kind in SENDABLE_KINDS:
                        rng = f"{start}-{line}" if start is not None else line
                        copy_items.append({
                            "id": f"{hid}:{rng}", "file": f["path"],
                            "kind": ANNOT_KINDS[kind][0], "text": text})
                line_annots[line] = out
            hunks_html.append(render_hunk(h, f["path"], line_annots,
                                          generated=f.get("generated", False)))

            # hunk-level annotations render below the hunk (line unspecified)
            anchor = hunk_comment_anchor(h) if is_branch else None
            hunk_send = ({"hid": hid, "path": f["path"], "scope": "whole",
                          **anchor} if anchor else None)
            for kind, text in hunk_whole.get(hid, []):
                send = hunk_send if kind in SENDABLE_KINDS else None
                hunks_html.append(note_html(text, kind, sendable=send))
                if kind in SENDABLE_KINDS:
                    copy_items.append({"id": hid, "file": f["path"],
                                       "kind": ANNOT_KINDS[kind][0],
                                       "text": text})
            hunks_html.append(
                f'<textarea class="cmt" data-key="hunk:{hid}" rows="1" '
                f'placeholder="このハンクにコメントを残す…"></textarea>')
        intent = g.get("intent", "")
        intent_html = (f'<div class="intent"><span class="intent-label">意図:'
                       f'</span> {md_to_html(intent)}</div>') if intent else ""
        sections.append(f"""
<section class="group risk-{risk["cls"]}" id="group-{gi}">
  <header class="group-head">
    <div class="group-title">
      <span class="badge {risk["cls"]}">{risk["label"]}</span>
      <h2>{esc(g.get("name", "(無題)"))}</h2>
    </div>
    <label class="approve"><input type="checkbox" class="approve-cb"
      data-gid="{gi}" onchange="updateProgress()"> 確認して承認</label>
  </header>
  {intent_html}
  <div class="group-body">
    {"".join(hunks_html)}
    <textarea class="cmt cmt-group" data-key="group:{gi}" rows="1"
      placeholder="このグループ全体へのコメント…"></textarea>
  </div>
</section>""")

    store_key = f"diffReview:{title}:{src.get('merge_base', src['mode'])[:12]}"

    hunk_files = {hid: f["path"] for hid, (h, f) in hmap.items()}
    # per-hunk PR-comment anchor: hid -> {path, line, side}
    hunk_anchors = {}
    for hid, (h, f) in hmap.items():
        anchor = hunk_comment_anchor(h)
        if anchor:
            hunk_anchors[hid] = {"path": f["path"], **anchor}
    pr_context = {
        "mode": src["mode"],
        "head": src.get("head", ""),
        "base": src.get("base_branch", ""),
    }
    data_js = (
        f"var COPY_ITEMS = {json.dumps(copy_items, ensure_ascii=False)};\n"
        f"var GROUP_META = {json.dumps(group_meta, ensure_ascii=False)};\n"
        f"var HUNK_FILES = {json.dumps(hunk_files, ensure_ascii=False)};\n"
        f"var HUNK_ANCHORS = {json.dumps(hunk_anchors, ensure_ascii=False)};\n"
        f"var PR_CONTEXT = {json.dumps(pr_context, ensure_ascii=False)};\n"
        f"var PAGE_TITLE = {json.dumps(title, ensure_ascii=False)};"
    )
    extra_js = """
var CKEY = KEY + ':comments';
var comments = (function () {
  try { return JSON.parse(localStorage.getItem(CKEY) || '{}'); }
  catch (e) { return {}; }
})();
function persistComments() {
  try { localStorage.setItem(CKEY, JSON.stringify(comments)); } catch (e) {}
}
function bindComment(t) {
  if (comments[t.dataset.key] != null) t.value = comments[t.dataset.key];
  t.addEventListener('input', function () {
    comments[t.dataset.key] = t.value;
    persistComments();
  });
}
document.querySelectorAll('.cmt').forEach(bindComment);
// ---- per-line comments (single line or a multi-line range) -------------
// A line comment lives in a textarea that is BOTH a .cmt (so it persists and
// feeds the summary) and carries data-cpath/cline/cside (+ data-cstart for a
// range) so it can become a GitHub review line comment. The comment anchors
// to `cline` (the end line); a range additionally sends start_line=cstart.
// Key: line:<path>:<line>:<side>:<n>. Range starts persist in RANGEKEY.
var RANGEKEY = KEY + ':lineRanges';
var lineRanges = (function () {
  try { return JSON.parse(localStorage.getItem(RANGEKEY) || '{}'); }
  catch (e) { return {}; }
})();
function makeLineCommentRow(path, line, side, n, colspan, startLine) {
  startLine = (startLine == null) ? line : startLine;
  var isRange = String(startLine) !== String(line);
  var tr = document.createElement('tr');
  tr.className = 'line-cmt-row';
  var td = document.createElement('td');
  td.colSpan = colspan;
  var box = document.createElement('div');
  box.className = 'line-cmt-box';
  var meta = document.createElement('div');
  meta.className = 'line-cmt-meta';
  meta.textContent = path + ':' + (isRange ? (startLine + '-' + line) : line)
    + ' (' + side + ')';
  var del = document.createElement('button');
  del.className = 'line-cmt-del';
  del.textContent = '削除';
  var key = 'line:' + path + ':' + line + ':' + side + ':' + n;
  del.onclick = function () {
    delete comments[key];
    delete lineRanges[key];
    persistComments(); persistRanges();
    tr.parentNode.removeChild(tr);
  };
  var ta = document.createElement('textarea');
  ta.className = 'cmt line-cmt';
  ta.rows = 2;
  ta.dataset.key = key;
  ta.dataset.cpath = path;
  ta.dataset.cline = line;
  ta.dataset.cside = side;
  if (isRange) ta.dataset.cstart = startLine;
  ta.placeholder = isRange ? 'この範囲へのコメント…' : 'この行へのコメント…';
  meta.appendChild(del);
  box.appendChild(meta);
  box.appendChild(ta);
  td.appendChild(box);
  tr.appendChild(td);
  bindComment(ta);
  return { tr: tr, ta: ta };
}
function persistRanges() {
  try { localStorage.setItem(RANGEKEY, JSON.stringify(lineRanges)); }
  catch (e) {}
}
// insert a comment row under `endRow`, after any existing comment rows there
function insertLineComment(endRow, path, line, side, startLine) {
  var colspan = endRow.children.length;
  var n = 0;
  while (comments['line:' + path + ':' + line + ':' + side + ':' + n] != null)
    n++;
  var made = makeLineCommentRow(path, line, side, n, colspan, startLine);
  var anchor = endRow;
  while (anchor.nextSibling && anchor.nextSibling.classList &&
         anchor.nextSibling.classList.contains('line-cmt-row')) {
    anchor = anchor.nextSibling;
  }
  endRow.parentNode.insertBefore(made.tr, anchor.nextSibling);
  comments[made.ta.dataset.key] = '';
  if (startLine != null && String(startLine) !== String(line)) {
    lineRanges[made.ta.dataset.key] = startLine;
    persistRanges();
  }
  made.ta.focus();
}
function toggleLineComment(btn) {
  var row = btn.closest('tr');
  insertLineComment(row, row.dataset.cpath, row.dataset.cline,
                    row.dataset.cside);
}
// ---- drag selection on the new-side line-number column -----------------
// Everything is scoped to the START cell's table so overlapping line numbers
// in other hunks/files can't be mis-selected. We paint by DOM position
// between the start and current rows (not by numeric line value).
(function () {
  var startCell = null, startTable = null;
  function clearSel() {
    document.querySelectorAll('tr.range-sel').forEach(function (r) {
      r.classList.remove('range-sel');
    });
  }
  // paint every lnum-bearing row between two rows (inclusive) in one table
  function paintBetween(rowA, rowB, table) {
    clearSel();
    var rows = Array.prototype.slice.call(
      table.querySelectorAll('tr')).filter(function (r) {
        return r.querySelector(':scope > td.lnum');
      });
    var ia = rows.indexOf(rowA), ib = rows.indexOf(rowB);
    if (ia < 0 || ib < 0) return;
    var lo = Math.min(ia, ib), hi = Math.max(ia, ib);
    for (var i = lo; i <= hi; i++) rows[i].classList.add('range-sel');
  }
  function lnumCellFrom(e) {
    return e.target && e.target.closest ? e.target.closest('td.lnum') : null;
  }
  document.addEventListener('mousedown', function (e) {
    var cell = lnumCellFrom(e);
    if (!cell) return;
    e.preventDefault();                 // stop native text selection
    startCell = cell;
    startTable = cell.closest('table');
    startTable.classList.add('dragging');
    paintBetween(cell.closest('tr'), cell.closest('tr'), startTable);
  });
  document.addEventListener('mousemove', function (e) {
    if (!startCell) return;
    var cell = lnumCellFrom(e);
    if (!cell || cell.closest('table') !== startTable) return;
    paintBetween(startCell.closest('tr'), cell.closest('tr'), startTable);
  });
  document.addEventListener('mouseup', function (e) {
    if (!startCell) return;
    var sc = startCell, tbl = startTable;
    startCell = null; startTable = null;
    if (tbl) tbl.classList.remove('dragging');
    // end cell = the lnum cell under the pointer, else the start cell
    var endCell = lnumCellFrom(e);
    if (!endCell || endCell.closest('table') !== tbl) endCell = sc;
    var a = parseInt(sc.dataset.lnum, 10),
        b = parseInt(endCell.dataset.lnum, 10);
    var loLn = Math.min(a, b), hiLn = Math.max(a, b);
    // the end row (anchor) is whichever of the two cells has the higher line
    var endRow = (a >= b ? sc : endCell).closest('tr');
    clearSel();
    var path = endRow.dataset.cpath, side = endRow.dataset.cside;
    if (path == null) return;
    insertLineComment(endRow, path, hiLn, side, loLn === hiLn ? null : loLn);
  });
})();
// restore saved line comments: group keys by their target row, rebuild DOM
(function () {
  var byRow = {};
  Object.keys(comments).forEach(function (k) {
    if (k.indexOf('line:') !== 0) return;
    // line:<path>:<line>:<side>:<n> — path may contain ':'? split from right
    var parts = k.split(':');
    var n = parts.pop(), side = parts.pop(), line = parts.pop();
    var path = parts.slice(1).join(':');
    (byRow[path + '\\u0000' + line + '\\u0000' + side] =
      byRow[path + '\\u0000' + line + '\\u0000' + side] || []).push(
      { n: parseInt(n, 10), path: path, line: line, side: side, key: k });
  });
  Object.keys(byRow).forEach(function (rk) {
    var items = byRow[rk].sort(function (a, b) { return a.n - b.n; });
    var first = items[0];
    var sel = 'tr[data-cpath="' + (window.CSS && CSS.escape ?
      CSS.escape(first.path) : first.path) + '"][data-cline="' +
      first.line + '"][data-cside="' + first.side + '"]';
    var row;
    try { row = document.querySelector(sel); } catch (e) { row = null; }
    if (!row) return;
    var colspan = row.children.length;
    var anchor = row;
    items.forEach(function (it) {
      var made = makeLineCommentRow(it.path, it.line, it.side, it.n, colspan,
                                    lineRanges[it.key]);
      row.parentNode.insertBefore(made.tr, anchor.nextSibling);
      anchor = made.tr;
    });
  });
})();
// ---- AI-comment send toggles (findings/unclear -> PR line comments) ----
var AIKEY = KEY + ':aisend';
var aiSend = (function () {
  try { return JSON.parse(localStorage.getItem(AIKEY) || '{}'); }
  catch (e) { return {}; }
})();
document.querySelectorAll('.ai-send-cb').forEach(function (cb) {
  var k = cb.dataset.key;
  if (aiSend[k] === false) cb.checked = false;   // default checked
  cb.addEventListener('change', function () {
    aiSend[k] = cb.checked;
    try { localStorage.setItem(AIKEY, JSON.stringify(aiSend)); } catch (e) {}
  });
});
function toast(msg) {
  var el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  setTimeout(function () { el.classList.remove('show'); }, 1800);
}
function buildSummary() {
  var lines = ['## レビューまとめ: ' + PAGE_TITLE, ''];
  ['指摘', '要改善'].forEach(function (kind) {
    var items = COPY_ITEMS.filter(function (i) { return i.kind === kind; });
    if (!items.length) return;
    lines.push('### ' + kind + ' (レビューAI)');
    items.forEach(function (i) {
      lines.push('- [' + i.id + '] ' + i.file + ' — ' + i.text);
    });
    lines.push('');
  });
  var cmtLines = [];
  document.querySelectorAll('.cmt').forEach(function (t) {
    if (!t.value.trim()) return;
    var key = t.dataset.key, label;
    if (key.indexOf('group:') === 0) {
      var g = GROUP_META[parseInt(key.slice(6), 10)];
      label = 'グループ: ' + (g ? g.name : key);
    } else if (key.indexOf('line:') === 0) {
      label = t.dataset.cpath + ':' + (t.dataset.cstart ?
        t.dataset.cstart + '-' + t.dataset.cline : t.dataset.cline);
    } else if (key.indexOf('hunk:') === 0) {
      var hid = key.slice(5);
      label = hid + (HUNK_FILES[hid] ? ' ' + HUNK_FILES[hid] : '');
    } else {
      label = key;
    }
    cmtLines.push('- [' + label + '] ' + t.value.trim());
  });
  if (cmtLines.length) {
    lines.push('### レビュアーのコメント');
    lines = lines.concat(cmtLines);
    lines.push('');
  }
  var unapproved = [];
  document.querySelectorAll('.approve-cb').forEach(function (cb) {
    if (!cb.checked) {
      var g = GROUP_META[parseInt(cb.dataset.gid, 10)];
      unapproved.push(g ? g.name : cb.dataset.gid);
    }
  });
  if (unapproved.length) {
    lines.push('### 未承認グループ');
    unapproved.forEach(function (n) { lines.push('- ' + n); });
  }
  return lines.join('\\n').trim() + '\\n';
}
function copyText(text, msg) {
  function fallback(t) {
    var ta = document.createElement('textarea');
    ta.value = t;
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); } catch (e) {}
    document.body.removeChild(ta);
  }
  var done = function () { toast(msg); };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(done,
      function () { fallback(text); done(); });
  } else { fallback(text); done(); }
}
function copySummary() {
  copyText(buildSummary(), 'レビューまとめをコピーしました');
}
// ---- PR review payload (for `gh api .../reviews`) -----------------------
function selectedEvent() {
  var r = document.querySelector('input[name="review-event"]:checked');
  return r ? r.value : 'COMMENT';
}
var AI_PREFIX = '🤖 Claude';
function buildReviewPayload() {
  // Comments come from three sources, each tagged with an author:
  //  - human line comments (exact line)      author: 'human'
  //  - human hunk comments (representative)   author: 'human'
  //  - checked AI findings/unclear            author: 'ai' (prefixed body)
  var comments = [];
  var skipped = [];
  document.querySelectorAll('.cmt').forEach(function (t) {
    var key = t.dataset.key;
    if (!t.value.trim()) return;
    if (key.indexOf('line:') === 0) {
      var c = { path: t.dataset.cpath,
                line: parseInt(t.dataset.cline, 10),
                side: t.dataset.cside, body: t.value.trim(),
                author: 'human' };
      if (t.dataset.cstart) {           // multi-line range comment
        c.start_line = parseInt(t.dataset.cstart, 10);
        c.start_side = t.dataset.cside;
      }
      comments.push(c);
    } else if (key.indexOf('hunk:') === 0) {
      var hid = key.slice(5);
      var a = HUNK_ANCHORS[hid];
      if (!a) { skipped.push(hid); return; }
      comments.push({ path: a.path, line: a.line, side: a.side,
                      body: t.value.trim(), author: 'human' });
    }
  });
  // checked AI comments: prefix the body so GitHub readers see the author
  document.querySelectorAll('.ai-send-cb').forEach(function (cb) {
    if (!cb.checked) return;
    var raw = cb.dataset.body || '';
    if (!raw.trim()) return;
    var c = {
      path: cb.dataset.cpath,
      line: parseInt(cb.dataset.cline, 10),
      side: cb.dataset.cside,
      body: AI_PREFIX + ' (' + cb.dataset.kind + '): ' + raw.trim(),
      author: 'ai'
    };
    if (cb.dataset.cstart) {           // AI range comment
      c.start_line = parseInt(cb.dataset.cstart, 10);
      c.start_side = cb.dataset.cstartside || 'RIGHT';
    }
    comments.push(c);
  });
  var event = selectedEvent();
  var body = (document.getElementById('review-body') || {}).value || '';
  var nHuman = comments.filter(function (c) { return c.author === 'human'; })
    .length;
  var nAi = comments.length - nHuman;
  var payload = {
    event: event,          // APPROVE | REQUEST_CHANGES | COMMENT
    body: body.trim(),
    comments: comments,
    _context: {
      head: PR_CONTEXT.head, base: PR_CONTEXT.base, mode: PR_CONTEXT.mode,
      title: PAGE_TITLE,
      counts: { human: nHuman, ai: nAi },
      skipped_hunks: skipped   // hunks whose comment had no anchorable line
    }
  };
  return payload;
}
function copyReviewPayload() {
  if (PR_CONTEXT.mode !== 'branch') {
    toast('PR送信はbranchモードの差分でのみ利用できます');
    return;
  }
  var p = buildReviewPayload();
  var c = p._context.counts;
  copyText(JSON.stringify(p, null, 2),
    'PR送信用JSONをコピー（人間 ' + c.human + '件 / AI ' + c.ai + '件）');
}
"""

    # PR review panel — only for branch-mode diffs (a PR reviews a branch)
    if src["mode"] == "branch":
        pr_panel_html = """
  <div class="seclabel">03 / PRレビューを送信</div>
  <section class="pr-panel">
    <p class="pr-note">送信対象は 2 種類: あなたが各行・各ハンクに書いた
      コメント（author=human）と、レビューAIの指摘・要改善のうち「PRに送る」に
      チェックしたもの（author=ai、本文に🤖 Claude prefix付き）。AIの指摘は
      デフォルトで送信ONなので、不要なものはチェックを外してください。判定を
      選び「PR送信用にコピー」でJSONをコピーし、作業セッションに戻して送信を
      依頼してください。</p>
    <div class="pr-events">
      <label><input type="radio" name="review-event" value="COMMENT" checked>
        コメントのみ (COMMENT)</label>
      <label><input type="radio" name="review-event" value="APPROVE">
        承認 (APPROVE)</label>
      <label><input type="radio" name="review-event" value="REQUEST_CHANGES">
        変更を要求 (REQUEST_CHANGES)</label>
    </div>
    <textarea id="review-body" class="cmt" rows="2"
      placeholder="レビュー全体のサマリーコメント（任意）…"></textarea>
    <button class="copybtn pr-send" onclick="copyReviewPayload()">
      PR送信用にコピー</button>
  </section>"""
    else:
        pr_panel_html = ""

    html_doc = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<style>
:root {{
  --bg:#f7f8fa; --card:#fff; --border:#e3e6eb; --fg:#20242c;
  --muted:#6b7280; --accent:#2563eb;
  --green:#15803d; --red:#c2333b;
  --add-bg:#e9f7ee; --add-ln:#d4eedd; --del-bg:#fdeeee; --del-ln:#f7d9d9;
  --hl-del:#f3b8bc; --hl-add:#b3e2c1;
  --risk-high:#d64550; --risk-med:#e5a53a; --risk-low:#aab2bd;
  --find-bg:#fdf2f2; --find-border:#e4a3a8;
  --note-bg:#f4f7fe; --note-border:#b9cdf2;
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg);
  font:14px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans",
  "Hiragino Kaku Gothic ProN","Noto Sans CJK JP",Meiryo,sans-serif; }}
.wrap {{ max-width:1240px; margin:0 auto; padding:0 28px 100px; }}
/* ---- header ---- */
.topbar {{ position:sticky; top:0; z-index:20; background:var(--card);
  border-bottom:1px solid var(--border);
  box-shadow:0 1px 4px rgba(20,24,32,.04); }}
.topbar-in {{ max-width:1240px; margin:0 auto; display:flex;
  align-items:center; gap:18px; padding:14px 28px; }}
.brand {{ font-family:var(--mono); font-size:12px; letter-spacing:.35em;
  color:var(--muted); white-space:nowrap; }}
.doc-title {{ font-size:18px; font-weight:700; line-height:1.4;
  max-width:420px; }}
.stats {{ font-family:var(--mono); font-size:13px; background:var(--bg);
  border:1px solid var(--border); border-radius:8px; padding:6px 14px;
  white-space:nowrap; }}
.plus {{ color:var(--green); font-weight:700; }}
.minus {{ color:var(--red); font-weight:700; }}
.progress-wrap {{ margin-left:auto; display:flex; align-items:center;
  gap:12px; white-space:nowrap; }}
.progress {{ width:220px; height:6px; border-radius:3px; background:#e8eaef;
  overflow:hidden; }}
.progress > div {{ height:100%; width:0%; background:var(--green);
  transition:width .25s; }}
.helpbtn {{ width:32px; height:32px; border-radius:8px;
  border:1px solid var(--border); background:var(--bg); cursor:pointer;
  font-family:var(--mono); }}
/* ---- section labels ---- */
.seclabel {{ font-family:var(--mono); font-size:13px; letter-spacing:.25em;
  color:var(--muted); margin:44px 0 16px; }}
/* ---- overview ---- */
.ovlist {{ background:var(--card); border:1px solid var(--border);
  border-radius:12px; overflow:hidden; }}
.ov {{ display:flex; gap:16px; align-items:center; padding:16px 20px;
  border-left:4px solid var(--risk-low); text-decoration:none;
  color:inherit; }}
.ov + .ov {{ border-top:1px solid var(--border); }}
.ov:hover {{ background:#fbfcfe; }}
.ov.risk-high {{ border-left-color:var(--risk-high); }}
.ov.risk-medium {{ border-left-color:var(--risk-med); }}
.ov-name {{ font-weight:700; font-size:15px; }}
.ov-desc {{ color:var(--muted); font-size:13px; }}
.ov-side {{ margin-left:auto; display:flex; align-items:center; gap:10px;
  white-space:nowrap; }}
.pill {{ font-family:var(--mono); font-size:12px; padding:2px 10px;
  border:1px solid var(--border); border-radius:7px; background:var(--bg);
  color:var(--muted); }}
.hunkct {{ font-family:var(--mono); font-size:13px; color:var(--muted); }}
.findct {{ color:var(--red); font-weight:700; font-size:13px; }}
.unclct {{ color:#956a00; font-weight:700; font-size:13px; }}
.badge {{ font-size:12px; font-weight:700; padding:3px 10px;
  border-radius:7px; }}
.badge.high {{ background:#fbe3e5; color:#b02a33; }}
.badge.medium {{ background:#fdf3d7; color:#956a00; }}
.badge.low {{ background:#edeff3; color:#5b6472; }}
/* ---- group detail ---- */
.group {{ background:var(--card); border:1px solid var(--border);
  border-left:4px solid var(--risk-low); border-radius:12px;
  margin-bottom:28px; padding:20px 24px; }}
.group.risk-high {{ border-left-color:var(--risk-high); }}
.group.risk-medium {{ border-left-color:var(--risk-med); }}
.group-head {{ display:flex; align-items:flex-start; gap:14px; }}
.group-title {{ display:flex; align-items:center; gap:12px; flex-wrap:wrap; }}
.group-title h2 {{ font-size:19px; margin:0; }}
.approve {{ margin-left:auto; display:flex; align-items:center; gap:9px;
  border:1px solid var(--border); border-radius:10px; padding:10px 18px;
  font-weight:600; cursor:pointer; user-select:none; background:var(--card);
  white-space:nowrap; }}
.approve:has(input:checked) {{ background:#e9f7ee; border-color:#8fd0a4;
  color:var(--green); }}
.approve input {{ width:16px; height:16px; accent-color:var(--green); }}
.intent {{ margin:10px 0 4px; }}
.intent-label {{ color:var(--green); font-weight:700; }}
.intent p {{ display:inline; margin:0; }}
.intent p + p {{ display:block; margin-top:6px; }}
/* ---- hunks ---- */
.hunk {{ margin-top:18px; border:1px solid var(--border); border-radius:10px;
  overflow:hidden; }}
.hunk-head {{ display:flex; gap:12px; align-items:baseline;
  background:#f2f4f8; border-bottom:1px solid var(--border);
  padding:8px 14px; font-family:var(--mono); font-size:13px; }}
.hid {{ color:var(--muted); }}
.hpath {{ font-weight:700; }}
.hrange {{ color:var(--muted); }}
.genbadge {{ margin-left:auto; font-size:11px; padding:1px 8px;
  border-radius:6px; background:#edeff3; color:#5b6472;
  border:1px solid var(--border); }}
table.diff {{ width:100%; border-collapse:collapse; font-family:var(--mono);
  font-size:12.5px; line-height:21px; }}
table.diff td {{ padding:0 9px; vertical-align:top; }}
td.ln {{ width:1%; min-width:46px; text-align:right; color:#9aa1ac;
  user-select:none; border-right:1px solid #eef0f4; background:var(--card); }}
td.ln.lnum {{ cursor:pointer; }}
td.ln.lnum:hover {{ background:#dbe3f4; color:var(--accent); }}
/* during a drag, suppress native text selection across the table */
table.diff.dragging {{ user-select:none; -webkit-user-select:none; }}
tr.range-sel td.code {{ background:#e0eaff; }}
tr.range-sel td.ln {{ background:#cfddff; }}
td.code {{ white-space:pre-wrap; word-break:break-all; position:relative; }}
.sign {{ display:inline-block; width:13px; user-select:none;
  color:var(--muted); }}
tr.add td.code {{ background:var(--add-bg); }}
tr.add td.ln {{ background:var(--add-ln); }}
tr.del td.code {{ background:var(--del-bg); }}
tr.del td.ln {{ background:var(--del-ln); }}
tr.del .hl {{ background:var(--hl-del); border-radius:3px; }}
tr.add .hl {{ background:var(--hl-add); border-radius:3px; }}
tr.meta td.code {{ color:var(--muted); font-style:italic; }}
/* ---- per-line comment ---- */
.addcmt {{ position:absolute; left:-11px; top:50%;
  transform:translateY(-50%); width:20px; height:20px; padding:0;
  border:none; border-radius:6px; background:var(--accent); color:#fff;
  font-size:15px; line-height:20px; cursor:pointer; opacity:0;
  transition:opacity .12s; z-index:2; }}
tr:hover .addcmt {{ opacity:1; }}
.addcmt:hover {{ background:#1d4fd0; }}
tr.annot-row td.annot-cell {{ padding:6px 12px 6px 40px;
  background:var(--card); white-space:normal; }}
tr.annot-row .annot {{ margin:4px 0; }}
tr.line-cmt-row td {{ padding:0; background:var(--card); }}
.line-cmt-box {{ margin:8px 12px 8px 52px; }}
.line-cmt-box .line-cmt-meta {{ font-family:var(--mono); font-size:11.5px;
  color:var(--muted); margin-bottom:4px; }}
.line-cmt-box textarea {{ margin:0; }}
.line-cmt-del {{ float:right; border:none; background:none; cursor:pointer;
  color:var(--muted); font-size:12px; }}
.line-cmt-del:hover {{ color:var(--red); }}
/* ---- annotations ---- */
.annot {{ display:flex; gap:12px; margin:10px 0 4px; border:1px solid;
  border-radius:10px; padding:10px 14px; font-size:13px; }}
.annot.hintent {{ background:#f4f1fb; border-color:#c8b8ec; }}
.annot.note {{ background:var(--note-bg); border-color:var(--note-border); }}
.annot.code {{ background:#eef8f1; border-color:#a8d8ba; }}
.annot.finding {{ background:var(--find-bg); border-color:var(--find-border); }}
.annot.unclear {{ background:#fdf7e7; border-color:#e2c078; }}
.annot-label {{ font-weight:800; white-space:nowrap; }}
.hintent .annot-label {{ color:#6d4bc0; }}
.note .annot-label {{ color:var(--accent); }}
.code .annot-label {{ color:var(--green); }}
.finding .annot-label {{ color:var(--red); }}
.unclear .annot-label {{ color:#956a00; }}
.annot-body p {{ margin:0 0 4px; }}
.annot-body p:last-child {{ margin:0; }}
.annot-body ul {{ margin:4px 0; padding-left:20px; }}
.ai-send {{ display:inline-flex; align-items:center; gap:6px; margin-top:6px;
  font-size:12px; color:var(--muted); cursor:pointer; user-select:none; }}
.ai-send input {{ width:14px; height:14px; accent-color:var(--accent); }}
.cmt {{ display:block; width:100%; margin:10px 0 2px;
  border:1px dashed var(--border); border-radius:8px; padding:8px 12px;
  font:inherit; font-size:13px; resize:vertical; background:#fbfcfe;
  color:var(--fg); min-height:38px; }}
.cmt:focus {{ outline:none; border:1px solid var(--accent);
  background:var(--card); }}
.cmt-group {{ border-color:#cdd4de; }}
.copybtn {{ border:1px solid var(--border); border-radius:8px;
  background:var(--bg); padding:7px 14px; cursor:pointer; font-weight:600;
  font-size:13px; white-space:nowrap; }}
.copybtn:hover {{ background:#eef1f6; }}
#toast {{ position:fixed; bottom:24px; left:50%;
  transform:translateX(-50%); background:#20242c; color:#fff;
  padding:10px 20px; border-radius:10px; opacity:0; transition:opacity .2s;
  pointer-events:none; z-index:50; font-size:13px; }}
#toast.show {{ opacity:1; }}
code {{ background:rgba(148,158,175,.18); border-radius:4px; padding:1px 5px;
  font-family:var(--mono); font-size:12px; }}
pre {{ background:#f2f4f8; border-radius:8px; padding:10px; overflow-x:auto; }}
pre code {{ background:none; padding:0; }}
/* ---- PR review panel ---- */
.pr-panel {{ background:var(--card); border:1px solid var(--border);
  border-radius:12px; padding:20px 24px; margin-bottom:28px; }}
.pr-note {{ color:var(--muted); font-size:13px; margin:0 0 14px; }}
.pr-events {{ display:flex; flex-wrap:wrap; gap:10px 22px; margin-bottom:12px; }}
.pr-events label {{ display:flex; align-items:center; gap:7px; font-weight:600;
  cursor:pointer; }}
.pr-events input {{ width:16px; height:16px; accent-color:var(--accent); }}
.pr-send {{ margin-top:12px; }}
/* ---- help dialog ---- */
dialog {{ border:1px solid var(--border); border-radius:12px; padding:22px;
  max-width:460px; }}
dialog::backdrop {{ background:rgba(20,24,32,.35); }}
dialog h3 {{ margin-top:0; }}
.legend {{ display:grid; grid-template-columns:auto 1fr; gap:8px 14px;
  align-items:center; font-size:13px; }}
</style>
</head>
<body>
<div class="topbar"><div class="topbar-in">
  <span class="brand">DIFF REVIEW</span>
  <span class="doc-title">{esc(title)}</span>
  <span class="stats">{len(files)} files / {n_hunks} hunks
    <span class="plus">+{total_add}</span>
    <span class="minus">-{total_del}</span></span>
  <span class="progress-wrap">
    <span class="progress"><div id="progress-fill"></div></span>
    <span id="progress-text">承認 0/{len(groups)}</span>
    <button class="copybtn" onclick="copySummary()">まとめをコピー</button>
    {'<button class="copybtn" onclick="copyReviewPayload()">PR送信用にコピー</button>' if src["mode"] == "branch" else ""}
    <button class="helpbtn" onclick="document.getElementById('help').showModal()">?</button>
  </span>
</div></div>
<div class="wrap">
  <div class="seclabel">対象: {src_line} · 生成 {esc(data["generated_at"])}
    · 解説量 {esc(data.get("detail", "medium"))}
    {"· 指摘 " + str(n_findings_total) + "件" if n_findings_total else ""}
    {"· 要改善 " + str(n_unclear_total) + "件" if n_unclear_total else ""}</div>
  <div class="seclabel">01 / 変更グループ一覧</div>
  <div class="ovlist">{"".join(ov_items)}</div>
  <div class="seclabel">02 / 変更グループ詳細</div>
  {"".join(sections)}
  {pr_panel_html}
</div>
<dialog id="help">
  <h3>この画面の見方</h3>
  <div class="legend">
    <span class="badge high">要注意</span><span>挙動変更やリスクを含み、重点的に確認が必要</span>
    <span class="badge medium">注意</span><span>広範囲だが機械的な変更。ざっと確認</span>
    <span class="badge low">低リスク</span><span>docs・生成物など影響の小さい変更</span>
    <span class="annot-label" style="color:var(--red)">指摘</span><span>レビューで対応を検討すべき点</span>
    <span class="annot-label" style="color:#956a00">要改善</span><span>改善余地あり、または変更の意図が読み取れない箇所</span>
    <span class="annot-label" style="color:#6d4bc0">意図</span><span>そのハンク固有の変更意図（グループ意図とは別）</span>
    <span class="annot-label" style="color:var(--accent)">解説</span><span>変更の意図・背景の説明</span>
    <span class="annot-label" style="color:var(--green)">コード解説</span><span>変更後のコードが何をしているかの読解補助</span>
  </div>
  <p>各グループの「確認して承認」をチェックすると上部の進捗に反映されます。
  ハンクやグループのコメント欄に書いた内容は「まとめをコピー」で指摘・要改善と
  一緒に Markdown 化され、そのまま作業セッションへ貼り付けられます。
  承認状態とコメントはこのブラウザに保存されます。</p>
  <form method="dialog"><button class="helpbtn" style="width:auto;padding:6px 16px">閉じる</button></form>
</dialog>
<div id="toast"></div>
<script>
var KEY = {json.dumps(store_key)};
function loadState() {{
  try {{ return JSON.parse(localStorage.getItem(KEY) || '{{}}'); }}
  catch (e) {{ return {{}}; }}
}}
function updateProgress() {{
  var cbs = document.querySelectorAll('.approve-cb');
  var state = {{}};
  var done = 0;
  cbs.forEach(function (cb) {{
    state[cb.dataset.gid] = cb.checked;
    if (cb.checked) done++;
  }});
  document.getElementById('progress-text').textContent =
    '承認 ' + done + '/' + cbs.length;
  document.getElementById('progress-fill').style.width =
    (cbs.length ? (100 * done / cbs.length) : 0) + '%';
  try {{ localStorage.setItem(KEY, JSON.stringify(state)); }} catch (e) {{}}
}}
(function () {{
  var state = loadState();
  document.querySelectorAll('.approve-cb').forEach(function (cb) {{
    if (state[cb.dataset.gid]) cb.checked = true;
  }});
  updateProgress();
}})();
{data_js}
{extra_js}
</script>
</body>
</html>"""

    out = args.out or os.path.join(workdir, "diff_review.html")
    with open(out, "w") as fp:
        fp.write(html_doc)
    print(out)
    if key_warnings:
        print("WARNING: これらの注釈キーは指定行がハンク内に存在しないため "
              "ハンク単位にフォールバックしました（行番号は新側/RIGHTの実在行を "
              "指定してください）:", file=sys.stderr)
        for k in key_warnings:
            print(f"  {k}", file=sys.stderr)


# ----------------------------------------------------------------------- cli


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("extract", help="compute and parse the diff")
    pe.add_argument("--mode", default="branch",
                    choices=["branch", "unstaged", "staged", "worktree"])
    pe.add_argument("--base", help="base branch (branch mode; auto-detected)")
    pe.add_argument("--head", help="head ref (branch mode; default HEAD)")
    pe.add_argument("--workdir", help="output dir (default: mktemp)")
    pe.add_argument("--detail", default="medium",
                    choices=["small", "medium", "large"],
                    help="how much explanation prose to write (small/medium/"
                         "large); the caller reads this and writes "
                         "explanations.json accordingly")
    pe.set_defaults(func=cmd_extract)

    pr = sub.add_parser("render", help="render the review HTML")
    pr.add_argument("--workdir", required=True)
    pr.add_argument("--out", help="output HTML path")
    pr.add_argument("--no-review", action="store_true",
                    help="explanation-only: drop AI findings/unclear, keep "
                         "解説・human comments・PR submission")
    pr.set_defaults(func=cmd_render)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
