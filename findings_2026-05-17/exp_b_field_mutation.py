#!/usr/bin/env python3
"""
EXP-B/G: Mutate top-level fields ([20], [9], [22], [16]) in latest GCM payload, see if any change quota verdict.
"""
import gzip, struct, requests, time
from pathlib import Path

P = Path('/tmp/wf_exp/last_gcm_payload.bin').read_bytes()

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

def field_v(num,val): return varint_enc((num<<3)|0)+varint_enc(val)
def field_ld(num,c): return varint_enc((num<<3)|2)+varint_enc(len(c))+c

def split_top(payload):
    """Yield (start_offset, end_offset, fnum, wire, value_bytes_including_tag_and_len)"""
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
        yield (start, o, fnum, wire, payload[start:o])

def replace_field(payload, fnum_target, new_field_bytes, instance=0):
    """Replace nth occurrence of field fnum with new_field_bytes (full encoded field)."""
    out=b''; cnt=0; replaced=False
    for s,e,fn,w,v in split_top(payload):
        if fn==fnum_target and cnt==instance:
            out += new_field_bytes
            replaced=True
        else:
            out += v
        if fn==fnum_target: cnt+=1
    return out, replaced

def drop_field(payload, fnum_target):
    out=b''
    dropped=0
    for s,e,fn,w,v in split_top(payload):
        if fn==fnum_target:
            dropped+=1
            continue
        out += v
    return out, dropped

def envelope(payload):
    comp = gzip.compress(payload)
    return bytes([0x01]) + struct.pack(">I", len(comp)) + comp

URL = "https://server.self-serve.windsurf.com/exa.api_server_pb.ApiServerService/GetChatMessage"
HEADERS = {
    'Content-Type': 'application/connect+proto',
    'Connect-Protocol-Version': '1',
    'Connect-Content-Encoding': 'gzip',
    'Connect-Accept-Encoding': 'gzip',
    'Accept-Encoding': 'identity',
    'User-Agent': 'connect-go/1.18.1 (go1.26.1)',
}

def send_test(label, payload):
    env = envelope(payload)
    t0=time.time()
    try:
        r = requests.post(URL, data=env, headers=HEADERS, timeout=30)
        elapsed=(time.time()-t0)*1000
        body=r.content
        # decode envelope
        if len(body)>=5:
            flag=body[0]; ln=struct.unpack(">I",body[1:5])[0]
            inner=body[5:5+ln]
            if flag&1 and inner[:2]==b'\x1f\x8b':
                inner=gzip.decompress(inner)
            text = inner[:300].decode('utf-8','replace')
        else:
            text = body[:300].decode('utf-8','replace')
        # categorize
        if 'failed_precondition' in text and 'quota' in text:
            cat="❌ QUOTA"
        elif 'permission_denied' in text or 'invalid_argument' in text or 'unauthenticated' in text:
            cat="🚫 REJECT"
        elif flag & 0x02:  # endstream w/ error
            cat="❓ENDSTREAM"
        elif len(body)>1000:
            cat="✅ SUCCESS_LARGE"
        else:
            cat="❓ OTHER"
        print(f"  [{label:30s}] {cat}  HTTP{r.status_code} {len(body)}B {elapsed:.0f}ms")
        if cat == "✅ SUCCESS_LARGE":
            print(f"     >>> {text[:200]}")
        elif cat == "❓ OTHER":
            print(f"     {text[:150]}")
        return r.status_code, len(body), text, cat
    except Exception as e:
        print(f"  [{label:30s}] ERR: {e}")
        return None

# === Baseline ===
print("=== Baseline (untouched) ===")
send_test("baseline_opus", P)

# === EXP-B1: Drop field [20] ===
print("\n=== Drop field [20] ===")
mod, n = drop_field(P, 20)
print(f"  dropped {n} occurrences, payload {len(P)}→{len(mod)}")
send_test("drop_f20", mod)

# === EXP-B2: field [20]=0 ===
print("\n=== field [20]=0 ===")
mod, ok = replace_field(P, 20, field_v(20, 0))
print(f"  replaced: {ok}")
send_test("f20=0", mod)

# === EXP-B3: field [20]=999 ===
print("\n=== field [20]=999 ===")
mod, _ = replace_field(P, 20, field_v(20, 999))
send_test("f20=999", mod)

# === EXP-B4: drop field [9] ===
print("\n=== Drop field [9] (4654B) ===")
mod, n = drop_field(P, 9)
print(f"  dropped {n}, payload {len(P)}→{len(mod)}")
send_test("drop_f9", mod)

# === EXP-B5: field [9] = single zero byte ===
print("\n=== field [9] = empty ===")
mod, _ = replace_field(P, 9, field_ld(9, b''))
send_test("f9=empty", mod)

# === EXP-B6: drop field [22] (cascade_id?) ===
print("\n=== Drop field [22] ===")
mod, n = drop_field(P, 22)
print(f"  dropped {n}")
send_test("drop_f22", mod)

# === EXP-B7: drop field [16] ===
print("\n=== Drop field [16] ===")
mod, n = drop_field(P, 16)
print(f"  dropped {n}")
send_test("drop_f16", mod)

# === EXP-B8: drop field [7] ===
print("\n=== Drop field [7]=5 (varint) ===")
mod, n = drop_field(P, 7)
print(f"  dropped {n}")
send_test("drop_f7", mod)

# === EXP-B9: field [7]=0 ===
print("\n=== field [7]=0 ===")
mod, _ = replace_field(P, 7, field_v(7, 0))
send_test("f7=0", mod)
