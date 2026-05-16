"""
Mitmproxy addon: 给 Windsurf 相关流量打标签 + 实时打印关键事件。
不修改请求/响应,只观察。
"""
from mitmproxy import http
import time

INTERESTING = (
    "server.self-serve.windsurf.com",
    "unleash.codeium.com",
    "server.codeium.com",
    "inference.codeium.com",
    "windsurf.com",
    "codeium.com",
)

def request(flow: http.HTTPFlow):
    h = flow.request.pretty_host
    if any(k in h for k in INTERESTING):
        path = flow.request.path.split("?")[0]
        print(f"[REQ ] {flow.request.method} {h}{path}  ({len(flow.request.raw_content or b'')}B)")

def response(flow: http.HTTPFlow):
    h = flow.request.pretty_host
    if any(k in h for k in INTERESTING):
        path = flow.request.path.split("?")[0]
        sz = len(flow.response.raw_content or b"")
        print(f"[RESP] {flow.response.status_code} {h}{path}  ({sz}B)")
