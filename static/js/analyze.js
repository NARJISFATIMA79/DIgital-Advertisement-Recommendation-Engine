/* Guided workflow. One state object S; the server does all analysis. Two journeys: "idea" and "existing". */
const S = { step: 0, mode: "", ads: [], concepts: [], conceptSig: "", csv_text: null, queries: [], qsig: "", searchedSig: "", selected: [], found: [], competitor_perf: [], isDemo: false, searching: false };
const LAST = 6, DRAFT = "adpilot_draft_v2";
const FIELDS = ["brand", "industry", "other_desc", "product", "benefit", "problem", "audience", "market", "price", "goal", "initial_hook", "offer", "own_url", "total", "currency", "share", "days", "minad", "maxad", "reserve", "scenario", "region", "per-q"];
const FORMATS = [["", "Not sure"], ["skippable", "Skippable in-stream"], ["non_skippable", "Non-skippable in-stream"], ["bumper", "Bumper"], ["shorts", "Shorts"], ["in_feed", "In-feed video"]];
const PERF = [["impressions", "Impressions"], ["views", "Views (as reported for the format)"], ["clicks", "Clicks"], ["spend", "Advertising spend"], ["conversions", "Conversions (leads, orders)"], ["revenue", "Attributed revenue"], ["avg_watch_seconds", "Average watch time (seconds)"], ["completion_100", "Views completed to 100%"]];
const val = id => ($("#" + id) || {}).value || "";
const objective = () => { const r = $("input[name=objective]:checked"); return r ? r.value : ""; };
const strat = () => window.ADPILOT.strategies[val("industry")] || window.ADPILOT.strategies.other;
function profile() { return { brand: val("brand"), industry: val("industry"), product: val("product"), market: val("market"), audience: val("audience"), price: val("price"), goal: val("goal"), benefit: val("benefit"), problem: val("problem"), initial_hook: val("initial_hook"), offer: val("offer"), other_desc: val("other_desc") }; }

/* ---------- draft (kept in this browser tab only, so going back or reloading loses nothing) ---------- */
function saveDraft() {
  if (S.isDemo) return;
  try { const f = {}; FIELDS.forEach(id => f[id] = val(id)); f.objective = objective();
    sessionStorage.setItem(DRAFT, JSON.stringify({ f, mode: S.mode, ads: S.ads, concepts: S.concepts, conceptSig: S.conceptSig, selected: S.selected, queries: S.queries, qsig: S.qsig, csv_text: S.csv_text, competitor_perf: S.competitor_perf, step: S.step })); } catch (e) { /* storage full or blocked: ignore */ }
}
function restoreDraft() {
  try { const d = JSON.parse(sessionStorage.getItem(DRAFT) || "null"); if (!d || !d.f || !(d.f.product || d.f.industry)) return false;
    FIELDS.forEach(id => { if ($("#" + id) && d.f[id] !== undefined) $("#" + id).value = d.f[id]; });
    $$("input[name=objective]").forEach(r => r.checked = r.value === d.f.objective);
    Object.assign(S, { mode: d.mode || "", ads: d.ads?.length ? d.ads : S.ads, concepts: d.concepts || [], conceptSig: d.conceptSig || "", selected: d.selected || [], queries: d.queries || [], qsig: d.qsig || "", csv_text: d.csv_text || null, competitor_perf: d.competitor_perf || [] });
    $$("input[name=mode]").forEach(r => r.checked = r.value === S.mode);
    $("#other-wrap").hidden = val("industry") !== "other"; $("#draft-banner").hidden = false; return d.step || 0; } catch (e) { return false; }
}
$("#draft-clear").addEventListener("click", () => { sessionStorage.removeItem(DRAFT); location.href = "/analyze"; });
document.addEventListener("input", debounce(saveDraft, 400)); document.addEventListener("change", saveDraft);

