#!/usr/bin/env python3
"""Inspect raw response bytes + headers for unleash flows."""
import sys, gzip
from mitmproxy import io as mio
from mitmproxy.http import HTTPFlow

with open(sys.argv[1], "rb") as f:
    seen = 0
    for flow in mio.FlowReader(f).stream():
        if not isinstance(flow, HTTPFlow): continue
        if "unleash.codeium.com" not in flow.request.pretty_host: continue
        if flow.request.method != "GET": continue
        if not flow.response or flow.response.status_code != 200: continue
        body = flow.response.raw_content or b""
        if not body: continue
        print(f"=== {flow.request.path[:80]}... ===")
        print(f"  status: {flow.response.status_code}")
        print(f"  raw bytes: {len(body)}")
        print(f"  first 16 hex: {body[:16].hex()}")
        for k, v in flow.response.headers.items():
            kl = k.lower()
            if kl in ("content-encoding", "content-type", "content-length", "vary", "cf-cache-status"):
                print(f"  {k}: {v}")
        # Try common decompressions
        for name, fn in [("gzip", gzip.decompress)]:
            try:
                d = fn(body)
                print(f"  {name} decompress OK, {len(d)}B, first 80: {d[:80]}")
            except Exception as e:
                pass
        try:
            import brotli
            d = brotli.decompress(body)
            print(f"  brotli decompress OK, {len(d)}B, first 80: {d[:80]}")
        except ImportError:
            print("  (brotli module not installed)")
        except Exception as e:
            pass
        try:
            import zstandard as zstd
            d = zstd.decompress(body)
            print(f"  zstd decompress OK, {len(d)}B, first 80: {d[:80]}")
        except ImportError:
            pass
        except Exception:
            pass
        print()
        seen += 1
        if seen >= 3: break
