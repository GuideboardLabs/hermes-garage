# Custodian — Vault Wanderer (Optional)

A background agent that wanders your knowledge vault, picking contrasting folder pairs, reading random notes, and writing structured discoveries. Detects echoes (related ideas across domains), gaps (missing connections), and drift (contradictions or stale references).

## Files

| Path | What |
|------|------|
| `sub-agents/custodian.py` | The wanderer agent — wander, lint, drift modes |
| `sub-agents/custodian-promoter.py` | Promotes discoveries to research notes |
| `jobs/custodian-wander.sh` | Shell wrapper for wander walks |
| `jobs/custodian-lint.sh` | Shell wrapper for lint walks |
| `jobs/custodian-drift.sh` | Shell wrapper for drift walks |
| `config/custodian.ini` | Config template — copy to `~/.hermes/scripts/` |

## Setup

Requires a running LLM server. Set `$VAULT_ROOT`, `$LLAMA_URL`, `$LLAMA_MODEL`.

```bash
# Wander: pick contrasting folder pairs, read notes, write discoveries
python3 sub-agents/custodian.py wander

# Lint: check for broken links, orphan notes, stale metadata
python3 sub-agents/custodian.py lint

# Drift: detect contradictions and stale cross-links
python3 sub-agents/custodian.py drift
```

## Schedule

```bash
# Wander every hour
hermes cron create --schedule "every 60m" \
  --script custodian/jobs/custodian-wander.sh \
  --no-agent --deliver local

# Lint daily at 6am
hermes cron create --schedule "0 6 * * *" \
  --script custodian/jobs/custodian-lint.sh \
  --no-agent --deliver local
```
