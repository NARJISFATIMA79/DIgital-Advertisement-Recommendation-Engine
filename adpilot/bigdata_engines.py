"""The same analytical task in three engines.

Task: GROUP BY (industry, ad_format); SUM impressions, views, clicks, spend, conversions, revenue; COUNT rows.
Every engine returns rows with the same keys, sorted by (industry, ad_format).
"""
from __future__ import annotations
import os
import time
import zlib
from multiprocessing import Pool

from .metrics import cpa, cpc, ctr, roas

HEADER = ["date", "campaign_id", "ad_id", "industry", "objective", "ad_format", "audience_segment", "device",
          "impressions", "views", "clicks", "spend", "conversions", "revenue",
          "completion_25", "completion_50", "completion_75", "completion_100", "is_synthetic"]
IDX = {c: i for i, c in enumerate(HEADER)}
NEEDED = ["industry", "ad_format", "impressions", "views", "clicks", "spend", "conversions", "revenue"]


def _finish(groups: dict) -> list:
    out = []
    for (ind, fmt), v in sorted(groups.items()):
        rows, impr, views, clicks, spend, conv, rev = v
        out.append({"industry": ind, "ad_format": fmt, "rows": int(rows), "impressions": int(impr), "views": int(views), "clicks": int(clicks),
                    "spend": round(float(spend), 2), "conversions": int(conv), "revenue": round(float(rev), 2),
                    "ctr": ctr(clicks, impr), "cpc": cpc(spend, clicks), "cpa": cpa(spend, conv), "roas": roas(rev, spend)})
    return out


# ------------------------------------------------------------------ Pandas
def run_pandas(path: str) -> dict:
    import pandas as pd
    t0 = time.perf_counter()
    dtypes = {"industry": "category", "ad_format": "category", "impressions": "int64", "views": "int64", "clicks": "int64",
              "spend": "float64", "conversions": "int64", "revenue": "float64"}
    df = pd.read_csv(path, usecols=NEEDED, dtype=dtypes)
    t1 = time.perf_counter()
    g = df.groupby(["industry", "ad_format"], observed=True).agg(rows=("clicks", "size"), impressions=("impressions", "sum"), views=("views", "sum"),
                                                                  clicks=("clicks", "sum"), spend=("spend", "sum"), conversions=("conversions", "sum"), revenue=("revenue", "sum"))
    t2 = time.perf_counter()
    groups = {k: [r.rows, r.impressions, r.views, r.clicks, r.spend, r.conversions, r.revenue] for k, r in zip(g.index, g.itertuples())}
    return {"result": _finish(groups), "records": int(len(df)), "timing": {"load_seconds": round(t1 - t0, 3), "compute_seconds": round(t2 - t1, 3)},
            "processing_seconds": round(t2 - t0, 3), "implementation": "pandas.read_csv + DataFrame.groupby().agg() in a single process."}


