#!/usr/bin/env python3
"""
EXP-I: Minimal valid request — does any model_uid pass with minimal fields?
Maybe the validation handlers differ when fields are sparse.
"""
import gzip, struct, requests, time

# Build minimal valid envelope: just metadata + 1 chat msg + chat_model
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
def fld(n,c): return ve((n<<3)|2) + ve(len(c)) + c
def fv(n,v): return ve((n<<3)|0) + ve(v)

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

# Get metadata bytes from fresh capture
P = open('/tmp/wf_exp/fresh_payload.bin','rb').read()
META_FIELD = None
for fn,v in st(P):
    if fn == 1:
        META_FIELD = v  # tag + len + content
        break
print(f"meta field: {len(META_FIELD)}B")

URL = "https://server.self-serve.windsurf.com/exa.api_server_pb.ApiServerService/GetChatMessage"
HEADERS = {
    'Content-Type': 'application/connect+proto',
    'Connect-Protocol-Version': '1',
    'Connect-Content-Encoding': 'gzip',
    'User-Agent': 'connect-go/1.18.1 (go1.26.1)',
}

def send(label, payload):
    env = bytes([0x01]) + struct.pack(">I", len(gzip.compress(payload))) + gzip.compress(payload)
    t0=time.time()
    try:
        r = requests.post(URL, data=env, headers=HEADERS, timeout=20)
        elapsed=(time.time()-t0)*1000
        body=r.content
        flag=body[0]
        ln=struct.unpack(">I",body[1:5])[0]
        inner=body[5:5+ln] if 5+ln<=len(body) else body[5:]
        if flag&1 and inner[:2]==b'\x1f\x8b':
            try: inner=gzip.decompress(inner)
            except: pass
        text=inner[:300].decode('utf-8','replace')
        print(f"  [{label:35s}] HTTP{r.status_code} {len(body)}B {elapsed:.0f}ms")
        print(f"     → {text[:200]}")
    except Exception as e:
        print(f"  [{label:35s}] ERR: {e}")

# Tests
chat_msg = fv(2, 1) + fld(3, b"hi")  # source=1 USER, prompt='hi'
sys_prompt = b"You are helpful."

print("\n=== EXP-I1: Minimal request, model=opus ===")
body = META_FIELD + fld(2, sys_prompt) + fld(3, chat_msg) + fld(21, b'claude-opus-4-7-max-fast')
send("min_opus", body)

print("\n=== EXP-I2: Minimal request, model=kimi ===")
body = META_FIELD + fld(2, sys_prompt) + fld(3, chat_msg) + fld(21, b'kimi-k2-6')
send("min_kimi", body)

print("\n=== EXP-I3: model field repeated [21] kimi+opus ===")
body = META_FIELD + fld(2, sys_prompt) + fld(3, chat_msg) + fld(21, b'kimi-k2-6') + fld(21, b'claude-opus-4-7-max-fast')
send("dup_kimi_opus", body)

print("\n=== EXP-I4: model field repeated [21] opus+kimi ===")
body = META_FIELD + fld(2, sys_prompt) + fld(3, chat_msg) + fld(21, b'claude-opus-4-7-max-fast') + fld(21, b'kimi-k2-6')
send("dup_opus_kimi", body)

print("\n=== EXP-I5: protobuf packed encoding for [21] (wrong type) ===")
# wire type 0 instead of 2 — varint instead of string
body = META_FIELD + fld(2, sys_prompt) + fld(3, chat_msg) + fv(21, 999)
send("wrong_wire", body)
