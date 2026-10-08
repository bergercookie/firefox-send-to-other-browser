"""End-to-end: real Firefox + the real extension + the real native host.

Only the target browsers are faked: executables named `vivaldi` and
`google-chrome` that record the arguments they were started with. Everything
between the extension's popup and that exec call is the production code path.

Requires Firefox (override with $FIREFOX_BIN) and selenium (`just setup`).
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait

ROOT = Path(__file__).resolve().parents[2]
EXTENSION_ID = "send-to-other-browser@bergercookie"
EXTENSION_UUID = str(uuid.uuid4())
POPUP_URL = f"moz-extension://{EXTENSION_UUID}/popup/popup.html"

FAKE_BROWSER = """#!/bin/sh
printf '%s\\n' "$@" >> "$E2E_LOG_DIR/$(basename "$0").log"
"""


class _Page(BaseHTTPRequestHandler):
    def do_GET(self):
        body = f"<title>{self.path}</title><h1>{self.path}</h1>".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="session")
def web_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Page)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Fake browsers + a throwaway HOME holding the native messaging manifest."""
    bin_dir, log_dir, home = tmp_path / "bin", tmp_path / "logs", tmp_path / "home"
    for d in (bin_dir, log_dir, home):
        d.mkdir()
    for name in ("vivaldi", "google-chrome"):
        exe = bin_dir / name
        exe.write_text(FAKE_BROWSER)
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    subprocess.run(
        [sys.executable, str(ROOT / "host" / "install.py"), "--dest", str(home / ".mozilla" / "native-messaging-hosts")],
        check=True,
        capture_output=True,
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SEND_TO_OTHER_BROWSER_PATH", str(bin_dir))
    monkeypatch.setenv("E2E_LOG_DIR", str(log_dir))
    return log_dir


@pytest.fixture
def firefox(env):
    options = Options()
    options.add_argument("-headless")
    if os.environ.get("FIREFOX_BIN"):
        options.binary_location = os.environ["FIREFOX_BIN"]
    # Pin the extension's moz-extension:// host so the test can open its popup.
    options.set_preference("extensions.webextensions.uuids", json.dumps({EXTENSION_ID: EXTENSION_UUID}))
    # --allow-system-access: chrome-context access, see open_extension_page
    driver = webdriver.Firefox(options=options, service=Service(service_args=["--allow-system-access"]))
    driver.install_addon(str(ROOT / "extension"), temporary=True)
    yield driver
    driver.quit()


def open_extension_page(driver, url):
    """WebDriver refuses to navigate to moz-extension:// URLs, so open the tab from chrome context."""
    before = set(driver.window_handles)
    with driver.context(driver.CONTEXT_CHROME):
        driver.execute_script(
            "const tab = gBrowser.addTab(arguments[0], {triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal()});"
            "gBrowser.selectedTab = tab;",
            url,
        )
    handle = WebDriverWait(driver, 10).until(lambda d: (set(d.window_handles) - before) or False)
    driver.switch_to.window(handle.pop())
    WebDriverWait(driver, 10).until(
        lambda d: d.current_url.startswith("moz-extension://")
        and d.execute_script("return document.readyState") == "complete"
    )


def open_tabs(driver, urls):
    """Open each url in its own tab; return their Firefox tab ids."""
    ids = []
    for url in urls:
        driver.switch_to.new_window("tab")
        driver.get(url)
    # Read the ids from an extension page, where the tabs API is available.
    open_extension_page(driver, POPUP_URL)
    tabs = driver.execute_async_script(
        "const done = arguments[arguments.length - 1];"
        "browser.tabs.query({currentWindow: true}).then(done);"
    )
    by_url = {t["url"]: t["id"] for t in tabs}
    return [by_url[u] for u in urls]


def open_popup(driver, tab_ids):
    open_extension_page(driver, f"{POPUP_URL}?tabIds={','.join(map(str, tab_ids))}")


def wait_for_log(log_dir, name, timeout=10):
    path = log_dir / f"{name}.log"
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists() and path.read_text().strip():
            return path.read_text().split()
        time.sleep(0.1)
    raise AssertionError(f"{name} was never started")


def status_text(driver, contains):
    return WebDriverWait(driver, 10).until(
        lambda d: (t := d.find_element(By.ID, "status").text) and contains in t and t
    )


def test_send_selected_tabs_to_vivaldi(firefox, env, web_server):
    urls = [f"{web_server}/one", f"{web_server}/two", f"{web_server}/three"]
    tab_ids = open_tabs(firefox, urls)
    open_popup(firefox, tab_ids[:2])  # the user selected the first two tabs

    summary = WebDriverWait(firefox, 10).until(
        lambda d: "2 tabs selected" in d.find_element(By.ID, "summary").text
    )
    assert summary
    WebDriverWait(firefox, 10).until(lambda d: d.find_elements(By.CSS_SELECTOR, "#browsers button"))
    buttons = {b.get_attribute("data-browser"): b for b in firefox.find_elements(By.CSS_SELECTOR, "#browsers button")}
    assert {"vivaldi", "chrome"} <= set(buttons)

    buttons["vivaldi"].click()
    status_text(firefox, "Sent 2 tabs to Vivaldi")

    assert wait_for_log(env, "vivaldi") == urls[:2]
    assert not (env / "google-chrome.log").exists()


def test_send_to_chrome_and_close_tabs(firefox, env, web_server):
    urls = [f"{web_server}/a", f"{web_server}/b"]
    tab_ids = open_tabs(firefox, urls)
    open_popup(firefox, tab_ids)
    WebDriverWait(firefox, 10).until(lambda d: d.find_elements(By.CSS_SELECTOR, "#browsers button"))

    firefox.find_element(By.ID, "close").click()
    firefox.find_element(By.CSS_SELECTOR, "button[data-browser=chrome]").click()
    status_text(firefox, "Sent 2 tabs to Google Chrome")

    assert wait_for_log(env, "google-chrome") == urls
    remaining = firefox.execute_async_script(
        "const done = arguments[arguments.length - 1];"
        "browser.tabs.query({}).then((t) => done(t.map((x) => x.url)));"
    )
    assert not set(urls) & set(remaining)


def test_non_web_tabs_are_skipped(firefox, env, web_server):
    url = f"{web_server}/web"
    tab_ids = open_tabs(firefox, [url])
    open_popup(firefox, tab_ids)
    # The popup tab itself is a moz-extension:// page and must never be sent.
    own_id = firefox.execute_async_script(
        "const done = arguments[arguments.length - 1];"
        "browser.tabs.getCurrent().then((t) => done(t.id));"
    )
    open_popup(firefox, tab_ids + [own_id])
    WebDriverWait(firefox, 10).until(lambda d: "1 skipped" in d.find_element(By.ID, "summary").text)
    WebDriverWait(firefox, 10).until(lambda d: d.find_elements(By.CSS_SELECTOR, "#browsers button"))
    firefox.find_element(By.CSS_SELECTOR, "button[data-browser=vivaldi]").click()
    status_text(firefox, "Sent 1 tab to Vivaldi")
    assert wait_for_log(env, "vivaldi") == [url]


def test_missing_native_host_shows_a_helpful_error(firefox, env, web_server, tmp_path):
    shutil.rmtree(Path(os.environ["HOME"]) / ".mozilla" / "native-messaging-hosts")
    tab_ids = open_tabs(firefox, [f"{web_server}/x"])
    open_popup(firefox, tab_ids)
    assert "just install-host" in status_text(firefox, "native host")
