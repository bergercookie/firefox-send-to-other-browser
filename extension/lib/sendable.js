// Pure helpers: deciding which tabs can be handed to another browser.

/** Only web pages make sense in another browser; about:, moz-extension:, file: etc. do not. */
export function isSendableUrl(url) {
  try {
    const { protocol } = new URL(url);
    return protocol === "http:" || protocol === "https:";
  } catch {
    return false;
  }
}

/**
 * Split tabs into sendable ones and skipped ones.
 * `urls` is de-duplicated (order preserved); `sendableTabs` keeps every sendable tab.
 */
export function partitionTabs(tabs) {
  const sendableTabs = [];
  const skipped = [];
  const urls = [];
  for (const tab of tabs) {
    if (isSendableUrl(tab.url)) {
      sendableTabs.push(tab);
      if (!urls.includes(tab.url)) urls.push(tab.url);
    } else {
      skipped.push(tab);
    }
  }
  return { urls, sendableTabs, skipped };
}

/**
 * The tabs the user has selected (highlighted, i.e. ctrl/shift-clicked).
 * With `clickedTab` (tab context menu) the selection only applies if the
 * clicked tab is part of it, matching what the browser's own tab menu does.
 */
export async function getSelectedTabs(tabsApi, clickedTab = null) {
  const query = clickedTab
    ? { highlighted: true, windowId: clickedTab.windowId }
    : { highlighted: true, currentWindow: true };
  const highlighted = await tabsApi.query(query);
  if (clickedTab && !highlighted.some((t) => t.id === clickedTab.id)) {
    return [clickedTab];
  }
  return highlighted;
}
