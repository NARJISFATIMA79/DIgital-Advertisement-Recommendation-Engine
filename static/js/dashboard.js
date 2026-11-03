async function load() {
  const box = $("#dash");
  try {
    const { reports } = await api("/api/reports");
    if (!reports.length) {
      box.innerHTML = `<div class="empty"><h3>No analyses yet</h3><p style="margin:0 auto 16px">Run your first analysis, or load a labelled demo analysis to see how the results look.</p><div class="row" style="justify-content:center"><a class="btn" href="/analyze">Plan your YouTube ads</a><button class="btn ghost" id="demo">Load demo analysis</button></div></div>`;
      $("#demo").addEventListener("click", loadDemo); return;
    }
    const real = reports.filter(r => !r.is_demo), demo = reports.filter(r => r.is_demo);
    const sum = arr => arr.reduce((a, r) => a + (r.total_spend || 0), 0);
    const warn = reports.filter(r => r.mode !== "idea" && r.status !== "established");
    box.innerHTML = `<div class="stats"><div class="stat"><b>${real.length}</b><span>Your analyses</span></div><div class="stat"><b>${real.reduce((a, r) => a + r.ads, 0)}</b><span>Existing ads analyzed</span></div><div class="stat"><b>${sum(real) ? num(sum(real), 0) : "n/a"}</b><span>Historical spend you supplied</span></div><div class="stat"><b>${demo.length}</b><span>Demo analyses (labelled)</span></div></div>
    ${warn.length ? `<div class="callout" style="margin-top:20px"><b>${warn.length} analysis(es) have no established best performer.</b> The data was too thin or too close to call. Open them to see what is missing.</div>` : ""}
    <h3 style="margin-top:32px">Recent reports</h3><div class="tbl-wrap"><table><thead><tr><th>Name</th><th>Date</th><th>Objective</th><th>Type</th><th class="num">Ads or concepts</th><th>Best performer</th><th></th></tr></thead><tbody>${reports.map(r => `<tr><td><b>${esc(r.title)}</b> ${r.is_demo ? '<span class="badge demo">Demo data</span>' : ""}</td><td>${esc(new Date(r.created).toLocaleDateString())}</td><td>${esc(r.objective)}</td><td>${r.mode === "idea" ? "Product idea" : "Existing ads"}</td><td class="num">${r.mode === "idea" ? r.concepts : r.ads}</td><td>${r.mode === "idea" ? '<span class="badge">No results yet</span>' : r.best ? esc(r.best) : '<span class="badge limited">Inconclusive</span>'}</td><td><a class="btn ghost small" href="/report/${esc(r.id)}">Open</a></td></tr>`).join("")}</tbody></table></div>`;
  } catch (e) { box.innerHTML = `<div class="callout"><b>Could not load analyses.</b> ${esc(e.message)}</div>`; }
}
async function loadDemo() {
  try { for (const m of ["idea", "existing"]) { const d = await api("/api/demo-input?mode=" + m); d.save = true; await api("/api/analyze", { method: "POST", body: d }); } load(); toast("Demo analysis added. It is labelled as demo data."); } catch (e) { toast(e.message); }
}
load();
