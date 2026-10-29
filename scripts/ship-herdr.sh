#!/usr/bin/env bash
# Run scripts/ship.py in a Herdr workspace labelled "ship <name>": ship.py in
# the left pane, the builder and reviewer logs tailing on the right (top and
# bottom). Takes the same arguments as ship.py.
#
# Usage: bash scripts/ship-herdr.sh [--print] task tasks/<name>.md [options]
#        bash scripts/ship-herdr.sh [--print] branch <branch> --task tasks/<name>.md [options]
#
# --print only prints the herdr commands it would run. Without herdr, or with
# no herdr server running, it runs ship.py directly in this terminal.
#
# Herdr CLI as documented for v0.9.5 at https://herdr.dev/docs/socket-api/:
#   herdr workspace create --cwd <dir> --label <text>
#   herdr pane split <pane> --direction right|down
#   herdr pane run <pane> "<command>"   (queues the command; does not wait)
# Per `herdr --skill`: workspace create returns .result.root_pane, pane split
# returns .result.pane.pane_id, and server errors exit 1 with JSON on stderr.
set -euo pipefail

usage() {
  echo "usage: $0 [--print] task tasks/<name>.md [ship.py options]" >&2
  echo "       $0 [--print] branch <branch> --task tasks/<name>.md [ship.py options]" >&2
}

print_only=0
if [[ "${1:-}" == "--print" ]]; then
  print_only=1
  shift
fi
if [[ $# -lt 2 ]]; then
  usage
  exit 2
fi

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# The run is named after the task file's stem, as in ship.py.
task=""
case "$1" in
  task) task="$2" ;;
  branch)
    prev=""
    for arg in "$@"; do
      if [[ "$prev" == "--task" ]]; then task="$arg"; fi
      prev="$arg"
    done
    ;;
  *)
    usage
    exit 2
    ;;
esac
if [[ -z "$task" ]]; then
  echo "branch mode needs --task tasks/<name>.md" >&2
  exit 2
fi
name="$(basename "$task" .md)"
logs="$HOME/projects/.ship/$name"

printf -v quoted '%q ' "$@"
ship_cmd="uv run python scripts/ship.py ${quoted% }"
printf -v builder_cmd 'tail -F %q' "$logs/builder.log"
printf -v reviewer_cmd 'tail -F %q' "$logs/reviewer.log"

if [[ $print_only -eq 1 ]]; then
  cat <<EOF
herdr workspace create --cwd $repo --label "ship $name"   # LEFT=.result.root_pane
herdr pane split "\$LEFT" --direction right --cwd $repo --no-focus   # RIGHT=.result.pane.pane_id
herdr pane split "\$RIGHT" --direction down --cwd $repo --no-focus   # BOTTOM=.result.pane.pane_id
herdr pane run "\$LEFT" "$ship_cmd"
herdr pane run "\$RIGHT" "$builder_cmd"
herdr pane run "\$BOTTOM" "$reviewer_cmd"
EOF
  exit 0
fi

if ! command -v herdr >/dev/null 2>&1; then
  echo "herdr is not installed; running ship.py in this terminal." >&2
  cd "$repo" && exec uv run python scripts/ship.py "$@"
fi
if ! herdr workspace list >/dev/null 2>&1; then
  echo "herdr is not running; running ship.py in this terminal." >&2
  cd "$repo" && exec uv run python scripts/ship.py "$@"
fi

# Read a pane id from a herdr JSON response on stdin.
pane_id() {
  python3 -c '
import json, sys
result = json.load(sys.stdin)["result"]
pane = result.get("pane") or result["root_pane"]
print(pane["pane_id"] if isinstance(pane, dict) else pane)
'
}

left="$(herdr workspace create --cwd "$repo" --label "ship $name" | pane_id)"
right="$(herdr pane split "$left" --direction right --cwd "$repo" --no-focus | pane_id)"
bottom="$(herdr pane split "$right" --direction down --cwd "$repo" --no-focus | pane_id)"
herdr pane run "$left" "$ship_cmd" >/dev/null
herdr pane run "$right" "$builder_cmd" >/dev/null
herdr pane run "$bottom" "$reviewer_cmd" >/dev/null
echo "ship $name: running in Herdr workspace \"ship $name\" (panes $left, $right, $bottom)"
