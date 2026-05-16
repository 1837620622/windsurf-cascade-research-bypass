# 流量文件数据摘要

## 文件列表

| 文件 | 大小 | 说明 |
|------|------|------|
| `/tmp/windsurf_flows.mitm` | ~1.2MB | 第 1 次捕获：85 个请求到 server.self-serve.windsurf.com, 40 个到 unleash.codeium.com |
| `/tmp/windsurf_flows2.mitm` | — | 第 2 次捕获（因代理中断而不完整） |

## 第 1 次捕获完整请求列表

### server.self-serve.windsurf.com (85 个请求)

| 序号 | API | 次数 | 方向 |
|------|-----|------|------|
| 1-2 | GetUserStatus | 2 | 请求/响应 |
| 3 | GetChatMessage | 1 | 请求/响应 |
| 4-5 | GetCliModelConfigs | 2+ | 请求/响应 |
| 6-8 | CASCADE_STEP_COMPLETED | 3+ | 仅请求 |
| 9 | CASCADE_ERROR_STEP | 1 | 仅请求 |
| 10 | CASCADE_MCP_SERVER_INIT | 1 | 仅请求 |
| 11+ | 其他 Connect-RPC | ~70 | 混合 |

### 观察到的模型

```
CASCADE_STEP_COMPLETED → model = "claude-opus-4-7-max-fast"
```

这说明用户会话被分配到了 Windsurf 当前提供的最高级模型（Claude Opus 4.7 Max Fast）。

### 错误分析

```
CASCADE_ERROR_STEP → "proxyconnect tcp: dial tcp 127.0.0.1:8080: connect: connection refused"
```

这发生在代理停止时，说明语言服务器确实在尝试通过代理连接。

## 认证数据

```
Authorization: Basic devin-session-token$eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzZXNzaW9uX2lkIjoid2luZHN1cmYtc2Vzc2lvbi1iM2Q0ZjA4OS1jZmRhLTRjYjEtOTQ5OS02ODg3M2E3YmZhNTcifQ.6S5Lpvgh3XgJ9H_jLVqI4tIPCLrxzr0NAr7FfHXps_E
```

解码 JWT Payload:
```json
{
  "session_id": "windsurf-session-<session-uuid>"
}
```
