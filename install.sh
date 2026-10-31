#!/bin/sh
set -eu
cd "$(dirname "$0")"
command -v python3.13 >/dev/null 2>&1 || { echo 'Python 3.13 is required for the tested dependency set.'; exit 1; }
exec python3.13 setup.py install "$@"
