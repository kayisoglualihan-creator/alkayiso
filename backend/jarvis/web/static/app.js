/* J.A.R.V.I.S. – Weboberfläche (Desktop-Dashboard + installierbare iPhone-PWA). Keine externen Abhängigkeiten. */
"use strict";

// ---------------------------------------------------------------- Zustand & Speicher
const store = {
  get(k, d = null) { try { const v = localStorage.getItem("jv_" + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("jv_" + k, JSON.stringify(v)); } catch { /* privat/voll */ } },
  del(k) { try { localStorage.removeItem("jv_" + k); } catch { /* */ } },
};
const S = {
  mode: null, adminToken: null, device: store.get("device"), online: true, ws: null, wsRetry: 0,
  conv: store.get("conv"), tfilter: "open", approvals: [], jobs: {}, queue: store.get("queue", []),
  status: null, settings: null, speaking: false,
};
const STATUS_LABEL = { pending: "Wartend", approval_required: "Genehmigung erforderlich", running: "In Bearbeitung",
  succeeded: "Erfolgreich", failed: "Fehlgeschlagen", cancelled: "Abgebrochen", offline: "PC offline" };
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (ts) => ts ? new Date(ts * 1000).toLocaleString("de-DE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "–";
function el(html) { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; }
function toast(msg, ms = 3500) { const t = $("#toast"); t.textContent = msg; t.classList.remove("hidden"); clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.add("hidden"), ms); }

// ---------------------------------------------------------------- API
class OfflineError extends Error {}
class ApiErr extends Error { constructor(status, code, message) { super(message); this.status = status; this.code = code; } }

function token() { return S.mode === "admin" ? S.adminToken : S.device?.access; }

async function refreshDevice() {
  const d = S.device;
  if (!d) throw new ApiErr(401, "no_device", "Nicht gekoppelt");
  let r;
  try { r = await fetch("/api/auth/refresh", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ device_id: d.id, refresh_token: d.refresh }) }); }
  catch { throw new OfflineError("offline"); }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) {
    const code = j.error?.code || "refresh_failed";
    if (["device_revoked", "refresh_invalid", "refresh_expired"].includes(code)) { unpairLocal(j.error?.message); }
    throw new ApiErr(r.status, code, j.error?.message || "Erneuerung fehlgeschlagen");
  }
  S.device = { ...d, access: j.access_token, exp: j.expires_at, refresh: j.refresh_token };
  store.set("device", S.device);
}

async function api(path, { method = "GET", body, raw = false, retry = true, timeout = 60000 } = {}) {
  if (S.mode === "device" && (!S.device.access || S.device.exp - 30 < Date.now() / 1000)) await refreshDevice();
  const headers = { Authorization: "Bearer " + token() };
  if (body !== undefined && !(body instanceof FormData)) headers["content-type"] = "application/json";
  const ctl = new AbortController(); const timer = setTimeout(() => ctl.abort(), timeout);
  let r;
  try { r = await fetch(path, { method, headers, body: body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body), signal: ctl.signal }); }
  catch (e) { setOnline(false); throw new OfflineError("PC nicht erreichbar"); }
  finally { clearTimeout(timer); }
  setOnline(true);
  if (raw) return r;
  const j = await r.json().catch(() => ({}));
  if (!r.ok) {
    const code = j.error?.code || "error";
    if (r.status === 401 && S.mode === "device" && retry && ["token_expired", "token_revoked"].includes(code)) { S.device.access = null; return api(path, { method, body, raw, retry: false }); }
    if (["device_revoked", "remote_disabled"].includes(code)) { if (code === "device_revoked") unpairLocal(j.error.message); else toast(j.error.message); }
    throw new ApiErr(r.status, code, j.error?.message || j.detail?.[0]?.msg || `Fehler ${r.status}`);
  }
  return j;
}

// ---------------------------------------------------------------- Online/Offline
function setOnline(on) {
  if (S.online === on) return;
  S.online = on;
  $("#offline-banner").classList.toggle("hidden", on);
  $("#conn-dot").className = "dot " + (on ? "ok" : "err");
  if (on) { flushQueue(); connectWS(); loadAll(); } else { $("#top-status").textContent = "PC offline"; }
}
async function ping() {
  try { const ctl = new AbortController(); setTimeout(() => ctl.abort(), 4000); const r = await fetch("/api/health", { signal: ctl.signal, cache: "no-store" }); setOnline(r.ok); }
  catch { setOnline(false); }
}
async function flushQueue() {
  const q = S.queue; if (!q.length) return;
  S.queue = []; store.set("queue", []);
  for (const item of q) {
    try { await api(item.path, { method: item.method, body: item.body }); } catch (e) { if (e instanceof OfflineError) { S.queue.push(item); } }
  }
  store.set("queue", S.queue);
  if (!S.queue.length) toast("Offline-Änderungen synchronisiert"); loadTasks();
}
async function mutate(path, method, body) {
  // Für ungefährliche Änderungen (Aufgaben/Listen): bei Offline in Warteschlange stellen
  try { return await api(path, { method, body }); }
  catch (e) { if (e instanceof OfflineError) { S.queue.push({ path, method, body }); store.set("queue", S.queue); toast("Offline gespeichert – wird synchronisiert"); return null; } throw e; }
}

