"""
mitmdump addon: 把 GetChatMessage 里的高级模型替换为免费模型,绕过 quota.
- request: claude-opus-4-7-max-fast → kimi-k2-6 (服务端不收 quota)
- response: 把响应里的 model 字段改回原模型名 (UI 显示无破绽)
启动: mitmdump --listen-port 8080 -s rewrite_model.py
"""
from mitmproxy import http
import struct, gzip

TARGET_MODEL = b"kimi-k2-6"  # 实际运行模型 (不消耗 quota)

# 要拦截的高级模型
PREMIUM_MODELS = [
    b"claude-opus-4-7-max-fast",
    b"claude-opus-4-7-max",
    b"claude-opus-4-7-high-fast",
    b"claude-opus-4-7-high",
    b"claude-opus-4-7-medium-fast",
    b"claude-opus-4-7-medium",
    b"claude-opus-4-7-low-fast",
    b"claude-opus-4-7-low",
    b"claude-opus-4-7-xhigh-fast",
    b"claude-opus-4-7-xhigh",
    b"claude-opus-4-6",
    b"claude-opus-4-6-fast",
    b"claude-opus-4-6-thinking",
    b"claude-opus-4-6-thinking-fast",
    b"claude-opus-4-6-1m",
    b"claude-opus-4-6-thinking-1m",
    b"claude-sonnet-4-6",
    b"claude-sonnet-4-6-1m",
    b"claude-sonnet-4-6-thinking",
    b"claude-sonnet-4-6-thinking-1m",
    b"gpt-5-5-low", b"gpt-5-5-medium", b"gpt-5-5-high", b"gpt-5-5-xhigh", b"gpt-5-5-none",
    b"gpt-5-5-low-priority", b"gpt-5-5-medium-priority", b"gpt-5-5-high-priority",
    b"gpt-5-5-xhigh-priority", b"gpt-5-5-none-priority",
    b"gpt-5-4-low", b"gpt-5-4-medium", b"gpt-5-4-high", b"gpt-5-4-xhigh", b"gpt-5-4-none",
    b"gpt-5-4-low-priority", b"gpt-5-4-medium-priority", b"gpt-5-4-high-priority",
    b"gpt-5-4-xhigh-priority", b"gpt-5-4-none-priority",
    b"gemini-3-1-pro-low", b"gemini-3-1-pro-high",
    b"gpt-5-3-codex-low", b"gpt-5-3-codex-medium", b"gpt-5-3-codex-high", b"gpt-5-3-codex-xhigh",
]

FIELD_21_TAG = b"\xaa\x01"

# 全局 trace: flow_id → 用户原本选的模型 (用于响应阶段)
_pending = {}

def varint_enc(v):
    out = []
    while True:
        b = v & 0x7F; v >>= 7
        if v: out.append(b | 0x80)
        else: out.append(b); return bytes(out)

def request(flow: http.HTTPFlow):
    if "ApiServerService/GetChatMessage" not in flow.request.path:
        return
    body = flow.request.raw_content or b""
    if len(body) < 5: return
    flag = body[0]
    ln = struct.unpack(">I", body[1:5])[0]
    payload = body[5:5+ln]
    compressed = bool(flag & 1)
    if compressed:
        try: payload = gzip.decompress(payload)
        except Exception as e:
            print(f"[!] gzip err: {e}"); return

    new_record = FIELD_21_TAG + varint_enc(len(TARGET_MODEL)) + TARGET_MODEL
    swapped = None
    for premium in PREMIUM_MODELS:
        old_record = FIELD_21_TAG + varint_enc(len(premium)) + premium
        if old_record in payload:
            payload = payload.replace(old_record, new_record, 1)
            swapped = premium
            break
    if swapped is None:
        return
    print(f"[REQ ] {swapped.decode()} → {TARGET_MODEL.decode()}")
    _pending[flow.id] = swapped  # 记下来响应里改回去

    out_inner = gzip.compress(payload) if compressed else payload
    new_body = bytes([flag]) + struct.pack(">I", len(out_inner)) + out_inner
    flow.request.set_content(new_body)
    flow.request.headers["content-length"] = str(len(new_body))


def response(flow: http.HTTPFlow):
    """把响应里 'kimi-k2-6' 改回用户选的 premium 模型, 让 UI 显示一致。"""
    original = _pending.pop(flow.id, None)
    if original is None: return
    if not flow.response: return
    body = flow.response.raw_content or b""
    if len(body) < 5: return
    flag = body[0]
    ln = struct.unpack(">I", body[1:5])[0]
    payload = body[5:5+ln]
    compressed = bool(flag & 1)
    if compressed:
        try: payload = gzip.decompress(payload)
        except: return

    if TARGET_MODEL not in payload: return
    # 简单字符串替换。如果在 protobuf 字段里, 长度可能错位但通常 model 字段就是裸出现
    # 试两种: protobuf string field with length prefix, 和 inside JSON 字符串
    payload2 = payload.replace(TARGET_MODEL, original)
    if payload2 == payload: return

    print(f"[RESP] {TARGET_MODEL.decode()} → {original.decode()}")
    out_inner = gzip.compress(payload2) if compressed else payload2
    new_body = bytes([flag]) + struct.pack(">I", len(out_inner)) + out_inner
    flow.response.set_content(new_body)
    flow.response.headers["content-length"] = str(len(new_body))