# ------------------------------------------------------------------ MapReduce (local, multiprocessing)
def _splits(path, parts):
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        f.readline()
        start = f.tell()
    step = max((size - start) // parts, 1)
    bounds = [start + i * step for i in range(parts)] + [size]
    out = []
    with open(path, "rb") as f:
        aligned = [start]
        for b in bounds[1:-1]:
            f.seek(b); f.readline(); aligned.append(f.tell())
    aligned.append(size)
    for i in range(len(aligned) - 1):
        if aligned[i] < aligned[i + 1]:
            out.append((path, aligned[i], aligned[i + 1]))
    return out


def map_task(args):
    """MAP: parse each line and emit (key, value); COMBINE locally; PARTITION by hash(key) % R."""
    path, start, end, R = args
    ii, fi = IDX["industry"], IDX["ad_format"]
    cols = [IDX[c] for c in ("impressions", "views", "clicks", "spend", "conversions", "revenue")]
    combined = {}
    with open(path, "rb") as f:
        f.seek(start)
        pos = start
        for line in f:
            pos += len(line)
            if pos - len(line) >= end:
                break
            p = line.decode().rstrip("\n").split(",")
            key = (p[ii], p[fi])                                  # emit key
            val = (1, int(p[cols[0]]), int(p[cols[1]]), int(p[cols[2]]), float(p[cols[3]]), int(p[cols[4]]), float(p[cols[5]]))
            acc = combined.get(key)                               # combiner
            if acc is None:
                combined[key] = list(val)
            else:
                for j in range(7):
                    acc[j] += val[j]
    parts = [dict() for _ in range(R)]
    for k, v in combined.items():                                 # shuffle: partition by key hash
        parts[zlib.crc32((k[0] + '|' + k[1]).encode()) % R][k] = v  # deterministic hash (Python's hash() differs per process)
    return parts


def reduce_task(partials):
    """REDUCE: sum all partial values for each key in this partition."""
    out = {}
    for d in partials:
        for k, v in d.items():
            acc = out.get(k)
            if acc is None:
                out[k] = list(v)
            else:
                for j in range(7):
                    acc[j] += v[j]
    return out


def run_mapreduce(path: str, workers: int | None = None) -> dict:
    workers = workers or os.cpu_count() or 1
    R = max(workers, 2)
    t0 = time.perf_counter()
    splits = [(p, s, e, R) for (p, s, e) in _splits(path, max(workers * 4, 4))]
    with Pool(workers) as pool:
        mapped = pool.map(map_task, splits)
        t1 = time.perf_counter()
        per_reducer = [[m[r] for m in mapped] for r in range(R)]
        reduced = pool.map(reduce_task, per_reducer)
    t2 = time.perf_counter()
    groups = {}
    for d in reduced:
        groups.update(d)
    records = int(sum(v[0] for v in groups.values()))
    return {"result": _finish(groups), "records": records, "timing": {"map_seconds": round(t1 - t0, 3), "shuffle_reduce_seconds": round(t2 - t1, 3)},
            "processing_seconds": round(t2 - t0, 3), "workers": workers, "splits": len(splits),
            "implementation": f"Local MapReduce with Python multiprocessing ({workers} workers, {len(splits)} input splits, {R} reducers): map + combiner + hash partition (crc32) + reduce. Not Hadoop."}


# ------------------------------------------------------------------ Spark
def run_spark(path: str) -> dict:
    from pyspark.sql import SparkSession, functions as F, types as T
    t0 = time.perf_counter()
    spark = (SparkSession.builder.master("local[*]").appName("AdPilotLab").config("spark.ui.enabled", "false")
             .config("spark.sql.shuffle.partitions", "8").config("spark.driver.memory", os.environ.get("ADPILOT_SPARK_DRIVER_MEMORY", "2g")).getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    t1 = time.perf_counter()
    schema = T.StructType([T.StructField(c, T.StringType() if c in ("date", "campaign_id", "ad_id", "industry", "objective", "ad_format", "audience_segment", "device")
                                         else (T.DoubleType() if c in ("spend", "revenue") else T.LongType()), True) for c in HEADER])
    df = spark.read.csv(path, header=True, schema=schema)
    g = df.groupBy("industry", "ad_format").agg(F.count(F.lit(1)).alias("rows"), F.sum("impressions").alias("impressions"), F.sum("views").alias("views"),
                                                  F.sum("clicks").alias("clicks"), F.sum("spend").alias("spend"), F.sum("conversions").alias("conversions"), F.sum("revenue").alias("revenue"))
    rows = g.collect()
    t2 = time.perf_counter()
    groups = {(r["industry"], r["ad_format"]): [r["rows"], r["impressions"], r["views"], r["clicks"], r["spend"], r["conversions"], r["revenue"]] for r in rows}
    version = spark.version
    spark.stop()
    return {"result": _finish(groups), "records": int(sum(v[0] for v in groups.values())),
            "timing": {"session_startup_seconds": round(t1 - t0, 3), "read_and_compute_seconds": round(t2 - t1, 3)},
            "processing_seconds": round(t2 - t1, 3), "startup_seconds": round(t1 - t0, 3), "spark_version": version,
            "implementation": f"PySpark {version}, local[*] mode on this machine (not a cluster): read.csv with explicit schema + groupBy().agg(). processing_seconds excludes session startup, which is reported separately."}
