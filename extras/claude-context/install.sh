#!/bin/sh
# Restore of a context pack on a new machine or in another account.
# Run from the repository root, with the pack copied into the same untracked folder:
#   sh <pack>/install.sh            # memory, local rules, skills, settings
#   sh <pack>/install.sh --repo     # plus uncommitted work (patch and new files)
#   sh <pack>/install.sh --resume   # plus raw transcripts for claude --resume
#
# Overwrites nothing: memory and skills are added (existing files untouched), settings
# and local rules only when missing. Secrets are not part of the pack.
set -eu
PACK=$(cd "$(dirname "$0")" && pwd)
REPO=$(git -C "$PACK" rev-parse --show-toplevel)
SLUG=$(printf '%s' "$REPO" | sed 's#[^A-Za-z0-9]#-#g')
PROJ="$HOME/.claude/projects/$SLUG"
mkdir -p "$PROJ/memory" "$HOME/.claude/skills"

echo "memory: $PROJ/memory"
rsync -a --ignore-existing "$PACK/memory/" "$PROJ/memory/"

echo "local rules"
for f in "$PACK"/rules/*; do
  [ -f "$f" ] || continue
  target="$REPO/$(basename "$f" | sed 's#__#/#g')"
  mkdir -p "$(dirname "$target")"
  [ -f "$target" ] || cp "$f" "$target"
done

echo "skills: ~/.claude/skills"
rsync -a --ignore-existing "$PACK/skills/" "$HOME/.claude/skills/"
[ -f "$HOME/.claude/settings.json" ] || cp "$PACK/settings.json" "$HOME/.claude/settings.json"

for arg in "$@"; do
  case "$arg" in
    --repo)
      BASE=$(cat "$PACK/repo/base-commit.txt")
      if [ "$(git -C "$REPO" rev-parse HEAD)" != "$BASE" ]; then
        echo "HEAD is not $BASE: check out that commit first"; exit 1
      fi
      if [ -n "$(git -C "$REPO" status --porcelain)" ]; then
        echo "the working tree is not clean: the patch is not applied"; exit 1
      fi
      git -C "$REPO" apply --binary "$PACK/repo/uncommitted.patch"
      tar -xzf "$PACK/repo/untracked.tar.gz" -C "$REPO"
      echo "uncommitted work restored: $(git -C "$REPO" status --short | wc -l | tr -d ' ') files"
      ;;
    --resume)
      rsync -a --ignore-existing "$PACK/project/" "$PROJ/"
      echo "transcripts copied: claude --resume shows the earlier conversations"
      ;;
  esac
done
echo "done. Next: README.md, step 5 (the first prompt)."
