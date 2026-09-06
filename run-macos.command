#!/bin/bash
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  echo 'Please run the setup commands in README.md first.'
  exit 1
fi
exec .venv/bin/python -m linguaflow