// ---------------------------------------------------------------- WebSocket
function connectWS() {
  if (S.ws && S.ws.readyState <= 1) return;
  const t = token(); if (!t) return;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws?token=${encodeURIComponent(t)}`);
  S.ws = ws;
  ws.onopen = () => { S.wsRetry = 0; };
  ws.onmessage = (m) => { try { onEvent(JSON.parse(m.data)); } catch { /* pong */ } };
  ws.onclose = (e) => {
    S.ws = null;
    if (e.code === 4401 && S.mode === "device") { refreshDevice().then(connectWS).catch(() => {}); return; }
    setTimeout(connectWS, Math.min(30000, 1000 * 2 ** S.wsRetry++));
  };
}
function onEvent(ev) {
  const d = ev.data;
  switch (ev.type) {
    case "approval.created": case "approval.updated": loadApprovals(); break;
    case "job.updated": updateJob(d); break;
    case "job.event": if (d.type === "approval_required") loadApprovals(); break;
    case "task.changed": case "task.deleted": loadTasks(); break;
    case "reminder.changed": loadReminders(); break;
    case "notification": onNotification(d); break;
    case "pairing.claimed": showPairingRequest(d); break;
    case "devices.changed": case "device.revoked": if (S.mode === "admin") loadDevices(); break;
    case "voice.state": Core.set({ listening: "listening", thinking: "thinking", error: "error" }[d.state] || "idle"); break;
    case "voice.transcript": addMsg("user", "🎙 " + d.text); break;
    case "voice.reply": {
      addMsg("assistant", d.text); S.conv = d.conversation_id; store.set("conv", S.conv);
      const v = S.settings?.voice; if (!(v && (v.tts_piper || v.tts_elevenlabs))) speak(d.text);
      break;
    }
  }
}
function onNotification(n) {
  loadNotifications();
  if (n.kind === "job") return; // Ergebnis steht bereits im Chat
  toast(`${n.title}${n.body ? ": " + n.body.slice(0, 120) : ""}`, 6000);
  if (n.kind === "reminder" || n.kind === "briefing") speak(n.body || n.title);
  try { if (document.hidden && "Notification" in window && Notification.permission === "granted") new Notification(n.title, { body: n.body, icon: "/static/icons/icon-192.png" }); } catch { /* */ }
}

// ---------------------------------------------------------------- Jarvis-Core-Animation
const Core = {
  state: "idle", level: 0, target: 0, t: 0, raf: null,
  colors: { idle: [0, 229, 255], listening: [46, 230, 166], thinking: [30, 123, 255], speaking: [0, 229, 255], acting: [255, 194, 75], error: [255, 84, 112], offline: [120, 130, 140] },
  labels: { idle: "Bereit", listening: "Ich höre zu", thinking: "Denke nach", speaking: "Spreche", acting: "Führe aus", error: "Fehler", offline: "PC offline" },
  set(state) { this.state = state; $("#core-state").textContent = this.labels[state] || state; },
  init() {
    this.cv = $("#core"); this.ctx = this.cv.getContext("2d");
    const resize = () => { const r = this.cv.getBoundingClientRect(); const dpr = Math.min(2, devicePixelRatio || 1); this.cv.width = r.width * dpr; this.cv.height = r.width * dpr; };
    resize(); addEventListener("resize", resize);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) this.loop(); });
    this.cv.addEventListener("click", () => { stopSpeaking(); });
    this.loop();
  },
  loop() {
    if (this.raf) cancelAnimationFrame(this.raf);
    const step = () => { if (document.hidden) { this.raf = null; return; } this.draw(); this.raf = requestAnimationFrame(step); };
    this.raf = requestAnimationFrame(step);
  },
  draw() {
    const { ctx, cv } = this; const W = cv.width, c = W / 2; this.t += 0.016;
    const st = S.online ? this.state : "offline";
    let tgt = { idle: 0.08, listening: 0.35 + this.level * 0.9, thinking: 0.4, speaking: 0.3 + Math.abs(Math.sin(this.t * 9)) * 0.4, acting: 0.5, error: 0.2, offline: 0 }[st] ?? 0.1;
    this.target += (tgt - this.target) * 0.12;
    const e = this.target; const [r, g, b] = this.colors[st] || this.colors.idle;
    const col = (a) => `rgba(${r},${g},${b},${a})`;
    ctx.clearRect(0, 0, W, W);
    const glow = ctx.createRadialGradient(c, c, W * 0.05, c, c, W * 0.5);
    glow.addColorStop(0, col(0.35 + e * 0.3)); glow.addColorStop(0.35, col(0.08)); glow.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = glow; ctx.fillRect(0, 0, W, W);
    ctx.lineCap = "round";
    const speed = st === "thinking" ? 2.2 : st === "acting" ? 1.6 : 0.6;
    const rings = [[0.44, 0.012, 0.8, 1], [0.38, 0.006, -1.3, 0.7], [0.32, 0.018, 0.5, 0.9], [0.25, 0.008, -2, 0.6]];
    rings.forEach(([rad, w, dir, alpha], i) => {
      const R = W * rad * (1 + e * 0.04 * Math.sin(this.t * 3 + i));
      const segs = 3 + i; const rot = this.t * dir * speed;
      ctx.lineWidth = W * w; ctx.strokeStyle = col(alpha * (0.5 + e * 0.5));
      for (let s = 0; s < segs; s++) {
        const a0 = rot + (s * Math.PI * 2) / segs; const len = (Math.PI * 2) / segs * (0.55 + 0.25 * Math.sin(this.t + s));
        ctx.beginPath(); ctx.arc(c, c, R, a0, a0 + len); ctx.stroke();
      }
    });
    // Tick-Marken
    ctx.strokeStyle = col(0.35); ctx.lineWidth = W * 0.003;
    for (let i = 0; i < 72; i++) {
      const a = (i / 72) * Math.PI * 2 + this.t * 0.1; const r1 = W * 0.47, r2 = W * (i % 6 ? 0.475 : 0.485);
      ctx.beginPath(); ctx.moveTo(c + Math.cos(a) * r1, c + Math.sin(a) * r1); ctx.lineTo(c + Math.cos(a) * r2, c + Math.sin(a) * r2); ctx.stroke();
    }
    // Wellenform
    ctx.beginPath(); ctx.lineWidth = W * 0.006; ctx.strokeStyle = col(0.9);
    const R0 = W * 0.16;
    for (let i = 0; i <= 120; i++) {
      const a = (i / 120) * Math.PI * 2;
      const amp = e * W * 0.035 * (Math.sin(a * 6 + this.t * 5) + Math.sin(a * 11 - this.t * 7) * 0.5);
      const x = c + Math.cos(a) * (R0 + amp), y = c + Math.sin(a) * (R0 + amp);
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    }
    ctx.closePath(); ctx.stroke();
    const core = ctx.createRadialGradient(c, c, 0, c, c, R0 * 0.8);
    core.addColorStop(0, "rgba(255,255,255,0.95)"); core.addColorStop(0.3, col(0.9)); core.addColorStop(1, col(0.05));
    ctx.fillStyle = core; ctx.beginPath(); ctx.arc(c, c, R0 * (0.75 + e * 0.15), 0, Math.PI * 2); ctx.fill();
  },
};

// ---------------------------------------------------------------- Sprache (Web Speech API)
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
const Voice = { rec: null, active: false, wake: false, stream: null, analyser: null, mediaRec: null };
function voicePrefs() { return store.get("voice", { name: "", rate: 1, volume: 1, tts: true }); }
function speak(text) {
  const p = voicePrefs();
  if (!p.tts || !("speechSynthesis" in window) || !text) return;
  stopSpeaking();
  const clean = text.replace(/[#*_`>|]/g, "").replace(/https?:\/\/\S+/g, "Link").slice(0, 1200);
  const u = new SpeechSynthesisUtterance(clean);
  const voices = speechSynthesis.getVoices();
  u.voice = voices.find((v) => v.name === p.name) || voices.find((v) => v.lang?.startsWith("de")) || null;
  u.lang = u.voice?.lang || "de-DE"; u.rate = p.rate; u.volume = p.volume;
  u.onstart = () => { S.speaking = true; Core.set("speaking"); };
  u.onend = u.onerror = () => { S.speaking = false; if (Core.state === "speaking") Core.set("idle"); };
  speechSynthesis.speak(u);
}
function stopSpeaking() { if ("speechSynthesis" in window && speechSynthesis.speaking) { speechSynthesis.cancel(); S.speaking = false; Core.set("idle"); } }

async function startLevelMeter() {
  if (Voice.analyser || /iPhone|iPad/.test(navigator.userAgent)) return;
  try {
    Voice.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const ac = new (window.AudioContext || window.webkitAudioContext)();
    const src = ac.createMediaStreamSource(Voice.stream); const an = ac.createAnalyser(); an.fftSize = 256; src.connect(an);
    Voice.analyser = an; const data = new Uint8Array(an.frequencyBinCount);
    const tick = () => { if (!Voice.analyser) return; an.getByteFrequencyData(data); Core.level = data.reduce((a, b) => a + b, 0) / data.length / 128; requestAnimationFrame(tick); };
    tick(); Voice.ac = ac;
  } catch { /* Kein Mikrofon */ }
}
function stopLevelMeter() { Voice.analyser = null; Core.level = 0; Voice.stream?.getTracks().forEach((t) => t.stop()); Voice.stream = null; Voice.ac?.close(); Voice.ac = null; }

