#!/usr/bin/env bash
# Wrapper: Mr. Scan pulse mode
exec python3 "$(dirname "$0")/mr-scan.py" pulse
