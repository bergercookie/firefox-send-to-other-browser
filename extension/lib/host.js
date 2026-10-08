// Thin client for the native messaging host (host/send_to_other_browser.py).

export const HOST_NAME = "send_to_other_browser";

async function call(runtime, message) {
  const response = await runtime.sendNativeMessage(HOST_NAME, message);
  if (!response || !response.ok) {
    throw new Error((response && response.error) || "Native host returned no response");
  }
  return response;
}

/** @returns {Promise<{id: string, name: string, path: string}[]>} */
export async function listBrowsers(runtime) {
  return (await call(runtime, { action: "list" })).browsers;
}

export function sendUrls(runtime, browserId, urls) {
  return call(runtime, { action: "send", browser: browserId, urls });
}
