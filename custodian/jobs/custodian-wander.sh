#!/usr/bin/env bash
# Wrapper: Custodian wander mode
exec python3 "$(dirname "$0")/../sub-agents/custodian.py" wander
