#!/usr/bin/env bash
set -euo pipefail
umask 077

# macOS and Linux, current user only. No curl|sh, no sudo, no Agent config overwrite.
kit_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python_cmd="${MEMORY_SHARE_PYTHON:-python3}"
device="${1:?Usage: bash installers/install-unix.sh DEVICE_ID ABSOLUTE_VAULT_PATH}"
vault="${2:?Provide existing or new absolute Vault path}"
if [[ "$vault" != /* ]]; then echo 'Vault path must be absolute' >&2; exit 2; fi
"$python_cmd" -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ required"'
if [[ "$(uname -s)" == Darwin ]]; then
  install_root="${MEMORY_SHARE_INSTALL_ROOT:-$HOME/Library/Application Support/MemoryShare}"
else
  install_root="${MEMORY_SHARE_INSTALL_ROOT:-${XDG_DATA_HOME:-$HOME/.local/share}/memory-share}"
fi
mkdir -p "$install_root"
chmod 700 "$install_root"
venv="$install_root/venv"
if [[ -d "$venv" ]]; then
  echo 'Existing installation found; use documented upgrade procedure instead of overwriting it.' >&2
  exit 2
fi
"$python_cmd" -m venv "$venv"
python_bin="$venv/bin/python"
"$python_bin" -m pip install -r "$kit_dir/requirements.lock"
"$python_bin" -m pip install --no-deps "$kit_dir/dist/memory_share_kit-0.1.3-py3-none-any.whl"
if [[ ! -f "$install_root/client.json" ]]; then
  "$python_bin" -m memory_share --state "$install_root" init --device "$device" --vault "$vault"
else
  echo 'Existing client identity retained.'
fi
"$python_bin" -m memory_share --state "$install_root" snippets
"$python_bin" "$kit_dir/tools/autostart.py" --state "$install_root" --output "$install_root/autostart"
echo "Installed. Python executable: $python_bin"
echo "Private state: $install_root"
echo 'Next: configure device token, merge generated MCP snippets, exclude generated folder in Remotely Save.'