/* ---------- existing-ads inputs ---------- */
function newAd(d = {}) { return { name: "", url: "", format: "", duration_seconds: "", creative_approach: "", hook: "", main_message: "", offer: "", cta: "", audience: "", landing_note: "", performance: {}, ...d }; }
function renderAds() {
  $("#ads").innerHTML = S.ads.map((a, i) => `<div class="adcard" data-i="${i}"><header><h3>Ad ${i + 1}</h3>${S.ads.length > 1 ? `<button class="btn ghost small" data-rm="${i}">Remove</button>` : ""}</header>
    <div class="fgrid"><div class="field" data-f="name"><label>Advertisement name</label><input data-k="name" value="${esc(a.name)}" placeholder="e.g. Routine tutorial"><div class="err" hidden></div></div><div class="field"><label>YouTube video link <span class="hint">optional</span></label><input data-k="url" value="${esc(a.url)}" placeholder="https://www.youtube.com/watch?v=..."><div class="fine" data-urlmsg></div></div></div>
    <div class="fgrid3"><div class="field"><label>Campaign format</label><select data-k="format">${FORMATS.map(([v, l]) => `<option value="${v}" ${a.format === v ? "selected" : ""}>${l}</option>`).join("")}</select></div><div class="field"><label>Video length (seconds)</label><input data-k="duration_seconds" type="number" min="1" value="${esc(a.duration_seconds)}"></div>
      <div class="field"><label>Creative approach</label><select data-k="creative_approach"><option value="">Not sure</option>${strat().approaches.map(x => `<option ${a.creative_approach === x ? "selected" : ""}>${esc(x)}</option>`).join("")}</select></div></div>
    <div class="field"><label>Opening hook <span class="hint">what happens in the first 5 seconds</span></label><input data-k="hook" value="${esc(a.hook)}"></div>
    <div class="field"><label>Main message</label><input data-k="main_message" value="${esc(a.main_message)}"></div>
    <div class="fgrid"><div class="field"><label>Offer or promotion</label><input data-k="offer" value="${esc(a.offer)}"></div><div class="field"><label>Call to action</label><input data-k="cta" value="${esc(a.cta)}" placeholder="e.g. Shop now"></div></div>
    <div class="fgrid"><div class="field"><label>Who this ad targets <span class="hint">if different</span></label><input data-k="audience" value="${esc(a.audience)}"></div><div class="field"><label>Landing page, briefly</label><input data-k="landing_note" value="${esc(a.landing_note)}" placeholder="e.g. Product page with 20% off banner"></div></div>
    <details class="perf" ${Object.values(a.performance).some(v => v !== "" && v !== undefined) ? "open" : ""}><summary>Historical results for this ad (totals)</summary><p class="fine">Leave a box empty if you do not have the figure. Empty means unknown, not zero.</p><div class="fgrid3">${PERF.map(([k, l]) => `<div class="field"><label>${l}</label><input data-p="${k}" type="number" min="0" step="any" value="${esc(a.performance[k] ?? "")}"></div>`).join("")}</div></details></div>`).join("");
  $$(".adcard").forEach(card => {
    const i = +card.dataset.i;
    $$("[data-k]", card).forEach(el => el.addEventListener("input", () => { S.ads[i][el.dataset.k] = el.value; }));
    $$("[data-p]", card).forEach(el => el.addEventListener("input", () => { S.ads[i].performance[el.dataset.p] = el.value; }));
    const u = $('[data-k="url"]', card); u.addEventListener("blur", async () => { const m = $("[data-urlmsg]", card); if (!u.value.trim()) { m.textContent = ""; return; }
      try { await api("/api/youtube/parse", { method: "POST", body: { url: u.value } }); m.textContent = "Link accepted. It is only stored with the report."; } catch (e) { m.textContent = e.message + " This link will be ignored; it is optional."; } });
  });
  $$("[data-rm]").forEach(b => b.addEventListener("click", () => { S.ads.splice(+b.dataset.rm, 1); renderAds(); }));
}
$("#csv-file").addEventListener("change", async e => {
  const f = e.target.files[0]; if (!f) return; const fd = new FormData(); fd.append("file", f);
  $("#csv-report").innerHTML = `<div class="loading"><div class="spin"></div>Checking your file...</div>`;
  try { const v = await api("/api/validate-csv", { method: "POST", body: fd }); S.csv_text = v.errors.length ? null : v.csv_text; const s = v.summary;
    $("#csv-report").innerHTML = (v.errors.length ? `<div class="callout"><b>This file cannot be used yet.</b><br>${v.errors.map(esc).join("<br>")}</div>` : `<div class="callout info"><b>${s.clean_rows}</b> of ${s.uploaded_rows} rows are usable. ${s.excluded_rows} excluded, ${s.warning_count} warning(s). Excluded rows are listed in the report, never hidden.</div>`)
      + (v.excluded.length ? `<details><summary>Excluded rows</summary><ul>${v.excluded.slice(0, 30).map(x => `<li>Row ${x.row}: ${esc(x.reason)}</li>`).join("")}</ul></details>` : "") + (v.warnings.length ? `<details><summary>Warnings</summary><ul>${v.warnings.slice(0, 30).map(x => `<li>${esc(x)}</li>`).join("")}</ul></details>` : "");
    $("#csv-clear").hidden = !S.csv_text; saveDraft(); } catch (err) { $("#csv-report").innerHTML = `<div class="callout">${esc(err.message)}</div>`; }
});
$("#csv-clear").addEventListener("click", () => { S.csv_text = null; $("#csv-file").value = ""; $("#csv-report").innerHTML = ""; $("#csv-clear").hidden = true; });
$("#add-ad").addEventListener("click", () => { S.ads.push(newAd()); renderAds(); });

