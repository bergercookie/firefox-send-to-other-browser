#!/usr/bin/env python3
"""Register (or remove) the native messaging manifest for Firefox.

install.py                 # install for the current user
install.py --uninstall
install.py --dest DIR      # custom manifest directory (used by the tests)
"""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

HOST_NAME = "send_to_other_browser"
EXTENSION_ID = "send-to-other-browser@bergercookie"
HERE = Path(__file__).resolve().parent


SNAP_NOTE = """\
Snap Firefox detected. It reaches the host through xdg-desktop-portal, which needs
Ubuntu's patched portal (22.04+ / 24.04) and about:config
widget.use-xdg-desktop-portal.native-messaging = 1 (or 2). See the README, "Snap Firefox"."""


def default_dest() -> Path:
    return Path.home() / ".mozilla" / "native-messaging-hosts"


def build_manifest(host_path: Path) -> dict[str, Any]:
    return {
        "name": HOST_NAME,
        "description": "Opens URLs from the Send to Other Browser extension in Vivaldi, Chrome, ...",
        "path": str(host_path),
        "type": "stdio",
        "allowed_extensions": [EXTENSION_ID],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dest", type=Path, default=default_dest())
    parser.add_argument("--host", type=Path, default=HERE / "send_to_other_browser.py")
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args(argv)

    target = args.dest / f"{HOST_NAME}.json"
    if args.uninstall:
        target.unlink(missing_ok=True)
        print(f"removed {target}")
        return 0

    host = args.host.resolve()
    if not host.is_file():
        print(f"host script not found: {host}", file=sys.stderr)
        return 1
    os.chmod(host, host.stat().st_mode | 0o111)
    args.dest.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(build_manifest(host), indent=2) + "\n")
    print(f"installed {target} -> {host}")
    if Path("/snap/bin/firefox").exists():
        print(SNAP_NOTE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
