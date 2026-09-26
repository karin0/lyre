#!/bin/sh
set -e
cd "$(dirname "$0")"
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest -q