function makeRecognizer(continuous) {
  const rec = new SR(); rec.lang = (S.settings?.values?.language === "en" ? "en-US" : "de-DE");
  rec.interimResults = true; rec.continuous = continuous; rec.maxAlternatives = 1;
  return rec;
}
function listenOnce() {
  if (!SR) return recordFallback();
  if (Voice.active) { Voice.rec?.stop(); return; }
  stopSpeaking();
  const rec = makeRecognizer(false); Voice.rec = rec; Voice.active = true;
  let finalText = "";
  rec.onstart = () => { Core.set("listening"); $("#btn-mic").classList.add("listening"); startLevelMeter(); };
  rec.onresult = (e) => { let t = ""; for (const r of e.results) t += r[0].transcript; $("#chat-input").value = t; if (e.results[e.results.length - 1].isFinal) finalText = t; };
  rec.onerror = (e) => { if (e.error !== "no-speech" && e.error !== "aborted") toast("Spracherkennung: " + e.error); };
  rec.onend = () => {
    Voice.active = false; $("#btn-mic").classList.remove("listening"); stopLevelMeter();
    if (Core.state === "listening") Core.set("idle");
    const text = (finalText || $("#chat-input").value).trim();
    if (text) { $("#chat-input").value = ""; sendMessage(text); }
    if (Voice.wake) setTimeout(startWake, 400);
  };
  try { rec.start(); } catch { Voice.active = false; }
}
function startWake() {
  if (!SR || !Voice.wake || Voice.active) return;
  const rec = makeRecognizer(true); Voice.rec = rec;
  rec.onresult = (e) => {
    const r = e.results[e.results.length - 1]; if (!r.isFinal) return;
    const t = r[0].transcript.trim(); const m = t.match(/(?:hey\s+)?jarvis[,.!]?\s*(.*)/i);
    if (!m) return;
    rec.onend = null; rec.stop();
    if (m[1] && m[1].length > 2) { sendMessage(m[1]); setTimeout(startWake, 800); } else { speak("Ja?"); setTimeout(listenOnce, 700); }
  };
  rec.onend = () => { if (Voice.wake && !Voice.active) setTimeout(startWake, 300); };
  rec.onerror = (e) => { if (e.error === "not-allowed") { Voice.wake = false; $("#wake-toggle").checked = false; toast("Mikrofon nicht erlaubt"); } };
  try { rec.start(); } catch { /* läuft bereits */ }
}
async function recordFallback() {
  // Ohne Browser-Spracherkennung: Aufnahme -> Server (faster-whisper), falls dort installiert
  if (Voice.mediaRec) { Voice.mediaRec.stop(); return; }
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) return toast("Spracheingabe wird von diesem Browser nicht unterstützt");
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const mr = new MediaRecorder(stream); const chunks = []; Voice.mediaRec = mr;
  mr.ondataavailable = (e) => chunks.push(e.data);
  mr.onstart = () => { Core.set("listening"); $("#btn-mic").classList.add("listening"); };
  mr.onstop = async () => {
    Voice.mediaRec = null; stream.getTracks().forEach((t) => t.stop()); $("#btn-mic").classList.remove("listening"); Core.set("thinking");
    const fd = new FormData(); fd.append("audio", new Blob(chunks, { type: mr.mimeType }), "speech" + (mr.mimeType.includes("mp4") ? ".m4a" : ".webm"));
    try { const r = await api("/api/voice/transcribe", { method: "POST", body: fd }); Core.set("idle"); if (r.text) sendMessage(r.text); }
    catch (e) { Core.set("idle"); toast(e.message); }
  };
  mr.start(); setTimeout(() => mr.state === "recording" && mr.stop(), 15000);
}

// ---------------------------------------------------------------- Chat
function addMsg(role, text, extra = "") {
  const log = $("#chat-log");
  const m = el(`<div class="msg ${role}">${esc(text)}${extra}</div>`);
  log.appendChild(m); log.scrollTop = log.scrollHeight; return m;
}
function statusChip(status) { return `<span class="status st-${status}">${STATUS_LABEL[status] || status}</span>`; }

async function sendMessage(text) {
  text = text.trim(); if (!text) return;
  stopSpeaking(); addMsg("user", text);
  if (!S.online) { addMsg("event", "", statusChip("offline")); toast("Der PC ist nicht erreichbar – Befehl wurde nicht gesendet."); return; }
  if (S.mode === "device") return sendAsJob(text);
  return streamChat(text);
}

async function streamChat(text) {
  Core.set("thinking"); $("#chat-send").disabled = true;
  let r;
  try { r = await api("/api/chat/stream", { method: "POST", body: { message: text, conversation_id: S.conv }, raw: true, timeout: 600000 }); }
  catch (e) { Core.set("error"); addMsg("event", e.message); $("#chat-send").disabled = false; return; }
  if (!r.ok) { const j = await r.json().catch(() => ({})); addMsg("event", j.error?.message || "Fehler"); Core.set("error"); $("#chat-send").disabled = false; return; }
  const reader = r.body.getReader(); const dec = new TextDecoder(); let buf = "";
  try {
    for (;;) {
      const { value, done } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const line = buf.slice(0, idx).replace(/^data: /, ""); buf = buf.slice(idx + 2);
        try { handleAgentEvent(JSON.parse(line)); } catch { /* */ }
      }
    }
  } finally { $("#chat-send").disabled = false; if (Core.state !== "speaking") Core.set("idle"); }
}
function handleAgentEvent(ev) {
  switch (ev.type) {
    case "status": Core.set("thinking"); break;
    case "tool_call": Core.set("acting"); addMsg("event", `⚙ ${ev.summary}`); break;
    case "tool_denied": addMsg("event", `⛔ ${ev.tool}: ${ev.reason}`); break;
    case "approval_required": addMsg("event", `⏳ Genehmigung erforderlich: ${ev.approval.summary}`); loadApprovals(); break;
    case "approval_result": addMsg("event", ev.status === "approved" ? "✓ Genehmigt" : `✗ ${ev.status === "expired" ? "Abgelaufen" : "Abgelehnt"}`); loadApprovals(); break;
    case "error": addMsg("event", ev.message); Core.set("error"); break;
    case "final":
      S.conv = ev.conversation_id; store.set("conv", S.conv);
      addMsg("assistant", ev.text); speak(ev.text); refreshSide(); break;
  }
}

