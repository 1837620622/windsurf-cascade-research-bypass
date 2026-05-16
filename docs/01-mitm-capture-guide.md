# Windsurf 抓包配置完整指南

本文档记录逆向分析 Windsurf 所需的抓包配置方法，包括环境准备、启动步骤、常见问题及解决方案。可用于在其他工具或新环境中重现抓包流程。

## 概述

Windsurf 使用 Go 语言服务器和 Rust 二进制进行 API 通信。主要 API 端点为 `server.self-serve.windsurf.com`，使用 Connect-RPC over HTTP/1.1 协议。抓包需要同时处理系统代理检测、LLM 流式传输以及多个进程的策略。

## 架构速览

```
Windsurf.app
  ├── Extension Host (extension.js) — Unleash 客户端、UI 显示
  ├── language_server_macos_arm (Go) — Connect-RPC 到 server.self-serve.windsurf.com
  └── devin (Rust) — ACP 协议、SSE 流
```

关键参数：
- `--detect_proxy=true` — Go 二进制会自动检测 macOS 系统代理
- 通信协议：Connect-RPC (`Content-Type: application/proto`, `connect-protocol-version: 1`)
- 认证：`Authorization: Basic devin-session-token$<JWT>`

## 方案 A: 无代理被动抓包（tcpdump）— 推荐

### 适用场景
- 需要捕获流量但不想干扰 Windsurf 连接
- 只需要看数据包源/目的地/Certificate 信息
- 不能接受任何连接中断

### 步骤

#### 1. 关闭 macOS 系统代理

```bash
# 关闭 HTTP 代理
sudo networksetup -setwebproxystate Wi-Fi off

# 关闭 HTTPS 代理
sudo networksetup -setsecurewebproxystate Wi-Fi off

# 验证
networksetup -getwebproxy Wi-Fi
# 预期输出: Enabled: No

networksetup -getsecurewebproxy Wi-Fi
# 预期输出: Enabled: No
```

#### 2. 重启语言服务器（使代理变更生效）

```bash
# 找到语言服务器进程
ps aux | grep language_server

# 终止旧进程（会自动重启）
kill <PID>

# 等待自动重启
sleep 3
ps aux | grep language_server
# 确认新进程已启动
```

#### 3. 启动 tcpdump 被动抓包

```bash
# 创建输出目录
mkdir -p /tmp/windsurf_capture

# 启动 tcpdump（后台运行），同时捕获 Windsurf 所有 API 域名
sudo tcpdump -i en0 -s 0 \
  "host server.self-serve.windsurf.com or host unleash.codeium.com or host server.codeium.com or host inference.codeium.com" \
  -w /tmp/windsurf_capture/traffic.pcap &

# 记录 tcpdump PID
echo $!
```

#### 4. 使用 Windsurf

在 Windsurf 中正常使用 Cascade，发送消息。

#### 5. 停止抓包并分析

```bash
# 停止 tcpdump
sudo kill <TCPDUMP_PID>

# 分析 pcap 文件（三种方式）
# 方式 1: 基本统计
capinfos /tmp/windsurf_capture/traffic.pcap

# 方式 2: 查看所有连接
tshark -r /tmp/windsurf_capture/traffic.pcap \
  -T fields -e ip.src -e ip.dst -e tcp.srcport -e tcp.dstport \
  -e tls.handshake.extensions_server_name

# 方式 3: 按域名筛选
tshark -r /tmp/windsurf_capture/traffic.pcap \
  -Y "tls.handshake.extensions_server_name == server.self-serve.windsurf.com" \
  -T fields -e frame.time -e ip.src -e ip.dst
```

### 优点
- 完全不影响 Windsurf 连接
- 可以看到所有网络请求的时间、大小、目标
- 可以观察 TLS 握手（证书、SNI）

### 缺点
- 看不到请求/响应明文（TLS 加密）
- 只能分析元数据

---

## 方案 B: mitmproxy 中间人抓包 — 高级

### 适用场景
- 需要查看/修改请求和响应内容
- 需要解码 protobuf 负载
- 需要分析认证令牌

### 先决条件

```bash
# 安装 mitmproxy
brew install mitmproxy

# 信任 mitmproxy CA 证书
# 启动 mitmproxy 后，访问 http://mitm.it 下载证书
# 或手动安装：
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain \
  ~/.mitmproxy/mitmproxy-ca-cert.pem
```

### 配置步骤

#### 1. 设置系统代理

