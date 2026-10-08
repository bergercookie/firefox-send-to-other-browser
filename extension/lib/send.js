import { partitionTabs } from "./sendable.js";
import { sendUrls } from "./host.js";

/**
 * Send the given tabs to `browserId`.
 * Resolves to { sent, skipped, closed }; rejects if nothing is sendable or the host fails.
 */
export async function sendTabs(api, browserId, tabs, { close = false } = {}) {
  const { urls, sendableTabs, skipped } = partitionTabs(tabs);
  if (urls.length === 0) {
    throw new Error("None of the selected tabs can be sent (only http/https pages are supported).");
  }
  await sendUrls(api.runtime, browserId, urls);
  let closed = 0;
  if (close) {
    await api.tabs.remove(sendableTabs.map((t) => t.id));
    closed = sendableTabs.length;
  }
  return { sent: urls.length, skipped: skipped.length, closed };
}
