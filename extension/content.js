const EDITABLE = 'textarea, input[type="text"], input[type="search"], input:not([type]), [contenteditable=""], [contenteditable="true"]';
let bubble, target, timer, seq = 0;

function getText(el) { return el.isContentEditable ? el.innerText : el.value; }

function pageContext(el) {
  const sel = String(window.getSelection() || "").trim();
  if (sel) return sel;
  let node = el.parentElement, text = "";
  while (node && text.length < 400 && node !== document.body) { text = node.innerText || ""; node = node.parentElement; }
  return `${document.title}\n${text.replace(getText(el), "")}`.slice(-3000);
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
  if (!bubble) {
    bubble = document.createElement("div");
    bubble.id = "sissi-voice-bubble";
    Object.assign(bubble.style, {
      position: "fixed", zIndex: 2147483647, maxWidth: "360px", padding: "8px",
      background: "#fffdf7", border: "1px solid #e8dcc0", borderRadius: "14px",
      boxShadow: "0 8px 24px rgba(0,0,0,.15)", font: "13px/1.4 -apple-system, system-ui, sans-serif",
      color: "#222", transition: "opacity .15s, transform .15s",
    });
    bubble.addEventListener("mousedown", (e) => e.preventDefault());
    document.body.appendChild(bubble);
  }
  const r = el.getBoundingClientRect();
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
  chrome.runtime.sendMessage({ text: getText(el), context: pageContext(el) }, (res) => {
    if (id !== seq || target !== el) return;
    if (!res || res.error) return show(el, `<div style="color:#b00">${res?.error ? "hiccup, retrying…" : "voice server offline"}</div>`), res?.error && setTimeout(() => target === el && request(el), 500);
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

document.addEventListener("focusin", (e) => {
  const el = e.target.closest?.(EDITABLE);
  if (!el) return;
  target = el;
  request(el);
});
document.addEventListener("input", (e) => {
  if (e.target !== target) return;
  clearTimeout(timer);
  timer = setTimeout(() => request(target), 900);
});
document.addEventListener("focusout", (e) => { if (e.target === target) { target = null; hide(); } });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") hide(); });
