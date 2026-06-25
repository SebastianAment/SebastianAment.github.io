#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

LOCK_FILE="/tmp/update_publications.lock"
LOG_FILE="$HOME/.local/log/update_publications.log"
mkdir -p "$(dirname "$LOG_FILE")"

# Prevent concurrent runs.
if [ -f "$LOCK_FILE" ]; then
    echo "Another update is already running (lock: $LOCK_FILE). Aborting."
    exit 1
fi
trap 'rm -f "$LOCK_FILE"' EXIT
touch "$LOCK_FILE"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG_FILE"; }

log "==> Pulling latest changes..."
if ! git pull; then
    log "ERROR: git pull failed (merge conflict or network issue). Aborting."
    exit 1
fi

# Check for unresolved merge state.
if [ -f .git/MERGE_HEAD ]; then
    log "ERROR: Merge conflict detected. Resolve manually, then re-run."
    exit 1
fi

log ""
log "==> Updating publications from Semantic Scholar..."
python3 update_publications.py

log ""
log "==> Updating publications from Google Scholar..."
/Users/sebastianament/opt/miniconda3/bin/python3 update_publications.py --source scholar

if git diff --quiet media/; then
    log ""
    log "No changes detected — nothing to commit."
    exit 0
fi

log ""
log "==> Committing and pushing..."
git add media/publications.json media/citation_history.json \
       media/publications_scholar.json media/citation_history_scholar.json
git commit -m "citations update"

if ! git push; then
    log "ERROR: git push failed. You may need to pull and resolve conflicts."
    exit 1
fi

log ""
log "Done."
