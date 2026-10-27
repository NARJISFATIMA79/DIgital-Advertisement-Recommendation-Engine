"""Subprocess entry point: python -m adpilot.bigdata_worker <pandas|mapreduce|spark> <csv> <out.json> [workers]"""
import json
import sys

from . import bigdata_engines as E


def main():
    engine, path, out = sys.argv[1], sys.argv[2], sys.argv[3]
    workers = int(sys.argv[4]) if len(sys.argv) > 4 else None
    if engine == "pandas":
        res = E.run_pandas(path)
    elif engine == "mapreduce":
        res = E.run_mapreduce(path, workers)
    elif engine == "spark":
        res = E.run_spark(path)
    else:
        raise SystemExit(f"Unknown engine {engine}")
    with open(out, "w") as f:
        json.dump(res, f)


if __name__ == "__main__":
    main()
