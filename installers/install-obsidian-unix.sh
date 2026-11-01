#!/usr/bin/env bash
set -euo pipefail
kit_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python_cmd="${MEMORY_SHARE_PYTHON:-python3}"
download_dir="${MEMORY_SHARE_DOWNLOAD_DIR:-$HOME/Downloads/MemoryShare-Obsidian}"
case "$(uname -s)" in
  Darwin)
    if [[ -d /Applications/Obsidian.app || -d "$HOME/Applications/Obsidian.app" ]]; then
      echo 'Existing Obsidian found; keeping it.'; exit 0
    fi
    "$python_cmd" "$kit_dir/tools/download_obsidian.py" macos --output "$download_dir"
    mount_dir="$(mktemp -d)"
    trap 'hdiutil detach "$mount_dir" >/dev/null 2>&1 || true; rmdir "$mount_dir" 2>/dev/null || true' EXIT
    hdiutil attach "$download_dir/Obsidian-1.14.5.dmg" -nobrowse -mountpoint "$mount_dir"
    mkdir -p "$HOME/Applications"
    ditto "$mount_dir/Obsidian.app" "$HOME/Applications/Obsidian.app"
    echo 'Installed in ~/Applications. Open Obsidian, then Open folder as vault.'
    ;;
  Linux)
    if command -v obsidian >/dev/null 2>&1; then echo 'Existing Obsidian command found; keeping it.'; exit 0; fi
    case "$(uname -m)" in
      x86_64) asset_platform=linux-x86_64; filename=Obsidian-1.14.5.AppImage ;;
      aarch64|arm64) asset_platform=linux-arm64; filename=Obsidian-1.14.5-arm64.AppImage ;;
      *) echo 'Unsupported Linux CPU; use official download page.' >&2; exit 2 ;;
    esac
    if [[ -e "$HOME/.local/bin/obsidian-memory-share" ]]; then echo 'Existing launcher found; keeping it.'; exit 0; fi
    "$python_cmd" "$kit_dir/tools/download_obsidian.py" "$asset_platform" --output "$download_dir"
    app_dir="$HOME/.local/opt/obsidian-memory-share"
    mkdir -p "$app_dir" "$HOME/.local/bin"
    cp "$download_dir/$filename" "$app_dir/$filename"
    chmod +x "$app_dir/$filename"
    ln -s "$app_dir/$filename" "$HOME/.local/bin/obsidian-memory-share"
    echo "Installed. Run: $HOME/.local/bin/obsidian-memory-share"
    echo 'Requires a graphical desktop and working AppImage/FUSE support. Do not run as root or disable the sandbox.'
    ;;
  *) echo 'Supported: macOS and Linux' >&2; exit 2 ;;
esac
