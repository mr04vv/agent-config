#!/bin/sh
# Symlink this repo into ~/.claude and ~/.codex. Safe to re-run.
set -eu

ROOT=$(cd "$(dirname "$0")" && pwd)
CLAUDE_DIR=${CLAUDE_CONFIG_DIR:-$HOME/.claude}
CODEX_DIR=${CODEX_HOME:-$HOME/.codex}
BACKUP_DIR=$HOME/.agent-config-backup/$(date +%Y%m%d%H%M%S)

# Shared skills that codex also gets; everything in skills/ goes to Claude.
CODEX_SKILLS="paper-details html documenting-with-sources writing-quotation explain
  grilling herdr show-me"

# Backups go outside the config dirs: a leftover copy under skills/ would load
# as a duplicate skill.
backup() {
  rel=${1#"$HOME"/}
  mkdir -p "$(dirname "$BACKUP_DIR/$rel")"
  mv "$1" "$BACKUP_DIR/$rel"
  echo "backed up $1 -> $BACKUP_DIR/$rel"
}

link() { # <src> <dst>
  mkdir -p "$(dirname "$2")"
  if [ -e "$2" ] && [ ! -L "$2" ]; then
    backup "$2"
  fi
  ln -sfn "$1" "$2"
}

# Files are linked one by one so unmanaged files next to them survive.
link_files() { # <src dir> <dst dir>
  (cd "$1" && find . -type f ! -name .DS_Store) | while read -r f; do
    link "$1/${f#./}" "$2/${f#./}"
  done
}

# --- Claude Code ---
link_files "$ROOT/claude" "$CLAUDE_DIR"
for d in "$ROOT"/skills/*/; do
  link "${d%/}" "$CLAUDE_DIR/skills/$(basename "$d")"
done
link_files "$ROOT/ponytail/commands" "$CLAUDE_DIR/commands"
# The hooks read ../skills/ponytail/SKILL.md; ponytail/skills is a symlink to
# ../skills, so that path resolves to skills/ponytail in this repo.
link "$ROOT/ponytail" "$CLAUDE_DIR/ponytail"

# --- Codex ---
for f in "$ROOT"/codex/*; do
  [ "$(basename "$f")" = config.base.toml ] && continue
  link "$f" "$CODEX_DIR/$(basename "$f")"
done
for s in $CODEX_SKILLS; do
  link "$ROOT/skills/$s" "$CODEX_DIR/skills/$s"
done

# Codex writes machine state (project trust, hook trust hashes, MCP servers,
# plugins) into the same config.toml, so it cannot be a symlink. Rebuild it
# from config.base.toml and keep every key/table that the base does not set.
python3 - "$ROOT/codex/config.base.toml" "$CODEX_DIR/config.toml" <<'EOF'
import os, re, sys, tomllib

base_path, out_path = sys.argv[1], sys.argv[2]
HEADER = re.compile(r'^\s*\[\[?\s*([^\]]+?)\s*\]\]?\s*(#.*)?$')
KEY = re.compile(r'^\s*("[^"]*"|[A-Za-z0-9_.-]+)\s*=')

def split(text):
    """-> (top-level lines, [(table name, lines)])"""
    top, tables = [], []
    for line in text.splitlines():
        m = HEADER.match(line)
        if m:
            tables.append((m.group(1), [line]))
        elif tables:
            tables[-1][1].append(line)
        else:
            top.append(line)
    return top, tables

base = open(base_path).read()
base_top, base_tables = split(base)
base_keys = set(tomllib.loads(base).keys())

old_top, old_tables = [], []
if os.path.exists(out_path):
    old_top, old_tables = split(open(out_path).read())

# ponytail: line-based merge, a multi-line top-level value (array/string)
# written by codex itself would be split; parse with a TOML lib if that happens.
kept_top = [l for l in old_top
            if (m := KEY.match(l)) and m.group(1).split('.')[0].strip('"') not in base_keys]
kept_tables = [t for t in old_tables
               if t[0].split('.')[0].strip('"') not in base_keys]

out = '\n'.join(base_top + kept_top) + '\n'
for _, lines in base_tables + kept_tables:
    out += '\n'.join(lines).rstrip('\n') + '\n\n'
tomllib.loads(out)  # refuse to write something codex cannot read

tmp = out_path + '.tmp'
os.makedirs(os.path.dirname(out_path), exist_ok=True)
with open(tmp, 'w') as f:
    f.write(out)
os.replace(tmp, out_path)
print(f'generated {out_path}')
EOF
