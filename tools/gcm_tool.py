#!/usr/bin/env python3
"""
GCM 请求改装工具:
- 解 Connect-RPC 信封
- 解 gzip
- protobuf 字段定位 + 替换
- 重打包
"""
import sys, struct, gzip

def varint_decode(d, o):
    v = 0; s = 0
    while True:
        b = d[o]; o += 1
        v |= (b & 0x7F) << s
        if not (b & 0x80): return v, o
        s += 7

def varint_encode(v):
    out = []
    while True:
        b = v & 0x7F
        v >>= 7
        if v: out.append(b | 0x80)
        else: out.append(b); return bytes(out)

def unwrap(data):
    flag = data[0]; ln = struct.unpack(">I", data[1:5])[0]
    payload = data[5:5+ln]
    if flag & 1:
        payload = gzip.decompress(payload)
        compressed = True
    else:
        compressed = False
    return flag, compressed, payload

def wrap(payload, compressed=True):
    if compressed:
        payload = gzip.compress(payload)
        flag = 0x01
    else:
        flag = 0x00
    return bytes([flag]) + struct.pack(">I", len(payload)) + payload

def find_field_at_path(data, path, depth=0):
    """
    Recursive: walk protobuf, when at path[0] descend; on last, yield position.
    path = [(field_num, occurrence)] e.g. [(1, 0), (21, 0)]
    yields (start_offset_of_value, length_of_value, wire_type)
    """
    o = 0
    occ = {}
    while o < len(data):
        try: k, o = varint_decode(data, o)
        except: return
        wire = k & 7; fnum = k >> 3
        if fnum == 0: return
        if wire == 0:
            v_start = o
            try: v, o = varint_decode(data, o)
            except: return
            if depth < len(path) and (fnum, occ.get(fnum, 0)) == path[depth]:
                if depth == len(path) - 1:
                    yield ("varint", v_start, o - v_start, v, data)
                # varint can't recurse
            occ[fnum] = occ.get(fnum, 0) + 1
        elif wire == 2:
            try: ln, o2 = varint_decode(data, o)
            except: return
            ln_start = o; o = o2
            v_start = o
            v_end = o + ln
            if depth < len(path) and (fnum, occ.get(fnum, 0)) == path[depth]:
                if depth == len(path) - 1:
                    yield ("ld", v_start, ln, data[v_start:v_end], data)
                else:
                    yield from find_field_at_path(data[v_start:v_end], path, depth+1)
            occ[fnum] = occ.get(fnum, 0) + 1
            o = v_end
        elif wire == 1: o += 8
        elif wire == 5: o += 4
        else: return

def list_top_level(data):
    """List all top-level fields with their offsets."""
    o = 0
    while o < len(data):
        try: k, o2 = varint_decode(data, o)
        except: return
        wire = k & 7; fnum = k >> 3
        if fnum == 0: return
        key_start = o
        o = o2
        if wire == 0:
            try: v, o = varint_decode(data, o)
            except: return
            yield (fnum, "varint", key_start, v)
        elif wire == 2:
            try: ln, o = varint_decode(data, o)
            except: return
            yield (fnum, "ld", key_start, data[o:o+ln])
            o += ln
        elif wire == 1: yield (fnum, "fix64", key_start, data[o:o+8]); o += 8
        elif wire == 5: yield (fnum, "fix32", key_start, data[o:o+4]); o += 4
        else: return

def replace_string_field(payload, target_old, target_new):
    """Replace a string field (length-delimited) at top level by content match."""
    target_old_b = target_old.encode() if isinstance(target_old, str) else target_old
    target_new_b = target_new.encode() if isinstance(target_new, str) else target_new
    idx = payload.find(target_old_b)
    if idx < 0:
        raise ValueError(f"not found: {target_old}")
    # Walk forward from idx to find length prefix; the byte just before should be a varint of len(target_old_b)
    # Length is encoded as varint right before content; find by checking
    # Actually simpler: scan from start, when we hit string field whose content == target_old, replace
    o = 0
    out = bytearray()
    last_end = 0
    while o < len(payload):
        rec_start = o
        try: k, o = varint_decode(payload, o)
        except: break
        wire = k & 7
        if wire == 0:
            try: v, o = varint_decode(payload, o)
            except: break
        elif wire == 2:
            try: ln, after_len = varint_decode(payload, o)
            except: break
            content_start = after_len
            content_end = content_start + ln
            content = payload[content_start:content_end]
            if content == target_old_b:
                # rebuild this record with new content
                out.extend(payload[last_end:rec_start])
                out.extend(varint_encode(k))
                out.extend(varint_encode(len(target_new_b)))
                out.extend(target_new_b)
                last_end = content_end
            o = content_end
        elif wire == 1: o += 8
        elif wire == 5: o += 4
        else: break
    out.extend(payload[last_end:])
    return bytes(out)

if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "decode":
        data = open(sys.argv[2], "rb").read()
        flag, comp, payload = unwrap(data)
        print(f"flag=0x{flag:02x} compressed={comp} payload_size={len(payload)}")
        for fnum, wire, ks, val in list_top_level(payload):
            if isinstance(val, bytes):
                preview = val[:60].hex() if not all(32 <= b < 127 or b in (10,13,9) for b in val[:80]) else val[:80].decode("utf-8", errors="replace")
                print(f"  [{fnum}] {wire} ({len(val)}B): {preview!r}")
            else:
                print(f"  [{fnum}] {wire}: {val}")
    elif cmd == "swap":
        # swap top-level string field <old> -> <new>
        in_path, old, new, out_path = sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
        data = open(in_path, "rb").read()
        flag, comp, payload = unwrap(data)
        new_payload = replace_string_field(payload, old, new)
        # wrap
        out = wrap(new_payload, compressed=bool(flag & 1))
        open(out_path, "wb").write(out)
        print(f"wrote {len(out)}B  (orig payload {len(payload)} → new {len(new_payload)})")
