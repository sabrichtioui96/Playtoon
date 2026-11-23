// Playtoon content script. Injected only into tabs the user explicitly enabled from the popup.
// Reads visible page text (questions, multiple-choice options, progressively rendered text) and
// chatbot messages, and forwards them to the Playtoon engine. Nothing is read from hidden fields,
// inputs, or password boxes.
(() => {
  if (window.__playtoonActive) return;
  window.__playtoonActive = true;

  const PAGE_ID = "p" + Math.random().toString(36).slice(2, 10);
  const BLOCK_TAGS = new Set(["P", "H1", "H2", "H3", "H4", "H5", "H6", "LI", "LABEL", "TD", "TH", "DT", "DD",
    "BUTTON", "LEGEND", "FIGCAPTION", "BLOCKQUOTE", "PRE", "SUMMARY", "OPTION"]);
  const CHAT_SEL = '[role="log"], [aria-live="polite"], [data-chat], [class*="chat" i], [id*="chat" i], [class*="conversation" i]';
  const MSG_SEL = '[data-message-id], [data-role], [role="article"], [class*="message" i], [class*="bubble" i], [class*="msg" i]';
  const STABLE_MS = 1500;

  // ---------------------------------------------------------------- transport
  function send(path, body) {
    if (window.__playtoonTransport) return window.__playtoonTransport(path, body);   // test harness
    if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.id) {
      chrome.runtime.sendMessage({ kind: "playtoon.ingest", path, body });
      return;
    }
  }

  // ---------------------------------------------------------------- helpers
  function visible(el) {
    if (!el || !el.getClientRects().length) return false;
    const cs = getComputedStyle(el);
    return cs.visibility !== "hidden" && cs.display !== "none" && parseFloat(cs.opacity || "1") > 0.05;
  }
  function blockOf(node) {
    let el = node.parentElement;
    while (el && el !== document.body) {
      if (BLOCK_TAGS.has(el.tagName) || getComputedStyle(el).display.match(/block|list-item|flex|grid|table-cell/)) return el;
      el = el.parentElement;
    }
    return document.body;
  }
  function inChat(el) { return !!(el.closest && el.closest(CHAT_SEL)); }
  function skip(el) {
    return !el || el.closest("script,style,noscript,textarea,input,select,[contenteditable=true],[aria-hidden=true]");
  }

  // ---------------------------------------------------------------- page text
  let lastPageSig = "";
  function collectBlocks() {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const order = [];
    const texts = new Map();
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const t = n.nodeValue.replace(/\s+/g, " ");
      if (!t.trim()) continue;
      const pe = n.parentElement;
      if (skip(pe) || inChat(pe) || !visible(pe)) continue;
      const b = blockOf(n);
      if (!texts.has(b)) { texts.set(b, ""); order.push(b); }
      texts.set(b, texts.get(b) + t);
    }
    return order.map((b, i) => ({ id: b.id || String(i), text: texts.get(b).trim() })).filter(b => b.text);
  }
  function flushPage() {
    const blocks = collectBlocks();
    const sig = blocks.map(b => b.text).join("\n");
    if (sig === lastPageSig) return;
    lastPageSig = sig;
    send("/ingest/browser", { page_id: PAGE_ID, url: location.href, title: document.title, blocks });
  }

  // ---------------------------------------------------------------- chatbot messages
  const msgIds = new WeakMap();
  let msgSeq = 0;
  const msgState = new Map();   // id -> {text, sentFinal, timer}
  function roleOf(el) {
    const r = (el.getAttribute("data-role") || el.getAttribute("data-author") || el.className || "").toString().toLowerCase();
    if (/\b(user|me|self|outgoing|sent|human)\b/.test(r) || /(^|[-_ ])user([-_ ]|$)/.test(r)) return "user";
    return "assistant";
  }
  function scanChats() {
    const convs = document.querySelectorAll(CHAT_SEL);
    convs.forEach((conv, ci) => {
      if (conv.parentElement && conv.parentElement.closest(CHAT_SEL)) return;   // outermost container only
      const convId = conv.id || `chat${ci}`;
      let msgs = Array.from(conv.querySelectorAll(MSG_SEL)).filter(m => !m.parentElement.closest(MSG_SEL) || m.parentElement.closest(MSG_SEL) === conv);
      if (!msgs.length) msgs = Array.from(conv.children);
      msgs.forEach(m => {
        if (!visible(m)) return;
        if (!msgIds.has(m)) msgIds.set(m, m.getAttribute("data-message-id") || `m${++msgSeq}`);
        const id = msgIds.get(m);
        const text = (m.innerText || "").trim();
        if (!text) return;
        const st = msgState.get(id) || { text: "", sentFinal: false, timer: null };
        if (st.text === text) return;
        st.text = text; st.sentFinal = false;
        const body = { conversation_id: `${PAGE_ID}:${convId}`, message_id: id, role: roleOf(m), text, final: false };
        send("/ingest/chat", body);
        clearTimeout(st.timer);
        // A streaming message is final once it stops changing.
        st.timer = setTimeout(() => {
          if (st.text === text && !st.sentFinal) { st.sentFinal = true; send("/ingest/chat", { ...body, final: true }); }
        }, STABLE_MS);
        msgState.set(id, st);
      });
    });
  }

  // ---------------------------------------------------------------- observe
  let debounce = null;
  function schedule() {
    clearTimeout(debounce);
    debounce = setTimeout(() => { flushPage(); scanChats(); }, 350);
  }
  new MutationObserver(schedule).observe(document.documentElement,
    { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["style", "class", "hidden"] });
  schedule();
})();