/* ---------- concepts (idea journey) ---------- */
const csig = () => JSON.stringify([profile(), objective()]);
function conceptLabel(c) { const cr = c.creative; return cr && cr.overall !== null ? `<span class="badge ${cr.confidence === "good" ? "high" : cr.confidence}">Checklist ${cr.overall}/100, ${esc(cr.confidence)} confidence</span>` : '<span class="badge limited">Checklist: not enough text yet</span>'; }
function renderConcepts() {
  const box = $("#concepts");
  if (!S.concepts.length) { box.innerHTML = `<div class="empty">No concepts yet.</div>`; return; }
  $("#concept-note").innerHTML = S.conceptSig && S.conceptSig !== csig() ? '<span class="badge moderate">Your answers changed since these were made. Choose Generate again to update (your edits will be replaced).</span>' : "";
  box.innerHTML = S.concepts.map((c, i) => `<div class="panel concept" data-ci="${i}" style="margin-bottom:16px"><div class="row" style="justify-content:space-between"><label style="margin:0"><input type="checkbox" data-sel style="width:auto" ${c.selected ? "checked" : ""}> <b>Include in analysis</b></label><span class="badge">${esc(c.label || "Creative proposal, not a tested ad")}</span></div>
    <h3 style="margin-top:10px">${esc(c.title)} ${c.is_user_idea ? '<span class="badge">your idea</span>' : ""}</h3>
    <div class="field"><label>Opening hook</label><textarea data-ck="hook" style="min-height:60px">${esc(c.hook)}</textarea>${(c.hook_options || []).length > 1 ? `<div class="row" style="gap:6px;margin-top:6px">${c.hook_options.map((h, j) => `<button class="btn ghost small" data-hook="${j}">Alternative hook ${j + 1}</button>`).join("")}</div>` : ""}</div>
    <div class="field"><label>Main message</label><input data-ck="main_message" value="${esc(c.main_message)}"></div>
    <div class="fgrid"><div class="field"><label>Offer <span class="hint">optional</span></label><input data-ck="offer" value="${esc(c.offer)}"></div><div class="field"><label>Call to action</label><input data-ck="cta" value="${esc(c.cta)}"></div></div>
    ${c.outline ? `<p class="fine"><b>Outline:</b> ${esc(c.outline)}</p>` : ""}${c.why_it_may_appeal ? `<p class="fine"><b>Why it might appeal (a hypothesis):</b> ${esc(c.why_it_may_appeal)}</p>` : ""}
    <div data-chk>${conceptLabel(c)}</div>
    ${(c.assumptions || []).length ? `<details><summary>Assumptions to validate</summary><ul>${c.assumptions.map(a => `<li>${esc(a)}</li>`).join("")}</ul></details>` : ""}</div>`).join("");
  $$(".concept").forEach(card => {
    const i = +card.dataset.ci, c = S.concepts[i];
    $("[data-sel]", card).addEventListener("change", e => { if (e.target.checked && S.concepts.filter(x => x.selected).length >= 4) { e.target.checked = false; return toast("Choose at most four concepts to compare."); } c.selected = e.target.checked; saveDraft(); });
    const recheck = debounce(async () => { try { const r = await api("/api/concepts/assess", { method: "POST", body: { concept: c, profile: profile(), objective: objective() } }); c.creative = r.creative; $("[data-chk]", card).innerHTML = conceptLabel(c); } catch (e) { /* checklist is optional */ } }, 700);
    $$("[data-ck]", card).forEach(el => el.addEventListener("input", () => { c[el.dataset.ck] = el.value; recheck(); }));
    $$("[data-hook]", card).forEach(b => b.addEventListener("click", () => { c.hook = c.hook_options[+b.dataset.hook]; $('[data-ck="hook"]', card).value = c.hook; recheck(); saveDraft(); }));
  });
}
async function genConcepts() {
  $("#concepts").innerHTML = `<div class="loading"><div class="spin"></div>Preparing concepts from your answers...</div>`;
  try { const r = await api("/api/concepts", { method: "POST", body: { profile: profile(), objective: objective() } }); S.concepts = r.concepts; S.conceptSig = csig(); renderConcepts(); saveDraft(); }
  catch (e) { $("#concepts").innerHTML = `<div class="callout">${esc(e.message)}</div>`; }
}
$("#regen").addEventListener("click", genConcepts);
$("#add-concept").addEventListener("click", () => { if (S.concepts.length >= 8) return toast("That is the maximum number of concepts."); S.concepts.push({ id: "c" + (Date.now() % 100000), archetype: "", title: "My concept", approach: "My concept", hook: "", hook_options: [], main_message: "", offer: "", cta: "", outline: "", why_it_may_appeal: "", assumptions: [], selected: true, is_user_idea: true, label: "Your own concept, not a tested ad", creative: null }); renderConcepts(); });

