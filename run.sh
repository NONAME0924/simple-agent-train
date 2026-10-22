#!/usr/bin/env sh
set -eu

APP_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$APP_DIR"

# 可指定 Python；依賴準備由 bootstrap.py 統一處理。
if [ -n "${PYTHON_EXEC:-}" ]; then
    :
elif [ -x "$APP_DIR/.venv/bin/python" ]; then
    PYTHON_EXEC="$APP_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_EXEC=python3
else
    PYTHON_EXEC=python
fi

if ! command -v "$PYTHON_EXEC" >/dev/null 2>&1; then
    echo "找不到 Python。請安裝 Python 3.10+（含 venv），或設定 PYTHON_EXEC。" >&2
    exit 1
fi

# 首次自動建立環境、安裝套件，完成後進入共用 launcher.py。
exec "$PYTHON_EXEC" -u -B "$APP_DIR/launcher/bootstrap.py" "$@"
