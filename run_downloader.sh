#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Stanley E. Strawbridge
# Run with: bash run_downloader.sh
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
export PYTHONUTF8=1
export PYTHONNOUSERSITE=1

fail() { printf '\n%s\n' "$*" >&2; exit 1; }
[[ -f download_dumortier_2019.py && -f requirements.txt ]] || fail 'Extract the full repository ZIP before running this launcher.'

if [[ ! -x .venv/bin/python ]]; then
    PYTHON=""
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
            PYTHON="$candidate"
            break
        fi
    done
    [[ -n "$PYTHON" ]] || fail 'Python 3.10 or newer is required. Install Python, then run this launcher again. See README.md.'
    printf '%s\n' 'Creating an isolated Python environment in .venv ...'
    "$PYTHON" -m venv .venv || fail 'Could not create .venv. Check write permissions and Python venv support. See README.md.'
fi

.venv/bin/python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || fail 'The local .venv is not usable. Remove only .venv and rerun the launcher. Do not remove your data.'

# Skip installation when dependencies and the requirements fingerprint agree.
if ! .venv/bin/python -c 'import hashlib, pathlib, requests; p=pathlib.Path(".venv/requirements.sha256"); assert p.read_text().strip() == hashlib.sha256(pathlib.Path("requirements.txt").read_bytes()).hexdigest()' >/dev/null 2>&1; then
    printf '%s\n' 'Installing the downloader dependency into .venv ...'
    .venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt || fail 'Dependency installation failed. Check the network/proxy settings and see README.md.'
    .venv/bin/python -c 'import hashlib, pathlib; pathlib.Path(".venv/requirements.sha256").write_text(hashlib.sha256(pathlib.Path("requirements.txt").read_bytes()).hexdigest())'
fi

# Arguments are passed unchanged. Relative destinations are relative to ROOT.
exec .venv/bin/python download_dumortier_2019.py "$@"
