#!/usr/bin/env python3
"""Test all known models with fresh JWT to see current state on 0 quota Pro."""
import gzip, struct, requests, time

P = open('/tmp/wf_exp/fresh_payload.bin','rb').read()

def varint_dec(d,o):
    v=0;s=0
    while True:
        b=d[o]; o+=1
        v |= (b&0x7F)<<s
        if not (b&0x80): return v,o
        s+=7

def varint_enc(v):
    out=[]
    while True:
        b=v&0x7F; v>>=7
        if v: out.append(b|0x80)
        else: out.append(b); return bytes(out)

def field_ld(num,c): return varint_enc((num<<3)|2)+varint_enc(len(c))+c

def split_top(payload):
    o=0
    while o<len(payload):
        start=o
        try: k,o=varint_dec(payload,o)
        except: break
        wire=k&7; fnum=k>>3
        if fnum==0: break
        if wire==0:
            try: v,o=varint_dec(payload,o)
            except: break
        elif wire==1: o+=8
        elif wire==2:
            try: ln,o=varint_dec(payload,o)
            except: break
            o+=ln
        elif wire==5: o+=4
        else: break
        yield (fnum, payload[start:o])

def replace_21(payload, new_model):
    out=b''
    for fn,v in split_top(payload):
        if fn==21:
            out += field_ld(21, new_model)
        else:
            out += v
    return out

URL = "https://server.self-serve.windsurf.com/exa.api_server_pb.ApiServerService/GetChatMessage"
HEADERS = {
    'Content-Type': 'application/connect+proto',
    'Connect-Protocol-Version': '1',
    'Connect-Content-Encoding': 'gzip',
    'User-Agent': 'connect-go/1.18.1 (go1.26.1)',
}

MODELS = [
    'claude-opus-4-7-max-fast',  # known: rate-limited now
    'claude-opus-4-7-max',
    'claude-opus-4-7-low',
    'claude-opus-4-7',
    'claude-opus-4-6',
    'claude-sonnet-4-6',
    'claude-sonnet-4-6-thinking',
    'claude-haiku-4-5',
    'gpt-5-5-medium',
    'gpt-5-4-mini-low',
    'gpt-5-3-codex',
    'kimi-k2-6',
    'swe-1-6',
    'swe-1-6-fast',
    'swe-check',
    'swe-1p5',
    'MODEL_GOOGLE_GEMINI_2_5_FLASH',
    'MODEL_CLAUDE_4_OPUS_BYOK',
    'gemini-3-1-pro-low',
    'gemini-3-1-pro-high',
    'adaptive',
    'deepseek-v4',
]

for model in MODELS:
    mod = replace_21(P, model.encode())
    env = bytes([0x01]) + struct.pack(">I", len(gzip.compress(mod))) + gzip.compress(mod)
    t0 = time.time()
    try:
        r = requests.post(URL, data=env, headers=HEADERS, timeout=60)
        elapsed = (time.time()-t0)*1000
        body = r.content
        flag = body[0]
        ln = struct.unpack(">I",body[1:5])[0]
        inner = body[5:5+ln]
        if flag & 1 and inner[:2]==b'\x1f\x8b':
            inner = gzip.decompress(inner)
        text = inner[:300].decode('utf-8','replace')
        if 'failed_precondition' in text and 'quota' in text:
            cat = "❌ QUOTA"
        elif 'permission_denied' in text and 'rate limit' in text:
            cat = "🔶 RATELIMIT"
        elif 'permission_denied' in text:
            cat = "🚫 PERM"
        elif 'invalid_argument' in text:
            cat = "🚫 INVALID"
        elif 'unauthenticated' in text:
            cat = "🚫 AUTH"
        elif flag & 0x02:
            cat = f"❓EOS"
        elif len(body) > 1000:
            cat = "✅ LARGE"
        else:
            cat = f"❓SMALL"
        print(f"  {model:38s} → {cat:14s} {len(body):>5}B {elapsed:>5.0f}ms  flag={flag:#x}")
        if cat in ("✅ LARGE","❓SMALL","❓EOS"):
            print(f"     content: {text[:200]}")
    except Exception as e:
        print(f"  {model:38s} ERR: {e}")
    time.sleep(0.5)
