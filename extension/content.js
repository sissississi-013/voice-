const EDITABLE = 'textarea, input[type="text"], input:not([type]), [contenteditable=""], [contenteditable="true"]';
const SKIP = /search|query|find|filter|url|address|password|email|e-mail|zip|phone|code|username|login|captcha|amount|date/i;

function fieldLabel(el) {
  const byId = el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
  return [el.getAttribute("aria-label"), el.getAttribute("placeholder"), el.name, byId?.innerText, el.getAttribute("data-placeholder")]
    .filter(Boolean).join(" | ").slice(0, 200);
}

function skip(el) {
  if (el.getAttribute("role") === "combobox" || el.closest('[role="search"], form[action*="search"]')) return true;
  return el.tagName === "INPUT" && SKIP.test(`${el.name} ${el.id} ${fieldLabel(el)} ${el.autocomplete}`);
}
let bubble, target, timer, seq = 0;

function getText(el) { return el.isContentEditable ? el.innerText : el.value; }

function pageContext(el) {
  const sel = String(window.getSelection() || "").trim();
  if (sel) return sel;
  let node = el.parentElement, text = "";
  while (node && text.length < 1500 && node !== document.body) { text = node.innerText || ""; node = node.parentElement; }
  const near = text.replace(getText(el), "").slice(-2000);
  const all = (document.body.innerText || "").replace(/\n{3,}/g, "\n\n");
  const page = all.length > 10000 ? `${all.slice(0, 2000)}\n…\n${all.slice(-8000)}` : all;
  return `TITLE: ${document.title}\nURL: ${location.href}\n\nNEAR THE BOX:\n${near}\n\nFULL PAGE:\n${page}`;
}

function insert(el, value) {
  el.focus();
  if (el.isContentEditable) {
    document.execCommand("selectAll"); document.execCommand("insertText", false, value);
  } else {
    const set = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), "value").set;
    set.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }
}

function show(el, html) {
  const r = el.getBoundingClientRect ? el.getBoundingClientRect() : el;
  if (!bubble) {
    bubble = document.createElement("div");
    bubble.id = "voice-bubble";
    Object.assign(bubble.style, {
      position: "fixed", zIndex: 2147483647, maxWidth: "360px", padding: "8px",
      background: "#fffdf7", border: "1px solid #e8dcc0", borderRadius: "14px",
      boxShadow: "0 8px 24px rgba(0,0,0,.15)", font: "13px/1.4 -apple-system, system-ui, sans-serif",
      color: "#222", transition: "opacity .15s, transform .15s",
    });
    bubble.addEventListener("mousedown", (e) => e.preventDefault());
    document.body.appendChild(bubble);
  }
  const below = r.bottom + 170 < innerHeight;
  bubble.style.left = `${Math.max(8, Math.min(r.left, innerWidth - 370))}px`;
  bubble.style.top = below ? `${r.bottom + 6}px` : "";
  bubble.style.bottom = below ? "" : `${innerHeight - r.top + 6}px`;
  bubble.innerHTML = html;
  bubble.style.opacity = "1"; bubble.style.transform = "translateY(0)";
}

function hide() { if (bubble) bubble.style.opacity = "0", bubble.style.transform = "translateY(4px)", bubble.style.pointerEvents = "none"; }

function request(el) {
  const id = ++seq;
  show(el, `<div style="opacity:.6">✨ thinking in your voice…</div>`);
  bubble.style.pointerEvents = "auto";
  const full = getText(el), m = full.match(TRIGGER);
  const text = m ? full.slice(0, m.index).trim() : full, hint = m?.[2]?.trim() || "";
  chrome.runtime.sendMessage({ text, hint, context: pageContext(el), field: fieldLabel(el), site: `${location.hostname} — ${document.title}` }, (res) => {
    if (id !== seq || target !== el) return;
    if (!res || res.error) return show(el, `<div style="color:#b00">${res?.error ? "hiccup: " + String(res.error).slice(0, 80) : "voice server offline — refresh tab"}</div>`);
    show(el, `<div style="font-size:11px;opacity:.55;margin:0 4px 6px">✨ in your voice</div>`);
    for (const s of res.suggestions) {
      const b = document.createElement("div");
      b.textContent = s;
      Object.assign(b.style, { padding: "7px 10px", margin: "3px 0", borderRadius: "10px", cursor: "pointer", background: "#f6efdf" });
      b.onmouseenter = () => (b.style.background = "#efe2c4");
      b.onmouseleave = () => (b.style.background = "#f6efdf");
      b.onclick = () => { insert(el, s); hide(); };
      bubble.appendChild(b);
    }
  });
}

// Only draft when you type "@v" (optionally followed by a hint, e.g. "@v say no nicely").
const TRIGGER = /(^|\s)@v(?:\s+(.*))?$/s;
document.addEventListener("input", (e) => {
  const el = e.target.closest?.(EDITABLE);
  if (!el || skip(el)) return;
  const m = getText(el).match(TRIGGER);
  clearTimeout(timer);
  if (!m) { if (target === el) hide(); return; }
  target = el;
  show(el, `<div style="opacity:.6">✨ @v ${m[2] ? "— " + m[2].replace(/</g, "&lt;") : ""} (keep typing a hint, or wait)</div>`);
  timer = setTimeout(() => request(el), 1100);
});
document.addEventListener("focusout", (e) => { if (e.target === target) { target = null; hide(); } });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") hide(); });

// Highlight any text -> say it in my voice.
let selRange = null;
document.addEventListener("mouseup", (e) => {
  if (bubble && bubble.contains(e.target)) return;
  setTimeout(() => {
    const sel = window.getSelection();
    const active = document.activeElement;
    const editable = active && active.matches?.(EDITABLE) ? active : null;
    const inField = editable && !editable.isContentEditable;
    const text = (inField ? editable.value.slice(editable.selectionStart, editable.selectionEnd) : String(sel || "")).trim();
    if (text.length < 8 || (!inField && !sel.rangeCount)) return;
    selRange = inField ? null : sel.getRangeAt(0).cloneRange();
    let rect = inField ? editable.getBoundingClientRect() : selRange.getBoundingClientRect();
    const id = ++seq;
    target = editable || document.body;
    show(rect, `<div style="opacity:.6">✨ saying it in your voice…</div>`);
    bubble.style.pointerEvents = "auto";
    chrome.runtime.sendMessage({ text, context: "", field: "rewrite selection", site: location.hostname }, (res) => {
      if (id !== seq) return;
      if (!res || res.error) return show(rect, `<div style="color:#b00">hiccup — try again</div>`);
      show(rect, `<div style="font-size:11px;opacity:.55;margin:0 4px 6px">✨ in your voice${editable ? " — click to replace" : " — click to copy"}</div>`);
      for (const s of res.suggestions) {
        const b = document.createElement("div");
        b.textContent = s;
        Object.assign(b.style, { padding: "7px 10px", margin: "3px 0", borderRadius: "10px", cursor: "pointer", background: "#f6efdf" });
        b.onmouseenter = () => (b.style.background = "#efe2c4");
        b.onmouseleave = () => (b.style.background = "#f6efdf");
        b.onclick = () => {
          if (editable) {
            editable.focus();
            if (selRange) { const w = window.getSelection(); w.removeAllRanges(); w.addRange(selRange); }
            document.execCommand("insertText", false, s);
          } else {
            navigator.clipboard.writeText(s);
            b.textContent = "copied ✓";
            setTimeout(hide, 600);
            return;
          }
          hide();
        };
        bubble.appendChild(b);
      }
    });
  }, 10);
});
