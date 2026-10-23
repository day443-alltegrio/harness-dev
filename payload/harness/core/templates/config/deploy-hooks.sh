# Project steps of harness/core/scripts/deploy.sh (sourced by it). Fill in each function.
# A failed step returns non-zero; it never prints a warning and goes on.
# Available: $NOTES (release notes), $WORK (local temporary folder).
# The commented lines are an example for one Linux machine reached over ssh with a
# systemd service; replace them with the project's own transport.

TARGET_HOST="${TARGET_HOST:-}"           # e.g. app-1.internal
TARGET_DIR="${TARGET_DIR:-/opt/app}"     # the running code
SERVICE="${SERVICE:-app}"                # systemd unit
REMOTE_ARCHIVE="/tmp/release-$$.tar.gz"

not_configured() { echo "harness/config/deploy-hooks.sh: $1 is not configured yet" >&2; return 1; }

# Only committed files ship (preflight has proved the tree is clean). git archive
# never packs macOS metadata files (._*), which once stopped a deploy.
deploy_package() {   # $1 = archive path
  git archive --format=tar.gz -o "$1" HEAD
}

deploy_ship() {      # $1 = archive path
  not_configured deploy_ship
  # scp -q "$1" "$TARGET_HOST:$REMOTE_ARCHIVE"
}

# Unpack next to the running code and check it there, before anything is replaced.
# Print the JSON line of deploy_check.py; deploy.sh reads the verdict from it.
deploy_verify() {    # $1 = the reason an API break is allowed (may be empty)
  not_configured deploy_verify
  # ssh "$TARGET_HOST" "set -e; S=\$(mktemp -d /tmp/stage-XXXXXXXX); \
  #   tar -xzf $REMOTE_ARCHIVE -C \$S; cd \$S; \
  #   $TARGET_DIR/.venv/bin/python harness/core/scripts/deploy_check.py check \
  #     --staged \$S --current $TARGET_DIR ${1:+--allow-breaking \"$1\"}; \
  #   echo \$S > /tmp/release-stage-$$"
}

deploy_swap() {
  not_configured deploy_swap
  # ssh "$TARGET_HOST" "set -e; S=\$(cat /tmp/release-stage-$$); \
  #   sudo rsync -a --delete --exclude .venv \$S/ $TARGET_DIR/; \
  #   sudo systemctl restart $SERVICE; rm -rf \$S $REMOTE_ARCHIVE /tmp/release-stage-$$"
}

# QG5: up and answering. Add smoke checks of the main function (a real request with a
# non-empty answer), not only "the process runs".
deploy_health() {
  not_configured deploy_health
  # sleep 3
  # ssh "$TARGET_HOST" "systemctl is-active --quiet $SERVICE" &&
  #   curl -fsS "http://$TARGET_HOST:8080/health" >/dev/null
}

# Optional: record attempts in the project's own deploy table instead of the default
# harness/.state/deploys.jsonl. Print the attempt id.
# deploy_journal() {  # $1 = DONE|BLOCKED|FAILED, $2 = report JSON
#   ...
# }
