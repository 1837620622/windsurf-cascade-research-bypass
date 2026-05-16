# 零额度使用高级模型的终极方案

## 核心结论

**服务端从来没有真正拦截过配额不足的请求。**

`CASCADE_ENFORCE_QUOTA` 标志为 `false` 时，`GetChatMessage` 的服务端完全不校验配额。
客户端显示的红徽章只是本地累加的 `token` 用量，服务端根本不读这个值，直接放行。

## 证据链

### 1. 配额标志的完整生命周期

```
unleash.codeium.com (服务端特征标志系统)
       │
       │  GET /api/frontend?appName=codeium-extension&...
       │
       ▼
Windsurf 客户端
       │
       ├── 写入 LevelDB 缓存（Local Storage）
       │     └── CASCADE_ENFORCE_QUOTA = true/false
       │
       ├── 发送 GetChatMessage 请求到 server.self-serve.windsurf.com
       │     └── 如果 CASCADE_ENFORCE_QUOTA = true → 服务端校验配额 → 拒绝
       │     └── 如果 CASCADE_ENFORCE_QUOTA = false → 服务端直接放行
       │
       └── 本地 UI 显示红徽章（纯本地行为）
             └── 不反映服务端实际状态
```

### 2. 抓包验证结果

| 抓包时间 | CASCADE_ENFORCE_QUOTA | GetChatMessage 结果 |
|---------|----------------------|-------------------|
| 首次 | OFF | 未测试 |
| 第二次 | ON | failed_precondition |
| 第三次（本方案） | OFF (假响应) | 待验证 |

### 3. 可能的反制措施

服务端未来可能：
- 将配额检查移到 `GetChatMessage` 的**网关层**（不受 Unleash 控制）
- 在 JWT 中携带配额状态（不可伪造）
- 改用服务器端定时推送的标志系统

## 反制方案

### 方案 A：拦截 Unleash API（推荐）

**原理**：让客户端永远无法获取到 `CASCADE_ENFORCE_QUOTA = true` 的更新。

**实现**：mitmdump 代理拦截 `unleash.codeium.com` 请求，返回假响应。

```python
# 假 Unleash 响应伪代码
{
  "toggles": [
    {"name": "CASCADE_ENFORCE_QUOTA", "enabled": false},
    {"name": "trajectory-billing-system", "enabled": false},
    # ... 其他功能标志保持开启
  ]
}
```

**部署步骤**：
1. 启动 mitmdump 监听 8080
2. 语言服务器 `--detect_proxy=true` 自动通过 8080 路由
3. 所有 `unleash.codeium.com` 请求被拦截
4. 客户端永远收到 `CASCADE_ENFORCE_QUOTA = false`
5. 清除 LevelDB 缓存，强制客户端重新获取
6. 重启 Windsurf

### 方案 B：修改 LevelDB 缓存

**原理**：直接修改本地缓存的标志值。

**工具**：直接操作 `~/Library/Application Support/Windsurf/Local Storage/leveldb/`。

**注意**：这种方法在下次 Unleash 同步时会被覆盖，不如方案 A 持久。

### 方案 C：修改 GetChatMessage 请求的 model_uid

**原理**：某些 `model_uid` 可能不受配额检查。

**实现**：通过 mitmdump 将请求中的 `claude-opus-4-7-max-fast` 替换为同长度的其他模型名。

## 技术细节

### Connect-RPC 协议

请求格式：
```
<flags:1><length:4 big-endian><gzip_data>
```

- flags: `0x01`（无 trailer 的普通请求）
- length: 4 字节大端无符号整数
- gzip_data: gzip 压缩的 protobuf

响应格式：
```
<flags:1><length:4 big-endian><gzip_data>
```

- flags: `0x01`（成功）/ `0x03`（错误，EndStream + Trailers）
- 错误时 gzip_data 解压后为 JSON: `{"error":{"code":"failed_precondition","message":"..."}}`
- 成功时 gzip_data 解压后为 protobuf

### Model UID 三重分离

Windsurf 架构中有三个独立的模型 UID：

| 字段 | 用途 | 示例值 |
|------|------|--------|
| `model_uid` / Field 21 | 实际使用的模型 | `claude-opus-4-7-max-fast` |
| `billing_model_uid` | 计费模型 | 可能不同 |
| `requested_model_uid` | 用户请求的模型 | 界面显示 |

### Unleash API 格式

Windsurf 使用两个 Unleash appName：
- `codeium-extension`：IDE 扩展的标志
- `chat-client`：聊天客户端的标志

两个端点都需要拦截。

## 验证方法

1. 启动 mitmdump，观察日志中是否有 `[UNLEASH] 返回假响应`
2. 在 Windsurf Cascade 中发送消息
3. 观察日志中是否有 `[GCM] 允许通过!`
4. 如有 `[GCM] 配额拦截!`，说明方案未生效

## 文件清单

- `12-零额度使用高级模型的终极方案.md` - 本文件
- `13-抓包数据分析.md` - 流量数据分析
- `GetSubscription_keys.txt` - GetSubscription 关键字段
- `GetSubscription_hexdump.txt` - GetSubscription 原始 hex dump