```bash
# 开启 HTTP 代理
sudo networksetup -setwebproxy Wi-Fi 127.0.0.1 8080

# 开启 HTTPS 代理
sudo networksetup -setsecurewebproxy Wi-Fi 127.0.0.1 8080
```

#### 2. 启动 mitmdump（无 UI，更稳定）

```bash
# 启动 mitmdump 后台运行
mitmdump --listen-port 8080 \
  -w /tmp/windsurf_capture/flows.mitm \
  --set block_global=false \
  --set flow_detail=4 \
  > /tmp/windsurf_capture/mitmproxy.log 2>&1 &

echo "mitmdump PID: $!"
```

#### 3. 设置环境变量（确保 Go 二进制使用代理）

```bash
# 显式设置代理环境变量（Go 的 http.ProxyFromEnvironment 使用这些）
export HTTPS_PROXY=http://127.0.0.1:8080
export HTTP_PROXY=http://127.0.0.1:8080
export NO_PROXY=localhost,127.0.0.1
```

#### 4. 重启语言服务器

```bash
kill <language_server_PID>
sleep 3
```

#### 5. 使用 Windsurf

在 Windsurf 中使用 Cascade。

#### 6. 停止抓包

```bash
# 停止 mitmdump
kill <MITMDUMP_PID>

# 关闭系统代理
sudo networksetup -setwebproxystate Wi-Fi off
sudo networksetup -setsecurewebproxystate Wi-Fi off
```

### 流量分析

```bash
# 使用 mitmproxy 的 Python API 分析流量
pip install mitmproxy

# 示例: 提取所有 GET / POST 请求
cat << 'PYEOF' > /tmp/analyze_flows.py
from mitmproxy import io
from mitmproxy.http import HTTPFlow

with open("/tmp/windsurf_capture/flows.mitm", "rb") as f:
    reader = io.FlowReader(f)
    for flow in reader.stream():
        if flow.request:
            print(f"{flow.request.method} {flow.request.pretty_url}")
            if "GetUserStatus" in flow.request.pretty_url:
                print(f"  Auth: {flow.request.headers.get('Authorization', 'N/A')}")
                print(f"  Response length: {len(flow.response.content) if flow.response else 0}")
        print()
PYEOF

python3 /tmp/analyze_flows.py
```

### 常见问题

#### 问题 1: Connection Refused

**症状**: 语言服务器日志中出现 `proxyconnect tcp: dial tcp 127.0.0.1:8080: connect: connection refused`

**原因**: mitmproxy 未运行，但系统代理或环境变量仍指向它

**解决**:
```bash
# 检查代理是否在运行
lsof -i :8080

# 如果不需要代理，关闭系统代理
sudo networksetup -setwebproxystate Wi-Fi off
sudo networksetup -setsecurewebproxystate Wi-Fi off

# 重启语言服务器
kill <language_server_PID>
```

#### 问题 2: mitmproxy 进程崩溃

**症状**: mitmproxy 意外退出，抓包中断

**原因**: 端口冲突、手动 Ctrl+C

**解决**: 使用 `mitmdump` 替代 `mitmweb`（无 UI 更稳定）；使用后台模式

#### 问题 3: LLM 流式响应中断

**症状**: AI 回复在代理模式下无法完整输出

**原因**: SSE 流式连接通过代理时超时或断开

**解决**: 
- 确保代理有较长的超时设置
- 在代理模式下不要频繁重启 mitmproxy
- 考虑对 LLM 域名（如 `inference.codeium.com`）设置 `NO_PROXY`

#### 问题 4: TLS 证书不被信任

**症状**: 连接错误，TLS 握手失败

**解决**:
```bash
# 手动信任 mitmproxy 根证书
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain \
  ~/.mitmproxy/mitmproxy-ca-cert.pem
```

---

## 方案 C: 日志分析（无需代理）

### 适用场景
- 不需要实时抓包，仅需要排查连接问题
- 只想看语言服务器内部状态

### 日志位置

```bash
# 扩展主机日志
~/Library/Application\ Support/Windsurf/logs/*/window*/exthost/codeium.windsurf/Windsurf.log

# ACP 日志
~/Library/Application\ Support/Windsurf/logs/*/window*/exthost/codeium.windsurf/Windsurf\ ACP.log

# Devin 云日志
~/Library/Application\ Support/Windsurf/logs/*/window*/exthost/codeium.windsurf/Windsurf\ ACP\ devin-cloud.log
```

