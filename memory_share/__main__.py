import sys
from .cli import main

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

try:
    sys.exit(main())
except (ValueError, FileNotFoundError) as exc:
    print(str(exc), file=sys.stderr)
    sys.exit(2)
