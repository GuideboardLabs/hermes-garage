#!/usr/bin/env bash
# Wrapper: Custodian lint mode
exec python3 "$(dirname "$0")/../sub-agents/custodian.py" lint