async function sendAsJob(text) {
  const bubble = addMsg("assistant", "", statusChip("pending"));
  try {
    const job = await api("/api/jobs", { method: "POST", body: { text, conversation_id: S.conv } });
    S.jobs[job.id] = { bubble }; renderJobBubble(job); pollJob(job.id);
  } catch (e) {
    bubble.innerHTML = esc(e.message) + statusChip(e instanceof OfflineError ? "offline" : "failed");
  }
}
function renderJobBubble(job) {
  const ref = S.jobs[job.id]; if (!ref) return;
  let text = "";
  if (job.status === "succeeded" || job.status === "failed") text = job.result?.text || job.error || "";
  else if (job.status === "approval_required") text = "Bitte genehmige die Aktion oben.";
  else if (job.status === "running") text = "Jarvis arbeitet auf deinem PC …";
  else text = "Auftrag übermittelt …";
  ref.bubble.innerHTML = esc(text) + "<br>" + statusChip(job.status);
  if (["succeeded", "failed"].includes(job.status) && !ref.spoken) {
    ref.spoken = true; if (job.conversation_id) { S.conv = job.conversation_id; store.set("conv", S.conv); }
    speak(text); Core.set(job.status === "failed" ? "error" : "idle"); refreshSide();
  } else if (job.status === "running") Core.set("acting");
  $("#chat-log").scrollTop = $("#chat-log").scrollHeight;
}
function updateJob(job) {
  if (!job) return;
  renderJobBubble(job); renderActiveJobs();
  if (job.status === "approval_required") loadApprovals();
  if ($("#view-remote").classList.contains("active")) loadJobs();
}
async function pollJob(id) {
  for (let i = 0; i < 60; i++) {
    try {
      const job = await api(`/api/jobs/${id}?wait=20`, { timeout: 30000 });
      updateJob(job); if (["succeeded", "failed", "cancelled"].includes(job.status)) return;
    } catch (e) {
      if (e instanceof OfflineError) { const ref = S.jobs[id]; if (ref) ref.bubble.innerHTML = "Verbindung zum PC verloren." + statusChip("offline"); return; }
      await new Promise((r) => setTimeout(r, 3000));
    }
  }
}
async function loadConversation(cid) {
  const msgs = await api(`/api/conversations/${cid}/messages`);
  S.conv = cid; store.set("conv", cid); $("#chat-log").innerHTML = "";
  msgs.forEach((m) => addMsg(m.role, m.content));
  showView("home");
}

// ---------------------------------------------------------------- Genehmigungen
async function loadApprovals() {
  try { S.approvals = await api("/api/approvals"); } catch { return; }
  const bar = $("#approvals-bar"); bar.innerHTML = "";
  for (const a of S.approvals) {
    const crit = a.requires_confirm_text;
    const node = el(`<div class="approval ${crit ? "critical" : ""}">
      <div class="what"><b>${crit ? "Kritische Aktion" : "Genehmigung erforderlich"}:</b> ${esc(a.summary)}<div class="small muted">angefragt von ${esc(a.requested_by)} · läuft ab ${fmt(a.expires_at)}</div></div>
      ${crit ? '<input placeholder="BESTÄTIGEN eingeben" class="confirm">' : ""}
      <button class="primary yes">Ausführen</button><button class="danger no">Ablehnen</button></div>`);
    node.querySelector(".yes").onclick = () => decide(a.id, true, node.querySelector(".confirm")?.value);
    node.querySelector(".no").onclick = () => decide(a.id, false);
    bar.appendChild(node);
  }
  if (S.approvals.length) Core.set("acting");
}
async function decide(id, approve, confirm_text) {
  try { await api(`/api/approvals/${id}`, { method: "POST", body: { approve, confirm_text } }); loadApprovals(); }
  catch (e) { toast(e.message); }
}

// ---------------------------------------------------------------- Seitenleiste / Status
function meter(label, pct, txt) { return `<div>${esc(label)} <span class="muted">${esc(txt ?? pct + "%")}</span><div class="meter"><i style="width:${Math.min(100, pct)}%"></i></div></div>`; }
async function refreshSide() {
  try {
    const st = await api("/api/status"); S.status = st; store.set("status", st);
    renderStatus(st);
    const b = await api("/api/briefing"); $("#briefing").textContent = b.text; store.set("briefing", b.text);
  } catch { renderStatus(store.get("status")); $("#briefing").textContent = store.get("briefing", "–"); }
  renderActiveJobs();
}
function renderStatus(st) {
  if (!st) return;
  const s = st.system;
  const html = meter("CPU", s.cpu_percent) + meter("RAM", s.ram_percent, `${s.ram_used_gb}/${s.ram_total_gb} GB`) +
    (s.disks || []).slice(0, 3).map((d) => meter(`Laufwerk ${d.mount}`, d.percent, `${d.free_gb} GB frei`)).join("") +
    `<div class="muted small">${esc(s.hostname)} · ${esc(s.os)} · Laufzeit ${s.uptime_h} h${s.battery ? ` · Akku ${s.battery.percent}%` : ""}</div>`;
  $("#sys-stats").innerHTML = html; $("#pc-status").innerHTML = html;
  $("#top-status").textContent = `${S.online ? "Verbunden mit " + st.hostname : "PC offline (Stand " + fmt(Date.now() / 1000) + ")"} · KI: ${st.ai.provider === "offline" ? "Lokaler Basismodus" : st.ai.model}${st.dry_run ? " · TESTMODUS" : ""}`;
}
async function renderActiveJobs() {
  const box = $("#active-jobs");
  try {
    const jobs = (await api("/api/jobs")).filter((j) => ["pending", "running", "approval_required"].includes(j.status));
    box.innerHTML = jobs.length ? jobs.map((j) => `<div>${esc(j.text.slice(0, 60))} ${statusChip(j.status)}</div>`).join("") : "Keine";
  } catch { /* offline */ }
}

// ---------------------------------------------------------------- Aufgaben, Erinnerungen, Listen
async function loadTasks() {
  let tasks;
  try { tasks = await api(`/api/tasks?status=${S.tfilter}`); store.set("tasks_" + S.tfilter, tasks); } catch { tasks = store.get("tasks_" + S.tfilter, []); }
  const ul = $("#task-list"); ul.innerHTML = tasks.length ? "" : '<li class="muted">Keine Aufgaben</li>';
  for (const t of tasks) {
    const li = el(`<li class="${t.status === "done" ? "done" : ""}"><button class="check ${t.status === "done" ? "on" : ""}" aria-label="erledigt"></button>
      <div class="grow">${esc(t.title)}<div class="meta">${t.priority === 3 ? "❗ hoch · " : ""}${t.due_at ? "fällig " + fmt(t.due_at) : ""}${t.project ? " · " + esc(t.project) : ""}</div></div>
      <button class="ghost small del">✕</button></li>`);
    li.querySelector(".check").onclick = async () => { await mutate(`/api/tasks/${t.id}`, "PATCH", { status: t.status === "done" ? "open" : "done" }); loadTasks(); };
    li.querySelector(".del").onclick = async () => { if (confirm("Aufgabe löschen?")) { await mutate(`/api/tasks/${t.id}`, "DELETE"); loadTasks(); } };
    ul.appendChild(li);
  }
}
async function loadReminders() {
  let rs; try { rs = await api("/api/reminders"); store.set("reminders", rs); } catch { rs = store.get("reminders", []); }
  const ul = $("#reminder-list"); ul.innerHTML = rs.length ? "" : '<li class="muted">Keine Erinnerungen</li>';
  for (const r of rs) {
    const li = el(`<li><div class="grow">${esc(r.text)}<div class="meta">${fmt(r.due_at)}${r.repeat ? " · " + r.repeat : ""}</div></div><button class="ghost small">✕</button></li>`);
    li.querySelector("button").onclick = async () => { await api(`/api/reminders/${r.id}`, { method: "DELETE" }); loadReminders(); };
    ul.appendChild(li);
  }
}
async function loadLists() {
  let items; try { items = await api("/api/lists"); store.set("lists", items); } catch { items = store.get("lists", []); }
  const ul = $("#list-items"); ul.innerHTML = items.length ? "" : '<li class="muted">Leer</li>';
  for (const i of items) {
    const li = el(`<li class="${i.checked ? "done" : ""}"><button class="check ${i.checked ? "on" : ""}"></button><div class="grow">${esc(i.text)}<div class="meta">${esc(i.list_name)}</div></div><button class="ghost small">✕</button></li>`);
    li.querySelector(".check").onclick = async () => { await mutate(`/api/lists/${i.id}`, "PATCH", { checked: !i.checked }); loadLists(); };
    li.querySelector(".ghost").onclick = async () => { await mutate(`/api/lists/${i.id}`, "DELETE"); loadLists(); };
    ul.appendChild(li);
  }
}

