# Windsurf 二进制架构总体分析

## 概述

Windsurf 编辑器基于 VSCode，包含三个核心二进制模块和多个配置缓存文件。以下是对其架构的全面逆向分析。

## 核心二进制文件

### 1. 语言服务器 `language_server_macos_arm` (163MB)
- **位置**: `/Applications/Windsurf.app/Contents/Resources/app/extensions/windsurf/bin/language_server_macos_arm`
- **语言**: Go
- **职责**:
  - 模型路由（决定请求发往哪个模型后端）
  - 配额执行（检查用户是否有足够额度）
  - Flex Credits 管理
  - Cascade 执行引擎
  - MCP 服务器支持
  - Connect-RPC 通信（向 `server.self-serve.windsurf.com` 发送请求）
- **通信协议**: Connect-RPC over HTTP/1.1
  - `Content-Type: application/proto`
  - `connect-protocol-version: 1`
  - 响应为 gzip 压缩的 protobuf

### 2. Devin 二进制 `devin` (110MB)
- **位置**: `/Applications/Windsurf.app/Contents/Resources/app/extensions/windsurf/devin/bin/devin`
- **语言**: Rust
- **职责**:
  - ACP (Agent Communication Protocol) 实现
  - SSE 流式传输
  - 子代理支持
  - 通过 API Key 认证
- **特征**: 构建工具为 chisel (Rust)

### 3. VSCode 扩展 `extension.js` (9.6MB)
- **位置**: `/Applications/Windsurf.app/Contents/Resources/app/extensions/windsurf/dist/extension.js`
- **职责**:
  - Unleash 功能开关客户端
  - Credential/账单展示逻辑
  - Protobuf 定义（包含 ModelUsageStats）

## 配置缓存文件

### `model_configs_v2.bin`
- **位置**: `~/.cache/devin/cli/model_configs_v2.bin`
- **编码**: Protobuf
- **内容**: 所有可用模型的完整配置
  - 显示名称 (display_name)
  - 内部 ID (model_uid)
  - Token 限制 (context_length/max_output_tokens)
  - 努力级别 (effort_levels: low/medium/high)
  - 速度模式 (fast_reasoning: true/false)
  - 定价信息 (pricing 对象)
  - 后端处理器 (handler: 如 `strawberry-pancake`)
  - Tokenizer 类型 (LLAMA_WITH_SPECIAL2 / CL100K_WITH_SPECIAL2)
- **路由**: 所有模型经过 `https://server.codeium.com`（但在实际流量中我们看到使用 `server.self-serve.windsurf.com`）

### `team_settings.bin`
- **位置**: `~/.cache/devin/cli/team_settings.bin`
- **编码**: Protobuf
- **内容**: 当前用户/团队的模型可用性优先级列表

## 进程架构

```
Windsurf.app (Electron)
  ├── Extension Host (extension.js)
  │     ├── Unleash 客户端 (特征开关)
  │     ├── Credits/账单展示
  │     └── ModelUsageStats 追踪
  ├── language_server_macos_arm (Go, 163MB)
  │     ├── Connect-RPC → server.self-serve.windsurf.com
  │     ├── Unleash → unleash.codeium.com
  │     ├── 模型路由 (strawberry-pancake handler)
  │     ├── 配额执行 (CASCADE_ENFORCE_QUOTA)
  │     └── MCP 服务器
  └── devin (Rust, 110MB)
        ├── ACP (Agent Communication Protocol)
        ├── SSE 流式传输
        └── 子代理管理
```

## 通信流

```
用户消息
    ↓
Extension Host (extension.js)
    ↓
language_server_macos_arm (Go 二进制)
    ├──→ GET /api/client/register (内部注册)
    ├──→ server.self-serve.windsurf.com (Connect-RPC)
    │     ├── GetUserStatus
    │     ├── GetCliModelConfigs
    │     ├── GetChatMessage
    │     ├── CASCADE_STEP_COMPLETED
    │     ├── CASCADE_ERROR_STEP
    │     └── CASCADE_MCP_SERVER_INIT
    └──→ 模型推理（直接连接模型提供商）
```

## 存储层

| 存储 | 位置 | 内容 |
|------|------|------|
| LevelDB | `~/Library/Application Support/Windsurf/Local Storage/leveldb/` | Unleash 特征开关、JWT 缓存 |
| IndexedDB LevelDB | `.../IndexedDB/vscode-file_vscode-app_0.indexeddb.leveldb/` | 工作区状态 |
| Cache.db | `~/Library/Caches/com.exafunction.windsurf/Cache.db` | URL 响应缓存（当前为空） |
| blob_storage | `~/Library/Application Support/Windsurf/blob_storage/` | Blob 存储（当前为空） |
| Session Storage | `.../Session Storage/` | 会话存储（当前为空） |

## 关键发现

1. **`billing_model_uid` ≠ `model_uid`**: 架构的核心设计——可以为用户提供高级模型，但按较低层级计费。
2. **认证是会话级而非模型级**: `devin-session-token$JWT` 仅包含 session_id，无模型级授权。
3. **主 API 端点是 `server.self-serve.windsurf.com`**（非 `server.codeium.com`）。
4. **模型赋值使用 TTL 缓存**: 缓存的配置在 `model_configs_v2.bin` 和 `team_settings.bin` 中跨会话持久保存。
5. **配额和计费强制执行在服务端被禁用**: 通过 Unleash 特征开关确认。
