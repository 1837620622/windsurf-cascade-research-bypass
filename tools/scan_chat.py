#!/usr/bin/env python3
"""列出所有 chat/completion 类请求，按响应状态分类。"""
import sys
from collections import Counter
from mitmproxy import io as mio
from mitmproxy.http import HTTPFlow

statuses = Counter()
chat_flows = []
with open(sys.argv[1], "rb") as f:
    for flow in mio.FlowReader(f).stream():
        if not isinstance(flow, HTTPFlow): continue
        path = flow.request.path
        # 任何含 Chat/Message/Completions 的 endpoint
        if not any(k in path for k in ("ChatMessage", "ChatCompletions", "Completions", "GetMessage", "Cortex")):
            continue
        host = flow.request.pretty_host
        status = flow.response.status_code if flow.response else "no-resp"
        ep = path.split("?")[0]
        sz_req = len(flow.request.raw_content or b"")
        sz_resp = len(flow.response.raw_content or b"") if flow.response else 0
        statuses[(host, ep, status)] += 1
        chat_flows.append((host, ep, status, sz_req, sz_resp, flow))

print(f"=== {len(chat_flows)} 个 chat/completion flow ===\n")
for (host, ep, status), cnt in statuses.most_common():
    print(f"  [{status}] x{cnt:>3}  {host}{ep}")

# 找成功的（可能是 200, body > 1KB 表示真正回复; 218B 是错误信封）
print("\n=== 真正成功的 (resp > 1KB) ===")
for host, ep, status, sz_req, sz_resp, flow in chat_flows:
    if status == 200 and sz_resp > 500:
        print(f"  resp={sz_resp:>6}B req={sz_req:>6}B  {host}{ep}")
