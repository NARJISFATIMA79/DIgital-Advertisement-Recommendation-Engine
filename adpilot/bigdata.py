"""Big Data Laboratory: synthetic data generator + benchmark runner.

Every engine runs the SAME task on the SAME CSV file, in its own subprocess so memory is
measured per engine. Nothing is simulated: times and memory come from real execution.
"""
from __future__ import annotations
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

SIZES = [10_000, 100_000, 1_000_000, 10_000_000]
INDUSTRIES = ["fashion", "education", "food", "beauty", "software", "real_estate", "ecommerce"]
OBJECTIVES = ["awareness", "traffic", "leads", "sales"]
FORMATS = ["skippable", "non_skippable", "bumper", "shorts", "in_feed"]
AUDIENCES = ["18-24", "25-34", "35-44", "45-54", "55+"]
DEVICES = ["mobile", "desktop", "tv", "tablet"]
COLUMNS = ["date", "campaign_id", "ad_id", "industry", "objective", "ad_format", "audience_segment", "device",
           "impressions", "views", "clicks", "spend", "conversions", "revenue",
           "completion_25", "completion_50", "completion_75", "completion_100", "is_synthetic"]
GROUP_KEYS = ["industry", "ad_format"]
SUM_FIELDS = ["impressions", "views", "clicks", "spend", "conversions", "revenue"]

# per-format baselines (illustrative synthetic parameters, NOT market benchmarks)
FMT = {"skippable": dict(vr=0.30, ctr=0.007, cpm=250, imp=9.0), "non_skippable": dict(vr=0.85, ctr=0.004, cpm=420, imp=8.6),
       "bumper": dict(vr=0.90, ctr=0.002, cpm=320, imp=9.6), "shorts": dict(vr=0.45, ctr=0.005, cpm=180, imp=9.4),
       "in_feed": dict(vr=0.12, ctr=0.010, cpm=230, imp=8.4)}
IND_AOV = {"fashion": 3500, "education": 12000, "food": 1800, "beauty": 2600, "software": 9000, "real_estate": 40000, "ecommerce": 3000}
OBJ_CVR = {"awareness": 0.004, "traffic": 0.012, "leads": 0.05, "sales": 0.03}


