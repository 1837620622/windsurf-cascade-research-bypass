#!/usr/bin/env python3
"""提取最新的 outer session token + inner JWT + user-id + team-id。"""
import sys, struct, gzip, base64, json, re, time
from mitmproxy import io as mio
from mitmproxy.http import HTTPFlow

def varint(d, o):
    v = 0; s = 0
    while True:
        if o >= len(d): raise ValueError
        b = d[o]; o += 1
        v |= (b & 0x7F) << s
        if not (b & 0x80): return v, o
        s += 7

def fields(d):
    o = 0; out = []
    while o < len(d):
        try: k, o = varint(d, o)
        except: return out
        wire = k & 7; fnum = k >> 3
        if fnum == 0: return out
        if wire == 0:
            try: v, o = varint(d, o); out.append((fnum, v))
            except: return out
        elif wire == 2:
            try: ln, o = varint(d, o)
            except: return out
            if o + ln > len(d): return out
            out.append((fnum, d[o:o+ln])); o += ln
        elif wire == 1: o += 8
        elif wire == 5: o += 4
        else: return out
    return out

def b64d(s):
    s += "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s)

latest = None
with open(sys.argv[1], "rb") as f:
    for flow in mio.FlowReader(f).stream():
        if not isinstance(flow, HTTPFlow): continue
        # 找 GetUserJwt 的响应里的最新 inner JWT
        if "GetUserJwt" not in flow.request.path: continue
        if not flow.response: continue
        body = flow.response.raw_content or b""
        if flow.response.headers.get("content-encoding") == "gzip":
            try: body = gzip.decompress(body)
            except: continue
        # find eyJhbGci... 在 protobuf string 里
        m = re.search(rb"eyJhbGc[A-Za-z0-9_.-]+", body)
        if not m: continue
        jwt = m.group().decode()
        parts = jwt.split(".")
        if len(parts) != 3: continue
        try:
            payload = json.loads(b64d(parts[1]))
        except: continue
        latest = (jwt, payload, flow.request)

if not latest:
    print("没找到 GetUserJwt response")
    sys.exit(1)

jwt, payload, req = latest
print("=== 最新 inner JWT ===")
print(json.dumps(payload, indent=2, ensure_ascii=False))
print(f"\nexp = {payload['exp']} ({time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(payload['exp']))})")
print(f"now = {int(time.time())}")
print(f"剩余 {payload['exp'] - int(time.time())} 秒")

# 同时把请求里的外层 session token 拿出来
# 在 GetUserJwt 请求 body (Connect-RPC framed) 里
body = req.raw_content or b""
if len(body) >= 5:
    flag = body[0]
    ln = struct.unpack(">I", body[1:5])[0]
    inner = body[5:5+ln]
    if flag & 1:
        try: inner = gzip.decompress(inner)
        except: pass
    m2 = re.search(rb"devin-session-token\$eyJhbGc[A-Za-z0-9_.-]+", inner)
    if m2:
        outer = m2.group().decode()
        print(f"\n=== outer session token ===\n{outer}")

# 写到文件
with open("/tmp/wf_exp/inner_jwt.txt", "w") as f:
    f.write(jwt)
print("\nwritten: /tmp/wf_exp/inner_jwt.txt")