### 关键日志模式

```bash
# 跟踪语言服务器 API 调用
tail -f ~/Library/Application\ Support/Windsurf/logs/*/window*/exthost/codeium.windsurf/Windsurf.log | grep -E "(Get|Post|proxy|API|error|Error)"

# 查看代理相关错误
grep -i "proxy" ~/Library/Application\ Support/Windsurf/logs/*/window*/exthost/codeium.windsurf/Windsurf.log

# 查看认证相关信息
grep -i "auth\|token\|jwt\|session" ~/Library/Application\ Support/Windsurf/logs/*/window*/exthost/codeium.windsurf/Windsurf.log
```

---

## 关键数据提取

### 1. 扩展 JS 中的 API 密钥和端点

```bash
# 提取 extension.js 中的服务器 URL
strings /Applications/Windsurf.app/Contents/Resources/app/extensions/windsurf/dist/extension.js | grep -i "server\." | sort -u
```

### 2. 语言服务器启动参数

```bash
ps aux | grep language_server | grep -v grep
```

### 3. 缓存的模型配置

```bash
# model_configs_v2.bin 和 team_settings.bin 位置
ls -la ~/.cache/devin/cli/
```

### 4. Unleash 特征开关（LevelDB）

```bash
# LevelDB 位置
ls -la ~/Library/Application\ Support/Windsurf/Local\ Storage/leveldb/

# 提取 Unleash 数据（如果 leveldb 工具可用）
strings ~/Library/Application\ Support/Windsurf/Local\ Storage/leveldb/*.log | grep -i "unleash\|feature\|CASCADE\|toggle"
```

---

## 完整抓包脚本

### 被动抓包（方案 A）

```bash
#!/bin/bash
# ===== 被动抓包脚本 =====

OUTPUT_DIR="/tmp/windsurf_capture_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUTPUT_DIR"

echo "=== 步骤 1: 关闭系统代理 ==="
sudo networksetup -setwebproxystate Wi-Fi off
sudo networksetup -setsecurewebproxystate Wi-Fi off

echo "=== 步骤 2: 重启语言服务器 ==="
LS_PID=$(ps aux | grep language_server | grep -v grep | awk '{print $2}')
if [ -n "$LS_PID" ]; then
    kill "$LS_PID"
    sleep 3
fi

echo "=== 步骤 3: 启动 tcpdump ==="
sudo tcpdump -i en0 -s 0 \
  "host server.self-serve.windsurf.com or host unleash.codeium.com or host server.codeium.com or host inference.codeium.com" \
  -w "$OUTPUT_DIR/traffic.pcap" &
TCPDUMP_PID=$!
echo "tcpdump PID: $TCPDUMP_PID"

echo ""
echo "=== 现在可以打开 Windsurf 使用 Cascade ==="
echo "=== 完成后执行以下命令停止抓包 ==="
echo "sudo kill $TCPDUMP_PID"
echo ""

# 保存 PID 供后续使用
echo "$TCPDUMP_PID" > "$OUTPUT_DIR/tcpdump_pid.txt"
```

### mitmproxy 抓包（方案 B）

```bash
#!/bin/bash
# ===== mitmproxy 抓包脚本 =====

OUTPUT_DIR="/tmp/windsurf_capture_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUTPUT_DIR"

echo "=== 步骤 1: 开启系统代理 ==="
sudo networksetup -setwebproxy Wi-Fi 127.0.0.1 8080
sudo networksetup -setsecurewebproxy Wi-Fi 127.0.0.1 8080

echo "=== 步骤 2: 启动 mitmdump ==="
mitmdump --listen-port 8080 \
  -w "$OUTPUT_DIR/flows.mitm" \
  --set block_global=false \
  > "$OUTPUT_DIR/mitmproxy.log" 2>&1 &
MITM_PID=$!
echo "mitmdump PID: $MITM_PID"

echo "=== 步骤 3: 设置环境变量 ==="
export HTTPS_PROXY=http://127.0.0.1:8080
export HTTP_PROXY=http://127.0.0.1:8080

echo "=== 步骤 4: 重启语言服务器 ==="
LS_PID=$(ps aux | grep language_server | grep -v grep | awk '{print $2}')
if [ -n "$LS_PID" ]; then
    kill "$LS_PID"
    sleep 3
fi

echo ""
echo "=== 现在可以打开 Windsurf 使用 Cascade ==="
echo "=== 完成后执行以下命令停止抓包 ==="
echo "kill $MITM_PID"
echo "sudo networksetup -setwebproxystate Wi-Fi off"
echo "sudo networksetup -setsecurewebproxystate Wi-Fi off"
echo ""

echo "$MITM_PID" > "$OUTPUT_DIR/mitmdump_pid.txt"
```

