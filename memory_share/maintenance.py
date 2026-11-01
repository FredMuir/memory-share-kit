import hashlib
from pathlib import Path
import subprocess
import time

from .core import Authority


def backup_upload(state, directory, remote=None):
    """Upload an immutable SQLite backup, then verify SHA256 by reading actual remote bytes."""
    directory = Path(directory).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (time.strftime("memory-%Y%m%dT%H%M%SZ-", time.gmtime()) + str(time.time_ns()) + ".sqlite3")
    Authority(Path(state) / "authority.sqlite3").backup(path)
    result = {"backup": str(path), "uploaded": False, "verified": False}
    if not remote:
        return result
    if remote.startswith("-") or ":" not in remote:
        raise ValueError("remote must be an existing rclone remote:path, not an option or local path")
    dest = remote.rstrip("/") + "/" + path.name
    # No shell; remote is one argument. Do not print rclone stderr which may contain private paths.
    cp = subprocess.run(["rclone", "copyto", str(path), dest, "--retries", "3"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if cp.returncode:
        raise RuntimeError("rclone upload failed; local backup retained. Retry using rclone copyto, then verify.")
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    proc = subprocess.Popen(["rclone", "cat", dest], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    digest = hashlib.sha256()
    try:
        while chunk := proc.stdout.read(1024 * 1024):
            digest.update(chunk)
    finally:
        proc.stdout.close()
    if proc.wait() or digest.hexdigest() != expected:
        raise RuntimeError("Remote backup verification failed; local backup retained")
    result.update(uploaded=True, verified=True, sha256=expected)
    return result
