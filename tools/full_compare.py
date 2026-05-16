#!/usr/bin/env python3
"""完整 dump 一个成功 + 一个失败请求, 看顶层全部字段."""
import sys, struct, gzip
from mitmproxy import io as mio
from mitmproxy.http import HTTPFlow

def varint(d, o):
    v = 0; s = 0
    while True:
        b = d[o]; o += 1
        v |= (b & 0x7F) << s
        if not (b & 0x80): return v, o
        s += 7

def list_top(d):
    o = 0; out = []
    while o < len(d):
        try: k, o2 = varint(d, o)
        except: return out
        wire = k & 7; fnum = k >> 3
        if fnum == 0: return out
        o = o2
        if wire == 0:
            try: v, o = varint(d, o); out.append((fnum, "v", v))
            except: return out
        elif wire == 2:
            try: ln, o = varint(d, o)
            except: return out
            out.append((fnum, "ld", d[o:o+ln])); o += ln
        elif wire == 1: out.append((fnum, "f64", d[o:o+8])); o += 8
        elif wire == 5: out.append((fnum, "f32", d[o:o+4])); o += 4
        else: return out
    return out

def unwrap(data):
    flag = data[0]; ln = struct.unpack(">I", data[1:5])[0]
    payload = data[5:5+ln]
    if flag & 1:
        try: payload = gzip.decompress(payload)
        except: pass
    return payload

def dump_full(payload, label):
    print(f"\n{'='*80}\n{label}  ({len(payload)}B)\n{'='*80}")
    fields = list_top(payload)
    counts = {}
    for fnum, wire, val in fields:
        c = counts.get(fnum, 0); counts[fnum] = c + 1
        if wire == "v":
            print(f"  [{fnum}] varint = {val}")
        elif wire in ("f32", "f64"):
            print(f"  [{fnum}] {wire}: {val.hex()}")
        else:
            try:
                s = val.decode("utf-8")
                preview = s[:80] if all(32 <= ord(c) < 127 or c in "\n\r\t" for c in s[:80]) else val[:30].hex()
            except:
                preview = val[:30].hex()
            print(f"  [{fnum}] ld({len(val)}B): {preview}")

successes = []; failures = []
with open(sys.argv[1], "rb") as f:
    for flow in mio.FlowReader(f).stream():
        if not isinstance(flow, HTTPFlow): continue
        if "GetChatMessage" not in flow.request.path: continue
        if not flow.response: continue
        sz = len(flow.response.raw_content or b"")
        if sz > 500: successes.append(flow)
        elif 200 < sz < 300: failures.append(flow)

# 取最近一对
suc = successes[-1]
fail = failures[-1]

dump_full(unwrap(suc.request.raw_content), f"SUCCESS  req={len(suc.request.raw_content)}B  resp={len(suc.response.raw_content)}B")
dump_full(unwrap(fail.request.raw_content), f"FAILURE  req={len(fail.request.raw_content)}B  resp={len(fail.response.raw_content)}B")

# 写两个 raw 出来
with open("/tmp/wf_exp/suc_raw.bin", "wb") as f: f.write(suc.request.raw_content)
with open("/tmp/wf_exp/suc_pb.bin", "wb") as f: f.write(unwrap(suc.request.raw_content))
with open("/tmp/wf_exp/fail_raw.bin", "wb") as f: f.write(fail.request.raw_content)
with open("/tmp/wf_exp/fail_pb.bin", "wb") as f: f.write(unwrap(fail.request.raw_content))
print("\nfiles written")