// ---------------------------------------------------------------- Gedächtnis
const CATS = ["allgemein", "praeferenz", "projekt", "ziel", "person", "interesse", "aufgabe", "fakt"];
async function loadMemory(q = "") {
  let ms; try { ms = await api("/api/memory" + (q ? "?q=" + encodeURIComponent(q) : "")); if (!q) store.set("memory", ms); } catch { ms = store.get("memory", []); }
  const ul = $("#memory-list"); ul.innerHTML = ms.length ? "" : '<li class="muted">Noch keine Erinnerungen</li>';
  for (const m of ms) {
    const li = el(`<li><div class="grow"><span class="memtext">${esc(m.content)}</span><div class="meta">${esc(m.category)} · ${fmt(m.updated_at)}${m.score ? " · Relevanz " + m.score : ""}</div></div>
      <button class="ghost small edit">✎</button><button class="ghost small del">✕</button></li>`);
    li.querySelector(".edit").onclick = async () => { const v = prompt("Erinnerung korrigieren:", m.content); if (v && v !== m.content) { await api(`/api/memory/${m.id}`, { method: "PATCH", body: { content: v } }); loadMemory(q); } };
    li.querySelector(".del").onclick = async () => { if (confirm("Erinnerung löschen?")) { await api(`/api/memory/${m.id}`, { method: "DELETE" }); loadMemory(q); } };
    ul.appendChild(li);
  }
}

// ---------------------------------------------------------------- PC, Geräte, Pairing
async function loadJobs() {
  try {
    const jobs = await api("/api/jobs");
    $("#job-list").innerHTML = jobs.slice(0, 20).map((j) => `<li><div class="grow">${esc(j.text)}<div class="meta">${fmt(j.created_at)} · ${esc(j.source)}</div></div>${statusChip(j.status)}</li>`).join("") || '<li class="muted">Keine Aufträge</li>';
  } catch { /* */ }
}
async function loadDevices() {
  if (S.mode !== "admin") return;
  try {
    const devs = await api("/api/devices");
    const ul = $("#device-list"); ul.innerHTML = devs.length ? "" : '<li class="muted">Noch kein Gerät gekoppelt</li>';
    for (const d of devs) {
      const li = el(`<li class="${d.revoked_at ? "done" : ""}"><div class="grow">${esc(d.name)} <span class="meta">(${esc(d.platform)})</span><div class="meta">gekoppelt ${fmt(d.created_at)} · zuletzt ${fmt(d.last_seen)}${d.revoked_at ? " · widerrufen" : ""}</div></div>${d.revoked_at ? "" : '<button class="danger small">Entfernen</button>'}</li>`);
      li.querySelector("button")?.addEventListener("click", async () => { if (confirm(`${d.name} entfernen? Der Zugriff endet sofort.`)) { await api(`/api/devices/${d.id}`, { method: "DELETE" }); loadDevices(); } });
      ul.appendChild(li);
    }
    $("#remote-toggle").checked = (await api("/api/remote-access")).enabled;
    const ts = await api("/api/network/tailscale");
    $("#tailscale-box").innerHTML = !ts.installed ? `⚠ ${esc(ts.hint)}` : !ts.running ? `⚠ Tailscale läuft nicht: ${esc(ts.hint || ts.backend_state)}` :
      `✓ Tailscale aktiv (${esc(ts.tailnet || "")})<br>${esc(ts.https_url)}<br>${ts.serve_configured ? "✓ Tailscale Serve konfiguriert" : "⚠ Tailscale Serve noch nicht eingerichtet – siehe scripts/tailscale_serve.ps1"}${ts.warning ? `<br><b style="color:var(--err)">${esc(ts.warning)}</b>` : ""}`;
  } catch (e) { $("#tailscale-box").textContent = e.message; }
}
async function startPairing() {
  const p = await api("/api/pairing/start", { method: "POST" });
  $("#pair-box").innerHTML = `<div class="qr">${p.qr_svg}</div><p class="small muted">Mit der iPhone-Kamera scannen. Gültig bis ${fmt(p.expires_at)}.<br>${p.tailscale_url_detected ? "" : "⚠ Keine Tailscale-HTTPS-Adresse erkannt – das iPhone kann diese Adresse evtl. nicht erreichen: " + esc(p.base_url)}</p>
    <details><summary>Link manuell kopieren</summary><input readonly value="${esc(p.link)}" onclick="this.select()"></details>`;
}
function showPairingRequest(d) {
  openModal(`<h3>Kopplungsanfrage</h3><p><b>${esc(d.device_name)}</b> möchte sich mit Jarvis verbinden.</p>
    <p class="muted small">Prüfnummer (muss auf dem iPhone identisch sein):</p><div class="verify-code">${esc(d.verify_code)}</div>
    <div class="row-form"><button class="primary" id="pair-yes">Verbinden</button><button class="danger" id="pair-no">Ablehnen</button></div>`);
  const done = async (ok) => { try { await api(`/api/pairing/${d.pairing_id}/decision`, { method: "POST", body: { approve: ok } }); toast(ok ? "Gerät gekoppelt" : "Abgelehnt"); } catch (e) { toast(e.message); } closeModal(); $("#pair-box").innerHTML = ""; loadDevices(); };
  $("#pair-yes").onclick = () => done(true); $("#pair-no").onclick = () => done(false);
}
function openModal(html) { $("#modal-card").innerHTML = html; $("#modal").classList.remove("hidden"); }
function closeModal() { $("#modal").classList.add("hidden"); }

// ---------------------------------------------------------------- Automatisierungen
async function loadAutomations() {
  try {
    const autos = await api("/api/automations");
    const ul = $("#auto-list"); ul.innerHTML = autos.length ? "" : '<li class="muted">Keine</li>';
    for (const a of autos) {
      const li = el(`<li><div class="grow"><b>${esc(a.name)}</b><div class="meta">${esc(a.action_type)} · ${esc(a.schedule)} · nächster Lauf ${fmt(a.next_run)} · zuletzt ${fmt(a.last_run)}</div>${a.last_result ? `<div class="meta">${esc(a.last_result.slice(0, 160))}</div>` : ""}</div>
        <button class="ghost small run">▶</button>${S.mode === "admin" ? `<label class="switch"><input type="checkbox" ${a.enabled ? "checked" : ""}><span></span></label><button class="ghost small del">✕</button>` : ""}</li>`);
      li.querySelector(".run").onclick = async () => { Core.set("acting"); try { const r = await api(`/api/automations/${a.id}/run`, { method: "POST", timeout: 600000 }); toast("Ausgeführt"); addMsg("assistant", r.result); } catch (e) { toast(e.message); } Core.set("idle"); loadAutomations(); };
      li.querySelector("input")?.addEventListener("change", async (e) => { await api(`/api/automations/${a.id}`, { method: "PATCH", body: { enabled: e.target.checked } }); loadAutomations(); });
      li.querySelector(".del")?.addEventListener("click", async () => { if (confirm("Löschen?")) { await api(`/api/automations/${a.id}`, { method: "DELETE" }); loadAutomations(); } });
      ul.appendChild(li);
    }
  } catch { /* */ }
}

