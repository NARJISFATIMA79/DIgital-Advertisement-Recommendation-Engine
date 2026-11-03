/* Shared helpers. Everything user-supplied goes through esc() before touching innerHTML. */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
function esc(v) { return String(v ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
function num(v, d = 2) { return v === null || v === undefined || Number.isNaN(v) ? "n/a" : Number(v).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d }); }
function money(v, cur = "") { return v === null || v === undefined ? "n/a" : (cur ? cur + " " : "") + Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 }); }
function toast(msg, ms = 3800) { const t = document.createElement("div"); t.className = "toast"; t.setAttribute("role", "status"); t.textContent = msg; document.body.appendChild(t); setTimeout(() => t.remove(), ms); }

async function api(path, opts = {}) {
  let res;
  try {
    const isForm = opts.body instanceof FormData;
    res = await fetch(path, { ...opts, headers: isForm ? {} : { "Content-Type": "application/json" }, body: opts.body && typeof opts.body !== "string" && !isForm ? JSON.stringify(opts.body) : opts.body });
  } catch (e) {
    throw new Error("Could not reach the AdPilot server. Is it still running in your terminal?");
  }
  let data = null;
  try { data = await res.json(); } catch (e) { /* non-JSON */ }
  if (!res.ok) throw new Error((data && data.error && data.error.message) || `The server returned an error (${res.status}).`);
  return data;
}

const METRIC_LABELS = { ctr: "CTR", cpc: "CPC", cpa: "CPA", conv_rate: "Conv. rate", roas: "ROAS", view_rate: "View rate", cpv: "Cost / view", cpm: "CPM", completion_rate: "Completion" };
function fmtMetric(k, v) {
  if (v === null || v === undefined) return "n/a";
  if (["ctr", "conv_rate", "view_rate", "completion_rate"].includes(k)) return num(v) + "%";
  if (k === "roas") return num(v) + "x";
  return num(v);
}
function badge(level) { const l = String(level || "").toLowerCase(); return `<span class="badge ${esc(l)}">${esc(level)}</span>`; }

/* simple horizontal bar chart (SVG, no dependencies). items: [{label, value, note}] */
function barChart(items, { unit = "", width = 640, color = "var(--forest)" } = {}) {
  if (!items.length) return "";
  const max = Math.max(...items.map(i => i.value), 1e-9), row = 34, left = 150, h = items.length * row + 8;
  const bars = items.map((it, i) => {
    const w = Math.max(2, (width - left - 90) * it.value / max), y = i * row + 4;
    return `<text x="0" y="${y + 18}">${esc(String(it.label).slice(0, 22))}</text><rect x="${left}" y="${y + 4}" width="${w}" height="18" rx="2" fill="${it.color || color}"/><text x="${left + w + 8}" y="${y + 18}">${esc(num(it.value, it.value < 10 ? 2 : 0))}${esc(unit)}${it.note ? " " + esc(it.note) : ""}</text>`;
  }).join("");
  return `<div class="chart"><svg viewBox="0 0 ${width} ${h}" role="img" aria-label="Bar chart">${bars}</svg></div>`;
}
function allocBar(lines) {
  return `<div class="alloc" role="img" aria-label="Proposed allocation">${lines.map((l, i) => `<div class="${l.role === "unallocated" ? "cu" : "c" + (i % 6)}" style="width:${l.percent}%" title="${esc(l.name)}: ${l.percent}%">${l.percent >= 7 ? l.percent + "%" : ""}</div>`).join("")}</div>
  <div class="legend">${lines.map((l, i) => `<span><i class="${l.role === "unallocated" ? "cu" : "c" + (i % 6)}"></i>${esc(l.name)}</span>`).join("")}</div>`;
}

/* ---- URL safety: only canonical YouTube watch links and YouTube thumbnail hosts are ever put into href/src ---- */
function safeHref(u) { return typeof u === "string" && /^https:\/\/(www\.youtube\.com\/watch\?v=|youtu\.be\/)[A-Za-z0-9_-]{11}$/.test(u) ? u : null; }
function safeImg(u) { return typeof u === "string" && /^https:\/\/[a-z0-9.-]*ytimg\.com\//i.test(u) ? u : null; }
function linkTo(u, text, cls = "") { const h = safeHref(u); return h ? `<a class="${cls}" href="${esc(h)}" target="_blank" rel="noopener noreferrer">${text}</a>` : text; }
function debounce(fn, ms = 600) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
const STATUS_CLASS = { "Verified Paid Ad": "verified", "Potential Advertising Creative": "moderate", "Relevant Public Video": "" };
const DEPTH_LABEL = { transcript: "Transcript-based", text_based: "Text-based", limited: "Limited (title only)" };
function originBadge(o) { return o === "youtube_api" ? '<span class="badge high">Retrieved from YouTube API</span>' : '<span class="badge">Entered by you</span>'; }

/* ---- Transparency Center evidence links: only Google's official host, and only well-formed advertiser/creative paths ---- */
function safeTU(u) { return typeof u === "string" && /^https:\/\/adstransparency\.google\.com\/(advertiser\/AR\d{6,30}(\/creative\/CR\d{6,30})?)?(\?region=[A-Za-z0-9]{1,8})?$/.test(u) ? u : null; }
function tuLink(u, text) { const h = safeTU(u); return h ? `<a href="${esc(h)}" target="_blank" rel="noopener noreferrer">${text}</a>` : ""; }
const TV_CLASS = { verified_exact: "verified", possible_match: "moderate", unverified: "limited", not_checked: "" };
function tvBadge(v) { const t = v && v.verification; return t ? `<span class="badge ${TV_CLASS[t.state] || ""}" title="${esc(t.reason || "")}">${esc(t.label)}</span>` : ""; }
function tvDetails(v) {
  const t = v && v.verification; if (!t) return "";
  const rec = t.record || {}, when = t.checked_at ? new Date(t.checked_at * 1000).toLocaleString() : "unknown";
  const link = tuLink(rec.evidence_url, "Open this record on Google Ads Transparency Center") || tuLink(t.manual_review_url, "Open the Transparency Center to review manually");
  return `<details><summary>Transparency Center check: ${esc(t.label)}</summary><p class="fine">${esc(t.reason)}</p>${(t.evidence || []).length ? `<ul>${t.evidence.map(e => `<li>${esc(e)}</li>`).join("")}</ul>` : ""}<p class="fine">Source: ${esc(t.source_label || "provider")}. Checked ${esc(when)}.${link ? " " + link + "." : ""}</p></details>`;
}
