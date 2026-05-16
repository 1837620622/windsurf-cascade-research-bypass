#!/usr/bin/env python3
"""Inventory all flows in a mitm dump."""
import sys, gzip
from collections import Counter, defaultdict
from mitmproxy import io as mio
from mitmproxy.http import HTTPFlow

path = sys.argv[1]
endpoints = Counter()
sizes = defaultdict(list)
samples = {}  # endpoint -> first flow

with open(path, "rb") as f:
    for flow in mio.FlowReader(f).stream():
        if not isinstance(flow, HTTPFlow): continue
        host = flow.request.pretty_host
        ep = flow.request.path.split("?")[0]
        key = f"{host}{ep}"
        endpoints[key] += 1
        if flow.response:
            sizes[key].append((len(flow.request.raw_content or b""), len(flow.response.raw_content or b"")))
        if key not in samples:
            samples[key] = flow

print(f"=== 总 flow 数: {sum(endpoints.values())} ===\n")
print(f"{'endpoint':<90}  {'cnt':>4}  {'req_avg':>8}  {'resp_avg':>8}")
print("-" * 120)
for key, cnt in endpoints.most_common():
    sz = sizes.get(key, [])
    req_avg = sum(s[0] for s in sz) // max(len(sz), 1)
    resp_avg = sum(s[1] for s in sz) // max(len(sz), 1)
    print(f"{key[:88]:<90}  {cnt:>4}  {req_avg:>8}  {resp_avg:>8}")
