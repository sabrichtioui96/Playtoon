// Forwards content-script payloads to the Playtoon engine and manages per-tab authorization.
const DEFAULT_ENDPOINT = "http://localhost:8765";

async function endpoint() {
  const { endpoint } = await chrome.storage.local.get("endpoint");
  return endpoint || DEFAULT_ENDPOINT;
}

chrome.runtime.onMessage.addListener((msg, sender) => {
  if (msg.kind !== "playtoon.ingest") return;
  endpoint().then(base => fetch(base + msg.path, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(msg.body),
  })).catch(err => console.warn("Playtoon: engine unreachable", err));
});

// Enabling a tab = explicit user action from the popup; the badge shows that reading is active.
chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg.kind !== "playtoon.enable") return;
  chrome.scripting.executeScript({ target: { tabId: msg.tabId }, files: ["content.js"] })
    .then(() => chrome.action.setBadgeText({ tabId: msg.tabId, text: "ON" }))
    .then(() => chrome.action.setBadgeBackgroundColor({ tabId: msg.tabId, color: "#d93025" }))
    .then(() => reply({ ok: true }), e => reply({ ok: false, error: String(e) }));
  return true;
});
