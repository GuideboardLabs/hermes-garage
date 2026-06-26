# Hermes Garage

A collection of scanfi's Hermes Agent tools, sub-agents, cron jobs, and bridge scripts for building persistent cognitive systems.

## Philosophy

Hermes agents that close loops. Research → vault → ideation → review → build. Every script here runs on a schedule — cron agents that wander your knowledge vault, export sessions, triage inboxes, and generate project ideas from real research.

The goal is a persistent cognitive system that gets better over time. Not a chatbot. Not a one-shot generator. Agents that read, write, and reason against a growing knowledge base.

Everything is designed to be **generalized**: set `$VAULT_ROOT` and `$LLAMA_URL` and it adapts to your setup. Fork it, gut it, make it yours.

## What's here

| Component | What it does | Required? |
|-----------|-------------|-----------|
| **[hackysack/](hackysack/)** | Creative ideation agent — reads research + vault walks, applies constraints, generates ranked ideas. Three-pane TUI for review. | ✅ Core |
| **[session-export/](session-export/)** | Export Hermes sessions to structured vault notes. | ✅ Core |
| **[inbox-triage/](inbox-triage/)** | Compress raw exports, age out stale inbox items, enforce inbox discipline. | ✅ Core |
| **[local-llm/](local-llm/)** | CLI tool to manage local LLM services (start, stop, switch models). | ✅ Core |
| **[custodian/](custodian/)** | Optional vault wanderer — cross-domain discovery, drift detection, lint walks. | ❌ Optional |
| **[cron/jobs.json](cron/jobs.json)** | Reference config showing how to wire everything up. | 📋 Reference |

## Quick start

```bash
# 1. Set your vault and LLM
export VAULT_ROOT="$HOME/my-vault"
export LLAMA_URL="http://127.0.0.1:8093"
export LLAMA_MODEL="qwen3.5-9b"

# 2. Run something
python3 hackysack/sub-agents/hackysack.py
python3 session-export/sub-agents/hermes-session-export.py
```

## Schedule as cron jobs

```bash
# Session export every 60 minutes
hermes cron create --schedule "every 60m" \
  --script session-export/sub-agents/hermes-session-export.py \
  --no-agent --deliver local

# Inbox triage every 15 minutes
hermes cron create --schedule "every 15m" \
  --script inbox-triage/sub-agents/vault-inbox-triage.sh \
  --no-agent --deliver local

# Hackysack ideation twice daily
hermes cron create --schedule "0 6,18 * * *" \
  --script hackysack/sub-agents/hackysack.py \
  --no-agent --deliver local
```

See each component's README for setup and usage. See [cron/jobs.json](cron/jobs.json) for a full reference config.

## License

MIT — use it, fork it, build on it.