/* ---------- competitor research ---------- */
if (!window.ADPILOT.youtube) $("#disc-off").hidden = false;
function renderQueries() {
  $("#q-list").innerHTML = S.queries.map((q, i) => `<div class="qrow"><input type="checkbox" data-q="${i}" ${q.on ? "checked" : ""} aria-label="Run this search"><div><b>${esc(q.query)}</b><br><span class="fine">${esc(q.reason || "Added by you")}</span></div><button class="btn ghost small" data-qd="${i}" style="margin-left:auto" aria-label="Remove this search">Remove</button></div>`).join("") || `<p class="fine">No searches yet. Fill in the product on the first step.</p>`;
  $$("[data-q]").forEach(c => c.addEventListener("change", () => { S.queries[+c.dataset.q].on = c.checked; saveDraft(); }));
  $$("[data-qd]").forEach(b => b.addEventListener("click", () => { S.queries.splice(+b.dataset.qd, 1); renderQueries(); saveDraft(); }));
}
async function genQueries() {
  const custom = S.queries.filter(q => !q.reason);
  try { const r = await api("/api/discovery/queries", { method: "POST", body: { profile: profile(), objective: objective(), concepts: S.mode === "idea" ? S.concepts.filter(c => c.selected) : [] } });
    S.queries = [...r.queries.map(q => ({ ...q, on: !!q.auto })), ...custom]; S.qsig = csig() + S.concepts.filter(c => c.selected).map(c => c.archetype).join();
    $("#q-help").textContent = window.ADPILOT.youtube ? `The first ${r.auto_searches} run automatically. ${r.cost_note} Tick more to run them too.` : "Searches are suggestions only until a YouTube API key is configured."; renderQueries(); }
  catch (e) { $("#q-list").innerHTML = `<div class="callout">${esc(e.message)}</div>`; }
}
$("#q-add").addEventListener("click", () => { const v = val("q-custom").trim().slice(0, 120); if (!v) return; S.queries.push({ query: v, reason: "", on: true }); $("#q-custom").value = ""; renderQueries(); saveDraft(); });
async function find(refresh) {
  const qs = S.queries.filter(q => q.on).map(q => q.query);
  if (!qs.length) return toast("Tick at least one search first.");
  if (S.searching) return; S.searching = true; $("#find").disabled = true;
  $("#disc-status").innerHTML = `<div class="loading"><div class="spin"></div>Searching public YouTube videos (${qs.length} search${qs.length > 1 ? "es" : ""})...</div>`;
  try {
    const r = await api("/api/discovery/search", { method: "POST", body: { profile: profile(), queries: qs, per_query: +val("per-q"), region: val("region"), refresh } });
    S.searchedSig = S.qsig + qs.join("|");
    if (!r.available) { $("#disc-status").innerHTML = `<div class="callout">${esc(r.message)}</div>`; S.found = []; renderFound(); return; }
    S.found = r.videos;
    const q = r.quota || {};
    $("#disc-status").innerHTML = `${r.videos.length} public video(s) found. ${r.retrieved_at ? "Retrieved " + esc(new Date(r.retrieved_at * 1000).toLocaleString()) : ""}${r.served_from_cache ? `. ${r.served_from_cache} search(es) came from saved results (no quota used); choose Refresh for new ones` : ""}. Quota used by this run: ${r.quota_units_used} units; AdPilot's estimate for today: ${q.estimated_units_used_today ?? "?"} of about ${num(q.assumed_daily_quota, 0)} (other apps on the same project are not counted).${r.unavailable_count ? ` ${r.unavailable_count} unavailable video(s) were skipped.` : ""}
      <details><summary>How relevance is calculated</summary><p class="fine">${esc(r.relevance_method)}</p></details>${r.errors.length ? `<div class="callout" style="margin-top:8px">${r.errors.map(e => esc(e.message)).join("<br>")}</div>` : ""}`;
    $("#refresh").hidden = false; $("#disc-filters").hidden = false; renderFound();
    if (!r.videos.length && !r.errors.length) $("#vgrid").innerHTML = `<div class="empty" style="grid-column:1/-1">No public videos matched. Try a shorter or different search, remove the region code, or add a competitor link below.</div>`;
  } catch (e) { $("#disc-status").innerHTML = `<div class="callout">${esc(e.message)}</div>`; }
  finally { S.searching = false; $("#find").disabled = false; }
}
async function enterDiscovery() {
  if (!S.queries.length || S.qsig !== csig() + S.concepts.filter(c => c.selected).map(c => c.archetype).join()) await genQueries();
  else renderQueries();
  if (window.ADPILOT.youtube && S.queries.some(q => q.on) && S.searchedSig !== S.qsig + S.queries.filter(q => q.on).map(q => q.query).join("|")) await find(false);
  else renderFound();
}
$("#find").addEventListener("click", () => find(false)); $("#refresh").addEventListener("click", () => find(true));
const isSel = id => S.selected.some(s => s.video_id === id);
function renderFound() {   // filtering and sorting happen here in the browser: no new API calls
  const st = val("f-status"), tx = val("f-text").toLowerCase().trim(), sort = val("f-sort") || "relevance";
  let v = S.found.filter(x => (!st || x.status === st) && (!tx || ((x.title || "") + " " + (x.description || "")).toLowerCase().includes(tx)));
  v = [...v].sort(sort === "date" ? (a, b) => (b.published_at || "").localeCompare(a.published_at || "") : sort === "title" ? (a, b) => (a.title || "").localeCompare(b.title || "") : (a, b) => b.relevance - a.relevance);
  $("#f-count").textContent = S.found.length ? `Showing ${v.length} of ${S.found.length}. ${S.selected.length} selected.` : "";
  $("#vgrid").innerHTML = v.map(x => { const on = isSel(x.video_id), img = safeImg(x.thumbnail);
    return `<div class="vcard ${on ? "sel" : ""}">${img ? `<img src="${esc(img)}" alt="" loading="lazy">` : ""}<div class="b"><span class="badge ${STATUS_CLASS[x.status] || ""}">${esc(x.status)}</span> ${tvBadge(x)} <span class="badge">match ${x.relevance}/100</span>
      <h4>${linkTo(x.url, esc(x.title || "Untitled video"))}</h4><div class="fine">${esc(x.channel_title || "Unknown channel")}${x.published_at ? ", " + esc(new Date(x.published_at).toLocaleDateString()) : ""}${x.duration_seconds ? ", " + Math.floor(x.duration_seconds / 60) + ":" + String(x.duration_seconds % 60).padStart(2, "0") : ""}</div>
      <p class="fine" style="margin-top:6px">${esc(x.why)}</p><p class="fine">Public views ${x.public_views !== null ? num(x.public_views, 0) : "unknown"}, likes ${x.public_likes !== null ? num(x.public_likes, 0) : "unknown"}. Public numbers, not advertising results.</p>
      <details><summary>Evidence for this label</summary><ul>${x.evidence.map(e => `<li>${esc(e)}</li>`).join("")}</ul><p class="fine">${esc(x.verification_note)}</p></details>${tvDetails(x)}
      <label style="margin-top:10px"><input type="checkbox" data-pick="${esc(x.video_id)}" ${on ? "checked" : ""} style="width:auto"> Add to comparison</label></div></div>`; }).join("");
  $$("[data-pick]").forEach(c => c.addEventListener("change", () => { const x = S.found.find(f => f.video_id === c.dataset.pick); if (c.checked) { if (S.selected.length >= 15) { c.checked = false; return toast("You can compare up to 15 videos."); } S.selected.push({ ...x, script_text: "" }); } else S.selected = S.selected.filter(s => s.video_id !== x.video_id); renderFound(); renderSelected(); saveDraft(); }));
}
["f-sort", "f-status"].forEach(id => $("#" + id).addEventListener("change", renderFound)); $("#f-text").addEventListener("input", debounce(renderFound, 250));
function cleanTranscript(t, name) { if (/\.(srt|vtt)$/i.test(name)) t = t.replace(/^WEBVTT.*$/m, "").replace(/^\d+\s*$/gm, "").replace(/^\d{1,2}:\d{2}[:.,\d]* --> .*$/gm, "").replace(/<[^>]+>/g, ""); return t.replace(/\n{2,}/g, "\n").trim().slice(0, 60000); }
function renderSelected() {
  $("#sel-list").innerHTML = S.selected.length ? `<h3>Videos in your comparison (${S.selected.length})</h3>` + S.selected.map((v, i) => `<div class="panel" style="margin-bottom:12px"><div class="row" style="justify-content:space-between"><b>${esc(v.title)}</b><span class="row" style="gap:6px">${originBadge(v.source)} <span class="badge ${STATUS_CLASS[v.status] || ""}">${esc(v.status)}</span> ${tvBadge(v)} <button class="btn ghost small" data-del="${i}">Remove</button></span></div>
    <p class="fine" style="margin:6px 0">${v.source === "youtube_api" ? `Public details retrieved from YouTube${v.retrieved_at ? " on " + esc(new Date(v.retrieved_at * 1000).toLocaleDateString()) : ""}. Anything you add below is yours.` : "Details entered by you."} Analysis depth: ${v.script_text && v.script_text.split(/\s+/).length >= 20 ? "transcript-based" : (v.description || "").split(/\s+/).length >= 20 ? "text-based (description)" : "limited (title only)"}.</p>
    <div class="field"><label>Transcript or script you supply <span class="hint">optional. YouTube does not provide other people's transcripts through its Data API.</span></label><textarea data-sc="${i}">${esc(v.script_text || "")}</textarea><div class="row" style="margin-top:6px"><input type="file" data-tf="${i}" accept=".txt,.srt,.vtt,text/plain" style="max-width:300px"></div></div>
    ${tvDetails(v)}<details><summary>I checked that this is a paid ad (user-confirmed)</summary><p class="fine">Only tick this if you confirmed it elsewhere, for example in the Ads Transparency Center, and name the source. AdPilot cannot check this itself, so a manual record is not the same as an automated check.</p><div class="fgrid"><div class="field"><label><input type="checkbox" data-vf="${i}" style="width:auto" ${v.manual_verified ? "checked" : ""}> Verified as a paid ad</label></div><div class="field"><label>Source</label><input data-vs="${i}" value="${esc(v.verify_source || "")}" placeholder="e.g. Ads Transparency Center listing, checked today"></div></div><button class="btn ghost small" data-vapply="${i}">Apply</button></details></div>`).join("") : `<p class="fine">No competitor videos selected yet. You can continue without any.</p>`;
  $$("[data-sc]").forEach(t => t.addEventListener("input", () => { S.selected[+t.dataset.sc].script_text = t.value; }));
  $$("[data-tf]").forEach(f => f.addEventListener("change", async () => { const file = f.files[0]; if (!file) return; if (file.size > 500000) return toast("That file is too large for a transcript."); S.selected[+f.dataset.tf].script_text = cleanTranscript(await file.text(), file.name); renderSelected(); saveDraft(); }));
  $$("[data-del]").forEach(b => b.addEventListener("click", () => { S.selected.splice(+b.dataset.del, 1); renderSelected(); renderFound(); saveDraft(); }));
  $$("[data-vapply]").forEach(b => b.addEventListener("click", async () => { const i = +b.dataset.vapply, v = S.selected[i]; v.manual_verified = $(`[data-vf="${i}"]`).checked; v.verify_source = $(`[data-vs="${i}"]`).value;
    try { const c = await api("/api/discovery/classify", { method: "POST", body: { video: v, profile: profile(), verification: v.verification || null, manual_verification: { verified: v.manual_verified, source: v.verify_source } } }); v.status = c.status; v.evidence = c.evidence; v.verification_note = c.verification_note; v.verification_method = c.verification_method; renderSelected(); renderFound(); if (v.manual_verified && c.status !== "Verified Paid Ad") toast("Add the source to record it as verified."); } catch (e) { toast(e.message); } }));
  $("#f-count") && S.found.length && ($("#f-count").textContent = `Showing results. ${S.selected.length} selected.`);
}

