let sparkOk = false;
(async () => {
  try { const i = await api("/api/lab/info"); sparkOk = i.spark.available; $("#spark-note").textContent = sparkOk ? "Local mode on this machine, not a cluster" : i.spark.message; if (!sparkOk) $("#spark-box").disabled = true; else $("#spark-box").checked = true; window.__env = i.environment; } catch (e) { $("#spark-note").textContent = "Could not check: " + e.message; }
  history();
})();
$$("input[name=size]").forEach(r => r.addEventListener("change", () => { $("#big-warn").hidden = +$("input[name=size]:checked").value < 10000000; }));
async function start(genOnly) {
  const size = +$("input[name=size]:checked").value, engines = $$("#spark-box, .choice input[type=checkbox]").filter((c, i, a) => a.indexOf(c) === i && c.checked && !c.disabled).map(c => c.value);
  const body = { size, seed: +$("#seed").value || 42, engines: genOnly ? [] : engines, generate_only: genOnly };
  $("#out").innerHTML = ""; $("#run").disabled = $("#gen").disabled = true;
  try {
    const { job_id } = await api("/api/lab/run", { method: "POST", body });
    for (;;) {
      const j = await api("/api/lab/jobs/" + job_id);
      $("#status").innerHTML = `<div class="loading"><div class="spin"></div><span>${esc(j.messages[j.messages.length - 1])}</span></div>`;
      if (j.state === "done") { $("#status").innerHTML = ""; show(j.result, genOnly); history(); break; }
      if (j.state === "failed") { $("#status").innerHTML = `<div class="callout"><b>The run failed.</b> ${esc(j.error)}</div>`; break; }
      await new Promise(r => setTimeout(r, 1200));
    }
  } catch (e) { $("#status").innerHTML = `<div class="callout">${esc(e.message)}</div>`; }
  finally { $("#run").disabled = $("#gen").disabled = false; }
}
$("#run").addEventListener("click", () => start(false)); $("#gen").addEventListener("click", () => start(true));
function show(r, genOnly) {
  const g = r.generation, env = r.environment, ok = r.engines.filter(e => e.status === "ok");
  let h = `<div class="panel" style="margin-top:20px"><p style="margin:0">${g.reused ? "Reused" : "Generated"} <b>${num(r.size, 0)}</b> <span class="badge demo">synthetic records</span> (seed ${g.seed}${g.seconds ? `, ${g.seconds}s to generate` : ""}, ${num(g.bytes / 1e6, 1)} MB).</p></div>`;
  if (genOnly) { $("#out").innerHTML = h; return; }
  h += `<h3 style="margin-top:28px">Comparison</h3><div class="tbl-wrap"><table><thead><tr><th>Engine</th><th class="num">Processing (s)</th><th class="num">Start-up (s)</th><th class="num">Wall clock (s)</th><th class="num">Peak memory (MB)</th><th class="num">Records</th><th>Same result as first engine</th></tr></thead><tbody>${r.engines.map(e => e.status === "ok" ? `<tr><td><b>${esc(e.engine)}</b></td><td class="num">${num(e.processing_seconds, 2)}</td><td class="num">${e.startup_seconds !== undefined ? num(e.startup_seconds, 2) : "n/a"}</td><td class="num">${num(e.wall_seconds, 2)}</td><td class="num">${num(e.peak_memory_mb, 0)}</td><td class="num">${num(e.records, 0)}</td><td>${e.correctness.match ? "Yes" : "<b>No</b>"}<br><span class="fine">${esc(e.correctness.detail)}</span></td></tr>` : `<tr><td><b>${esc(e.engine)}</b></td><td colspan="6">${esc(e.status === "unavailable" ? "Not run: " : "Failed: ")}${esc(e.message)}</td></tr>`).join("")}</tbody></table></div>
  <p class="fine"><b>Processing</b> = reading the file and computing the answer inside the engine. <b>Start-up</b> = creating the Spark session, reported separately. <b>Wall clock</b> = the whole subprocess including Python or JVM launch. Memory: ${esc((ok[0] || {}).memory_method || "")}</p>`;
  if (ok.length) {
    h += `<div class="two" style="margin-top:20px"><div class="panel chart"><h4>Processing time (seconds)</h4>${barChart(ok.map(e => ({ label: e.engine, value: e.processing_seconds, color: "var(--forest)" })), { unit: "s" })}</div><div class="panel chart"><h4>Peak memory (MB)</h4>${barChart(ok.map(e => ({ label: e.engine, value: e.peak_memory_mb, color: "var(--terracotta)" })), { unit: " MB" })}</div></div>
    <h3 style="margin-top:28px">What actually ran</h3><ul>${ok.map(e => `<li><b>${esc(e.engine)}:</b> ${esc(e.implementation)}</li>`).join("")}</ul>
    <h3 style="margin-top:20px">Result preview (first engine, ten largest groups by spend)</h3><div class="tbl-wrap"><table><thead><tr><th>Industry</th><th>Format</th><th class="num">Rows</th><th class="num">Impressions</th><th class="num">Clicks</th><th class="num">Spend</th><th class="num">Conv.</th><th class="num">CTR %</th><th class="num">CPA</th><th class="num">ROAS</th></tr></thead><tbody>${[...ok[0].result].sort((a, b) => b.spend - a.spend).slice(0, 10).map(x => `<tr><td>${esc(x.industry)}</td><td>${esc(x.ad_format)}</td><td class="num">${num(x.rows, 0)}</td><td class="num">${num(x.impressions, 0)}</td><td class="num">${num(x.clicks, 0)}</td><td class="num">${num(x.spend, 0)}</td><td class="num">${num(x.conversions, 0)}</td><td class="num">${fmtMetric("ctr", x.ctr).replace("%", "")}</td><td class="num">${num(x.cpa)}</td><td class="num">${num(x.roas)}</td></tr>`).join("")}</tbody></table></div>`;
  }
  h += `<h3 style="margin-top:28px">Environment</h3><p class="fine">Python ${esc(env.python)}, pandas ${esc(env.pandas)}, numpy ${esc(env.numpy)}, PySpark ${esc(env.pyspark || "not installed")}, ${esc(env.java || "Java not found")}. ${esc(env.platform)}, ${env.cpu_count} CPU core(s), ${env.ram_gb ?? "?"} GB RAM.</p>
  <div class="callout gold">Results depend on this computer. Pandas is often fastest on small data because Spark pays a start-up cost; Spark's advantages appear with more data, more cores, or a cluster. A single run is one measurement, so repeat it before drawing conclusions.</div>`;
  $("#out").innerHTML = h;
}
async function history() {
  try {
    const { runs } = await api("/api/lab/history"); const w = $("#hist-wrap");
    if (!runs.length) { w.innerHTML = ""; return; }
    w.innerHTML = `<h3>Earlier runs on this computer</h3><div class="tbl-wrap"><table><thead><tr><th>When</th><th class="num">Records</th><th>Engine</th><th class="num">Processing (s)</th><th class="num">Wall (s)</th><th class="num">Memory (MB)</th><th>Matched</th></tr></thead><tbody>${runs.slice(-24).reverse().map(r => `<tr><td>${esc(new Date(r.when).toLocaleString())}</td><td class="num">${num(r.size, 0)}</td><td>${esc(r.engine)}</td><td class="num">${num(r.processing_seconds, 2)}</td><td class="num">${num(r.wall_seconds, 2)}</td><td class="num">${num(r.peak_memory_mb, 0)}</td><td>${r.correct ? "Yes" : "No"}</td></tr>`).join("")}</tbody></table></div>`;
  } catch (e) { /* history is optional */ }
}
