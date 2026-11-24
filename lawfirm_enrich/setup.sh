#!/usr/bin/env bash
# One-time setup on Mac or Linux:  bash setup.sh
set -euo pipefail
cd "$(dirname "$0")"

PY=""
for candidate in python3.13 python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
    PY="$candidate"
    break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.11 or later is needed. Install it from https://www.python.org/downloads/ and run this again."
  exit 1
fi

echo "Using $($PY --version)"
"$PY" -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r requirements.txt
echo
.venv/bin/python lawaudit.py status
echo
echo "Setup done. From this folder, run steps with:  .venv/bin/python lawaudit.py <step>"
echo "(or 'source .venv/bin/activate' once, then just: python lawaudit.py <step>)"