/* ---- Paid-ad verification (optional third-party Transparency Center data). Reuses the videos already found: no extra YouTube API calls. ---- */
function tvState() {
  const on = window.ADPILOT.transparency;
  $("#tv-state").textContent = on ? "Provider configured" : "Off: SEARCHAPI_API_KEY not set"; $("#tv-state").className = "badge " + (on ? "high" : "limited");
  if (!on) $("#tv-status").innerHTML = `Automatic paid-ad verification is off, so no video is verified automatically. Discovery and analysis still work. You can open the <a href="https://adstransparency.google.com/" target="_blank" rel="noopener noreferrer">Google Ads Transparency Center</a>, check a video yourself, and record it under "I checked that this is a paid ad (user-confirmed)".`;
}
async function verifyVideos(refresh) {
  const pool = [...S.found, ...S.selected.filter(s => !S.found.some(f => f.video_id === s.video_id))];
  if (!pool.length) return toast("Find or add some videos first.");
  if (S.verifying) return; S.verifying = true; $("#tv-run").disabled = true;
  $("#tv-status").innerHTML = `<div class="loading"><div class="spin"></div>Checking Transparency Center records...</div>`;
  try {
    const r = await api("/api/transparency/verify", { method: "POST", body: { profile: profile(), region: val("region"), refresh, advertisers: val("tv-adv").split(",").map(x => x.trim()).filter(Boolean), max_details: +val("tv-max"),
      videos: pool.map(v => ({ video_id: v.video_id, title: v.title, channel_title: v.channel_title, relevance: v.relevance, manual_verified: v.manual_verified, verify_source: v.verify_source })) } });
    const by = Object.fromEntries((r.videos || []).map(x => [x.video_id, x]));
    [S.found, S.selected].forEach(list => list.forEach(v => { const x = by[v.video_id]; if (x) { v.status = x.status; v.evidence = x.evidence; v.verification_note = x.verification_note; v.verification = x.verification; v.verification_method = x.verification_method; if (x.transparency_url) v.transparency_url = x.transparency_url; } }));
    renderFound(); renderSelected(); saveDraft();
    const adv = (r.advertisers || []).map(a => `${esc(a.query)} → ${a.matched ? esc(a.matched.name || a.matched.domain || a.matched.advertiser_id) + ` (${a.details_checked} of ${a.creatives_reported ?? a.creatives_listed} creatives inspected)` : "no advertiser matched"}`).join("; ");
    $("#tv-status").innerHTML = r.available === false ? `<div class="callout">${esc(r.message)}</div>` : `${esc(r.message)} Region searched: ${esc(r.region === "ANYWHERE" ? "anywhere" : r.region)}. Provider requests used: ${r.requests_made}, served from saved results: ${r.cache_hits}${r.status && r.status.usage ? `; AdPilot's estimate this month: ${r.status.usage.requests_this_month}` : ""}.${adv ? `<br>Advertisers: ${adv}.` : ""}${(r.errors || []).length ? `<div class="callout" style="margin-top:8px">${r.errors.map(e => esc(e.message)).join("<br>")}</div>` : ""}<br><span class="fine">Unverified does not mean "not an ad": only a limited number of creatives is inspected per run.</span>`;
    $("#tv-refresh").hidden = false;
  } catch (e) { $("#tv-status").innerHTML = `<div class="callout">${esc(e.message)}</div>`; }
  finally { S.verifying = false; $("#tv-run").disabled = false; }
}
$("#tv-run").addEventListener("click", () => verifyVideos(false)); $("#tv-refresh").addEventListener("click", () => verifyVideos(true)); tvState();
function mvError(msg) { const f = $('[data-f="mv_link"]'); f.classList.toggle("invalid", !!msg); const e = $(".err", f); e.textContent = msg || ""; e.hidden = !msg; }
$("#mv-fetch").addEventListener("click", async () => {
  mvError(""); $("#mv-result").innerHTML = ""; const url = val("mv-link").trim();
  if (!url) return mvError("Paste a YouTube link, or leave this empty and rely on the automatic search.");
  $("#mv-fetch").disabled = true; $("#mv-result").innerHTML = `<div class="loading"><div class="spin"></div>Checking the link...</div>`;
  try {
    const r = await api("/api/youtube/video", { method: "POST", body: { url, profile: profile() } });
    if (r.retrieved) { if (isSel(r.video.video_id)) $("#mv-result").innerHTML = `<div class="callout info">That video is already in your comparison.</div>`; else { S.selected.push({ ...r.video, script_text: "" }); $("#mv-link").value = ""; $("#mv-result").innerHTML = `<div class="callout info"><b>Added: ${esc(r.video.title)}.</b> ${esc(r.explain)}</div>`; renderSelected(); renderFound(); saveDraft(); } }
    else { $("#mv-result").innerHTML = `<div class="callout">${esc(r.message)}</div>`; $("#mv-url").value = r.url || url; $("#mv-title").focus && 0; $("#mv-result").insertAdjacentHTML("beforeend", `<p class="fine">${esc(r.explain || "")}</p>`); }
  } catch (e) { $("#mv-result").innerHTML = ""; mvError(e.message); }
  finally { $("#mv-fetch").disabled = false; }
});
$("#mv-add").addEventListener("click", async () => {
  const t = val("mv-title").trim(); if (!t) return toast("Give the video a title so you can recognise it.");
  let url = val("mv-url").trim(), id = "manual-" + Date.now();
  if (url) { try { const p = await api("/api/youtube/parse", { method: "POST", body: { url } }); url = p.url; id = p.video_id; } catch (e) { return toast(e.message); } }
  if (isSel(id)) return toast("That video is already in your comparison.");
  S.selected.push({ video_id: id, title: t, url, description: val("mv-desc"), script_text: val("mv-script"), status: "Relevant Public Video", evidence: ["Added manually; no evidence that it is advertising."], verification_note: "Entered by you.", source: "manual" });
  ["mv-title", "mv-url", "mv-desc", "mv-script"].forEach(i => $("#" + i).value = ""); renderSelected(); saveDraft();
});
$("#mv-sample").addEventListener("click", () => {
  S.selected.push({ video_id: "sample-1", title: "SAMPLE: Competitor moisturizer commercial", url: "", description: "SAMPLE ENTRY, not retrieved from YouTube. 20% off this week. Visit our store.", script_text: "", status: "Relevant Public Video", evidence: ["Sample entry for demonstration."], source: "manual" },
    { video_id: "sample-2", title: "SAMPLE: Skincare routine with dermatologist tips", url: "", description: "SAMPLE ENTRY, not retrieved from YouTube.", script_text: "Tired of dry skin by midday? Dermatologists recommend a light moisturizer you can use every morning. Our formula is clinically tested and rated by thousands of customers. Try it today and get free delivery on your first order.", status: "Relevant Public Video", evidence: ["Sample entry for demonstration."], source: "manual" });
  renderSelected(); toast("Two clearly labelled sample entries were added.");
});
function renderCP() { $("#cp-list").innerHTML = S.competitor_perf.map((c, i) => `<div class="panel" style="margin-bottom:10px"><div class="fgrid"><div class="field"><label>Competitor name</label><input data-c="${i}" data-k="name" value="${esc(c.name)}"></div><div class="field"><label>Where the numbers came from</label><input data-c="${i}" data-k="source" value="${esc(c.source)}"></div></div><div class="fgrid3">${["impressions", "clicks", "spend", "conversions", "revenue"].map(k => `<div class="field"><label>${k}</label><input type="number" min="0" data-c="${i}" data-k="${k}" value="${esc(c[k] ?? "")}"></div>`).join("")}</div></div>`).join(""); $$("[data-c]").forEach(el => el.addEventListener("input", () => { S.competitor_perf[+el.dataset.c][el.dataset.k] = el.value; })); }
$("#cp-add").addEventListener("click", () => { S.competitor_perf.push({ name: "", source: "" }); renderCP(); });

