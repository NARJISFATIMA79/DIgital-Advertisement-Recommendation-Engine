"""AdPilot - Flask application (routes only; all analytics live in the adpilot/ package)."""
from __future__ import annotations
import csv
import io
import json
import threading
import time
import uuid
from datetime import datetime, timezone
import logging

from flask import Flask, Response, jsonify, render_template, request

from adpilot import bigdata as BD
from adpilot import discovery as D
from adpilot import transparency as T
from adpilot.budget import BudgetError
from adpilot.concepts import assess_concept, generate_concepts
from adpilot.pipeline import run_analysis, _profile
from adpilot.strategy import CATEGORY_ORDER, OBJECTIVES, STRATEGIES
from adpilot.validation import template_csv, validate_csv_text
from config import Config


def create_app(test_config=None, youtube_client=None, transparency_provider=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    inst = app.config["INSTANCE_DIR"]; (inst / "reports").mkdir(parents=True, exist_ok=True)
    app.config["DATA_DIR"].mkdir(parents=True, exist_ok=True)
    client = youtube_client or D.YouTubeClient()
    cache = D.DiscoveryCache(inst / "youtube_cache", app.config["CACHE_TTL_SECONDS"])
    cache.purge_expired()
    quota = D.QuotaTracker(inst / "quota.json")
    tcache = D.DiscoveryCache(inst / "transparency_cache", app.config["TRANSPARENCY_TTL_SECONDS"])
    tcache.purge_expired()
    tsvc = T.TransparencyService(transparency_provider or T.SearchApiProvider(), tcache, T.UsageCounter(inst / "transparency_usage.json"))
    log = logging.getLogger("adpilot")
    jobs, jobs_lock = {}, threading.Lock()
    API_TTL = D.MAX_CACHE_SECONDS

    def redact_expired(rec):
        """YouTube policy: stored API data must be deleted or refreshed within 30 days. Redact it from old reports."""
        comp = (rec.get("result") or {}).get("competitive")
        if not comp or not comp.get("analyses"):
            return rec, False
        cutoff = time.time() - API_TTL
        changed = False
        for i, a in enumerate(comp["analyses"]):
            if a.get("origin") == "youtube_api" and a.get("retrieved_at") and a["retrieved_at"] < cutoff and not a.get("expired"):
                comp["analyses"][i] = {"expired": True, "origin": "youtube_api", "video_id": a.get("video_id"), "url": a.get("url"), "title": "(details removed)",
                                       "depth": "limited", "analysis_level": "Expired", "evidence_quality": "Limited", "signals": {}, "missing_inputs": [], "not_analysed": [],
                                       "note": "YouTube API data is kept for at most 30 days. Run the competitor search again to refresh it."}
                changed = True
        if changed:
            comp["comparisons"] = []
            rec["result"]["api_data_expired"] = True
        return rec, changed

    def purge_reports():
        for p in (inst / "reports").glob("*.json"):
            try:
                rec, changed = redact_expired(json.loads(p.read_text()))
                if changed:
                    p.write_text(json.dumps(rec))
            except Exception:
                log.warning("Could not check report %s for expired data", p.name)
    purge_reports()

    def demo_input(mode="existing"):
        path = app.config["DEMO_PATH"]
        if mode == "idea":
            path = path.with_name("demo_idea.json")
        return json.loads(path.read_text())

    def ctx():
        return {"categories": [{"key": k, "label": STRATEGIES[k]["label"]} for k in CATEGORY_ORDER],
                "objectives": [{"key": k, "label": v} for k, v in OBJECTIVES.items()], "youtube_configured": client.configured, "transparency_configured": tsvc.configured}

    def _int_in(v, default):
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    def _body():
        """JSON body as a dict; anything else (list, string, bad JSON) becomes {} so endpoints reply with a clean 400."""
        b = request.get_json(silent=True)
        return b if isinstance(b, dict) else {}

    # ------------------------------------------------------------ pages
    @app.get("/")
    def landing():
        return render_template("landing.html", demo=run_analysis(demo_input()), idea=run_analysis(demo_input("idea")), **ctx())

    @app.get("/dashboard")
    def dashboard():
        return render_template("dashboard.html", **ctx())

    @app.get("/analyze")
    def analyze_page():
        return render_template("analyze.html", strategies={k: {"approaches": v["approaches"], "objectives": v["objectives"], "label": v["label"]} for k, v in STRATEGIES.items()}, **ctx())

    @app.get("/lab")
    def lab_page():
        return render_template("lab.html", sizes=BD.SIZES, **ctx())

    @app.get("/report/<rid>")
    def report_page(rid):
        return render_template("report.html", rid=rid, **ctx())

    # ------------------------------------------------------------ API
    def err(message, status=400, code="bad_request"):
        return jsonify({"error": {"message": message, "code": code}}), status

    @app.errorhandler(404)
    def nf(_e):
        return err("Not found.", 404, "not_found") if request.path.startswith("/api/") else (render_template("error.html", message="That page does not exist.", **ctx()), 404)

    @app.errorhandler(413)
    def too_big(_e):
        return err("The file is larger than 8 MB. Split it or upload a summary by ad and date.", 413, "too_large")

    @app.errorhandler(500)
    def server_error(_e):
        return err("Something went wrong on the server. Details were not shown for safety; check the terminal log.", 500, "server_error")

    @app.get("/api/config")
    def api_config():
        return jsonify({"youtube_configured": client.configured, "cache_ttl_seconds": cache.ttl, "transparency_url": D.TRANSPARENCY_URL, "transparency": tsvc.status(), "auto_searches": D.AUTO_SEARCHES,
                        "quota": {"search_units": D.SEARCH_COST, "videos_units": D.VIDEOS_COST, **quota.snapshot()}})

    @app.get("/api/demo-input")
    def api_demo():
        return jsonify(demo_input("idea" if request.args.get("mode") == "idea" else "existing"))

    @app.get("/api/sample-csv")
    def api_sample_csv():
        return Response(template_csv(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=adpilot_template.csv"})

    @app.post("/api/validate-csv")
    def api_validate_csv():
        text = None
        if request.files.get("file"):
            try:
                text = request.files["file"].read().decode("utf-8-sig")
            except UnicodeDecodeError:
                return err("The file is not UTF-8 text. Export it from your spreadsheet as 'CSV UTF-8'.")
        else:
            text = (_body()).get("csv_text")
        if not text or not text.strip():
            return err("No CSV content received.")
        v = validate_csv_text(text)
        v["clean_rows_preview"] = v.pop("clean_rows")[:20]
        v["csv_text"] = text
        return jsonify(v)

    @app.post("/api/analyze")
    def api_analyze():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return err("Send the analysis as JSON.")
        try:
            result = run_analysis(payload)
        except ValueError as e:
            return err(str(e))
        except Exception:
            log.exception("analysis failed")
            return err("The analysis hit an unexpected problem. Check your inputs and try again; details are in the server log.", 500, "server_error")
        rid = None
        if payload.get("save"):
            rid = uuid.uuid4().hex[:10]
            rec = {"id": rid, "created": datetime.now(timezone.utc).isoformat(), "title": (payload.get("profile") or {}).get("brand") or "Untitled analysis",
                   "is_demo": bool(payload.get("is_demo")), "mode": result["mode"],
                   "input": {k: v for k, v in payload.items() if k not in ("csv_text", "competitor_videos", "save")}, "result": result}
            (inst / "reports" / f"{rid}.json").write_text(json.dumps(rec))
        result["report_id"] = rid
        return jsonify(result)

    def _load(rid):
        if not rid.isalnum():
            return None
        p = inst / "reports" / f"{rid}.json"
        return json.loads(p.read_text()) if p.exists() else None

    @app.get("/api/reports")
    def api_reports():
        out = []
        for p in sorted((inst / "reports").glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:50]:
            r = json.loads(p.read_text()); res = r["result"]
            ads = res["ads"]
            spend = [a["totals"]["spend"] for a in ads if a.get("totals") and a["totals"].get("spend") is not None]
            out.append({"id": r["id"], "created": r["created"], "title": r["title"], "is_demo": r["is_demo"], "objective": res["objective_label"], "mode": res.get("mode", "existing"),
                        "ads": len(ads), "concepts": len(res.get("selected_concepts") or []), "total_spend": sum(spend) if spend else None, "best": (res["best_performer"] or {}).get("name"),
                        "status": res["evaluation"]["status"]})
        return jsonify({"reports": out})

    @app.get("/api/reports/<rid>")
    def api_report(rid):
        r = _load(rid)
        if not r: return err("Report not found.", 404, "not_found")
        r, changed = redact_expired(r)
        return jsonify(r)

    @app.get("/api/reports/<rid>/export.csv")
    def api_export(rid):
        r = _load(rid)
        if not r: return err("Report not found.", 404, "not_found")
        plan = r["result"].get("budget_plan")
        if plan and not r["result"].get("budget"):
            buf = io.StringIO(); w = csv.writer(buf)
            w.writerow(["plan", "item", "role", f"amount_{plan['currency']}", "percent_of_budget"])
            for l in plan["lines"]: w.writerow(["Exploratory testing plan", l["name"], l["role"], l["amount"], l["percent"]])
            w.writerow(["", "TOTAL", "", round(sum(l["amount"] for l in plan["lines"]), 2), 100])
            return Response(buf.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename=adpilot_plan_{rid}.csv"})
        sel = r["result"]["budget"]
        if not sel: return err("This report has no budget allocation to export.", 404)
        scen = request.args.get("scenario") or sel["selected"]
        s = sel["scenarios"].get(scen, {})
        if "lines" not in s: return err(s.get("error", "That scenario is unavailable."), 400)
        buf = io.StringIO(); w = csv.writer(buf)
        w.writerow(["scenario", "advertisement", "role", f"amount_{s['currency']}", "percent_of_budget", "mode"])
        for l in s["lines"]:
            w.writerow([s["scenario_label"], l["name"], l["role"], l["amount"], l["percent"], s["mode"]])
        w.writerow(["", "TOTAL", "", round(sum(l["amount"] for l in s["lines"]), 2), 100, ""])
        return Response(buf.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename=adpilot_allocation_{rid}.csv"})

    # ------------------------------------------------------------ concepts (product-idea journey)
    def _json_profile(p):
        if not isinstance(p, dict): return None
        return _profile(p)

    @app.post("/api/concepts")
    def api_concepts():
        p = _body()
        prof = _json_profile(p.get("profile"))
        if prof is None or not prof["product"]:
            return err("Tell us what you are advertising first (the product or service).")
        obj = p.get("objective") if p.get("objective") in OBJECTIVES else "sales"
        return jsonify({"concepts": generate_concepts(prof, obj), "generator": {"type": "rule_based_templates", "ai_model_used": False,
                        "note": "Built from editable templates and the information you entered. No AI model was used and nothing has been tested."}})

    @app.post("/api/concepts/assess")
    def api_concept_assess():
        p = _body()
        c, prof = p.get("concept"), _json_profile(p.get("profile"))
        if not isinstance(c, dict) or prof is None: return err("Send a concept and a profile.")
        obj = p.get("objective") if p.get("objective") in OBJECTIVES else "sales"
        return jsonify({"creative": assess_concept(c, prof, obj)})

    # ------------------------------------------------------------ YouTube URLs
    @app.post("/api/youtube/parse")
    def api_parse():
        r = D.parse_youtube_url((_body()).get("url"))
        return jsonify(r), (200 if r["ok"] else 400)

    @app.post("/api/youtube/video")
    def api_video():
        p = _body()
        prof = _json_profile(p.get("profile")) or {}
        prof["industry_label"] = STRATEGIES.get(prof.get("industry"), STRATEGIES["other"])["label"]
        try:
            res = D.lookup_video(client, cache, p.get("url"), prof, quota)
        except D.InvalidKeyError as e:
            return jsonify({"retrieved": False, "reason": e.code, "message": str(e)}), 200
        except D.DiscoveryError as e:
            return err(str(e), 400 if e.code == "invalid_url" else 502, e.code)
        res["quota"] = quota.snapshot()
        return jsonify(res)

    # ------------------------------------------------------------ discovery
    @app.post("/api/discovery/queries")
    def api_queries():
        p = _body()
        prof = _json_profile(p.get("profile"))
        if prof is None: return err("Send the business profile.")
        prof["industry_label"] = STRATEGIES.get(prof.get("industry"), STRATEGIES["other"])["label"]
        prof["objective"] = p.get("objective") or ""
        qs = D.generate_queries(prof, [c for c in (p.get("concepts") or []) if isinstance(c, dict)][:8])
        if not qs:
            return err("Enter a product or service first so relevant searches can be created.")
        for i, q in enumerate(qs): q["auto"] = i < D.AUTO_SEARCHES
        return jsonify({"queries": qs, "auto_searches": D.AUTO_SEARCHES, "cost_note": f"Each search costs about {D.SEARCH_COST + D.VIDEOS_COST} quota units."})

    @app.post("/api/discovery/search")
    def api_search():
        p = _body()
        prof = _json_profile(p.get("profile")) or {}
        queries = [q.strip()[:120] for q in (p.get("queries") or []) if isinstance(q, str) and q.strip()][:8]
        if not queries:
            return err("Choose at least one search to run.")
        if not client.configured:
            return jsonify({"available": False, "code": "missing_key", "videos": [],
                            "message": "Automatic discovery is off because no YouTube API key is configured. Everything else in AdPilot still works. Add videos manually, or enable discovery in .env (see the README).",
                            "transparency_url": D.TRANSPARENCY_URL}), 200
        prof["industry_label"] = STRATEGIES.get(prof.get("industry"), STRATEGIES["other"])["label"]
        try:
            res = D.discover(client, cache, prof, queries, per_query=max(1, min(int(p.get("per_query", 8) or 8), 15)), refresh=bool(p.get("refresh")), region=(p.get("region") or "")[:2].upper() or None, quota=quota)
        except D.DiscoveryError as e:
            return jsonify({"available": False, "code": e.code, "videos": [], "message": str(e)}), 200
        res["available"] = True
        res["quota"] = quota.snapshot()
        if res["errors"] and not res["videos"]:
            res["message"] = res["errors"][0]["message"]
        v = D.sort_and_filter(res["videos"], p.get("sort", "relevance"), p.get("status") or None, p.get("published_after") or None)
        res["videos"] = v
        res["transparency_url"] = D.TRANSPARENCY_URL
        return jsonify(res)

    @app.post("/api/discovery/classify")
    def api_classify():
        p = _body()
        v = p.get("video") or {}
        return jsonify(T.classify_with_verification(v, p.get("profile") or {}, p.get("manual_verification"), p.get("verification") or v.get("verification")))

    # ------------------------------------------------------------ Transparency Center verification (optional, third-party)
    @app.get("/api/transparency/status")
    def api_transparency_status():
        return jsonify(tsvc.status())

    @app.post("/api/transparency/verify")
    def api_transparency_verify():
        """Match already-discovered videos against Transparency Center records. Reuses the videos the browser holds: no extra YouTube API calls."""
        p = _body()
        vids = [v for v in (p.get("videos") or []) if isinstance(v, dict)][:30]
        if not vids:
            return err("Find or select some videos first, then check them.")
        try:
            region = T.normalise_region(p.get("region"))
        except ValueError as e:
            return err(str(e))
        hints = [h for h in (p.get("advertisers") or []) if isinstance(h, str)][:6]
        prof = _json_profile(p.get("profile")) or {}
        prof["industry_label"] = STRATEGIES.get(prof.get("industry"), STRATEGIES["other"])["label"]
        try:
            res = tsvc.verify(vids, hints, region, bool(p.get("refresh")), _int_in(p.get("max_advertisers"), T.DEFAULT_MAX_ADVERTISERS), _int_in(p.get("max_details"), T.DEFAULT_MAX_DETAILS))
        except Exception:
            log.exception("transparency verification failed")
            return err("The Transparency Center check hit an unexpected problem. Existing features are unaffected; details are in the server log.", 500, "server_error")
        classified = []
        for v in vids:
            vid = str(v.get("video_id"))
            manual = {"verified": bool(v.get("manual_verified")), "source": v.get("verify_source")} if v.get("manual_verified") else None
            c = T.classify_with_verification(v, prof, manual, res["results"].get(vid))
            classified.append({"video_id": vid, **{k: c.get(k) for k in ("status", "evidence", "verification_note", "verification_method", "transparency_url", "verification")}})
        res["videos"] = classified
        res["status"] = tsvc.status()
        return jsonify(res)

    # ------------------------------------------------------------ big data lab
    @app.get("/api/lab/info")
    def lab_info():
        ok, msg = BD.spark_available()
        return jsonify({"sizes": BD.SIZES, "environment": BD.environment_info(), "spark": {"available": ok, "message": msg}})

    @app.post("/api/lab/run")
    def lab_run():
        p = _body()
        size = p.get("size")
        engines = [e for e in (p.get("engines") or []) if e in ("pandas", "mapreduce", "spark")]
        if size not in BD.SIZES: return err(f"Choose one of the supported sizes: {', '.join(f'{s:,}' for s in BD.SIZES)}.")
        gen_only = bool(p.get("generate_only"))
        if not engines and not gen_only: return err("Choose at least one processing engine.")
        seed = int(p.get("seed", 42))
        with jobs_lock:
            if any(j["state"] == "running" for j in jobs.values()):
                return err("Another lab run is still in progress. Wait for it to finish.", 409, "busy")
            jid = uuid.uuid4().hex[:8]
            jobs[jid] = {"id": jid, "state": "running", "messages": ["Queued"], "size": size, "seed": seed, "started": time.time()}
        def work():
            job = jobs[jid]
            try:
                path = app.config["DATA_DIR"] / f"SYNTHETIC_{size}_{seed}.csv"
                free = __import__("shutil").disk_usage(app.config["DATA_DIR"]).free
                if not path.exists() and free < size * 130 * 3:
                    raise RuntimeError(f"Not enough free disk space for {size:,} records (need about {size*130*3/1e9:.1f} GB).")
                if path.exists():
                    job["messages"].append(f"Reusing existing synthetic file ({path.stat().st_size/1e6:.1f} MB).")
                    job["generation"] = {"rows": size, "seed": seed, "reused": True, "bytes": path.stat().st_size, "synthetic": True}
                else:
                    job["messages"].append(f"Generating {size:,} synthetic records...")
                    job["generation"] = BD.generate_dataset(size, seed, str(path))
                if gen_only:
                    job["result"] = {"engines": [], "environment": BD.environment_info(), "generation": job["generation"], "size": size}
                    job["state"] = "done"
                    return
                out = BD.run_benchmark(str(path), engines, p.get("workers"), progress=lambda m: job["messages"].append(m))
                out["generation"] = job["generation"]; out["size"] = size
                job["result"] = out; job["state"] = "done"
                hist = inst / "benchmarks.json"
                h = json.loads(hist.read_text()) if hist.exists() else []
                for e in out["engines"]:
                    if e["status"] == "ok":
                        h.append({"when": datetime.now(timezone.utc).isoformat(), "size": size, "engine": e["engine"], "processing_seconds": e["processing_seconds"],
                                  "wall_seconds": e["wall_seconds"], "peak_memory_mb": e["peak_memory_mb"], "records": e["records"], "correct": e["correctness"]["match"]})
                hist.write_text(json.dumps(h[-400:]))
            except Exception as ex:  # surfaced to the UI, not hidden
                job["state"] = "failed"; job["error"] = str(ex)
        threading.Thread(target=work, daemon=True).start()
        return jsonify({"job_id": jid})

    @app.get("/api/lab/jobs/<jid>")
    def lab_job(jid):
        j = jobs.get(jid)
        if not j: return err("Unknown job.", 404, "not_found")
        return jsonify({k: v for k, v in j.items()})

    @app.get("/api/lab/history")
    def lab_history():
        hist = inst / "benchmarks.json"
        return jsonify({"runs": json.loads(hist.read_text()) if hist.exists() else []})

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=False)
