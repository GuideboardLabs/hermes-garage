# Hermes Garage 🏠🔧

A collection of Hermes Agent tools, sub-agents, cron jobs, skills, and bridge scripts by [Seth Canfield](https://github.com/GuideboardLabs) / [Guideboard Labs](https://github.com/GuideboardLabs).

## Philosophy

I build Hermes agents that close loops. Research → vault → ideation → review → build. Every script in here is something I run daily — cron agents that wander my knowledge vault, export sessions, triage inboxes, and generate project ideas from real research.

The goal is a persistent cognitive system that gets better over time. Not a chatbot. Not a one-shot generator. Agents that read, write, and reason against a growing knowledge base.

Everything is designed to be **generalized**: set `$VAULT_ROOT` and `$LLAMA_URL` and it adapts to your setup. Fork it, gut it, make it yours.

## What's here

| Component | What it does |
|-----------|-------------|
| **[hackysack/](hackysack/)** | Creative ideation agent — reads research + vault walks, applies constraints, generates ranked ideas. Three-pane TUI for review. |
| **[custodian/](custodian/)** | Optional vault wanderer — cross-domain discovery, drift detection, lint walks. |
| **[session-export/](session-export/)** | Export Hermes sessions to structured vault notes. |
| **[inbox-triage/](inbox-triage/)** | Compress raw exports, age out stale inbox items, enforce inbox discipline. |
| **[local-llm/](local-llm/)** | CLI tool to manage local LLM services (start, stop, switch models). |
| **[cron/jobs.json](cron/jobs.json)** | Reference config showing how to wire everything up. |

## Quick start

```bash
# Set your vault and LLM
export VAULT_ROOT="$HOME/.second-brain"
export LLAMA_URL="http://127.0.0.1:8093"
export LLAMA_MODEL="qwen3.5-9b"

# Run something
python3 hackysack/sub-agents/hackysack.py
python3 session-export/sub-agents/hermes-session-export.py
```

See each component's README for setup and usage.

## License

MIT — use it, fork it, build on it.