/* ---------- wizard ---------- */
function applyMode() {
  const idea = S.mode === "idea", ex = S.mode === "existing";
  $("#idea-inputs").hidden = !idea; $("#existing-inputs").hidden = !ex;
  $$(".only-idea").forEach(e => e.hidden = !idea); $$(".only-existing").forEach(e => e.hidden = !ex);
  $('#rail li[data-s="3"]').style.display = idea ? "" : "none";
  $("#budget-lede").textContent = idea ? "A budget is optional. Without measured results AdPilot plans a first test and holds the rest back; it does not pretend to know a winner." : "AdPilot recalculates the split whenever you change these.";
  if (ex && !$("#ads").children.length) renderAds();
}
$$("input[name=mode]").forEach(r => r.addEventListener("change", () => { S.mode = r.value; applyMode(); $("#mode-err").hidden = true; saveDraft(); }));
const nextIdx = n => (n === 2 && S.mode !== "idea") ? 4 : n + 1, prevIdx = n => (n === 4 && S.mode !== "idea") ? 2 : n - 1;
function showStep(n) {
  S.step = n; applyMode();
  $$(".pane").forEach(p => p.classList.toggle("on", +p.dataset.s === n));
  $$("#rail li").forEach(li => { const s = +li.dataset.s; li.classList.toggle("on", s === n); li.classList.toggle("done", s < n); });
  $("#back").style.visibility = n === 0 ? "hidden" : "visible"; $("#next").style.display = n === LAST ? "none" : "";
  if (n === 2 && S.mode === "existing") renderAds();
  if (n === 3) { if (!S.concepts.length) genConcepts(); else renderConcepts(); }
  if (n === 4) enterDiscovery();
  if (n === 6) renderReview();
  saveDraft(); window.scrollTo({ top: 0, behavior: "smooth" });
}
function fail(field, msg) { const f = $(`[data-f="${field}"]`); if (!f) return toast(msg); f.classList.add("invalid"); const e = $(".err", f); if (e) { e.textContent = msg; e.hidden = false; } const i = $("input,select", f); if (i) i.focus(); }
function clearErrs() { $$(".field.invalid").forEach(f => f.classList.remove("invalid")); $$(".field .err").forEach(e => e.hidden = true); $("#mode-err").hidden = true; }
async function validateStep(n) {
  clearErrs();
  if (n === 0) { if (!val("industry")) return fail("industry", "Choose the closest category."), false; if (val("industry") === "other" && !val("other_desc").trim()) return fail("other_desc", "Describe your business in a few words."), false; if (!val("product").trim()) return fail("product", "Say what you want to advertise."), false; if (!objective()) return fail("objective", "Choose what the advertising should achieve."), false; }
  if (n === 1 && !S.mode) { $("#mode-err").hidden = false; return false; }
  if (n === 2 && S.mode === "idea" && val("own_url").trim()) { try { await api("/api/youtube/parse", { method: "POST", body: { url: val("own_url") } }); } catch (e) { return fail("own_url", e.message + " You can also leave it empty."), false; } }
  if (n === 2 && S.mode === "existing") {
    const names = S.ads.map(a => a.name.trim().toLowerCase());
    for (let i = 0; i < S.ads.length; i++) { if (!names[i]) { const card = $(`.adcard[data-i="${i}"]`); if (card) { card.querySelector("[data-f=name]").classList.add("invalid"); const e = card.querySelector(".err"); e.textContent = "Give this ad a name."; e.hidden = false; card.querySelector("input").focus(); } return false; } if (names.indexOf(names[i]) !== i) { toast("Ad names must be different from each other."); return false; } }
  }
  if (n === 3 && !S.concepts.some(c => c.selected)) { toast("Choose at least one concept to continue."); return false; }
  if (n === 5 && val("total") !== "" && !(parseFloat(val("total")) > 0)) return fail("total", "Enter a budget greater than zero, or leave it empty to skip budget planning."), false;
  return true;
}
$("#next").addEventListener("click", async () => { if (await validateStep(S.step)) showStep(nextIdx(S.step)); });
$("#back").addEventListener("click", () => showStep(prevIdx(S.step)));
$$("#rail li").forEach(li => li.addEventListener("click", async () => { const t = +li.dataset.s; if (t === S.step) return; if (t < S.step || await validateStep(S.step)) showStep(t > S.step ? nextIdx(S.step) : t); }));
$("#industry").addEventListener("change", () => { $("#other-wrap").hidden = val("industry") !== "other"; updateObjNotes(); });
function updateObjNotes() { const s = window.ADPILOT.strategies[val("industry")]; if (!s) return; window.ADPILOT.objectiveLabels.forEach(o => { const el = $("#ob-" + o.key); if (el) el.textContent = s.objectives.includes(o.key) ? `Common for ${s.label.toLowerCase()}` : ""; }); }
$$("input[name=objective]").forEach(r => r.addEventListener("change", () => { const s = window.ADPILOT.strategies[val("industry")]; const n = $("#strategy-note"); if (s) { n.hidden = false; n.innerHTML = `<b>${esc(s.label)} starting hypotheses:</b> compare ${s.approaches.slice(0, 4).map(esc).join(", ")}. These are ideas to test, not rules.`; } }));

