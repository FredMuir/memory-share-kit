#!/usr/bin/env bash
set -euo pipefail
umask 077
kit_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python_cmd="${MEMORY_SHARE_PYTHON:-python3}"
server_root="${MEMORY_SHARE_SERVER_ROOT:-$HOME/.local/share/memory-share-server}"
if [[ "${MEMORY_SHARE_ALLOW_UNAUTHENTICATED_PRIVATE_NETWORK:-0}" == "1" ]]; then
  bind_host="${MEMORY_SHARE_BIND_HOST:-0.0.0.0}"
  open_private_network=(--allow-unauthenticated-private-network)
else
  bind_host="${MEMORY_SHARE_BIND_HOST:-127.0.0.1}"
  open_private_network=()
fi
bind_port="${MEMORY_SHARE_BIND_PORT:-8731}"
if [[ -d "$server_root/venv" ]]; then echo 'Existing installation retained; use documented upgrade.' >&2; exit 2; fi
"$python_cmd" -c 'import sys; assert sys.version_info >= (3,11)'
mkdir -p "$server_root"
chmod 700 "$server_root"
"$python_cmd" -m venv "$server_root/venv"
python_bin="$server_root/venv/bin/python"
"$python_bin" -m pip install -r "$kit_dir/requirements.lock"
"$python_bin" -m pip install --no-deps "$kit_dir/dist/memory_share_kit-0.1.6-py3-none-any.whl"
"$python_bin" "$kit_dir/tools/autostart.py" --state "$server_root" --output "$server_root/autostart" --role server --host "$bind_host" --port "$bind_port" "${open_private_network[@]}"
echo "Server installed but not started. Python: $python_bin"
echo "State: $server_root"
echo 'Review generated unit. Private-network mode accepts tokenless clients only from private LAN/overlay IP ranges.'
if [[ "${MEMORY_SHARE_ALLOW_UNAUTHENTICATED_PRIVATE_NETWORK:-0}" != "1" ]]; then
  echo 'Token authentication remains enabled by default.'
fi
