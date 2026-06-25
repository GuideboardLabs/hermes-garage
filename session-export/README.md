# Session Export

Exports recent Hermes sessions as structured markdown notes in your vault. Preserves decisions, discoveries, and conversations as durable knowledge.

## Files

| Path | What |
|------|------|
| `sub-agents/hermes-session-export.py` | The export agent |
| `jobs/` | Shell wrappers for cron scheduling (coming) |

## Setup

```bash
export VAULT_ROOT="$HOME/.second-brain"
export HERMES_STATE_DB="$HOME/.hermes/state.db"

python3 sub-agents/hermes-session-export.py
```

## Schedule

```bash
hermes cron create --schedule "every 60m" \
  --script session-export/sub-agents/hermes-session-export.py \
  --no-agent --deliver local
```
