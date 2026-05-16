# API 流量分析

## 主 API 端点

```
server.self-serve.windsurf.com
```

## 认证机制

**格式**: `Authorization: Basic devin-session-token$<JWT>`

**JWT 解码**:
```
Header:  {"alg":"HS256","typ":"JWT"}
Payload: {"session_id":"windsurf-session-<uuid>"}
签名:    <HMAC-SHA256 签名>
```

特点：
- 认证是**会话级**，不包含模型授权信息
- 签名密钥在客户端存储（LevelDB 中）
- JWT 每 5 分钟刷新一次（`jwt-refresh-interval`）

## 捕获的 API 调用

从 mitmproxy 流量文件 (`/tmp/windsurf_flows.mitm`) 提取：

### 1. GetUserStatus (2 次请求/响应)

- **目的**: 获取用户状态、订阅信息、信用额度
- **请求流向**: `language_server` → `server.self-serve.windsurf.com`
- **响应结构** (protobuf):
  ```
  GetUserStatusResponse {
    subscription_tier: ...
    credits_remaining: ...
    billing_model: ...
    team_id: ...
    user_id: ...
  }
  ```
- **关键字段**: 可能包含 `credits_remaining` 和 `billing_model_uid`

### 2. GetCliModelConfigs (多次)

- **目的**: 获取模型配置缓存（刷新 model_configs_v2.bin 和 team_settings.bin 的本地缓存）
- **触发时机**: 启动时和定期刷新

### 3. GetChatMessage (1 次请求/响应)

- **目的**: 核心 Cascade 聊天消息
- **URL**: `server.self-serve.windsurf.com/codeium.CortexBackend/GetChatMessage`
- **请求体**: protobuf 编码，包含:
  - `message` (用户消息)
  - `conversation_id`
  - `model_uid`
  - `requested_model_uid`
- **响应**: gzip 压缩的 protobuf，包含模型回复

### 4. CASCADE_STEP_COMPLETED (多次)

- **目的**: Cascade 步完成报告
- **关键发现**: 
  ```
  model = "claude-opus-4-7-max-fast"  ← 最高级模型！
  ```
- **响应字段**:
  ```protobuf
  status = CORTEX_STEP_STATUS_DONE
  source = CORTEX_STEP_SOURCE_SYSTEM
  step_type = CORTEX_STEP_TYPE_ERROR_MESSAGE
  trajectoryId: <uuid>
  stepIndex: 0
  is_tool_call: false
  userErrorMessage: <错误消息>
  ```

### 5. CASCADE_ERROR_STEP

- **目的**: Cascade 错误报告
- **常见错误**:
  - `proxyconnect tcp: dial tcp 127.0.0.1:8080: connect: connection refused`
    - 原因: mitmproxy 未运行时的代理连接失败

### 6. CASCADE_MCP_SERVER_INIT

- **目的**: MCP 服务器初始化报告

## Unleash API

**端点**: `unleash.codeium.com`

**调用模式**:
- `GET /api/frontend` — 注册 Unleash 客户端
- `GET /api/frontend/metrics` — 报告使用指标
- 定期轮询获取最新特征开关

## Connect-RPC 协议细节

**请求头**:
```
POST /codeium.CortexBackend/GetChatMessage HTTP/1.1
Host: server.self-serve.windsurf.com
Content-Type: application/proto
connect-protocol-version: 1
Authorization: Basic devin-session-token$<JWT>
Accept-Encoding: gzip
User-Agent: devin/<version>
```

**响应头**:
```
HTTP/1.1 200 OK
Content-Type: application/proto
Content-Encoding: gzip
connect-content-type: application/proto
```

## LLM 推理调用

推理调用可能**不经过** mitmproxy（取决于配置）：
- 模型推理端点由 `handler` 字段决定（如 `strawberry-pancake`）
- 这些调用可能直接路由到模型提供商 API
- 在代理模式下，这些调用可能失败（TLS 证书问题）
