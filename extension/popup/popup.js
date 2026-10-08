import { getSelectedTabs, partitionTabs } from "../lib/sendable.js";

const $ = (id) => document.getElementById(id);

function setStatus(text, kind = "") {
  const el = $("status");
  el.textContent = text;
  el.className = kind;
}

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

// `?tabIds=1,2` overrides the selection; it is the hook the e2e test uses
// (a popup opened in a tab cannot see the user's real tab selection).
async function loadTabs() {
  const ids = new URLSearchParams(location.search).get("tabIds");
  if (ids) {
    return Promise.all(ids.split(",").map((id) => browser.tabs.get(Number(id))));
  }
  return getSelectedTabs(browser.tabs);
}

async function main() {
  const tabs = await loadTabs();
  const { urls, skipped } = partitionTabs(tabs);
  $("summary").textContent =
    urls.length === 0
      ? "No sendable tabs selected."
      : `${plural(urls.length, "tab")} selected` +
        (skipped.length ? ` (${skipped.length} skipped: not a web page)` : "") +
        ". Send to:";

  const reply = await browser.runtime.sendMessage({ type: "list" }).catch((e) => ({ ok: false, error: e.message }));
  if (!reply.ok) {
    setStatus(`Cannot reach the native host: ${reply.error}. Did you run "just install-host"?`, "error");
    return;
  }
  if (reply.browsers.length === 0) {
    setStatus("No other supported browser (Vivaldi, Chrome, Chromium, …) found on this system.", "error");
    return;
  }

  for (const b of reply.browsers) {
    const button = document.createElement("button");
    button.textContent = b.name;
    button.dataset.browser = b.id;
    button.disabled = urls.length === 0;
    button.addEventListener("click", async () => {
      setStatus("Sending…");
      const result = await browser.runtime.sendMessage({
        type: "send",
        browserId: b.id,
        tabIds: tabs.map((t) => t.id),
        close: $("close").checked,
      });
      if (result.ok) {
        setStatus(`Sent ${plural(result.sent, "tab")} to ${b.name}.`, "ok");
      } else {
        setStatus(result.error, "error");
      }
    });
    $("browsers").append(button);
  }
}

main().catch((err) => setStatus(err.message, "error"));
