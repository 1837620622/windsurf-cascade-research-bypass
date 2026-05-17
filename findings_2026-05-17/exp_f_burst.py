#!/usr/bin/env python3
"""
EXP-F: Burst many parallel requests to see if any race past quota/rate gate.
Test with both opus (quota+RPM blocked) and kimi (only RPM should block).
"""
import gzip, struct, requests, time, threading
from concurrent.futures import ThreadPoolExecutor

P = open('/tmp/wf_exp/fresh_payload.bin','rb').read()

def vd(d,o):
    v=0;s=0
    while True:
        b=d[o]; o+=1
        v|=(b&0x7F)<<s
        if not (b&0x80): return v,o
        s+=7

def ve(v):
    out=[]
    while True:
        b=v&0x7F; v>>=7
        if v: out.append(b|0x80)
        else: out.append(b); return bytes(out)

def fld(n,c): return ve((n<<3)|2)+ve(len(c))+c

def st(p):
    o=0
    while o<len(p):
        s=o
        try: k,o=vd(p,o)
        except: break
        w=k&7; fn=k>>3
        if fn==0: break
        if w==0:
            try: v,o=vd(p,o)
            except: break
        elif w==2:
            try: ln,o=vd(p,o)
            except: break
            o+=ln
        elif w==1: o+=8
        elif w==5: o+=4
        else: break
        yield (fn, p[s:o])

def replace_21(payload, model_bytes):
    out=b''
    for fn,v in st(payload):
        if fn==21: out += fld(21, model_bytes)
        else: out += v
    return out

URL = "https://server.self-serve.windsurf.com/exa.api_server_pb.ApiServerService/GetChatMessage"

def send_one(model_bytes, label):
    mod = replace_21(P, model_bytes)
    env = bytes([0x01]) + struct.pack(">I", len(gzip.compress(mod))) + gzip.compress(mod)
    t0=time.time()
    try:
        r = requests.post(URL, data=env, headers={
            'Content-Type':'application/connect+proto',
            'Connect-Protocol-Version':'1',
            'Connect-Content-Encoding':'gzip',
        }, timeout=30)
        elapsed=(time.time()-t0)*1000
        body=r.content
        flag=body[0] if body else 0
        ln=struct.unpack(">I",body[1:5])[0] if len(body)>=5 else 0
        inner=body[5:5+ln] if 5+ln<=len(body) else body[5:]
        if flag&1 and inner[:2]==b'\x1f\x8b':
            try: inner=gzip.decompress(inner)
            except: pass
        text=inner[:200].decode('utf-8','replace')
        if 'failed_precondition' in text and 'quota' in text:
            cat="QUOTA"
        elif 'permission_denied' in text and 'rate' in text:
            cat="RATELIMIT"
        elif 'permission_denied' in text:
            cat="PERM_OTHER"
        elif 'invalid' in text or 'unauthenticated' in text:
            cat="INVALID"
        elif len(body)>1000:
            cat="✅ LARGE"
        else:
            cat=f"SHORT({len(body)})"
        return f"[{label}] {elapsed:.0f}ms {cat} {len(body)}B"
    except Exception as e:
        return f"[{label}] ERR: {e}"

print("=== EXP-F1: 20 parallel kimi (RPM-only gate) ===")
with ThreadPoolExecutor(max_workers=20) as ex:
    futs = [ex.submit(send_one, b'kimi-k2-6', f'kimi{i}') for i in range(20)]
    for f in futs:
        print("  " + f.result())

time.sleep(2)
print("\n=== EXP-F2: 10 parallel opus (quota+RPM gate) ===")
with ThreadPoolExecutor(max_workers=10) as ex:
    futs = [ex.submit(send_one, b'claude-opus-4-7-max-fast', f'opus{i}') for i in range(10)]
    for f in futs:
        print("  " + f.result())
