#!/usr/bin/env python3
"""Filter Unleash flows: only GET, dump raw response JSON."""
import sys, gzip, json
from mitmproxy import io as mio
from mitmproxy.http import HTTPFlow

with open(sys.argv[1], "rb") as f:
    for flow in mio.FlowReader(f).stream():
        if not isinstance(flow, HTTPFlow): continue
        if "unleash.codeium.com" not in flow.request.pretty_host: continue
        if flow.request.method != "GET": continue
        if not flow.response or flow.response.status_code != 200: continue
        body = flow.response.raw_content or b""
        if not body: continue
        # Force gzip-detect by magic bytes
        if body[:2] == b"\x1f\x8b":
            try: body = gzip.decompress(body)
            except: pass
        if flow.response.headers.get("content-encoding") == "br":
            try:
                import brotli
                body = brotli.decompress(body)
            except: pass
        try:
            data = json.loads(body)
        except Exception as e:
            print(f"# {flow.request.pretty_url}\n  decode error: {e}")
            continue
        appname = "?"
        for tok in flow.request.path.split("&"):
            if tok.startswith("appName=") or tok.startswith("?appName="):
                appname = tok.split("=", 1)[1]
        print(f"\n### {flow.request.pretty_url[:100]}  ({len(body)}B)")
        toggles = data.get("toggles", [])
        print(f"  toggles: {len(toggles)}")
        for t in toggles:
            name = t.get("name", "?")
            en = t.get("enabled", "?")
            var = t.get("variant", {})
            payload_v = None
            if isinstance(var, dict):
                p = var.get("payload")
                if isinstance(p, dict):
                    payload_v = p.get("value")
            line = f"  {'ON ' if en else 'OFF'} {name}"
            if payload_v and len(str(payload_v)) < 80:
                line += f"  → {payload_v!r}"
            print(line)
