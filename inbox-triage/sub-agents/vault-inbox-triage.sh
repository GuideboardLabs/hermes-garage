#!/usr/bin/env bash
# vault-inbox-triage.sh
# Continuously triages 0-Inbox/. Moves mined/old content to ~/.hermes/vault-archive/.
# Run via cron every 15 min, or manually: ./vault-inbox-triage.sh
#
# Policy:
#   - .json / .jsonl / .json.gz  -> compress (if not already) and move to vault-archive/raw-exports/
#   - .md older than 14 days     -> move to vault-archive/unprocessed-notes/ (unless whitelisted)
#   - custodian/walks/ older than 30 days -> move to vault-archive/unprocessed-notes/custodian-walks/
#   - Files matching a vault-mining process log entry -> safe to archive
#   - Files < 14 days old        -> leave alone (still in active triage window)
#   - .process-log.md, INDEX.md  -> never move
#
# Idempotent. Safe to run repeatedly. Logs to ~/.hermes/vault-archive/triage.log.

set -euo pipefail

VAULT="${OBSIDIAN_VAULT_PATH:-$HOME/my-vault}"
ARCHIVE="${VAULT_ARCHIVE_PATH:-$HOME/.hermes/vault-archive}"
LOG="$ARCHIVE/triage.log"
PROCESS_LOG="$VAULT/0-Inbox/.process-log.md"
TODAY="$(date +%Y-%m-%d)"
NOW="$(date +%Y-%m-%dT%H:%M:%S)"

mkdir -p "$ARCHIVE/raw-exports" "$ARCHIVE/unprocessed-notes" "$ARCHIVE/unprocessed-notes/custodian-walks" "$ARCHIVE/promoted-archive"

log() {
  echo "[$NOW] $*" | tee -a "$LOG"
}

# Track counts for the run summary
MOVED_RAW=0
MOVED_OLD=0
COMPRESSED=0
SKIPPED=0
ERR=0

# --- 1. JSON/JSONL files (raw session exports) ---
# All raw exports are in the process log or have been mined. Move and compress.
shopt -s nullglob
for f in "$VAULT/0-Inbox/"*.json "$VAULT/0-Inbox/"*.jsonl "$VAULT/0-Inbox/"*.json.gz "$VAULT/0-Inbox/"*.jsonl.gz; do
  [ -e "$f" ] || continue
  base="$(basename "$f")"
  # Strip existing .gz for naming
  stem="${base%.gz}"
  dest="$ARCHIVE/raw-exports/${TODAY}-${stem}.gz"

  # If not already gzipped, compress
  if [[ "$base" != *.gz ]]; then
    gzip -c "$f" > "$dest"
    rm -f "$f"
    COMPRESSED=$((COMPRESSED + 1))
    MOVED_RAW=$((MOVED_RAW + 1))
    log "RAW-COMPRESS: $base -> raw-exports/$(basename "$dest")"
  else
    mv "$f" "$dest"
    MOVED_RAW=$((MOVED_RAW + 1))
    log "RAW-MOVE: $base -> raw-exports/$(basename "$dest")"
  fi
done

