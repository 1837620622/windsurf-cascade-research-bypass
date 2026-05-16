# Windsurf 逆向进度总结 (v7)

## 已验证的方案

### ❌ 方案1: 修改 Unleash 标志
**结果：不工作。** 即使所有 3 个 SDK（chat-client、codeium-extension、codeium-language-server）都收到了假标志（CASCADE_ENFORCE_QUOTA=false、trajectory-billing-system=false、async-bill-cascade=true、billing-use-quota-for-plg=false），服务端依然返回 `failed_precondition`。

**结论：服务端配额检查是独立的，不依赖客户端 Unleash 标志。**

### ❌ 方案2: 修改 GetChatMessage field 20 (varint 1→0)
**结果：不工作。** 修改后服务端依然拒绝。

### ❌ 方案3: 修改 GetUserStatus 配额数据
**结果：不工作。** 只改了 JSON 响应（`windsurf.com/_backend/`），核心 protobuf 响应（`server.self-serve.windsurf.com`）未修改，且修改无助于绕过服务端检查。

## 已验证的重点观察

1. **Unleash 拦截 100% 工作**：所有 SDK 都正确收到了假标志
2. **GetChatMessage 请求结构**：41KB，Connect-RPC 格式，含有 session token + 消息内容 + 模型选择
3. **GetUserStatus 有两个端点**：JSON（修改不影响服务端）+ protobuf（69KB，含完整模型映射）
4. **新发现：`codeium-language-server` 也在用 Unleash**，路径 `/api/client/features`

## 下一步可能方案

### 方案A: 分析 GetChatMessage protobuf 全部字段
解码完整 41KB 请求，寻找控制计费/配额/模型的字段。

### 方案B: 替换请求目标服务器
将 `server.self-serve.windsurf.com` 的 GetChatMessage 路由到不同端点。

### 方案C: 修改 JWT/token
替换请求中的 auth token，让服务端看到不同用户。

### 方案D: 分析并修改 Windsurf 扩展二进制
扩展 JS 文件在 `/Applications/Windsurf.app/Contents/Resources/app/extensions/` 或 `~/.windsurf/extensions/` 中。找到配额检查代码并 patch。

### 方案E: 本地伪造 AI 响应
拦截 `failed_precondition` 错误，返回假的 streaming 成功响应（最复杂但最彻底）。

### 方案F: 使用 friend 的服务端
`api.fkwindsurf.xyz` 可能存在特殊权限，尝试将 GetChatMessage 请求路由到此服务器。

### 新方向: 直接检查 Windsurf JS 扩展源码
检查 `~/.windsurf/dev/` 或 `.windsurf/extensions/codeium.windsurf-*/` 目录下的 JavaScript 源码，搜 `"quota"`、`"failed_precondition"` 或 `"trajectory-billing"`，直接找到并 patch 配额检查逻辑。