---

## Protobuf 解码

### model_configs_v2.bin

```python
import struct

def decode_protobuf_varint(data, offset):
    """解码 protobuf varint"""
    value = 0
    shift = 0
    while True:
        byte = data[offset]
        value |= (byte & 0x7F) << shift
        shift += 7
        offset += 1
        if not (byte & 0x80):
            break
    return value, offset

# 读取文件
with open("~/.cache/devin/cli/model_configs_v2.bin", "rb") as f:
    data = f.read()

# 通用 protobuf 解码函数
def decode_protobuf(data):
    """简单 protobuf 解码（字段号 + 类型）"""
    offset = 0
    fields = {}
    while offset < len(data):
        key, offset = decode_protobuf_varint(data, offset)
        field_num = key >> 3
        wire_type = key & 0x7
        # 根据 wire_type 解析
        if wire_type == 0: # Varint
            value, offset = decode_protobuf_varint(data, offset)
            fields[field_num] = value
        elif wire_type == 2: # Length-delimited
            length, offset = decode_protobuf_varint(data, offset)
            value = data[offset:offset+length]
            offset += length
            fields[field_num] = value
    return fields
```

### 从 mitmproxy 流量解码 protobuf

```python
from mitmproxy import io
from mitmproxy.http import HTTPFlow

def decode_protobuf_response(data):
    """解码 protobuf 响应（gzip 解压 + protobuf 解析）"""
    import gzip
    try:
        # Connect-RPC 响应是 gzip 压缩
        decompressed = gzip.decompress(data)
        return decode_protobuf(decompressed)
    except:
        return {"error": "解压失败", "raw_length": len(data)}

with open("/tmp/windsurf_capture/flows.mitm", "rb") as f:
    reader = io.FlowReader(f)
    for flow in reader.stream():
        if flow.response and "GetUserStatus" in flow.request.pretty_url:
            body = flow.response.content
            print(f"状态码: {flow.response.status_code}")
            print(f"响应长度: {len(body)}")
            decoded = decode_protobuf_response(body)
            print(f"解码结果: {decoded}")
```

---

## 配置检查清单

每次开始抓包前确认：

- [ ] macOS 系统代理状态正确（需要时开启/不需要时关闭）
- [ ] 代理软件（mitmdump/mitmweb）正在运行（如果使用方案 B）
- [ ] 语言服务器已重启（使代理变更生效）
- [ ] Windsurf 日志目录存在
- [ ] 抓包输出目录已创建
- [ ] tcpdump 已启动（如果使用方案 A）
- [ ] 抓包输出文件正在写入

## 故障排除流程

```
Windsurf Cascade 无法发送消息
    │
    ├→ 检查系统代理: networksetup -getwebproxy Wi-Fi
    │   ├→ Enabled: Yes → 确认代理正在监听 8080
    │   │                  → 如果不是: sudo networksetup -setwebproxystate Wi-Fi off
    │                         → 重启语言服务器
    │   └→ Enabled: No  → 正常，继续检查
    │
    ├→ 检查语言服务器日志
    │   ├→ 有 "proxyconnect" 错误 → 代理问题
    │   └→ 有 "connection refused" → 见上
    │
    ├→ 检查语言服务器进程是否运行
    │   ├→ 无进程 → Windsurf 可能已崩溃，重启 Windsurf
    │   └→ 有进程 → 正常
    │
    └→ 检查认证
        ├→ LevelDB 中的 JWT 是否有效
        └→ 可在 Windsurf 中重新登录
```

## 已发现的关键 API 端点

| 端点 | 方法 | 描述 |
|------|------|------|
| `server.self-serve.windsurf.com` | Connect-RPC | 主 API（GetUserStatus, GetChatMessage, GetCliModelConfigs, CASCADE_STEP_COMPLETED 等） |
| `unleash.codeium.com` | REST | Unleash 特征开关 |
| `server.codeium.com` | REST | 模型路由（model_configs_v2.bin 中的 handler） |
| `inference.codeium.com` | REST | 推理 API |

## 已发现的认证格式

```
Authorization: Basic devin-session-token$<JWT>
JWT: {"session_id": "windsurf-session-<uuid>"}
```
