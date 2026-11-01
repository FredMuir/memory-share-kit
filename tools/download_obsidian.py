"""Download pinned official installer and verify the release asset SHA256. Does not install."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

p = argparse.ArgumentParser()
p.add_argument("platform", choices=["windows", "macos", "linux-x86_64", "linux-arm64", "linux-deb-amd64"])
p.add_argument("--output", default="downloads")
a = p.parse_args()
manifest = json.loads((Path(__file__).resolve().parents[1] / "installers/obsidian-assets.json").read_text())
asset = manifest["assets"][a.platform]
target = Path(a.output).resolve() / asset["filename"]
target.parent.mkdir(parents=True, exist_ok=True)
if target.exists():
    if hashlib.sha256(target.read_bytes()).hexdigest() != asset["sha256"]:
        raise SystemExit("Existing installer failed checksum; preserved for inspection. Use another output directory.")
    print(str(target)); raise SystemExit(0)
partial = target.with_suffix(target.suffix + ".partial")
url = "https://github.com/obsidianmd/obsidian-releases/releases/download/v" + manifest["version"] + "/" + asset["filename"]
digest = hashlib.sha256()
try:
    with urllib.request.urlopen(url, timeout=60) as response, partial.open("wb") as output:
        while block := response.read(1024 * 1024):
            digest.update(block); output.write(block)
    if digest.hexdigest() != asset["sha256"]:
        raise SystemExit("Installer checksum mismatch; installer will not be run")
    partial.replace(target)
finally:
    partial.unlink(missing_ok=True)
print(str(target))
