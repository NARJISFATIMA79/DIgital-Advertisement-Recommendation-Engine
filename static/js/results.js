/* Renders an analysis result. Used by the analysis page and the saved-report page. */
function renderExisting(r, opts = {}) {
  const cur = (r.budget && r.budget.scenarios[r.budget.selected] && r.budget.scenarios[r.budget.selected].currency) || "PKR";
  const used = r.evaluation.metrics_used || [];
  const adsById = Object.fromEntries(r.ads.map(a => [a.id, a]));
  let h = `<div class="res">`;
  h += headerSection(r);
  h += `<section style="padding-top:0">${basisBanner(r)}</section>`;
  // ---- Performance vs. Next Best Test
  const bp = r.best_performer, pl = r.provisional_leader, nt = r.next_test, ev = r.evaluation;
  h += `<section><h2>Performance vs. Next Best Test</h2><div class="two">`;
  h += `<div class="panel"><h3>Best Performer</h3>`;
  if (bp) {
    const a = adsById[bp.id];
    h += `<p><b style="font-family:var(--serif);font-size:1.3rem;font-weight:500">${esc(bp.name)}</b> ${badge("Established")} ${badge(a.evidence.level + " evidence")}</p>
      <div class="metricrow">${used.map(k => `<span>${esc(METRIC_LABELS[k])}: <b>${fmtMetric(k, a.metrics[k])}</b></span>`).join("")}</div>
      <p class="fine">${esc(ev.why_these_metrics)}</p>
      <p><b>Compared with the others</b></p><ul>${(ev.comparison || []).filter(c => c.name !== bp.name).map(c => `<li>${esc(c.name)}: ${Object.entries(c.key_metrics).map(([k, v]) => esc(METRIC_LABELS[k]) + " " + esc(v)).join(", ")}${c.eligible ? "" : " (Limited evidence, not eligible)"}</li>`).join("")}</ul>
      ${ev.p_value !== undefined && ev.p_value !== null ? `<p class="fine">${esc(ev.test_used)}: p = ${ev.p_value}. A small p-value says the rate difference is unlikely to be chance; it does not prove why one ad did better.</p>` : ""}
      <div class="callout info"><b>Before you increase spend:</b> ${esc((ev.reasons || []).join(" ") || "Keep audience and dates comparable, and re-check after another week of data.")}</div>`;
  } else {
    h += `<p><b>No reliable winner yet</b> ${badge("Inconclusive")}</p><p>${esc((ev.reasons || []).join(" ") || "There is not enough comparable data.")}</p>
      ${pl ? `<p class="fine">Highest score so far: ${esc(pl.name)}. This is not established and should not drive budget on its own.</p>` : ""}
      <div class="callout"><b>What is missing:</b> comparable results (same objective, similar dates) for at least two ads, each with enough ${esc(ev.objective === "sales" || ev.objective === "leads" ? "conversions" : "clicks or views")} to trust. The test on the right is a good way to get there.</div>`;
  }
  h += `</div><div class="panel"><h3>Next Best Test</h3>`;
  if (nt.status === "ok") {
    h += `<p><b style="font-family:var(--serif);font-size:1.3rem;font-weight:500">${esc(nt.ad_name)}</b> ${nt.different_from_best ? '<span class="badge">different from the best performer</span>' : ""}</p>
      <p>${esc(nt.why)}</p><dl class="kv"><dt>Hypothesis</dt><dd>${esc(nt.hypothesis)}</dd><dt>What to change</dt><dd>${esc(nt.what_to_change)}</dd><dt>Success metric</dt><dd>${esc(nt.primary_metric)}</dd><dt>Test budget</dt><dd>${nt.test_budget ? esc(money(nt.test_budget, cur)) : "Not set"}<br><span class="fine">${esc(nt.test_budget_note)}</span></dd></dl>
      <p style="margin-top:12px"><b>How to decide</b></p><ul>${nt.decision_rule.map(x => `<li>${esc(x)}</li>`).join("")}</ul><p class="fine">Evidence behind this: ${esc(nt.evidence_basis)}. Untested ideas are not promised to win.</p>`;
  } else h += `<p>${esc(nt.message || "Add an advertisement to get a test recommendation.")}</p>`;
  h += `</div></div></section>`;

  // ---- comparison table
  h += `<section><h2>Side-by-side comparison</h2><div class="tbl-wrap"><table><caption>Measured results. n/a means the data needed was not supplied, which is different from zero.</caption><thead><tr><th>Advertisement</th><th>Data source</th>${["ctr", "cpc", "cpa", "conv_rate", "roas", "view_rate", "cpv"].map(k => `<th class="num">${METRIC_LABELS[k]}${used.includes(k) ? " *" : ""}</th>`).join("")}<th>Evidence</th></tr></thead><tbody>`;
  r.ads.forEach(a => {
    h += `<tr class="${bp && bp.id === a.id ? "best" : ""}"><td><b>${esc(a.name)}</b>${a.url ? `<br>${linkTo(a.url, "video link", "fine")}` : ""}</td><td>${esc(a.data_source || "none supplied")}</td>${["ctr", "cpc", "cpa", "conv_rate", "roas", "view_rate", "cpv"].map(k => `<td class="num" title="${esc(a.missing_metrics[k] || "")}">${fmtMetric(k, a.metrics[k])}</td>`).join("")}<td>${badge(a.evidence.level)}<br><span class="fine">${esc(a.evidence.reasons[0] || "")}</span></td></tr>`;
  });
  h += `</tbody></table></div><p class="fine">* Used to rank for ${esc(r.objective_label.toLowerCase())}. ${(ev.metrics_dropped || []).length ? "Left out because some ad lacks the data: " + esc(ev.metrics_dropped.map(k => METRIC_LABELS[k]).join(", ")) + "." : ""} Hover a cell that shows n/a to see what is missing.</p>`;
  const withScore = r.ads.filter(a => a.objective_score !== undefined && a.objective_score !== null);
  if (withScore.length) h += `<div class="panel flat" style="padding:16px 0"><p class="fine">Objective score (1.00 = best ad on every ranking metric)</p>${barChart(withScore.map(a => ({ label: a.name, value: a.objective_score })))}</div>`;
  h += `</section>`;

  // ---- creative
  h += `<section><h2>Creative assessment</h2><div class="callout gold">A rule-based checklist over the text you entered. It does not watch your video and does not predict sales. Missing information is shown as unavailable instead of guessed.</div><div class="three" style="margin-top:20px">`;
  r.ads.filter(a => a.creative).forEach(a => {
    const c = a.creative;
    h += `<div class="panel"><h3>${esc(a.name)}</h3><p>${c.overall === null ? "No score possible" : `<b style="font-size:1.6rem;font-family:var(--serif)">${c.overall}</b> / 100`} <span class="badge ${c.confidence === "good" ? "high" : c.confidence}">${esc(c.confidence)} confidence</span></p><p class="fine">${Math.round(c.coverage * 100)}% of checklist items had information.</p>`;
    Object.values(c.dimensions).forEach(d => {
      h += `<div class="dim"><div class="t"><span>${esc(d.label)}</span><b>${d.score === null ? "n/a" : d.score}</b></div><div class="bar ${d.score === null ? "na" : ""}"><i style="width:${d.score || 0}%"></i></div><small>${esc(d.evidence)}</small></div>`;
    });
    h += `</div>`;
  });
  h += `</div></section>`;

  // ---- budget
  if (r.budget) {
    const b = r.budget, sel = b.selected;
    h += `<section><h2>Budget recommendation</h2>`;
    if (r.budget_error) h += `<div class="callout"><b>Could not allocate:</b> ${esc(r.budget_error)}</div>`;
    else {
      h += `<div class="tabs" role="tablist">${Object.entries(b.scenarios).map(([k, s]) => `<button role="tab" data-scn="${k}" aria-selected="${k === sel}">${esc(s.scenario_label)}</button>`).join("")}</div><div id="scn-body"></div>`;
      h += `<h3 style="margin-top:28px">What if the budget changes?</h3><div class="tbl-wrap"><table><thead><tr><th>Budget</th>${Object.keys((b.sensitivity.find(x => x.amounts) || { amounts: {} }).amounts).map(n => `<th class="num">${esc(n)}</th>`).join("")}</tr></thead><tbody>${b.sensitivity.map(row => row.error ? `<tr><td>${esc(money(row.budget, cur))}</td><td colspan="9" class="fine">${esc(row.error)}</td></tr>` : `<tr><td>${esc(money(row.budget, cur))} (${Math.round(row.factor * 100)}%)</td>${Object.values(row.amounts).map(v => `<td class="num">${esc(money(v))}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
      if (opts.onRecalc) h += `<div class="row noprint" style="margin-top:16px"><div class="field" style="margin:0"><label for="whatif">Try a different total budget (${esc(cur)})</label><input id="whatif" type="number" min="1" step="any" value="${esc(b.scenarios[sel].total)}"></div><button class="btn" id="recalc" style="margin-top:22px">Recalculate</button></div>`;
    }
    h += `</section>`;
  }

  if (r.competitive) h += refsSection(r);
  h += evidenceMapSection(r) + actionsSection(r);

  h += explainSection(r) + qualitySection(r);
  h += `</div>`;
  return h;
}

function wireResults(root, r, opts = {}) {
  if (!r.budget || r.budget_error) return;
  const body = $("#scn-body", root); if (!body) return;
  const show = key => {
    const s = r.budget.scenarios[key];
    $$("[data-scn]", root).forEach(b => b.setAttribute("aria-selected", b.dataset.scn === key));
    if (s.error) { body.innerHTML = `<div class="callout"><b>${esc(s.scenario_label)} could not be calculated:</b> ${esc(s.error)}</div>`; return; }
    body.innerHTML = `<p class="lede" style="margin-bottom:8px">${esc(s.scenario_summary)}</p><p class="fine">${s.mode === "exploratory" ? '<span class="badge limited">Exploratory allocation</span> ' : '<span class="badge established">Evidence-based</span> '}Total ${esc(money(s.total, s.currency))}, reserve for testing ${esc(money(s.reserve, s.currency))}${s.unallocated > 0 ? `, unallocated ${esc(money(s.unallocated, s.currency))}` : ""}. ${s.reconciles ? "Lines add up to the total." : ""}</p>${allocBar(s.lines)}
      <div class="tbl-wrap" style="margin-top:14px"><table><thead><tr><th>Advertisement</th><th>Role</th><th class="num">Amount (${esc(s.currency)})</th><th class="num">Share</th><th>Why</th></tr></thead><tbody>${s.lines.map(l => `<tr><td><b>${esc(l.name)}</b></td><td>${esc(l.role)}</td><td class="num">${esc(money(l.amount))}</td><td class="num">${l.percent}%</td><td>${l.reasons.map(esc).join(" ")}${l.forecast ? `<br><span class="fine"><b>${esc(l.forecast.label)}:</b> about ${l.forecast.conversions} conversions. ${esc(l.forecast.assumption)}</span>` : ""}</td></tr>`).join("")}<tr><td><b>Total</b></td><td></td><td class="num"><b>${esc(money(s.lines.reduce((a, l) => a + l.amount, 0)))}</b></td><td class="num">100%</td><td></td></tr></tbody></table></div>
      <ul class="fine">${s.notes.map(n => `<li>${esc(n)}</li>`).join("")}</ul><p class="fine">${esc(s.disclaimer)}</p>`;
  };
  $$("[data-scn]", root).forEach(b => b.addEventListener("click", () => show(b.dataset.scn)));
  show(r.budget.selected);
  const rc = $("#recalc", root);
  if (rc && opts.onRecalc) rc.addEventListener("click", () => { const v = parseFloat($("#whatif", root).value); if (!(v > 0)) return toast("Enter a budget greater than zero."); opts.onRecalc(v); });
}

/* ====================== shared sections ====================== */
function renderResults(r, opts = {}) { return r.mode === "idea" ? renderIdea(r, opts) : renderExisting(r, opts); }
function headerSection(r) {
  const idea = r.mode === "idea";
  return `<section><div class="row" style="justify-content:space-between"><div><h2>${idea ? "Advertising plan" : "Results"} for ${esc(r.profile.brand || r.profile.product || "your campaign")}</h2>
    <p class="lede" style="margin:0">${idea ? "Starting from a product idea" : "Existing advertisements"}. Objective: <b>${esc(r.objective_label)}</b>.</p></div>
    <div class="row noprint">${r.is_demo ? '<span class="badge demo">Demo data</span>' : ""}<button class="btn ghost small" onclick="window.print()">Print or save as PDF</button>${r.report_id && (r.budget || r.budget_plan) ? `<a class="btn ghost small" href="/api/reports/${esc(r.report_id)}/export.csv${r.budget ? "?scenario=" + esc(r.budget.selected) : ""}">Export budget CSV</a>` : ""}${r.report_id ? `<a class="btn ghost small" href="/report/${esc(r.report_id)}">Open report page</a>` : ""}</div></div></section>`;
}
function basisBanner(r) { const b = r.comparison_basis; if (!b) return ""; const tags = [["measured", "Measured results"], ["creative_text", "Creative text"], ["public_video_text", "Public video text"]]; return `<div class="callout info"><b>What this analysis is based on.</b> ${esc(b.text)}<div class="row" style="margin-top:8px;gap:6px">${tags.map(([k, l]) => `<span class="badge ${b[k] ? "high" : ""}">${b[k] ? "Used" : "Not used"}: ${l}</span>`).join("")}</div></div>`; }
function evidenceMapSection(r) {
  const e = r.evidence_map; if (!e) return "";
  const list = a => a && a.length ? `<ul>${a.filter(Boolean).map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : '<p class="fine">Nothing to report.</p>';
  return `<section><h2>What is known and what is not</h2><p class="fine">AdPilot keeps these five kinds of statement apart so a guess is never read as a result.</p><div class="two">
    <div class="panel"><h3>Measured results</h3><p>${esc(e.measured)}</p></div><div class="panel"><h3>Observed in public video text</h3>${list(e.observed)}</div>
    <div class="panel"><h3>Hypotheses to test</h3>${list(e.hypotheses)}</div><div class="panel"><h3>Unknown</h3>${list(e.unknown)}</div></div></section>`;
}
function actionsSection(r) {
  const a = r.next_actions || []; if (!a.length) return "";
  return `<section><h2>Recommended next actions</h2><ol>${a.map(x => `<li style="margin-bottom:12px"><b>${esc(x.action)}</b><br><span class="fine">${esc(x.why)} <span class="badge">${esc(x.basis)}</span></span></li>`).join("")}</ol>${(r.improve_with || []).length ? `<p><b>What would improve this analysis</b></p><ul>${r.improve_with.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}</section>`;
}
function refsSection(r) {
  const c = r.competitive; if (!c) return "";
  let h = `<section><h2>Competitor references</h2>`;
  if (r.api_data_expired) h += `<div class="callout">Some YouTube details in this saved report were removed because YouTube's policy allows API data to be kept for 30 days. Run the competitor search again to refresh them.</div>`;
  if (c.analyses && c.analyses.length) {
    const d = c.depth_summary || {}, vs = c.verification_summary;
    if (vs) h += `<div class="callout ${vs.verified_automated + vs.user_confirmed ? "info" : "gold"}"><b>Paid-ad verification:</b> ${vs.verified_automated} verified by exact Transparency Center video-ID match, ${vs.user_confirmed} confirmed by you (not checked by AdPilot), ${vs.reference_only} unverified and treated as <b>public reference content</b> (${vs.possible_match} possible match${vs.possible_match === 1 ? "" : "es"}, ${vs.unverified} checked without a match, ${vs.not_checked} not checked). Reference content shows creative patterns in public videos; it is not evidence of what competitors paid to run. ${vs.verified_automated + vs.user_confirmed === 0 ? "Confidence that these are competitor <i>advertisements</i> is therefore low." : ""}</div>`;
    h += `<div class="callout gold">Creative observations from public text only. AdPilot did not watch these videos: visuals, audio and editing are not analysed. Depth reached: ${Object.entries(d).map(([k, v]) => `${v} ${esc(DEPTH_LABEL[k] || k).toLowerCase()}`).join(", ")}. They say nothing about how well any video performed commercially.</div><div class="vgrid" style="margin-top:16px">`;
    c.analyses.forEach(a => {
      if (a.expired) { h += `<div class="panel"><b>${esc(a.title)}</b><p class="fine">${esc(a.note)}</p></div>`; return; }
      const s = a.signals;
      h += `<div class="panel"><h4>${linkTo(a.url, esc(a.title))}</h4><div class="row" style="gap:6px">${originBadge(a.origin)}<span class="badge ${STATUS_CLASS[a.status] || ""}">${esc(a.status || "Relevant Public Video")}</span>${a.verification_basis === "user_confirmed" ? '<span class="badge moderate">User-confirmed, not checked by AdPilot</span>' : ""}${a.verification_basis === "transparency_exact" ? '<span class="badge verified">Exact video-ID match (automated)</span>' : tvBadge(a)}<span class="badge ${a.depth === "transcript" ? "high" : a.depth === "text_based" ? "moderate" : "limited"}">${esc(a.analysis_level)}</span></div>
        <dl class="kv" style="margin-top:10px"><dt>Hook</dt><dd>${esc(s.hook.text || "unavailable")}<br><span class="fine">${esc(s.hook.note)}</span></dd><dt>Structure</dt><dd>${esc((s.structures || []).join(", ") || "none detected in the text")}</dd><dt>Offer terms</dt><dd>${esc((s.offers || []).join(", ") || "none found")}</dd><dt>Proof terms</dt><dd>${esc((s.proof_terms || []).join(", ") || "none found")}</dd></dl>
        ${a.public_stats ? `<p class="fine">Public views ${a.public_stats.public_views !== null && a.public_stats.public_views !== undefined ? num(a.public_stats.public_views, 0) : "unknown"}, likes ${a.public_stats.public_likes !== null && a.public_stats.public_likes !== undefined ? num(a.public_stats.public_likes, 0) : "unknown"}. Public numbers, not advertising results.</p>` : ""}
        ${a.verification ? tvDetails(a) : ""}${a.depth !== "transcript" ? `<p class="fine"><b>Limits:</b> ${esc(a.missing_inputs.join(" "))}</p>` : ""}</div>`;
    });
    h += `</div>`;
    (c.comparisons || []).forEach(cmp => {
      h += `<h3 style="margin-top:28px">${esc(cmp.kind === "concept" ? "Concept" : "Ad")}: ${esc(cmp.for)} compared with the references</h3><div class="tbl-wrap"><table><thead><tr><th>Dimension</th><th>What the references show (observed)</th><th>Yours</th><th>Interpretation</th><th>Hypothesis to test</th></tr></thead><tbody>${cmp.dimensions.map(d => `<tr><td><b>${esc(d.dimension)}</b></td><td>${esc(d.observed)}</td><td>${d.assessable ? (d.yours === "yes" ? "Yes" : "No") : "n/a"}</td><td>${esc(d.interpretation || "")}</td><td>${esc(d.hypothesis || "")}</td></tr>`).join("")}</tbody></table></div>`;
      h += `<p class="fine">${esc(cmp.summary.note || "")}</p>`;
    });
  } else h += `<p>No competitor videos were compared.</p>`;
  h += `<div class="panel flat" style="margin-top:16px"><h3>Competitor performance</h3>${c.performance.available ? c.performance.entries.map(e => `<p><b>${esc(e.name)}</b> <span class="badge">customer-provided, unverified</span> (source: ${esc(e.source)})<br>${Object.entries(e.metrics).filter(([, v]) => v !== null).map(([k, v]) => esc(METRIC_LABELS[k]) + " " + fmtMetric(k, v)).join(", ") || "No metrics could be calculated."}</p>`).join("") : `<p>${esc(c.performance.message)}</p>`}</div></section>`;
  return h;
}
function explainSection(r) {
  return `<section><h2>Why AdPilot recommends this</h2>${(r.explanations || []).map(x => `<details class="expl"><summary>${esc(x.title)}: ${esc(x.recommendation)}</summary><dl class="kv"><dt>Why</dt><dd>${esc(x.why)}</dd><dt>Based on</dt><dd>${esc(x.basis)}</dd><dt>Data</dt><dd>${esc(x.data)}</dd><dt>Assumptions</dt><dd>${(x.assumptions || []).length ? x.assumptions.map(esc).join("<br>") : "None beyond the method described."}</dd><dt>To improve</dt><dd>${esc(x.to_improve)}</dd></dl></details>`).join("")}<p class="fine">${esc(r.method_note)}</p></section>`;
}
function qualitySection(r) {
  const dq = r.data_quality; let h = `<section><h2>Data quality and limitations</h2>`;
  if (dq.validation) { const s = dq.validation.summary; h += `<p>Uploaded <b>${s.uploaded_rows}</b> rows; <b>${s.clean_rows}</b> used, <b>${s.excluded_rows}</b> excluded, <b>${s.warning_count}</b> warnings.</p>${dq.validation.errors.length ? `<div class="callout">${dq.validation.errors.map(esc).join("<br>")}</div>` : ""}${dq.validation.excluded.length ? `<details><summary>Excluded rows and why</summary><ul>${dq.validation.excluded.slice(0, 100).map(e => `<li>Row ${e.row}: ${esc(e.reason)}</li>`).join("")}</ul></details>` : ""}`; }
  h += dq.warnings.length ? `<details open><summary>${dq.warnings.length} warning(s)</summary><ul>${dq.warnings.slice(0, 60).map(w => `<li>${esc(w)}</li>`).join("")}</ul></details>` : `<p class="fine">No data warnings.</p>`;
  if (dq.ads_without_data.length) h += `<div class="callout">No performance data for: ${dq.ads_without_data.map(esc).join(", ")}. They are treated as unproven and can only receive test or exploratory budget.</div>`;
  return h + `</section>`;
}

/* ====================== product-idea results ====================== */
function renderIdea(r, opts = {}) {
  const sel = (r.concepts || []).filter(c => (r.selected_concepts || []).includes(c.id));
  let h = `<div class="res">` + headerSection(r) + `<section style="padding-top:0">${basisBanner(r)}<div class="callout" style="margin-top:12px"><b>No advertisement or campaign data was supplied</b>, so nothing here is a measured result and no concept is called a winner. Everything below is a proposal or a hypothesis to test.</div></section>`;
  h += `<section><h2>Your advertising concepts</h2><p class="fine">${esc((r.concept_generator || {}).note || "")}</p><div class="three">${sel.map(c => `<div class="panel"><span class="badge">${esc(c.label)}</span><h3 style="margin-top:8px">${esc(c.title)}</h3>
    <dl class="kv"><dt>Hook</dt><dd>${esc(c.hook)}</dd><dt>Message</dt><dd>${esc(c.main_message)}</dd><dt>Offer</dt><dd>${esc(c.offer || "none")}</dd><dt>Call to action</dt><dd>${esc(c.cta)}</dd></dl>
    ${c.outline ? `<p class="fine"><b>Outline:</b> ${esc(c.outline)}</p>` : ""}${c.why_it_may_appeal ? `<p class="fine"><b>Why it might appeal (hypothesis):</b> ${esc(c.why_it_may_appeal)}</p>` : ""}
    <p>${c.creative && c.creative.overall !== null ? `Checklist <b>${c.creative.overall}</b>/100 <span class="badge ${c.creative.confidence === "good" ? "high" : c.creative.confidence}">${esc(c.creative.confidence)} confidence</span>` : '<span class="badge limited">Checklist: not enough text</span>'}</p>
    <p class="fine">The checklist counts how many items your text covers. It does not predict results.</p>
    ${(c.assumptions || []).length ? `<details><summary>Assumptions to validate</summary><ul>${c.assumptions.map(a => `<li>${esc(a)}</li>`).join("")}</ul></details>` : ""}</div>`).join("")}</div></section>`;
  if (r.competitive) h += refsSection(r); else h += `<section><h2>Competitor references</h2><div class="empty">No competitor videos were compared. Go back to the competitor step to search or paste a link; AdPilot can then show how your concepts differ from what is already on YouTube.</div></section>`;
  h += evidenceMapSection(r) + actionsSection(r);
  const x = r.experiments;
  if (x && x.status === "ok") h += `<section><h2>Experiment plan</h2><div class="panel"><h3>${esc(x.headline)}</h3><dl class="kv"><dt>Hypothesis</dt><dd>${esc(x.hypothesis)}</dd><dt>What changes</dt><dd>${esc(x.what_changes)}</dd><dt>Success metric</dt><dd>${esc(x.primary_metric)}</dd><dt>Minimum sample</dt><dd>${esc(x.minimum_sample)}</dd><dt>Test budget</dt><dd>${x.test_budget ? esc(money(x.test_budget, x.currency)) + ` <span class="fine">${esc(x.test_budget_note || "")}</span>` : esc(x.budget_note || "Not set")}</dd></dl><p><b>How to decide</b></p><ul>${x.decision_rule.map(d => `<li>${esc(d)}</li>`).join("")}</ul>${x.checklist_gaps.length ? `<p><b>Checklist gaps to fix first</b></p><ul>${x.checklist_gaps.map(d => `<li>${esc(d)}</li>`).join("")}</ul>` : ""}${x.follow_ups.length ? `<p><b>Follow-up tests</b></p><ul>${x.follow_ups.map(d => `<li>${esc(d)}</li>`).join("")}</ul>` : ""}</div></section>`;
  const p = r.budget_plan;
  if (r.budget_error) h += `<section><h2>Budget plan</h2><div class="callout">${esc(r.budget_error)}</div></section>`;
  if (p) h += `<section><h2>Exploratory budget plan</h2><span class="badge limited">Exploratory: no measured data</span><p class="fine" style="margin-top:8px">${esc(p.disclaimer)}</p>${allocBar(p.lines.map(l => ({ ...l, role: l.role === "held" ? "unallocated" : l.role })))}
    <div class="tbl-wrap" style="margin-top:14px"><table><thead><tr><th>Item</th><th>Role</th><th class="num">Amount (${esc(p.currency)})</th><th class="num">Share</th><th>Why</th></tr></thead><tbody>${p.lines.map(l => `<tr><td><b>${esc(l.name)}</b></td><td>${esc(l.role === "held" ? "held back" : "test")}</td><td class="num">${esc(money(l.amount))}</td><td class="num">${l.percent}%</td><td>${l.reasons.map(esc).join(" ")}</td></tr>`).join("")}<tr><td><b>Total</b></td><td></td><td class="num"><b>${esc(money(p.lines.reduce((a, l) => a + l.amount, 0)))}</b></td><td class="num">100%</td><td></td></tr></tbody></table></div><ul class="fine">${p.notes.map(n => `<li>${esc(n)}</li>`).join("")}</ul></section>`;
  return h + explainSection(r) + qualitySection(r) + `</div>`;
}
