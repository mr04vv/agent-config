#!/bin/sh
# Label the herdr pane with a one-line summary of the conversation.
#
# Codex CLI does not name threads on its own: with tui.terminal_title set to
# ["thread-title"], an unnamed thread falls back to the raw session UUID, so a
# Codex pane shows "019fa79f-..." where a Claude pane shows a summary. The TUI
# has /rename for this, but nothing does it automatically. This fills that gap.
#
# The label is set with `herdr pane report-metadata --title`, which is
# display-only and overlays the pane's terminal title.
#
# Why not the app-server "thread/name/set" method that /rename drives: it does
# set the real thread name and persists it, but the ThreadNameUpdated
# notification is delivered only to the connection that made the request
# (`self.outgoing` in thread_processor.rs). A hook necessarily runs as a separate
# process, so the already-running TUI never learns about the rename and keeps
# printing the UUID. Verified: the name lands in session_index.jsonl and reads
# back through thread/list, while the live pane title does not change.
#
# Wired to the Stop hook. Runs once per session -- the marker file below -- since
# the summary costs an extra `codex exec` call.
#
# RECURSION: the summarizer is itself a `codex exec`, and that child fires its
# own Stop hook on exit. Unguarded this forks without bound: every child is a
# NEW session, so a session-id marker does not stop it. Two independent guards,
# either of which alone is sufficient:
#   1. CODEX_TITLE_HOOK below -- inherited by the child (the hook runner does not
#      clear the environment), so the child's hook returns immediately.
#   2. the child is spawned with `-c hooks.events.stop=[]`, so it has no Stop
#      hook to fire in the first place.
#
# Kept separate from herdr-agent-state.sh on purpose: that file is owned by
# herdr and is overwritten by `herdr integration install codex`.

set -eu

# Guard 1: bail out if we are already inside a title-generating child.
[ -n "${CODEX_TITLE_HOOK:-}" ] && exit 0
export CODEX_TITLE_HOOK=1

input="$(cat)"

# The label goes to a herdr pane, so there is nothing to do outside herdr.
[ "${HERDR_ENV:-}" = "1" ] || exit 0
[ -n "${HERDR_PANE_ID:-}" ] || exit 0
command -v python3 >/dev/null 2>&1 || exit 0
command -v codex >/dev/null 2>&1 || exit 0
command -v herdr >/dev/null 2>&1 || exit 0

session_id="$(printf '%s' "$input" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("session_id") or "")' 2>/dev/null || true)"
transcript="$(printf '%s' "$input" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("transcript_path") or "")' 2>/dev/null || true)"
[ -n "$session_id" ] || exit 0

# One title per session. Without this the hook re-summarizes on every turn.
#
# The marker is only written once the label has actually been applied, at the
# very end. Claiming it up front means any earlier bail-out -- most importantly a
# first-turn Stop firing before the transcript has been flushed -- burns the
# marker and the session never gets a title on a later turn.
marker="${TMPDIR:-/tmp}/codex-title-$session_id"
[ -e "$marker" ] && exit 0

[ -n "$transcript" ] && [ -r "$transcript" ] || exit 0

# Only the head of the transcript matters: the opening request is what the title
# should describe, and this bounds what gets piped into the summarizer.
excerpt="$(python3 - "$transcript" <<'PY'
#
# Rollout lines are {type, timestamp, payload}; the conversation lives in the
# payload of type "response_item", whose content is a list of parts carrying
# "text". Two kinds of noise must be dropped or the title describes Codex's own
# scaffolding instead of the conversation:
#   - role "developer": injected permissions / multi-agent instructions
#   - <environment_context> blocks, which arrive under role "user"
import json, sys

out = []
try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get("type") != "response_item":
                continue
            payload = obj.get("payload")
            if not isinstance(payload, dict):
                continue
            role = payload.get("role")
            if role not in ("user", "assistant"):
                continue
            content = payload.get("content")
            if not isinstance(content, list):
                continue
            text = " ".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            ).strip()
            if not text or text.startswith("<environment_context>"):
                continue
            out.append(f"{role}: {text[:600]}")
            if len(out) >= 4:
                break
except Exception:
    pass
print("\n".join(out)[:2000])
PY
)"

[ -n "$excerpt" ] || exit 0

# Guard 2: the child runs with no Stop hook of its own. Pinned to the smallest
# model at low effort -- this is a one-line summary, not a reasoning task, and it
# sits on the critical path of every session's first turn.
#
# No `timeout` wrapper: coreutils timeout is not present on stock macOS, so the
# hook runner's own timeout (kill_on_drop) is what bounds this.
title="$(printf '%s' "$excerpt" | codex exec \
  --skip-git-repo-check \
  -c 'hooks.events.stop=[]' \
  -c 'model="gpt-5.4-mini"' \
  -c 'model_reasoning_effort="low"' \
  'Summarize what this conversation is about as a title. Reply with the title only: no quotes, no punctuation at the end, at most 40 characters, same language as the conversation.' \
  2>/dev/null | tail -1 | tr -d '\r' | cut -c1-80 || true)"

[ -n "$title" ] || exit 0

# Reported as a custom token, not --title: the sidebar rows in herdr.nix render
# named tokens, and a pane's --title metadata is not one of them, so a title set
# that way lands in the pane record and is never displayed. The matching
# $codex_title token is in the codex row of ui.sidebar.agents.rows_by_agent.
#
# --source names the reporter so the value can be cleared or replaced later
# without disturbing metadata herdr itself set.
herdr pane report-metadata "$HERDR_PANE_ID" \
  --source "codex-title" \
  --token "codex_title=$title" >/dev/null 2>&1 || exit 0

# Claim the session only now that a title is actually on the pane, so a failed
# or too-early attempt is retried on the next turn.
: > "$marker"
