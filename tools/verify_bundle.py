"""Verify the source distribution's checksums. The manifest is not a digital signature."""
import hashlib
from pathlib import Path

root = Path(__file__).resolve().parents[1]
manifest = root / "CHECKSUMS.sha256"
failed = []
for line in manifest.read_text(encoding="utf-8").splitlines():
    expected, name = line.split("  ", 1)
    path = (root / name).resolve()
    if not path.is_relative_to(root) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        failed.append(name)
if failed:
    print("Checksum failures:", ", ".join(failed))
    raise SystemExit(1)
print("Bundle checksums verified. This checks consistency, not publisher identity.")
