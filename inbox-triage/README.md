# Inbox Triage

Enforces inbox discipline on your vault. Compresses raw exports to an archive directory, ages out stale inbox items, and warns when the inbox exceeds a threshold.

## Files

| Path | What |
|------|------|
| `sub-agents/vault-inbox-triage.sh` | The triage script |

## Setup

```bash
export VAULT_ROOT="$HOME/.second-brain"

bash sub-agents/vault-inbox-triage.sh
```

## Schedule

```bash
hermes cron create --schedule "every 15m" \
  --script inbox-triage/sub-agents/vault-inbox-triage.sh \
  --no-agent --deliver local
```
