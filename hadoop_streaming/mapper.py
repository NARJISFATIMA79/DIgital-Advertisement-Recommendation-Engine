#!/usr/bin/env python3
"""Hadoop Streaming mapper: reads CSV lines (no header) from stdin, emits 'industry|format<TAB>values'."""
import sys
H = ["date", "campaign_id", "ad_id", "industry", "objective", "ad_format", "audience_segment", "device", "impressions", "views", "clicks", "spend", "conversions", "revenue"]
for line in sys.stdin:
    p = line.rstrip("\n").split(",")
    if len(p) < len(H) or p[0] == "date":
        continue
    print(f"{p[3]}|{p[5]}\t1,{p[8]},{p[9]},{p[10]},{p[11]},{p[12]},{p[13]}")