/* ---------- review + run ---------- */
function renderReview() {
  const p = profile(), lab = (window.ADPILOT.objectiveLabels.find(o => o.key === objective()) || {}).label || "";
  const idea = S.mode === "idea";
  $("#review").innerHTML = `<div class="panel"><dl class="kv"><dt>Product</dt><dd>${esc(p.product)} (${esc(strat().label)})</dd><dt>Audience</dt><dd>${esc(p.audience || "Not stated")}, ${esc(p.market || "market not stated")}</dd><dt>Objective</dt><dd>${esc(lab)}</dd><dt>Starting point</dt><dd>${idea ? "Product idea, no ads yet" : "Existing advertisements"}</dd>
    ${idea ? `<dt>Concepts</dt><dd>${S.concepts.filter(c => c.selected).map(c => esc(c.title)).join(", ") || "AdPilot will generate concepts"}</dd>` : `<dt>Ads</dt><dd>${S.ads.map(a => esc(a.name)).join(", ")}</dd><dt>Uploaded data</dt><dd>${S.csv_text ? "CSV attached" : "None (creative feedback only, no measured ranking)"}</dd>`}
    <dt>Competitor videos</dt><dd>${S.selected.length ? S.selected.length + " selected" : "None selected"}</dd><dt>Budget</dt><dd>${val("total") ? esc(val("currency") + " " + Number(val("total")).toLocaleString()) : "Not set"}</dd></dl></div>${S.isDemo ? '<p class="fine">Demo data. Results will be labelled as such.</p>' : ""}`;
}
function buildPayload(totalOverride) {
  const total = totalOverride ?? (val("total") === "" ? null : +val("total")), idea = S.mode === "idea";
  const cleanAd = a => ({ ...a, duration_seconds: a.duration_seconds === "" ? null : +a.duration_seconds, performance: Object.fromEntries(Object.entries(a.performance).filter(([, v]) => v !== "" && v !== undefined)) });
  const pr = profile(); if (!pr.product && pr.other_desc) pr.product = pr.other_desc;
  return { save: true, is_demo: S.isDemo, mode: S.mode, profile: pr, objective: objective(), own_url: idea ? val("own_url") : "",
    ads: idea ? [] : S.ads.map(cleanAd), csv_text: idea ? null : S.csv_text, concepts: idea ? S.concepts.map(({ creative, ...c }) => c) : [],
    budget: total ? (idea ? { total, currency: val("currency"), test_share_pct: val("share") === "" ? null : +val("share") } : { total, currency: val("currency"), days: +val("days") || null, min_per_ad: val("minad") === "" ? null : +val("minad"), max_per_ad: val("maxad") === "" ? null : +val("maxad"), reserve_pct: val("reserve") === "" ? null : +val("reserve"), scenario: val("scenario") }) : null,
    competitor_videos: S.selected.map(v => ({ video_id: v.video_id, title: v.title, url: v.url, description: v.description, duration_seconds: v.duration_seconds, script_text: v.script_text, status: v.status, verification_note: v.verification_note, verification: v.verification || null, source: v.source, retrieved_at: v.retrieved_at, channel_title: v.channel_title, public_views: v.public_views, public_likes: v.public_likes, public_comments: v.public_comments })),
    competitor_performance: S.competitor_perf.filter(c => c.name).map(c => ({ ...c })) };
}
async function run(totalOverride) {
  const st = $("#run-status"); $("#run").disabled = true;
  const steps = S.mode === "idea" ? ["Reading your product details", "Checking concepts against the checklist", "Comparing with competitor text", "Planning the first test"] : ["Checking your data", "Calculating metrics", "Comparing ads for your objective", "Allocating the budget"];
  let k = 0; st.innerHTML = `<div class="loading"><div class="spin"></div><span id="ps">${steps[0]}...</span></div>`;
  const tick = setInterval(() => { k = Math.min(k + 1, steps.length - 1); const el = $("#ps"); if (el) el.textContent = steps[k] + "..."; }, 450);
  try {
    const r = await api("/api/analyze", { method: "POST", body: buildPayload(totalOverride) });
    clearInterval(tick); st.innerHTML = ""; $("#wizard").hidden = true; const box = $("#results"); box.hidden = false;
    const onRecalc = v => { $("#total").value = v; run(v); };
    box.innerHTML = `<div class="row noprint" style="padding:20px 0"><button class="btn ghost small" id="edit">Edit my inputs</button><a class="btn ghost small" href="/dashboard">Go to dashboard</a></div>` + renderResults(r, { onRecalc });
    wireResults(box, r, { onRecalc });
    $("#edit").addEventListener("click", () => { box.hidden = true; $("#wizard").hidden = false; showStep(S.mode === "idea" ? 3 : 2); });
    window.scrollTo({ top: 0 });
  } catch (e) { clearInterval(tick); st.innerHTML = `<div class="callout"><b>The analysis could not run.</b> ${esc(e.message)}</div>`; }
  finally { $("#run").disabled = false; }
}
$("#run").addEventListener("click", () => run());

