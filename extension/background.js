chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  fetch("http://127.0.0.1:8765/suggest", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(msg),
  })
    .then((r) => r.json())
    .then(reply)
    .catch((e) => reply({ error: String(e) }));
  return true;
});
