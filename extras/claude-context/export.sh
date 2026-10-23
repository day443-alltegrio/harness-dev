#!/bin/sh
# Export of the Claude Code context of one repository into this pack folder, so the
# work can continue on another machine or in another account (README.md, "Restore").
# The pack lives in an untracked folder of the repository (e.g. sandbox/claude-context);
# it holds conversation digests and uncommitted work, so it never goes into git.
#
#   sh <pack>/export.sh          # by hand or nightly (launchd or cron, README.md)
#
# What it writes:
#   memory/     - the project memory of the agent, an exact copy;
#   rules/      - local files outside git listed in RULES (pack.conf);
#   repo/       - uncommitted work: a patch against HEAD, new files, git state;
#   sessions/   - conversation digests (tools/digest.py): no tool output, long numbers
#                 masked;
#   project/    - raw transcripts for `claude --resume` on the same path; never deleted
#                 here, so a transcript cleaned from the machine stays in the pack;
#   skills/, settings.json - user skills and global settings (no secrets expected:
#                 check yours before moving the pack).
# CONTEXT.md (the state of the work) is written by the agent on request, not here.
set -eu
DST=$(cd "$(dirname "$0")" && pwd)
REPO=$(git -C "$DST" rev-parse --show-toplevel)
RULES=".claude/settings.local.json CLAUDE.local.md"
# shellcheck source=/dev/null
[ -f "$DST/pack.conf" ] && . "$DST/pack.conf"
if ! git -C "$REPO" check-ignore -q "$DST"; then
  echo "the pack folder $DST is not ignored by git: add it to .gitignore first"
  exit 1
fi
SRC="$HOME/.claude/projects/$(printf '%s' "$REPO" | sed 's#[^A-Za-z0-9]#-#g')"
mkdir -p "$DST/project" "$DST/skills" "$DST/memory" "$DST/rules" "$DST/repo" "$DST/sessions"

[ -d "$SRC" ] && rsync -a --exclude memory "$SRC/" "$DST/project/"
[ -d "$SRC/memory" ] && rsync -a --delete "$SRC/memory/" "$DST/memory/"
[ -d "$HOME/.claude/skills" ] && rsync -a --delete "$HOME/.claude/skills/" "$DST/skills/"
[ -f "$HOME/.claude/settings.json" ] && cp "$HOME/.claude/settings.json" "$DST/settings.json"
for f in $RULES; do
  # A slash in the path is stored as "__" (install.sh turns it back).
  [ -f "$REPO/$f" ] && cp "$REPO/$f" "$DST/rules/$(printf '%s' "$f" | sed 's#/#__#g')"
done

cd "$REPO"
git rev-parse HEAD > "$DST/repo/base-commit.txt"
git diff HEAD --binary > "$DST/repo/uncommitted.patch"
git ls-files --others --exclude-standard -z | tar --null -T - -czf "$DST/repo/untracked.tar.gz"
{
  echo "branch: $(git branch --show-current)"
  echo "HEAD: $(git log -1 --format='%h %s')"
  echo "against origin: $(git status -sb | head -1)"
  echo "changed files: $(git diff HEAD --name-only | wc -l | tr -d ' ')"
  echo "new files: $(git ls-files --others --exclude-standard | wc -l | tr -d ' ')"
  echo
  git status --short
} > "$DST/repo/git-state.txt"

for f in "$SRC"/*.jsonl; do
  [ -f "$f" ] || continue
  id=$(basename "$f" .jsonl)
  day=$(head -c 400000 "$f" | grep -o '"timestamp":"[0-9-]*' | head -1 | cut -d'"' -f4)
  python3 "$DST/tools/digest.py" "$f" "$DST/sessions/${day:-undated}-${id%%-*}.md" > /dev/null
done

{
  echo "last export: $(date '+%Y-%m-%d %H:%M %Z')"
  echo "transcripts: $(ls "$DST/project"/*.jsonl 2>/dev/null | wc -l | tr -d ' ')"
  echo "digests: $(ls "$DST/sessions" | wc -l | tr -d ' ')"
  echo "memory files: $(ls "$DST/memory" | wc -l | tr -d ' ')"
  echo "uncommitted: $(sed -n 4,5p "$DST/repo/git-state.txt" | tr '\n' ' ')"
  echo "pack size: $(du -sh "$DST" | cut -f1)"
} > "$DST/last-export.txt"