// ---------------------------------------------------------------- Verlauf
async function loadHistory() {
  try {
    const convs = await api("/api/conversations");
    const ul = $("#conv-list"); ul.innerHTML = convs.length ? "" : '<li class="muted">Keine</li>';
    convs.slice(0, 50).forEach((c) => { const li = el(`<li><div class="grow">${esc(c.title)}<div class="meta">${fmt(c.updated_at)}</div></div><button class="ghost small">Öffnen</button></li>`); li.querySelector("button").onclick = () => loadConversation(c.id); ul.appendChild(li); });
  } catch { /* */ }
  loadNotifications();
  if (S.mode !== "admin") return;
  try {
    const audit = await api("/api/audit?limit=80");
    $("#audit-list").innerHTML = audit.map((a) => `<li><div class="grow">${esc(a.action)} <span class="risk risk-${a.risk || 1}">${a.outcome}</span><div class="meta">${fmt(a.ts)} · ${esc(a.actor)}</div></div></li>`).join("");
    const undo = await api("/api/undo");
    const ul = $("#undo-list"); ul.innerHTML = undo.length ? "" : '<li class="muted">Nichts rückgängig zu machen</li>';
    undo.forEach((u) => { const li = el(`<li><div class="grow">${esc(u.description)}<div class="meta">${fmt(u.ts)}</div></div><button class="ghost small">↶</button></li>`); li.querySelector("button").onclick = async () => { toast((await api(`/api/undo/${u.id}`, { method: "POST" })).result); loadHistory(); }; ul.appendChild(li); });
  } catch { /* */ }
}
async function loadNotifications() {
  let ns; try { ns = await api("/api/notifications"); store.set("notifs", ns); } catch { ns = store.get("notifs", []); }
  const unread = ns.filter((n) => !n.read).length;
  $("#notif-badge").textContent = unread; $("#notif-badge").classList.toggle("hidden", !unread);
  $("#notif-list").innerHTML = ns.map((n) => `<li class="${n.read ? "done" : ""}"><div class="grow"><b>${esc(n.title)}</b> ${esc(n.body)}<div class="meta">${fmt(n.ts)} · ${esc(n.kind)}</div></div></li>`).join("") || '<li class="muted">Keine</li>';
}

// ---------------------------------------------------------------- Einstellungen
async function loadSettings() {
  fillVoices();
  if (S.mode !== "admin") return;
  const st = await api("/api/settings"); S.settings = st;
  $("#set-provider").innerHTML = st.providers.map((p) => `<option value="${p}">${{ offline: "Lokaler Basismodus (ohne KI)", anthropic: "Anthropic Claude", openai: "OpenAI", ollama: "Ollama (lokal)" }[p]}</option>`).join("");
  $("#set-provider").value = st.ai.provider; $("#set-model").value = st.ai.model;
  $("#set-effort").value = st.ai.anthropic_effort; $("#set-ollama").value = st.ai.ollama_url; $("#set-openai").value = st.ai.openai_base_url;
  toggleProviderFields();
  $("#secret-backend").textContent = st.secret_backend;
  const names = { anthropic_api_key: "Anthropic API-Key", openai_api_key: "OpenAI API-Key", elevenlabs_api_key: "ElevenLabs API-Key", home_assistant_token: "Home-Assistant-Token", n8n_webhook_secret: "n8n-Webhook-Secret" };
  $("#secret-list").innerHTML = "";
  for (const [k, has] of Object.entries(st.secrets)) {
    const row = el(`<div class="row-form"><input type="password" placeholder="${names[k] || k}${has ? " (gespeichert)" : ""}" autocomplete="off"><button class="ghost small save">Speichern</button>${has ? '<button class="danger small del">✕</button>' : ""}</div>`);
    row.querySelector(".save").onclick = async () => { const v = row.querySelector("input").value.trim(); if (!v) return; await api(`/api/secrets/${k}`, { method: "PUT", body: { value: v } }); toast("Gespeichert"); loadSettings(); };
    row.querySelector(".del")?.addEventListener("click", async () => { await api(`/api/secrets/${k}`, { method: "DELETE" }); loadSettings(); });
    $("#secret-list").appendChild(row);
  }
  const labels = { system: "System", apps: "Programme", files: "Dateien", documents: "Dokumente", browser: "Browser/Web", screen: "Bildschirm/Tastatur", tasks: "Aufgaben", memory: "Gedächtnis", lists: "Listen", health: "Gewohnheiten", finance: "Finanzen", automation: "Automationen", calendar: "Kalender", smarthome: "Smart Home", n8n: "n8n", core: "Kern" };
  $("#module-list").innerHTML = "";
  st.modules.forEach((m) => {
    const lab = el(`<label class="switch"><input type="checkbox" ${st.disabled_modules.includes(m) ? "" : "checked"} ${m === "core" ? "disabled" : ""}><span></span> ${labels[m] || m}</label>`);
    lab.querySelector("input").onchange = async () => {
      const disabled = $$("#module-list input").map((i, idx) => (!i.checked ? st.modules[idx] : null)).filter(Boolean);
      await api("/api/settings", { method: "PATCH", body: { disabled_modules: disabled } }); toast("Module aktualisiert");
    };
    $("#module-list").appendChild(lab);
  });
  $("#set-roots").value = st.allowed_roots.join("\n");
  $("#set-ics").value = (st.values.calendar_ics_urls || []).join("\n");
  const v = st.voice;
  $("#voice-status").innerHTML = `Browser-Sprache: ${SR ? "✓ Erkennung" : "✗ Erkennung"} · ${"speechSynthesis" in window ? "✓ Ausgabe" : "✗ Ausgabe"}<br>Server: faster-whisper ${v.stt_faster_whisper ? "✓" : "✗"} · Piper ${v.tts_piper ? "✓" : "✗"} · ElevenLabs ${v.tts_elevenlabs ? "✓" : "✗"} · openWakeWord ${v.wakeword_openwakeword ? "✓" : "✗"}`;
  $("#set-wake-server").checked = !!st.values.wake_word_enabled;
  $("#set-wake-server").onchange = async (e) => {
    try { await api("/api/voice/wakeword", { method: "POST", body: { enabled: e.target.checked } }); toast(e.target.checked ? "Wake Word am PC aktiv" : "Wake Word aus"); }
    catch (err) { e.target.checked = false; toast(err.message); }
  };
  const tools = await api("/api/tools");
  $("#tool-list").innerHTML = "";
  tools.forEach((t) => {
    const li = el(`<li class="${t.active ? "" : "done"}"><div class="grow">${esc(t.name)} <span class="risk risk-${t.risk}">Stufe ${t.risk}</span><div class="meta">${esc(t.description.slice(0, 110))}</div></div>
      <select style="width:auto"><option value="default">Standard</option><option value="auto" ${t.risk >= 3 ? "disabled" : ""}>Automatisch</option><option value="ask">Immer fragen</option><option value="deny">Gesperrt</option></select></li>`);
    const sel = li.querySelector("select"); sel.value = t.grant;
    sel.onchange = async () => { if (sel.value === "default") return; try { await api(`/api/tools/${t.name}/grant`, { method: "PUT", body: { mode: sel.value } }); toast("Berechtigung gespeichert"); } catch (e) { toast(e.message); } };
    $("#tool-list").appendChild(li);
  });
  const u = await api("/api/usage");
  $("#usage").innerHTML = `${u.total.calls} Aufrufe · ${u.total.input_tokens} Eingabe- / ${u.total.output_tokens} Ausgabe-Tokens · ca. ${u.total.cost.toFixed(4)} USD` +
    u.by_model.map((m) => `<div class="muted">${esc(m.provider)}/${esc(m.model)}: ${m.calls} Aufrufe, ${m.cost.toFixed(4)} USD</div>`).join("");
}
function toggleProviderFields() {
  const p = $("#set-provider").value;
  $$(".hide-unless-anthropic").forEach((e) => e.classList.toggle("hidden", p !== "anthropic"));
  $$(".hide-unless-ollama").forEach((e) => e.classList.toggle("hidden", p !== "ollama"));
  $$(".hide-unless-openai").forEach((e) => e.classList.toggle("hidden", p !== "openai"));
  const models = S.settings?.ai?.models || {}; if (models[p] && document.activeElement !== $("#set-model")) $("#set-model").value = models[p];
}
function fillVoices() {
  if (!("speechSynthesis" in window)) return;
  const p = voicePrefs(); const voices = speechSynthesis.getVoices();
  for (const sel of [$("#set-voice"), $("#set-voice-dev")]) {
    sel.innerHTML = '<option value="">Automatisch (Deutsch)</option>' + voices.map((v) => `<option ${v.name === p.name ? "selected" : ""}>${esc(v.name)}</option>`).join("");
    sel.onchange = () => { store.set("voice", { ...voicePrefs(), name: sel.value }); speak("So klinge ich jetzt."); };
  }
  $("#set-rate").value = p.rate; $("#set-volume").value = p.volume;
}

