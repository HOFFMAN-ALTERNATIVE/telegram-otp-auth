const $ = (id) => document.getElementById(id);
const show = (id) => ["step-start", "step-code", "step-done"].forEach((s) => ($(s).hidden = s !== id));
const say = (t) => ($("msg").textContent = t || "");
let challenge = null, timer = null;

async function api(path, body) {
  const r = await fetch(path, { method: body ? "POST" : "GET", headers: { "content-type": "application/json" }, body: body && JSON.stringify(body), credentials: "same-origin" });
  let data = null; try { data = await r.json(); } catch { /* empty */ }
  return { ok: r.ok, status: r.status, data, retry: r.headers.get("retry-after") };
}

async function refreshMe() {
  const r = await api("/auth/me");
  if (r.ok) { $("uid").textContent = r.data.telegram_user_id; show("step-done"); } else show("step-start");
}

$("btn-start").addEventListener("click", async () => {
  say();
  const r = await api("/auth/telegram/start", {});
  if (!r.ok) return say(r.status === 429 ? `Too many attempts, retry in ${r.retry}s` : "Something went wrong");
  challenge = r.data.challenge_id;
  $("deep-link").href = r.data.deep_link;
  let ttl = r.data.expires_in; $("ttl").textContent = ttl;
  clearInterval(timer);
  timer = setInterval(() => { ttl -= 1; $("ttl").textContent = ttl; if (ttl <= 0) { clearInterval(timer); show("step-start"); say("Link expired, start again."); } }, 1000);
  show("step-code");
  window.open(r.data.deep_link, "_blank", "noopener");
});

$("form-code").addEventListener("submit", async (e) => {
  e.preventDefault();
  const r = await api("/auth/telegram/verify", { challenge_id: challenge, code: $("code").value });
  if (r.ok) { clearInterval(timer); say(); $("code").value = ""; return refreshMe(); }
  const d = (r.data && r.data.detail) || {};
  const map = {
    400: `Wrong code. Attempts left: ${d.attempts_left}`,
    409: "Open the bot and press Start first.",
    410: "Code expired or used. Start again.",
    423: `Too many failures. Locked for ${Math.ceil((r.retry || 60) / 60)} min.`,
    429: `Slow down, retry in ${r.retry}s.`,
  };
  say(map[r.status] || "Verification failed");
  if (r.status === 410) show("step-start");
});

$("btn-logout").addEventListener("click", async () => { await api("/auth/logout", {}); show("step-start"); });
refreshMe();