/* ---------- demo + init ---------- */
async function loadDemo(kind) {
  try {
    const d = await api("/api/demo-input" + (kind === "idea" ? "?mode=idea" : "")); S.isDemo = true; $("#demo-banner").hidden = false; S.mode = d.mode || "existing";
    Object.entries({ brand: d.profile.brand, industry: d.profile.industry, product: d.profile.product, market: d.profile.market, audience: d.profile.audience, price: d.profile.price, benefit: d.profile.benefit, problem: d.profile.problem }).forEach(([k, v]) => { $("#" + k).value = v ?? ""; });
    $$("input[name=objective]").forEach(r => r.checked = r.value === d.objective); $$("input[name=mode]").forEach(r => r.checked = r.value === S.mode);
    if (S.mode === "existing") S.ads = d.ads.map(a => newAd({ ...a, performance: { ...a.performance } }));
    $("#total").value = d.budget.total; $("#currency").value = d.budget.currency; if (d.budget.reserve_pct) $("#reserve").value = d.budget.reserve_pct; if (d.budget.scenario) $("#scenario").value = d.budget.scenario;
    updateObjNotes(); showStep(6);
  } catch (e) { toast(e.message); }
}
S.ads = [newAd()]; renderCP(); renderSelected();
const q = new URLSearchParams(location.search).get("demo");
if (q) { loadDemo(q === "idea" ? "idea" : "existing"); }
else { const st = restoreDraft(); if (st !== false) { updateObjNotes(); renderCP(); renderSelected(); showStep(st); } else showStep(0); }
