#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export DJANGO_DEBUG=1
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py bootstrap
exec .venv/bin/python manage.py runserver 127.0.0.1:8000
