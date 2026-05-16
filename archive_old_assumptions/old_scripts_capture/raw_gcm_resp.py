#!/usr/bin/env python3
"""Read GetChatMessage responses straight out of mitm file, in their wire form."""
import sys, struct, gzip, zlib, json
from mitmproxy import io as mio
from mitmproxy.http import HTTPFlow

def try_all_decompress(payload):
    out = []
    for label, fn in [
        ("gzip", lambda x: gzip.decompress(x)),
        ("zlib15", lambda x: zlib.decompress(x, 15)),
        ("raw-15", lambda x: zlib.decompress(x, -15)),
        ("gzip31", lambda x: zlib.decompress(x, 31)),
    ]:
        try: out.append((label, fn(payload)))
        except Exception as e: out.append((label, f"ERR: {e}"))
    return out

with open(sys.argv[1], "rb") as f:
    n = 0
    for flow in mio.FlowReader(f).stream():
        if not isinstance(flow, HTTPFlow): continue
        if "ApiServerService/GetChatMessage" not in flow.request.path: continue
        if not flow.response: continue
        body = flow.response.raw_content or b""
        print(f"\n=== flow #{n+1}  status={flow.response.status_code}  ct={flow.response.headers.get('content-type')}  encoding={flow.response.headers.get('content-encoding')} ===")
        print(f"raw size: {len(body)}")
        print(f"first 32 hex: {body[:32].hex()}")
        # If wrapped in Connect envelope: 1B flag + 4B len + payload
        if len(body) >= 5:
            flag = body[0]
            ln = struct.unpack(">I", body[1:5])[0]
            print(f"envelope: flag=0x{flag:02x}  len={ln}  body[5:]_size={len(body)-5}")
            payload = body[5:5+ln]
            print(f"payload first 16: {payload[:16].hex()}")
            print(f"payload last 8:   {payload[-8:].hex()}")
            # Try to decompress
            for label, result in try_all_decompress(payload):
                if isinstance(result, bytes):
                    print(f"  {label}: OK ({len(result)}B)  {result[:300]}")
                else:
                    print(f"  {label}: {result[:80]}")
            # Maybe payload is plain JSON
            try:
                j = json.loads(payload)
                print(f"  raw JSON: {json.dumps(j, ensure_ascii=False)[:400]}")
            except: pass
            try:
                s = payload.decode("utf-8")
                if s.startswith("{") or s[0:5].isprintable():
                    print(f"  utf-8: {s[:300]}")
            except: pass
        n += 1
