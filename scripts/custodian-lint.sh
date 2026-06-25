#!/usr/bin/env bash
# Wrapper: Custodian lint mode
exec python3 "$(dirname "$0")/custodian.py" lint
