#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv
fi
.venv/bin/python -c "import sys; assert sys.version_info >= (3, 11), 'Python 3.11 or newer is required'"
if [ ! -f .venv/tag_inserter_setup_complete ]; then
    .venv/bin/python -m pip install -r requirements.txt
    touch .venv/tag_inserter_setup_complete
fi
exec .venv/bin/python pdf_tag_inserter.py "$@"
