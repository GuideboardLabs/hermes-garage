#!/usr/bin/env bash
# Wrapper: Custodian wander mode
exec python3 "$(dirname "$0")/custodian.py" wander
