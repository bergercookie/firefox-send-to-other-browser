import { getSelectedTabs } from "./lib/sendable.js";
import { listBrowsers } from "./lib/host.js";
import { sendTabs } from "./lib/send.js";

const MENU_PREFIX = "send:";

async function flashBadge(text, color) {
  await browser.action.setBadgeBackgroundColor({ color });
  await browser.action.setBadgeText({ text });
  setTimeout(() => browser.action.setBadgeText({ text: "" }), 3000);
}

async function rebuildMenus() {
  await browser.menus.removeAll();
  let browsers = [];
  try {
    browsers = await listBrowsers(browser.runtime);
  } catch (err) {
    console.warn("Native host unavailable, no tab menu entries:", err.message);
  }
  for (const b of browsers) {
    browser.menus.create({
      id: MENU_PREFIX + b.id,
      title: `Send to ${b.name}`,
      contexts: ["tab"],
    });
  }
}

browser.runtime.onInstalled.addListener(rebuildMenus);
browser.runtime.onStartup.addListener(rebuildMenus);

browser.menus.onClicked.addListener(async (info, tab) => {
  if (!info.menuItemId.startsWith(MENU_PREFIX)) return;
  try {
    const tabs = await getSelectedTabs(browser.tabs, tab);
    await sendTabs(browser, info.menuItemId.slice(MENU_PREFIX.length), tabs);
    await flashBadge("✓", "#2e9e4f");
  } catch (err) {
    console.error(err);
    await flashBadge("!", "#d33");
  }
});

// Requests from the popup.
browser.runtime.onMessage.addListener((message) => {
  if (message.type === "list") {
    return listBrowsers(browser.runtime).then((browsers) => ({ ok: true, browsers }));
  }
  if (message.type === "send") {
    return Promise.all(message.tabIds.map((id) => browser.tabs.get(id)))
      .then((tabs) => sendTabs(browser, message.browserId, tabs, { close: message.close }))
      .then((result) => ({ ok: true, ...result }))
      .catch((err) => ({ ok: false, error: err.message }));
  }
  return undefined;
});
