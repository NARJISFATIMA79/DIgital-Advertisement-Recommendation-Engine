#!/usr/bin/env python3
"""Hadoop Streaming reducer: input sorted by key; sums the 7 values per key."""
import sys
cur, acc = None, [0.0] * 7
def flush():
    if cur is not None:
        r = [int(x) if i not in (4, 6) else round(x, 2) for i, x in enumerate(acc)]
        print(cur.replace("|", "\t") + "\t" + "\t".join(map(str, r)))
for line in sys.stdin:
    k, v = line.rstrip("\n").split("\t")
    if k != cur:
        flush(); cur, acc = k, [0.0] * 7
    for i, x in enumerate(v.split(",")):
        acc[i] += float(x)
flush()
