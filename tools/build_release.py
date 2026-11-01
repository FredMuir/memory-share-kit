"""Build source ZIP and checksum manifest; never includes runtime databases or private config."""
import hashlib
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[1]
output = root.parent / "artifacts"
output.mkdir(exist_ok=True)
excluded = {"__pycache__", "build", ".git", ".venv", "downloads"}
files = []
for p in root.rglob("*"):
    if not p.is_file() or p.is_symlink():
        continue
    parts = p.relative_to(root).parts
    if any(x in excluded or x.endswith(".egg-info") for x in parts):
        continue
    if p.name == "CHECKSUMS.sha256" or p.suffix in (".pyc", ".sqlite3") or p.name == "client.json":
        continue
    files.append(p)
files.sort()
manifest = root / "CHECKSUMS.sha256"
manifest.write_text("".join(hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.relative_to(root).as_posix() + "\n" for p in files), encoding="utf-8", newline="\n")
files.append(manifest)
archive = output / "memory-share-kit-v0.1.0.zip"
with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
    for p in files:
        z.write(p, "memory-share-kit/" + p.relative_to(root).as_posix())
digest = hashlib.sha256(archive.read_bytes()).hexdigest()
(output / (archive.name + ".sha256")).write_text(digest + "  " + archive.name + "\n", encoding="ascii")
print(str(archive))
print("files:", len(files), "bytes:", archive.stat().st_size)
print("SHA256:", digest)
