#!/usr/bin/env bash
# Wrapper: Custodian drift mode
exec python3 "$(dirname "$0")/custodian.py" drift
