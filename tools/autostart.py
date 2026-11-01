"""Generate reviewable native autostart files. Never enables services itself."""
import argparse
from pathlib import Path
import plistlib
import subprocess
import sys

from memory_share.core import atomic_write

p = argparse.ArgumentParser()
p.add_argument("--state", required=True)
p.add_argument("--output", required=True)
p.add_argument("--role", choices=["client", "server"], default="client")
p.add_argument("--host", default="127.0.0.1")
p.add_argument("--port", default="8731", type=int)
a = p.parse_args()
state = str(Path(a.state).expanduser().resolve())
out = Path(a.output).resolve(); out.mkdir(parents=True, exist_ok=True)
args = [sys.executable, "-m", "memory_share", "--state", state]
args += ["worker", "--interval", "30"] if a.role == "client" else ["serve", "--host", a.host, "--port", str(a.port)]
label = "org.memoryshare." + a.role

def sd_quote(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'

unit = f"""[Unit]
Description=Memory Share {a.role}
After=network.target

[Service]
Type=simple
ExecStart={" ".join(sd_quote(s) for s in args)}
Restart=on-failure
RestartSec=15
UMask=0077
NoNewPrivileges=true

[Install]
WantedBy=default.target
"""
atomic_write(out / ("memory-share-" + a.role + ".service"), unit)
plist = {"Label": label, "ProgramArguments": args, "RunAtLoad": True, "KeepAlive": True,
         "ThrottleInterval": 15, "StandardOutPath": str(Path(state) / (a.role + ".out.log")),
         "StandardErrorPath": str(Path(state) / (a.role + ".err.log"))}
atomic_write(out / (label + ".plist"), plistlib.dumps(plist).decode())

def ps(s):
    return "'" + s.replace("'", "''") + "'"

arguments = subprocess.list2cmdline(args[1:])
script = f"""$ErrorActionPreference = 'Stop'
$Action = New-ScheduledTaskAction -Execute {ps(args[0])} -Argument {ps(arguments)}
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User ([Security.Principal.WindowsIdentity]::GetCurrent().Name)
$Settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName 'MemoryShare-{a.role}' -Action $Action -Trigger $Trigger -Settings $Settings -User ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -RunLevel Limited -Force | Out-Null
Start-ScheduledTask -TaskName 'MemoryShare-{a.role}'
"""
atomic_write(out / ("enable-" + a.role + "-task.ps1"), script)
print(str(out))
