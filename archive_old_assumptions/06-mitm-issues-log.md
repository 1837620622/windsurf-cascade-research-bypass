# 抓包方法问题记录

## 使用的工具

- **mitmproxy/mitmweb**: HTTP/HTTPS 中间人代理
- **mitmdump**: mitmproxy 的无 UI 命令行版本

## 问题 1: Proxy 崩溃

### 症状
```
2026-05-16 11:46:57,092 - web: mitmweb is running at http://127.0.0.1:59595
Web 服务器已启动
正在保存到 /tmp/windsurf_flows2.mitm
^C
命令 'mitmweb' 失败
```

### 原因
- 端口冲突（多次启动 mitmweb）
- 手动 Ctrl+C 中断
- 代理进程被意外终止

### 影响
语言服务器尝试连接代理但被拒绝（connection refused），导致 Cascade 错误。

## 问题 2: TLS 证书信任

### 症状
Go 语言服务器的 HTTP 客户端可能不信任 mitmproxy 的 CA 证书。

### 解决方案
- mitmproxy 根证书需要被系统信任
- macOS 上安装 `~/.mitmproxy/mitmproxy-ca-cert.pem`

## 问题 3: 系统代理与显式代理

### 发现
Go 二进制文件有 `--detect_proxy=true` 参数用于检测系统代理。

### 推荐配置
```bash
# 显式设置 HTTPS_PROXY 更可靠
export HTTPS_PROXY=http://127.0.0.1:8080
export HTTP_PROXY=http://127.0.0.1:8080
# 或使用语言服务器的 detect_proxy
--detect_proxy=true
```

## 问题 4: 流式 LLM 调用

### 症状
控制面调用（GetUserStatus, CASCADE_STEP_COMPLETED）通过代理正常工作，但 LLM 推理调用可能失败。

### 原因
- LLM 推理使用 SSE 流式传输
- 流式连接可能在代理中断时挂起
- 模型提供商可能拒绝来自代理 IP 的连接

## 当前捕获状态

### 成功捕获
- `server.self-serve.windsurf.com` — 85 个请求 (Connect-RPC)
- `unleash.codeium.com` — 40 个请求
- `CASCADE_STEP_COMPLETED` — 确认模型为 `claude-opus-4-7-max-fast`
- Auth 令牌和 JWT 完整捕获

### 尚未捕获
- LLM 推理流（SSE 流）
- GetChatMessage 完整请求/响应（只捕获到 1 次）
- 文件编辑操作的具体内容

## 改进方案

### 方案 A: 稳定 mitmdump
```bash
# 使用 mitmdump 而不是 mitmweb（更稳定）
mitmdump --mode regular --listen-port 8080 \
  -w /tmp/windsurf_capture.mitm \
  --set flow_detail=4
```

### 方案 B: tcpdump 被动捕获
```bash
# 被动捕获，不拦截流量
sudo tcpdump -i en0 -s 0 \
  host server.self-serve.windsurf.com \
  -w /tmp/windsurf_traffic.pcap
```

### 方案 C: 组合使用
1. mitmdump 捕获控制面 API
2. tcpdump 捕获模型推理（TLS 加密但可分析端点）
3. 对比两者数据
