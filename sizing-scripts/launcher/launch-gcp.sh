#!/usr/bin/env bash
exec python3 "$(dirname "$0")/wiz-sizing.py" --csp gcp "$@"
