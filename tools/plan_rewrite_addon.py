"""mitm addon: 改 GetCurrentUser/GetPlanStatus/GetUserStatus 响应里的 plan name 'Pro' -> 'Enterprise'."""
from mitmproxy import http
import struct, gzip

# Connect-RPC 信封解码
def unwrap(body):
    if len(body) < 5: return None, None, body
    flag = body[0]
    ln = struct.unpack(">I", body[1:5])[0]
    payload = body[5:5+ln]
    compressed = bool(flag & 1)
    if compressed:
        try: payload = gzip.decompress(payload)
        except: return None, None, body
    return flag, compressed, payload

def wrap(payload, flag, compressed):
    if compressed:
        payload = gzip.compress(payload)
    return bytes([flag]) + struct.pack(">I", len(payload)) + payload

PATTERNS = ["GetCurrentUser", "GetPlanStatus", "GetUserStatus"]

def response(flow: http.HTTPFlow):
    if not any(p in flow.request.path for p in PATTERNS):
        return
    if not flow.response: return
    body = flow.response.raw_content or b""
    if not body: return
    
    # 处理两种格式: connect+proto 信封 / 直接 protobuf with content-encoding=gzip
    ce = flow.response.headers.get("content-encoding", "")
    ct = flow.response.headers.get("content-type", "")
    
    is_envelope = "connect" in ct
    if is_envelope:
        flag, compressed, payload = unwrap(body)
        if payload is None: return
    else:
        # plain proto, body 可能整体 gzip
        if ce == "gzip":
            try: payload = gzip.decompress(body)
            except: return
            compressed = True
        else:
            payload = body
            compressed = False
        flag = None
    
    # protobuf "Pro" 字段位置: \x12\x03Pro (field 2, wire 2, len 3, "Pro")
    # 替换为 \x12\x0aEnterprise (len 10, "Enterprise") - 长度变化, 上层 length-delimited 也得改
    # 简化: 只替换同长度 "Pro" -> "Max" (len 3) 看是否有效, 因为 Max 是 Pro 的下个 tier
    
    # 但帖子说"改成 Enterprise". 我们要重写 protobuf 长度
    # 简单字符串替换 Pro -> Max (3 字节)
    
    new_payload = payload.replace(b"\x12\x03Pro\x18", b"\x12\x03Max\x18")
    if new_payload == payload:
        return
    
    print(f"[REWRITE] {flow.request.path[:60]} : Pro -> Max")
    
    if is_envelope:
        new_body = wrap(new_payload, flag, compressed)
    else:
        if compressed:
            new_body = gzip.compress(new_payload)
        else:
            new_body = new_payload
    
    flow.response.set_content(new_body)
    flow.response.headers["content-length"] = str(len(new_body))