// ---------------------------------------------------------------- Navigation & Laden
function showView(name) {
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + name));
  $$("#nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  ({ tasks: () => { loadTasks(); loadReminders(); loadLists(); }, memory: () => loadMemory(), remote: () => { refreshSide(); loadJobs(); loadDevices(); },
     automations: loadAutomations, history: loadHistory, settings: loadSettings, home: refreshSide }[name] || (() => {}))();
}
function loadAll() { refreshSide(); loadApprovals(); loadNotifications(); loadTasks(); }

function bindUI() {
  $$("#nav button").forEach((b) => (b.onclick = () => showView(b.dataset.view)));
  $("#chat-form").onsubmit = (e) => { e.preventDefault(); const v = $("#chat-input").value; $("#chat-input").value = ""; sendMessage(v); };
  $("#btn-new-chat").onclick = () => { S.conv = null; store.del("conv"); $("#chat-log").innerHTML = ""; addMsg("assistant", "Neue Unterhaltung. Was kann ich für dich tun?"); };
  // Mikrofon: Tippen = Start/Stopp, Gedrückthalten = Push-to-Talk
  let pressT = 0;
  $("#btn-mic").addEventListener("pointerdown", () => { pressT = Date.now(); if (!Voice.active) listenOnce(); });
  $("#btn-mic").addEventListener("pointerup", () => { if (Date.now() - pressT > 600 && Voice.active) Voice.rec?.stop(); });
  $("#wake-toggle").onchange = (e) => { Voice.wake = e.target.checked; store.set("wake", Voice.wake); if (Voice.wake) { if (!SR) { toast("Browser unterstützt keine Spracherkennung"); return; } startWake(); toast("Sage „Hey Jarvis …“"); } else Voice.rec?.abort(); };
  $("#tts-toggle").checked = voicePrefs().tts;
  $("#tts-toggle").onchange = (e) => { store.set("voice", { ...voicePrefs(), tts: e.target.checked }); if (!e.target.checked) stopSpeaking(); };
  $("#set-rate").oninput = (e) => store.set("voice", { ...voicePrefs(), rate: +e.target.value });
  $("#set-volume").oninput = (e) => store.set("voice", { ...voicePrefs(), volume: +e.target.value });
  if ("speechSynthesis" in window) speechSynthesis.onvoiceschanged = fillVoices;
  $("#btn-notif").onclick = async () => { showView("history"); await api("/api/notifications/read", { method: "POST", body: {} }).catch(() => {}); loadNotifications(); try { if ("Notification" in window && Notification.permission === "default") Notification.requestPermission(); } catch { /* */ } };
  $("#task-form").onsubmit = async (e) => { e.preventDefault(); await mutate("/api/tasks", "POST", { title: $("#task-title").value, due: $("#task-due").value || null, priority: +$("#task-prio").value }); e.target.reset(); loadTasks(); };
  $$("[data-tfilter]").forEach((b) => (b.onclick = () => { S.tfilter = b.dataset.tfilter; $$("[data-tfilter]").forEach((x) => x.classList.toggle("active", x === b)); loadTasks(); }));
  $("#reminder-form").onsubmit = async (e) => { e.preventDefault(); try { await api("/api/reminders", { method: "POST", body: { text: $("#rem-text").value, when: $("#rem-when").value, repeat: $("#rem-repeat").value } }); e.target.reset(); loadReminders(); } catch (err) { toast(err.message); } };
  $("#list-form").onsubmit = async (e) => { e.preventDefault(); await mutate("/api/lists", "POST", { list_name: $("#list-name").value, text: $("#list-text").value }); $("#list-text").value = ""; loadLists(); };
  $("#mem-cat").innerHTML = CATS.map((c) => `<option>${c}</option>`).join("");
  $("#memory-form").onsubmit = async (e) => { e.preventDefault(); await api("/api/memory", { method: "POST", body: { content: $("#mem-content").value, category: $("#mem-cat").value } }); $("#mem-content").value = ""; loadMemory(); };
  let mt; $("#mem-search").oninput = (e) => { clearTimeout(mt); mt = setTimeout(() => loadMemory(e.target.value.trim()), 300); };
  $("#btn-mem-clear").onclick = async () => { if (prompt("Gesamtes Gedächtnis löschen? Zur Bestätigung LÖSCHEN eingeben") === "LÖSCHEN") { await api("/api/memory?confirm=true", { method: "DELETE" }); loadMemory(); } };
  $$("#quick-cmds [data-cmd]").forEach((b) => (b.onclick = () => { showView("home"); sendMessage(b.dataset.cmd); }));
  $("#btn-pair").onclick = () => startPairing().catch((e) => toast(e.message));
  $("#remote-toggle").onchange = async (e) => { await api("/api/remote-access", { method: "POST", body: { enabled: e.target.checked } }); toast(e.target.checked ? "Fernzugriff erlaubt" : "Fernzugriff deaktiviert"); };
  $("#btn-unpair").onclick = () => { if (confirm("Kopplung auf diesem Gerät entfernen?")) unpairLocal("Kopplung entfernt."); };
  $("#auto-form").onsubmit = async (e) => {
    e.preventDefault(); let payload = {};
    try { payload = $("#auto-payload").value.trim() ? JSON.parse($("#auto-payload").value) : {}; } catch { return toast("Payload ist kein gültiges JSON"); }
    try { await api("/api/automations", { method: "POST", body: { name: $("#auto-name").value, schedule: $("#auto-schedule").value, action_type: $("#auto-type").value, payload } }); e.target.reset(); loadAutomations(); } catch (err) { toast(err.message); }
  };
  $("#set-provider").onchange = toggleProviderFields;
  $("#btn-save-ai").onclick = async () => {
    const p = $("#set-provider").value; const models = { ...(S.settings?.values?.ai_models || {}), [p]: $("#set-model").value.trim() };
    await api("/api/settings", { method: "PATCH", body: { ai_provider: p, ai_models: models, anthropic_effort: $("#set-effort").value, ollama_url: $("#set-ollama").value.trim(), openai_base_url: $("#set-openai").value.trim() } });
    toast("KI-Einstellungen gespeichert"); loadSettings(); refreshSide();
  };
  $("#btn-test-ai").onclick = async () => { $("#ai-test").textContent = "Teste …"; const r = await api("/api/ai/test", { method: "POST" }); $("#ai-test").textContent = r.ok ? `✓ ${r.provider}/${r.model}: ${r.reply}` : `✗ ${r.error}`; };
  $("#btn-save-ics").onclick = async () => { await api("/api/settings", { method: "PATCH", body: { calendar_ics_urls: $("#set-ics").value.split("\n").map((s) => s.trim()).filter(Boolean) } }); toast("Kalender gespeichert"); refreshSide(); };
  $("#btn-save-roots").onclick = async () => { await api("/api/settings", { method: "PATCH", body: { allowed_roots: $("#set-roots").value.split("\n").map((s) => s.trim()).filter(Boolean) } }); toast("Ordner gespeichert"); };
  $("#modal").onclick = (e) => { if (e.target.id === "modal") closeModal(); };
}

