#!/usr/bin/env python3
"""Dump specific flows by URL substring."""
import sys
from mitmproxy import io as mio
from mitmproxy.http import HTTPFlow

needle = sys.argv[2]
with open(sys.argv[1], "rb") as f:
    for flow in mio.FlowReader(f).stream():
        if not isinstance(flow, HTTPFlow): continue
        url = flow.request.pretty_url
        if needle in url:
            print(f"\n{'='*80}\n{flow.request.method} {url}\n{'='*80}")
            print("--- Request headers ---")
            for k, v in flow.request.headers.items():
                if k.lower() in ("authorization", "cookie", "x-api-key"):
                    v = v[:40] + "…<redacted>"
                print(f"  {k}: {v}")
            body = flow.request.raw_content or b""
            if body:
                print(f"--- Request body ({len(body)}B) ---")
                if flow.request.headers.get("content-type", "").startswith(("application/json", "text/")):
                    try: print(body.decode("utf-8", errors="replace")[:2000])
                    except: print(body[:200].hex())
                else:
                    print(body[:200].hex(), "..." if len(body) > 200 else "")
            if flow.response:
                print(f"--- Response {flow.response.status_code} ({len(flow.response.raw_content or b'')}B) ---")
                rb = flow.response.raw_content or b""
                ct = flow.response.headers.get("content-type", "")
                if ct.startswith(("application/json", "text/")):
                    try: print(rb.decode("utf-8", errors="replace")[:2000])
                    except: print(rb[:200].hex())
                else:
                    print(rb[:200].hex())
