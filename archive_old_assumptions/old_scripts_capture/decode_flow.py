#!/usr/bin/env python3
"""Decode Connect-RPC flows: extract proto bodies and dump fields recursively."""
import sys, gzip, struct, json, re
from mitmproxy import io as mio
from mitmproxy.http import HTTPFlow

def read_varint(data, off):
    val = 0; shift = 0
    while True:
        if off >= len(data): raise EOFError
        b = data[off]; off += 1
        val |= (b & 0x7F) << shift
        if not (b & 0x80): return val, off
        shift += 7
        if shift > 70: raise ValueError

def try_decode(data):
    fields = []; off = 0
    while off < len(data):
        try: key, off = read_varint(data, off)
        except: return None
        wire = key & 7; fnum = key >> 3
        if fnum == 0: return None
        if wire == 0:
            try: v, off = read_varint(data, off)
            except: return None
            fields.append((fnum, wire, v))
        elif wire == 1:
            if off + 8 > len(data): return None
            fields.append((fnum, wire, data[off:off+8])); off += 8
        elif wire == 2:
            try: ln, off = read_varint(data, off)
            except: return None
            if off + ln > len(data): return None
            fields.append((fnum, wire, data[off:off+ln])); off += ln
        elif wire == 5:
            if off + 4 > len(data): return None
            fields.append((fnum, wire, data[off:off+4])); off += 4
        else: return None
    return fields

def looks_text(b):
    if not b or len(b) < 1: return False
    try: s = b.decode("utf-8")
    except: return False
    return sum(1 for c in s if c.isprintable() or c in "\n\r\t") / len(s) > 0.85

def fmt(v, indent="", depth=0, max_depth=14):
    if isinstance(v, int): return str(v)
    if isinstance(v, bytes):
        if depth < max_depth:
            sub = try_decode(v)
            if sub is not None and len(sub) > 0:
                lines = ["{"]
                for f, w, sv in sub:
                    lines.append(f"{indent}  [{f}] = {fmt(sv, indent+'  ', depth+1, max_depth)}")
                lines.append(f"{indent}}}")
                return "\n".join(lines)
        if looks_text(v):
            s = v.decode("utf-8")
            if len(s) > 300: return f"<str {len(s)}B> {json.dumps(s[:300])}…"
            return json.dumps(s)
        return f"<bytes {len(v)}B> {v[:48].hex()}{'…' if len(v)>48 else ''}"
    return repr(v)

def strip_connect_envelope(body):
    """Connect-RPC framing: 1B flags + 4B big-endian len + payload."""
    if len(body) < 5: return body, None
    flags = body[0]
    ln = struct.unpack(">I", body[1:5])[0]
    payload = body[5:5+ln]
    if flags & 0x01:
        # gzip compressed
        try: payload = gzip.decompress(payload)
        except: pass
    return payload, flags

def decode_flow(flow):
    print(f"\n{'='*100}\n{flow.request.method} {flow.request.pretty_url}\n{'='*100}")
    for label, msg in [("REQUEST", flow.request), ("RESPONSE", flow.response)]:
        if msg is None: continue
        body = msg.raw_content or b""
        if not body: continue
        ct = msg.headers.get("content-type", "")
        ce = msg.headers.get("content-encoding", "")
        print(f"\n--- {label}  Content-Type: {ct}  Encoding: {ce}  Size: {len(body)}B ---")

        payload = body
        if ce == "gzip":
            try: payload = gzip.decompress(payload)
            except: pass
        # Try Connect-RPC envelope first
        if "application/proto" in ct or "application/connect" in ct or "application/grpc" in ct:
            try:
                # Some flows have envelope, some don't
                stripped, flags = strip_connect_envelope(payload)
                if flags is not None:
                    decoded = try_decode(stripped)
                    if decoded:
                        for f, w, v in decoded:
                            print(f"[{f}] = {fmt(v, '', 0)}")
                        continue
                decoded = try_decode(payload)
                if decoded:
                    for f, w, v in decoded:
                        print(f"[{f}] = {fmt(v, '', 0)}")
                    continue
            except Exception as e:
                print(f"  (decode error: {e})")
        # Fallback: text or hex
        if looks_text(payload):
            try: print(payload.decode("utf-8", errors="replace")[:1500])
            except: pass
        else:
            print(payload[:200].hex())

needle = sys.argv[2] if len(sys.argv) > 2 else None
limit = int(sys.argv[3]) if len(sys.argv) > 3 else 999
seen = 0
with open(sys.argv[1], "rb") as f:
    for flow in mio.FlowReader(f).stream():
        if not isinstance(flow, HTTPFlow): continue
        if needle and needle not in flow.request.pretty_url: continue
        decode_flow(flow)
        seen += 1
        if seen >= limit: break