# --- 2. JSON/JSONL inside subdirectories at 0-Inbox level (e.g. Codex export folder) ---
# These are large archives already organized. Move the whole folder once it's been mined.
# Check process log: if the folder is named there, archive it.
for d in "$VAULT/0-Inbox"/*/; do
  [ -d "$d" ] || continue
  name="$(basename "$d")"
  # Skip live subdirs that shouldn't be archived
  case "$name" in
    custodian) continue ;;  # handled separately (walks inside)
    hermes-sessions) continue ;;  # live cron export target
    _raw) continue ;;
    .*) continue ;;
  esac

  # If this folder appears in the process log, archive it
  if [ -f "$PROCESS_LOG" ] && grep -qF "$name" "$PROCESS_LOG" 2>/dev/null; then
    archive_name="${TODAY}-${name}.tar.gz"
    tar -czf "$ARCHIVE/raw-exports/$archive_name" -C "$VAULT/0-Inbox" "$name" 2>/dev/null
    rm -rf "$d"
    MOVED_RAW=$((MOVED_RAW + 1))
    log "FOLDER-ARCHIVE: $name/ -> raw-exports/$archive_name (in process log)"
  fi
done

# --- 3. .md files in 0-Inbox/ older than 14 days (skip whitelisted) ---
WHITELIST_REGEX='^(\.process-log\.md|INDEX\.md)$'
for f in "$VAULT/0-Inbox/"*.md; do
  [ -e "$f" ] || continue
  base="$(basename "$f")"
  if [[ "$base" =~ $WHITELIST_REGEX ]]; then
    SKIPPED=$((SKIPPED + 1))
    continue
  fi
  # Age in days
  if [ "$(uname)" = "Darwin" ]; then
    mtime_epoch=$(stat -f %m "$f")
  else
    mtime_epoch=$(stat -c %Y "$f")
  fi
  now_epoch=$(date +%s)
  age_days=$(( (now_epoch - mtime_epoch) / 86400 ))

  if [ "$age_days" -gt 14 ]; then
    dest="$ARCHIVE/unprocessed-notes/${TODAY}-${base}"
    mv "$f" "$dest"
    MOVED_OLD=$((MOVED_OLD + 1))
    log "OLD-NOTE: $base (${age_days}d) -> unprocessed-notes/$(basename "$dest")"
  else
    SKIPPED=$((SKIPPED + 1))
  fi
done

# --- 4. Custodian walks older than 30 days ---
WALKS_DIR="$VAULT/0-Inbox/custodian/walks"
if [ -d "$WALKS_DIR" ]; then
  while IFS= read -r -d '' f; do
    if [ "$(uname)" = "Darwin" ]; then
      mtime_epoch=$(stat -f %m "$f")
    else
      mtime_epoch=$(stat -c %Y "$f")
    fi
    now_epoch=$(date +%s)
    age_days=$(( (now_epoch - mtime_epoch) / 86400 ))

    if [ "$age_days" -gt 30 ]; then
      base="$(basename "$f")"
      dest="$ARCHIVE/unprocessed-notes/custodian-walks/${TODAY}-${base}"
      mv "$f" "$dest"
      MOVED_OLD=$((MOVED_OLD + 1))
      log "OLD-WALK: custodian/walks/$base (${age_days}d) -> unprocessed-notes/custodian-walks/$(basename "$dest")"
    fi
  done < <(find "$WALKS_DIR" -maxdepth 1 -type f -name "*.md" -print0 2>/dev/null)
fi

# --- 5. Append INDEX entry ---
INDEX="$ARCHIVE/INDEX.md"
if [ -f "$INDEX" ]; then
  {
    echo ""
    echo "### Triage run — $NOW"
    echo ""
    echo "- Raw exports moved/compressed: $MOVED_RAW"
    echo "- Old notes archived: $MOVED_OLD"
    echo "- Files compressed: $COMPRESSED"
    echo "- Files skipped (whitelisted or recent): $SKIPPED"
    echo "- Errors: $ERR"
  } >> "$INDEX"
fi

# --- 6. Run summary ---
log "SUMMARY: raw=$MOVED_RAW old=$MOVED_OLD compressed=$COMPRESSED skipped=$SKIPPED errors=$ERR"

# --- 7. Health check: warn if inbox has grown past threshold ---
INBOX_COUNT=$(find "$VAULT/0-Inbox" -maxdepth 1 -type f \( -name "*.md" -o -name "*.json" -o -name "*.jsonl" \) 2>/dev/null | wc -l)
if [ "$INBOX_COUNT" -gt 30 ]; then
  log "WARN: 0-Inbox/ has $INBOX_COUNT top-level files (threshold: 30). Review needed."
fi

# Print to stdout too (useful when run interactively)
echo "Triage complete: raw=$MOVED_RAW old=$MOVED_OLD compressed=$COMPRESSED skipped=$SKIPPED errors=$ERR  inbox_top_level=$INBOX_COUNT"
