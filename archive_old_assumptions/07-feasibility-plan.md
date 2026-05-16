# 可行性方案与测试计划

## 目标

让用户能在代理环境下成功使用 Cascade 发送消息，同时捕获完整流量。

## 方案对比

### 方案 1: mitmdump 稳定模式（推荐优先测试）

**原理**: 使用 mitmdump（无 UI），监听固定端口，不手动中断

```bash
# 启动 mitmdump（后台运行）
mitmdump --listen-port 9090 \
  -w /tmp/windsurf_capture.mitm \
  --set block_global=false &

# 设置代理环境变量
export HTTPS_PROXY=http://127.0.0.1:9090
export HTTP_PROXY=http://127.0.0.1:9090

# 在有代理环境下启动 Windsurf
open -a Windsurf

# 观察日志
tail -f /tmp/windsurf_capture_log.txt
```

**优点**: 已证明能捕获 125 个请求；稳定
**缺点**: 可能干扰流式推理；LLM 调用可能失败

### 方案 2: 透明代理模式

**原理**: 使用透明代理，无需客户端配置

```bash
mitmproxy --mode transparent --listen-port 8080
```

**优点**: 不需要设置环境变量
**缺点**: 需要 root 权限和 iptables 规则

### 方案 3: mitmproxy + 反向代理模式

**原理**: 不代理，直接转发请求并记录

### 方案 4: tcpdump 被动嗅探

**原理**: 不拦截流量，只记录数据包

```bash
# 不设代理，只记录 Windsurf 的流量
sudo tcpdump -i en0 -s 0 \
  "host server.self-serve.windsurf.com or host unleash.codeium.com or host server.codeium.com" \
  -w /tmp/windsurf_traffic.pcap
```

**优点**: 完全不干扰流量
**缺点**: 只能看到加密数据，不能查看明文

### 方案 5: 无代理 + 日志分析

**原理**: 不设代理，仅分析 Windsurf 本身的日志

```bash
tail -f ~/Library/Application\ Support/Windsurf/logs/*/window*/exthost/codeium.windsurf/*.log
tail -f ~/Library/Application\ Support/Windsurf/logs/*/window*/exthost/codeium.windsurf/devin_server/*.log
```

## 推荐测试顺序

```
第 1 轮: 无代理，直接使用 Cascade → 确认能否正常发送消息
   ↓ （基线测试）
第 2 轮: tcpdump 被动捕获 → 确认数据包流向
   ↓ （不影响流量）
第 3 轮: mitmdump 端口 9090 + HTTPS_PROXY → 测试控制面 API
   ↓ （可能影响 LLM 流）
第 4 轮: 分析 1-3 轮结果 → 确定最优方案
```

## 测试指标

1. ✅ Cascade 消息是否可以正常发送和接收
2. ✅ CASCADE_STEP_COMPLETED 是否正常上报
3. ✅ GetChatMessage 请求/响应是否完整
4. ✅ 流式输出是否正常工作
5. ✅ 是否成功捕获到所有 API 调用
