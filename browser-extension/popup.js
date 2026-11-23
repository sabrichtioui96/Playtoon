const ep = document.getElementById("ep");
const status = document.getElementById("status");
chrome.storage.local.get("endpoint").then(({ endpoint }) => { ep.value = endpoint || "http://localhost:8765"; });
ep.addEventListener("change", () => chrome.storage.local.set({ endpoint: ep.value.trim() }));

document.getElementById("go").addEventListener("click", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  chrome.runtime.sendMessage({ kind: "playtoon.enable", tabId: tab.id }, r => {
    status.textContent = r && r.ok ? "Reading this tab." : "Could not enable: " + (r && r.error);
  });
});
