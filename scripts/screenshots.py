#!/usr/bin/env python3
"""Regenerate the screenshots embedded in README.md.

Starts headless Firefox with the extension loaded and the real native host wired
to fake target browsers (they only record the launch), then captures the popup in
the three states the docs show:

    popup-default.png   tabs selected, target browsers discovered
    popup-sent.png      after "Send to Vivaldi"
    popup-error.png     no native host registered

Requires Firefox ($FIREFOX_BIN picks the binary, otherwise PATH) and selenium.
Run it through `just screenshots`.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "host"))
from install import HOST_NAME  # noqa: E402

EXTENSION_ID = "send-to-other-browser@bergercookie"
EXTENSION_UUID = str(uuid.uuid4())
POPUP_URL = f"moz-extension://{EXTENSION_UUID}/popup/popup.html"

# Body width the popup gets in a real popup panel (popup.css min-width). Opened
# in a tab instead, the body would stretch across the whole window, so the width
# is pinned to this before shooting.
POPUP_WIDTH = 260
WINDOW_SIZE = (900, 800)
FAKE_BROWSERS = ("vivaldi", "google-chrome", "chromium", "brave-browser", "microsoft-edge")
TAB_COUNT = 3
WAIT = 20

STYLE_JS = """
const width = arguments[0];
document.documentElement.style.background = "#fff";
let style = document.getElementById("screenshot-style");
if (!style) {
  style = document.createElement("style");
  style.id = "screenshot-style";
  document.head.append(style);
}
style.textContent =
  "body { background: #fff; margin: 0 !important; padding: 12px !important;" +
  ` width: ${width}px; box-sizing: content-box; }`;
"""


class _Page(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = f"<title>{self.path}</title><h1>{self.path}</h1>".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


def make_home(base: Path) -> Path:
    """Throwaway $HOME with fake browser executables and the host registered."""
    home = base / "home"
    (home / ".mozilla" / "native-messaging-hosts").mkdir(parents=True)
    bin_dir = home / "bin"
    bin_dir.mkdir()
    for name in FAKE_BROWSERS:
        exe = bin_dir / name
        exe.write_text("#!/bin/sh\nexit 0\n")
        exe.chmod(0o755)
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "host" / "install.py"),
            "--dest",
            str(home / ".mozilla" / "native-messaging-hosts"),
        ],
        check=True,
        capture_output=True,
    )
    os.environ["HOME"] = str(home)
    os.environ["SEND_TO_OTHER_BROWSER_PATH"] = str(bin_dir)
    return home


def start_firefox() -> webdriver.Firefox:
    options = Options()
    options.add_argument("-headless")
    # Pin the extension host so the popup can be opened from chrome context, and
    # render at 2x so the committed PNGs stay crisp on HiDPI screens.
    options.set_preference(
        "extensions.webextensions.uuids", json.dumps({EXTENSION_ID: EXTENSION_UUID})
    )
    options.set_preference("layout.css.devPixelsPerPx", "2")
    if os.environ.get("FIREFOX_BIN"):
        options.binary_location = os.environ["FIREFOX_BIN"]
    driver = webdriver.Firefox(
        options=options, service=Service(service_args=["--allow-system-access"])
    )
    driver.install_addon(str(ROOT / "extension"), temporary=True)
    driver.set_window_size(*WINDOW_SIZE)
    return driver


def open_extension_page(driver: webdriver.Firefox, url: str) -> None:
    """WebDriver refuses to navigate to moz-extension:// URLs, so open the tab
    from chrome context, then wait for it to load."""
    before = set(driver.window_handles)
    with driver.context(driver.CONTEXT_CHROME):
        driver.execute_script(
            "const tab = gBrowser.addTab(arguments[0],"
            " {triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal()});"
            " gBrowser.selectedTab = tab;",
            url,
        )
    handle = (
        WebDriverWait(driver, WAIT).until(lambda d: (set(d.window_handles) - before) or False).pop()
    )
    driver.switch_to.window(handle)
    WebDriverWait(driver, WAIT).until(
        lambda d: (
            d.current_url.startswith("moz-extension://")
            and d.execute_script("return document.readyState") == "complete"
        )
    )


def open_popup(driver: webdriver.Firefox, base: str) -> None:
    """Open TAB_COUNT web tabs, then the popup with exactly those pre-selected."""
    for i in range(TAB_COUNT):
        driver.switch_to.new_window("tab")
        driver.get(f"{base}/tab-{i + 1}")
    # A first popup visit (in a tab) is the only place the extension's tab ids
    # are visible; the second one gets them via ?tabIds=, like the e2e tests.
    open_extension_page(driver, POPUP_URL)
    tabs = driver.execute_async_script(
        "const done = arguments[arguments.length - 1];"
        "browser.tabs.query({currentWindow: true}).then(done);"
    )
    ids = [t["id"] for t in tabs if t["url"].startswith(("http://", "https://"))]
    open_extension_page(driver, f"{POPUP_URL}?tabIds={','.join(map(str, ids))}")


def capture(driver: webdriver.Firefox, dest: Path) -> None:
    """Screenshot the popup body at its natural popup width."""
    driver.execute_script(STYLE_JS, POPUP_WIDTH)
    bottom = driver.execute_script(
        "return Math.ceil(document.body.getBoundingClientRect().bottom) + 8"
    )
    inner_height = driver.execute_script("return innerHeight")
    if bottom > inner_height:
        size = driver.get_window_size()
        driver.set_window_size(size["width"], size["height"] + bottom - inner_height)
    driver.find_element(By.TAG_NAME, "body").screenshot(str(dest))
    if not dest.is_file() or dest.stat().st_size == 0:
        raise RuntimeError(f"failed to write {dest}")


def wait_status(driver: webdriver.Firefox, contains: str) -> str:
    return WebDriverWait(driver, WAIT).until(
        lambda d: (t := d.find_element(By.ID, "status").text) and contains in t and t
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=ROOT / "docs" / "screenshots",
        help="directory for the PNGs (default: docs/screenshots)",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    workspace = Path(tempfile.mkdtemp(prefix="screenshots-"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Page)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        home = make_home(workspace)
        base = f"http://127.0.0.1:{server.server_port}"

        driver = start_firefox()
        try:
            open_popup(driver, base)
            WebDriverWait(driver, WAIT).until(
                lambda d: d.find_elements(By.CSS_SELECTOR, "#browsers button")
            )
            capture(driver, args.output / "popup-default.png")
            driver.find_element(By.CSS_SELECTOR, "button[data-browser=vivaldi]").click()
            wait_status(driver, "Sent")
            capture(driver, args.output / "popup-sent.png")
        finally:
            driver.quit()

        # Same HOME, host unregistered: the popup reports the missing native host.
        (home / ".mozilla" / "native-messaging-hosts" / f"{HOST_NAME}.json").unlink()
        driver = start_firefox()
        try:
            open_popup(driver, base)
            wait_status(driver, "native host")
            capture(driver, args.output / "popup-error.png")
        finally:
            driver.quit()
    finally:
        server.shutdown()
        server.server_close()
        shutil.rmtree(workspace, ignore_errors=True)

    for png in sorted(args.output.glob("*.png")):
        try:
            shown = png.relative_to(ROOT)
        except ValueError:
            shown = png
        print(f"wrote {shown} ({png.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