// ---------------------------------------------------------------- Kopplung (iPhone/PWA)
function b64urlDecode(s) { s = s.replace(/-/g, "+").replace(/_/g, "/"); while (s.length % 4) s += "="; return decodeURIComponent(escape(atob(s))); }
function unpairLocal(msg) { store.del("device"); S.device = null; S.mode = null; try { S.ws?.close(); } catch { /* */ } showAuth(msg || "Dieses Gerät ist nicht mehr gekoppelt."); }
function showAuth(message) {
  $("#app").classList.add("hidden"); $("#auth-screen").classList.remove("hidden");
  $("#auth-body").innerHTML = `${message ? `<p>${esc(message)}</p>` : ""}
    <p class="muted small">So verbindest du dein iPhone:<br>1. Tailscale auf PC und iPhone aktivieren<br>2. Am PC in Jarvis „PC → iPhone verbinden“ öffnen<br>3. QR-Code mit der iPhone-Kamera scannen</p>
    <input id="pair-link" placeholder="…oder Kopplungslink hier einfügen"><button class="primary mt" id="pair-go">Koppeln</button>`;
  $("#pair-go").onclick = () => { const v = $("#pair-link").value; const m = v.match(/#pair=([\w-]+)/); if (m) startClaim(m[1]); else toast("Ungültiger Link"); };
}
async function startClaim(enc) {
  let payload; try { payload = JSON.parse(b64urlDecode(enc)); } catch { return showAuth("Ungültiger QR-Code."); }
  if (payload.url && new URL(payload.url).origin !== location.origin) { location.href = payload.url + "/#pair=" + enc; return; }
  $("#app").classList.add("hidden"); $("#auth-screen").classList.remove("hidden");
  $("#auth-body").innerHTML = `<p>Verbinde mit <b>${esc(payload.host || "PC")}</b> …</p>`;
  const name = (/iPhone/.test(navigator.userAgent) ? "iPhone" : /iPad/.test(navigator.userAgent) ? "iPad" : "Browser") + " (Web-App)";
  let r;
  try { r = await fetch("/api/pairing/claim", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ pairing_id: payload.pid, code: payload.code, device_name: name, platform: /iPhone|iPad/.test(navigator.userAgent) ? "ios-pwa" : "web" }) }); }
  catch { return showAuth("PC nicht erreichbar. Sind beide Geräte im selben Tailscale-Netzwerk?"); }
  const j = await r.json();
  if (!r.ok) return showAuth(j.error?.message || "Kopplung fehlgeschlagen");
  $("#auth-body").innerHTML = `<p>Bitte am PC bestätigen. Prüfnummer:</p><div class="verify-code">${esc(j.verify_code)}</div><p class="muted small">Vergleiche die Nummer mit der Anzeige am PC.</p>`;
  for (let i = 0; i < 150; i++) {
    await new Promise((res) => setTimeout(res, 2000));
    let pr; try { pr = await (await fetch("/api/pairing/poll", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ pairing_id: payload.pid, claim_secret: j.claim_secret }) })).json(); } catch { continue; }
    if (pr.status === "completed") {
      S.device = { id: pr.device_id, refresh: pr.refresh_token, access: pr.access_token, exp: pr.expires_at, host: payload.host, paired_at: Date.now() / 1000 };
      store.set("device", S.device); history.replaceState(null, "", "/"); return boot();
    }
    if (["rejected", "expired", "cancelled", "locked"].includes(pr.status)) return showAuth(`Kopplung ${pr.status === "rejected" ? "abgelehnt" : "abgelaufen"}.`);
  }
  showAuth("Zeitüberschreitung bei der Kopplung.");
}

// ---------------------------------------------------------------- Start
async function boot() {
  const hash = new URLSearchParams(location.hash.slice(1));
  if (hash.get("admin")) { store.set("admin", hash.get("admin")); history.replaceState(null, "", "/"); }
  if (hash.get("pair")) return startClaim(hash.get("pair"));
  const admin = store.get("admin");
  if (admin) {
    S.mode = "admin"; S.adminToken = admin;
    try { await api("/api/auth/me"); } catch (e) {
      if (!(e instanceof OfflineError)) { store.del("admin"); S.mode = null; return boot(); }
    }
  } else if (S.device) {
    S.mode = "device";
    try { await refreshDevice(); } catch (e) { if (!(e instanceof OfflineError)) return; setOnline(false); }
  } else {
    return showAuth(location.hostname === "127.0.0.1" || location.hostname === "localhost"
      ? "Bitte Jarvis über das Startmenü/Infobereich öffnen (der lokale Zugang wird dabei automatisch hergestellt)." : "");
  }
  document.body.classList.toggle("is-device", S.mode === "device");
  $("#auth-screen").classList.add("hidden"); $("#app").classList.remove("hidden");
  if (S.mode === "device") $("#device-info").innerHTML = `Gerät: ${esc(S.device.id)}<br>Verbunden mit: ${esc(S.device.host || location.host)}`;
  if (!boot.bound) { bindUI(); Core.init(); boot.bound = true; }
  Voice.wake = store.get("wake", false) && !!SR && S.mode === "admin"; $("#wake-toggle").checked = Voice.wake; if (Voice.wake) startWake();
  $("#conn-dot").className = "dot " + (S.online ? "ok" : "err");
  if (S.conv) loadConversation(S.conv).catch(() => {}); else addMsg("assistant", S.mode === "device" ? "Hallo. Was soll ich auf deinem PC erledigen?" : "Guten Tag. Wie kann ich helfen?");
  showView("home"); loadAll(); connectWS();
  setInterval(ping, 10000); setInterval(() => { if (S.online && $("#view-home").classList.contains("active")) refreshSide(); }, 30000);
}

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
boot();
