#!/bin/sh
cd "$(dirname "$0")"
for command in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$command" >/dev/null 2>&1; then
    exec "$command" start.py
  fi
done
echo "需要 Python 3.10 或更高版本。"
exit 2