def generate_dataset(n: int, seed: int, out_path: str, chunk: int = 500_000) -> dict:
    """Write n synthetic records to CSV. Counts obey: completion_100<=75<=50<=25<=views<=impressions, clicks<=impressions, conversions<=clicks."""
    t0 = time.perf_counter()
    rng_attr = np.random.default_rng(seed)
    n_ads = int(min(400, max(20, n // 25)))
    ad_ind = rng_attr.integers(0, len(INDUSTRIES), n_ads)
    ad_obj = rng_attr.integers(0, len(OBJECTIVES), n_ads)
    ad_fmt = rng_attr.integers(0, len(FORMATS), n_ads)
    ad_aud = rng_attr.integers(0, len(AUDIENCES), n_ads)
    ad_q = rng_attr.lognormal(0.0, 0.25, n_ads)  # creative quality multiplier
    fmt_arr = np.array(FORMATS); ind_arr = np.array(INDUSTRIES); obj_arr = np.array(OBJECTIVES)
    aud_arr = np.array(AUDIENCES); dev_arr = np.array(DEVICES)
    base_vr = np.array([FMT[f]["vr"] for f in FORMATS]); base_ctr = np.array([FMT[f]["ctr"] for f in FORMATS])
    base_cpm = np.array([FMT[f]["cpm"] for f in FORMATS]); base_imp = np.array([FMT[f]["imp"] for f in FORMATS])
    aov = np.array([IND_AOV[i] for i in INDUSTRIES]); cvr = np.array([OBJ_CVR[o] for o in OBJECTIVES])
    day0 = np.datetime64("2025-01-01")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with open(out_path, "w", newline="") as fh:
        first = True
        chunk_no = 0
        while written < n:
            m = min(chunk, n - written)
            rng = np.random.default_rng([seed, chunk_no])
            a = rng.integers(0, n_ads, m)
            fi, ii, oi = ad_fmt[a], ad_ind[a], ad_obj[a]
            q = ad_q[a]
            impr = np.clip(rng.lognormal(base_imp[fi], 0.8), 50, 5_000_000).astype(np.int64)
            vr = np.clip(base_vr[fi] * np.exp(rng.normal(0, 0.15, m)), 0.01, 0.99)
            views = rng.binomial(impr, vr)
            ctr = np.clip(base_ctr[fi] * q * np.exp(rng.normal(0, 0.2, m)), 1e-5, 0.5)
            clicks = rng.binomial(impr, ctr)
            cpm = base_cpm[fi] * np.exp(rng.normal(0, 0.2, m))
            spend = np.round(impr / 1000.0 * cpm, 2)
            conv = rng.binomial(clicks, np.clip(cvr[oi] * q * np.exp(rng.normal(0, 0.25, m)), 0, 0.9))
            revenue = np.round(conv * aov[ii] * np.exp(rng.normal(0, 0.2, m)), 2)
            c25 = rng.binomial(views, 0.80); c50 = rng.binomial(c25, 0.75); c75 = rng.binomial(c50, 0.75); c100 = rng.binomial(c75, 0.70)
            days = rng.integers(0, 365, m)
            dates = (day0 + days.astype("timedelta64[D]")).astype(str)
            import pandas as pd
            df = pd.DataFrame({
                "date": dates, "campaign_id": ("C" + (a // 5).astype(str)), "ad_id": ("A" + a.astype(str)),
                "industry": ind_arr[ii], "objective": obj_arr[oi], "ad_format": fmt_arr[fi], "audience_segment": aud_arr[ad_aud[a]],
                "device": dev_arr[rng.choice(4, m, p=[0.62, 0.18, 0.15, 0.05])],
                "impressions": impr, "views": views, "clicks": clicks, "spend": spend, "conversions": conv, "revenue": revenue,
                "completion_25": c25, "completion_50": c50, "completion_75": c75, "completion_100": c100, "is_synthetic": 1})
            df.to_csv(fh, header=first, index=False)
            first = False; written += m; chunk_no += 1
    return {"rows": n, "seed": seed, "path": out_path, "bytes": os.path.getsize(out_path), "seconds": round(time.perf_counter() - t0, 2), "synthetic": True}


# ------------------------------------------------------------------ environment & availability
def java_version():
    if not shutil.which("java"):
        return None
    try:
        r = subprocess.run(["java", "-version"], capture_output=True, text=True, timeout=10)
        return (r.stderr or r.stdout).splitlines()[0]
    except Exception:
        return None


def environment_info() -> dict:
    import pandas
    info = {"python": platform.python_version(), "platform": platform.platform(), "cpu_count": os.cpu_count(), "numpy": np.__version__, "pandas": pandas.__version__}
    try:
        import psutil
        info["ram_gb"] = round(psutil.virtual_memory().total / 1e9, 1)
    except Exception:
        info["ram_gb"] = None
    try:
        import pyspark
        info["pyspark"] = pyspark.__version__
    except Exception:
        info["pyspark"] = None
    info["java"] = java_version()
    return info


def spark_available():
    try:
        import pyspark  # noqa: F401
    except Exception:
        return False, "PySpark is not installed. Run: pip install pyspark"
    if not java_version():
        return False, "Java was not found. Install a JDK (e.g. 17 or 21) and make sure 'java -version' works, then retry."
    return True, "ok"


# ------------------------------------------------------------------ benchmark runner
def _tree_rss(proc):
    total = 0
    try:
        procs = [proc] + proc.children(recursive=True)
    except Exception:
        return 0
    for p in procs:
        try:
            total += p.memory_info().rss
        except Exception:
            pass
    return total


def run_engine(engine: str, csv_path: str, workers: int | None = None, timeout: int = 7200) -> dict:
    """Run one engine in a subprocess; sample its process-tree RSS every 50 ms."""
    import psutil
    if engine == "spark":
        ok, msg = spark_available()
        if not ok:
            return {"engine": engine, "status": "unavailable", "message": msg}
    out = tempfile.NamedTemporaryFile(suffix=".json", delete=False); out.close()
    cmd = [sys.executable, "-m", "adpilot.bigdata_worker", engine, csv_path, out.name] + ([str(workers)] if workers else [])
    root = str(Path(__file__).resolve().parent.parent)
    t0 = time.perf_counter()
    p = subprocess.Popen(cmd, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    ps = psutil.Process(p.pid)
    peak, stop = [0], threading.Event()
    def sample():
        while not stop.is_set():
            peak[0] = max(peak[0], _tree_rss(ps)); time.sleep(0.05)
    th = threading.Thread(target=sample, daemon=True); th.start()
    try:
        _o, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill(); stop.set()
        return {"engine": engine, "status": "failed", "message": f"Timed out after {timeout}s."}
    stop.set(); th.join(timeout=1)
    wall = time.perf_counter() - t0
    try:
        data = json.loads(Path(out.name).read_text() or "{}")
    except Exception:
        data = {}
    finally:
        try: os.unlink(out.name)
        except OSError: pass
    if p.returncode != 0 or not data:
        tail = "\n".join((err or "").strip().splitlines()[-6:])
        return {"engine": engine, "status": "failed", "message": f"The {engine} run failed. {tail}"}
    data.update({"engine": engine, "status": "ok", "wall_seconds": round(wall, 3), "peak_memory_mb": round(peak[0] / 1e6, 1),
                 "memory_method": "Peak resident memory (RSS) of the engine's process tree, sampled every 50 ms. Python startup included; JVM included for Spark. Summing RSS across processes can double-count pages shared between a parent and its forked workers, so treat it as an approximate upper bound."})
    return data


def compare_results(ref: list, other: list, rel_tol=1e-9) -> dict:
    """Same groups, exact integer sums, float sums within tolerance."""
    if len(ref) != len(other):
        return {"match": False, "detail": f"Different group counts: {len(ref)} vs {len(other)}"}
    for a, b in zip(ref, other):
        if (a["industry"], a["ad_format"]) != (b["industry"], b["ad_format"]):
            return {"match": False, "detail": f"Different group keys at {a['industry']}/{a['ad_format']}"}
        for f in SUM_FIELDS + ["rows"]:
            x, y = a[f], b[f]
            if f in ("spend", "revenue"):
                if abs(x - y) > rel_tol * max(abs(x), abs(y), 1.0):
                    return {"match": False, "detail": f"{f} differs for {a['industry']}/{a['ad_format']}: {x} vs {y}"}
            elif int(x) != int(y):
                return {"match": False, "detail": f"{f} differs for {a['industry']}/{a['ad_format']}: {x} vs {y}"}
    return {"match": True, "detail": "All groups and totals agree (integers exact, money within 1e-9 relative)."}


def run_benchmark(csv_path: str, engines: list, workers=None, progress=None) -> dict:
    results, ref = [], None
    for e in engines:
        if progress: progress(f"Running {e}...")
        r = run_engine(e, csv_path, workers)
        if r["status"] == "ok":
            if ref is None:
                ref = r; r["correctness"] = {"match": True, "detail": "Reference result for this comparison."}
            else:
                r["correctness"] = compare_results(ref["result"], r["result"])
        results.append(r)
    return {"engines": results, "environment": environment_info()}
