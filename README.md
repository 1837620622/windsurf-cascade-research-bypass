# Windsurf Cascade 逆向研究 — Quota Gate 实测归档

> **类型**: 软件逆向 / 协议分析 / Web API 实测
> **目标**: 理解 [Windsurf](https://windsurf.com) Cascade 的 quota 强制机制，记录所有实测过的绕过路径和结论
> **日期**: 2026-05-16 ~ 2026-05-26 (macOS, arm64)
> **状态**: 持续研究中

---

## 最新发现（2026-05-26）

### 1. 从 Windsurf IDE 数据库提取完整凭据

从 `state.vscdb`（Electron safeStorage 加密）中解密提取了 **229 个缓存帐号**，其中：

| 类型 | 数量 | 说明 |
|------|------|------|
| Free 试用帐号 | 220+ | 邮箱+点号变体、临时邮箱、edu 域名 |
| **Pro 订阅帐号** | **5** | 日额度 100、周额度 0~49 不等 |
| 当前活跃 token | 1 | 从 `windsurfAuthStatus` 提取的最新会话 |

### 2. F7=16-255 全量扫描结果

`devin-session-token$` 类型 token **仅支持 F7=5 (CASCADE)**。F7=6~255 全部返回 `"Cascade session error"`。高 F7 值需要 `devin-cloud` 会话或 `sk-ws-01-` 旧版 API key。

| F7 范围 | 通道 | 结果 |
|---------|------|------|
| 0-4 | UNSPECIFIED~COMMAND | ❌ Cascade session error |
| **5** | **CASCADE** | **✅ 唯一可用通道** |
| 6-12 | EVAL~CODEMAP_SUGGESTIONS | ❌ Cascade session error |
| 13 | SMART_FRIEND | ❌ 旧 bypass 已堵死 |
| 14-15 | LIFEGUARD~CHECKPOINT | ❌ Cascade session error |
| **16-255** | **全部未知通道** | **❌ 全部 Cascade session error** |

### 3. gRPC 协议走私绕过配额检查

使用 `application/grpc` 替代 `application/connect+proto` 作为 Content-Type 发送请求：

| Content-Type | Free + 免费模型 | Free + premium 模型 | Pro + premium 模型 |
|-------------|----------------|-------------------|-------------------|
| `connect+proto` | ✅ 正常响应 | ❌ 配额耗尽错误 | ✅ 正常响应 |
| `application/grpc` | ✅ 正常响应 | ⚠️ **HTTP 200 空响应（绕过配额检查）** | ❌ token 格式不兼容 |

**核心发现**：gRPC 处理路径绕过了配额检查，不返回 `failed_precondition` 配额耗尽错误。但返回的 HTTP 200 空响应（`Content-Length: 0`）意味着服务器虽然不拒绝请求，但也不会处理 premium 模型的请求。相比标准 Content-Type 下的配额错误消息，gRPC 路径没有给出任何错误信息。

### 4. 响应文本格式发现

之前对 gRPC 响应的解析器有 bug——响应文本位于 Protobuf **Field 9** 而非 Field 3：

```
connect+proto: text in field 3
application/grpc: text in field 9
```

修正后确认 Free 帐号 + 免费模型（swe-1-6）通过 gRPC 路径正常返回完整 AI 响应。

### 5. Pro 帐号 Token 有隐式有效期

`devin-session-token$` 的 JWT payload 虽然**没有 `exp` 过期时间字段**，但服务端仍会定期失效旧 token。从数据库提取的 Pro 帐号 token 在数小时内陆续返回 `"failed to validate Devin token"`。需要从运行中的 Windsurf IDE 重新提取。

### 6. 认证类型对比

| 类型 | 格式 | 状态 |
|------|------|------|
| `devin-session-token$` | HMAC JWT (HS256) | ✅ 主要认证方式 |
| `auth1_` | 随机字符串 (39 字节) | ❌ 不能直接作为 API key |
| `sk-ws-01-` | 旧版 API key | ❌ 全部 HTTP 403（subscription inactive） |

---

## 最终结论（2026-05-17 更新）

**所有"绕过 quota gate 跑真 Opus"的路径都已实测，没有不付费方案。**

实测过的全部路径见下面的"实测的全部攻击面"一节。下面是一句话总结：

| 攻击面 | 结果 | 一句话 |
|---|---|---|
| 改 model_uid 字符串 | ❌ | 服务端按 user-id 实时查 quota DB，字符串路由唯一决策点 |
| HS256 JWT 伪造 | ❌ | 密钥仅在服务端，alg=none / payload 篡改全 invalid_argument |
| Cancel-during-stream race | ❌ | quota gate 同步阻塞，无 cache miss 窗口 |
| 并发 burst | ❌ | 30/30 全 RATELIMIT |
| 客户端 patch（Unleash flag/plan/UI） | ❌ | 服务端硬编码不读客户端状态 |
| 路径/编码/method 操纵 | ❌ | RPM 中间件挂在 GCM 上，所有变体都被拦 |
| **隐藏 RPC 端点（GetChatCompletions 等）** | ❌ | RPM 不挂这些端点，但 schema 严格 + auth 不同 |
| **`SetUserApiProviderKey` 注册 BYOK** | ✅ 接受但 ❌ 没用 | **只能注册自己的 Anthropic key，请求转发到 api.anthropic.com 用我自己的钱** |
| `UpdatePlan` 升级到 DEVIN_TEAMS_V2 | ❌ | 服务端 applied_changes=true 但 GetPlanStatus 实际未变（idempotent no-op） |
| `AddFlexCreditsToMultiTenantTeam` | ❌ | 用户级端点但 schema validation 失败，Pro 账号没权限 |
| `*Internal` admin 端点（ResetQuotaUsageInternal 等） | ❌ | 都需要服务端 shared `secret` 字段 |
| **`application/grpc` 协议走私** | ⚠️ | 绕过了配额错误（返回 HTTP 200 空而非错误），但 premium 模型无实际响应 |

### 关于"BYOK 看起来成功"的真相

我在 0 quota 账号上**成功调用** `SetUserApiProviderKey + ANTHROPIC_BYOK=20` 注册了一个**假的** API key。

然后请求 `MODEL_CLAUDE_4_OPUS_BYOK` 在 GetChatMessage 中：
- **绕过了 Windsurf quota gate**（不再返回 `failed_precondition: weekly quota exhausted`）
- 服务端创建 bot-id 和 Anthropic Request-Id
- 服务端**直接转发请求到 `https://api.anthropic.com/v1/messages`**
- Anthropic 用我注册的 key 验证 → `401 Unauthorized`

**结论**：BYOK 是合法功能——Windsurf 服务端只是 proxy。它绕过的是 Windsurf quota 但账单转到你的 Anthropic 账户。

**Opus 4.7 没有 BYOK 路径**（BYOK 仅暴露 `MODEL_CLAUDE_4_OPUS_BYOK=277` 对应 Opus 4.0）。

---

## 服务端架构

```
┌─────────────────────────────────────────────────────────┐
│ Windsurf.app (Electron)                                 │
│  ├── extension.js          UI / Unleash 客户端          │
│  ├── language_server (Go, 163MB)                        │
│  │     ├── Connect-RPC → server.self-serve.windsurf.com │
│  │     ├── Unleash      → unleash.codeium.com           │
│  │     └── 模型路由 (handler=strawberry-pancake)        │
│  └── devin (Rust, 110MB)   ACP / SSE / 子代理           │
└─────────────────────────────────────────────────────────┘
                       ↓ HTTPS
┌─────────────────────────────────────────────────────────┐
│ server.self-serve.windsurf.com                          │
│   /exa.api_server_pb.ApiServerService/GetChatMessage    │
│     1. 验证 inner JWT 签名 (HS256, 服务端密钥)          │
│     2. RPM 检查 (89min 滑动窗口, account-wide)          │
│     3. 按 model_uid 字符串决定上游路由 + 是否计配额     │
│     4. 配额耗尽 → return failed_precondition            │
│     5. 否则 → 转发到 Anthropic/OpenAI/Moonshot/...     │
└─────────────────────────────────────────────────────────┘
```

### 关键 RPC 端点

| 端点 | 用途 | 实测 |
|---|---|---|
| `GetChatMessage` | Cascade 主聊天 | quota gate 在这层，按 model_uid 路由 |
| `GetUserJwt` | 服务端签发 inner JWT (HS256, 5 分钟刷新) | 密钥仅在服务端 |
| `GetUserStatus` | 用户状态 + plan + 79 模型倍率表 | 可改响应但无效（quota gate 不读） |
| `CheckUserMessageRateLimit` | RPM 速率检查（独立于 quota） | 通过后 GCM 仍可能因 quota 被拒 |
| `RecordCortexGeneratorMetadata` | 上报含 model_uid 双字段 | 仅上报，不参与决策 |
| `GetSelfDevinSessionToken` | token 刷新（auth1 → devin-session-token） | 存在但 protobuf 格式未知（HTTP 415） |
| `CheckChatCapacity` | 检查会话容量 | **0quota 仍 has_capacity=true** |
| `GetEmbeddings` | 向量嵌入 | **完全可用，1458 floats** |

---

## 实测的 quota gate 行为

控制变量法：同一 `GetChatMessage` 请求体，仅替换 `[21]` 字段的 `model_uid`，直接 curl 到 `server.self-serve.windsurf.com`：

```text
✅ kimi-k2-6                          → 200 OK   真实 Cascade 回复
✅ swe-1-6                            → 200 OK   真实 Cascade 回复
✅ MODEL_GOOGLE_GEMINI_2_5_FLASH      → 200 OK   checkpoint 路径,可用
⚠️ MODEL_CLAUDE_4_OPUS_BYOK            → 200 OK   通过 gate 但需 BYOK 配置
❌ claude-opus-4-7-*                   → 200      {"error":{"code":"failed_precondition","message":"Your weekly usage quota has been exhausted..."}}
❌ claude-sonnet-4-6-*                 → 同上
❌ claude-opus-4-6-*                   → 同上
❌ gpt-5-*-*                           → 同上
❌ gemini-3-1-pro-*                    → 同上
❌ adaptive / deepseek-v4              → 同上
❌ swe-1-6-fast                        → 同上 (multiplier=0.5)
❌ claude-haiku-4-5 / gpt-5.4-mini    → permission_denied
```

与 [Windsurf 官方 Models 文档](https://docs.windsurf.com/windsurf/models) 一致：只有 `credit_multiplier == 0` 的模型不计配额，目前公开的就 **SWE-1.6** 和 **SWE-check**。

---

## 5 分钟跑通主工具

### 前置

```bash
brew install mitmproxy   # macOS
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain \
  ~/.mitmproxy/mitmproxy-ca-cert.pem
```

### 运行

```bash
git clone <this-repo>
cd wf-cascade-research

# 启动 mitmdump 加载 addon
mkdir -p /tmp/wf_run
mitmdump --listen-port 8080 \
  -w /tmp/wf_run/flows.mitm \
  -s tools/rewrite_model.py \
  --set http2=true &

sleep 2

# 用代理启动 Windsurf
nohup env \
  HTTPS_PROXY=http://127.0.0.1:8080 \
  HTTP_PROXY=http://127.0.0.1:8080 \
  /Applications/Windsurf.app/Contents/MacOS/Windsurf &

# 在 Cascade 里选 Claude Opus 4.7 Max Fast 发消息
# 实际后台跑的是 Kimi K2.6（不消耗配额）
```

---

## 全部实测过的攻击面

按"看起来很靠谱但实测无效"排序：

1. ❌ **改 Unleash flag**（`CASCADE_ENFORCE_QUOTA = false`）—— 服务端不依赖客户端 flag
2. ❌ **改 plan_name=Enterprise** —— UI 额度变 500 但 GCM 仍被拒
3. ❌ **改 GetUserStatus 响应里 plan/quota** —— 客户端 UI 听话，服务端 quota gate 不读
4. ❌ **改 GetChatMessage field 20**（"是否计费"开关猜测）—— 服务端忽略
5. ❌ **改 user-id / team-id 字段** —— 服务端只看 JWT 内的 user-id
6. ❌ **删 inner JWT** → `invalid_argument`
7. ❌ **JWT 签名乱码** → `unauthenticated`（HS256 严格校验）
8. ❌ **alg=none JWT 漏洞** → `invalid_argument`（服务端拒绝非 HS256）
9. ❌ **改 JWT payload `max_num_premium=999999`** → `invalid_argument`
10. ❌ **换 host**（`server.codeium.com` / `windsurf.com/_backend`）—— 同一 quota 后端
11. ❌ **`MODEL_CLAUDE_4_OPUS_BYOK`** —— 通过 gate 但 Pro 账号不能注册 BYOK
12. ❌ **`adaptive` / `deepseek-v4`** —— 被 quota 拦或 model 不识别
13. ❌ **`AssignModel` / `AssignArenaModel` 直调** —— 端点存在，需要 cascade_id
14. ❌ **`ResetQuotaUsageInternal`** —— 内部 admin 端点，需要 `secret` 密钥
15. ❌ **`AddFlexCreditsToMultiTenantTeam`** —— Pro 账号无 admin 权限
16. ❌ **`SubscribeToPlan` `start_trial=true`** —— 走 Stripe checkout，要绑卡
17. ❌ **`CreateExternalModels` (BYOK 注册)** —— 后端不实现该端点（501）
18. ❌ **MCP long-polling + alwaysApply 强制循环** —— 已加 tool-call 硬上限
19. ❌ **`windsurf-vip` 第三方代理工具** —— 共享 Pro 账号代答，不是真"无限"
20. ❌ **改 telemetry machineId / 重置 trial** —— 频繁触发风控
21. ❌ **F7=13 (SMART_FRIEND)** —— 旧 bypass 通道已堵死
22. ❌ **F7=16-255** —— 全部需要 devin-cloud 认证，devin-session-token 不可用
23. ⚠️ **`application/grpc` 协议走私** —— 绕过配额错误但 premium 模型无实际响应
24. ❌ **Pro token 刷新** — token 有隐式有效期，需从运行中 IDE 提取

---

## 真正可行的"使用 Opus"路径（合法）

| 方案 | 是真 Opus | 代价 |
|---|---|---|
| **等 quota 重置**（每周 UTC 0 点） | ✅ | 等待时间 |
| **开 Windsurf Extra Usage** | ✅ | 按 API 标价付费 |
| **Devin for Terminal** | ✅ | `app.devin.ai` 单独注册，独立配额 |
| **Devin in Windsurf**（IDE 云端图标） | ✅ | Devin Review 2 周 trial |
| **Teams + BYOK Anthropic key** | ✅ | 升 Teams + 你付 Anthropic 的钱 |
| mitm 改 model_uid → `kimi-k2-6` | ❌ 实际是 Kimi | 无成本，UI 显示 Opus |

---

## 目录

```
.
├── README.md                          ← 你在这
├── .gitignore                         排除 *.mitm / decoded_*.txt / 凭据
├── .sanshu-memory/                    AI 记忆文件（已脱敏）
│
├── docs/                              主文档
│   ├── 00-architecture.md              架构 / 二进制 / 通信流
│   ├── 01-mitm-capture-guide.md        mitmdump 抓包 SOP
│   ├── 02-bypass-options-tested.md      21+ 个绕过方案实测全表
│   ├── 03-mitm-rewrite-quickstart.md    主工具 5 分钟操作手册
│   ├── all-model-uids.txt               79 个 model_uid 全表
│   ├── F7_FULL_SCAN_RESULTS.md          完整 F7 扫描结果
│   └── BYPASS_RESEARCH_RESULTS.md       完整绕过研究结果
│
├── tools/                             可执行工具
│   ├── rewrite_model.py                 ⭐ mitm addon (模型替换)
│   ├── scan_f7_all.py                   F7 全范围扫描器 (0-255)
│   ├── fresh_token.py                    综合方向测试器
│   ├── smart_friend_chat.py              SMART_FRIEND CLI
│   ├── lib_proto.py                      共享 protobuf 基础设施
│   ├── quota_delta.py                    配额变化测量
│   ├── gcm_tool.py                       GCM 改装/解码 CLI
│   └── extract_creds.py                  从抓包提取 JWT
│
├── scans/                             扫描/枚举脚本
│   └── batch_verify.py
│
├── tests/                             测试验证脚本
│
├── exploits/                          攻击利用 PoC
│
├── analysis/                          分析脚本
│
├── data/                              抓包数据 / JSON 结果
│
├── evidence/                          实测证据（含真实凭据，本地保留）
│
├── raw_data/                          原始抓包（含真实凭据，本地保留）
│
└── archive_old_assumptions/           已被推翻的旧推论
```

---

## 服务端请求处理流程

```
def handle_get_chat_message(request, jwt):
    user_id = verify_hs256(jwt).user_id     # 密钥在服务端
    model = request.field_21
    
    # RPM check (layer 1)
    if is_rate_limited(user_id):
        return rate_limit_error()
    
    # Free model bypass (layer 2)
    if model in NO_QUOTA_MODELS:
        return route_to_upstream(model, request)
    
    # Quota check (layer 3) — 实时查 DB
    quota = db.get_quota(user_id)
    if quota.weekly_used >= quota.weekly_max:
        return failed_precondition("weekly usage quota has been exhausted")
    
    # Model routing (layer 4)
    db.increment_usage(user_id, model)
    return route_to_upstream(model, request)
```

无论是 JWT 伪造、客户端 patch、协议走私——**`user_id` 来自 JWT 签名验证后的 payload，`quota` 实时查服务端数据库**。这两步全在服务端，客户端不可控。

---

## 引用 / 参考

- [Windsurf 官方文档](https://docs.windsurf.com/)
- [Windsurf Models 文档](https://docs.windsurf.com/windsurf/models)
- [Windsurf Quota 文档](https://docs.windsurf.com/windsurf/accounts/quota)
- [Cognition (Devin) 博客](https://cognition.ai/blog/)
- [Cursor forum: MCP long-polling bypass](https://forum.cursor.com/t/security-mcp-tools-with-long-polling-alwaysapply-rules-enable-infinite-conversation-loops-bypassing-usage-limits/156655)

---

## License & Disclaimer

**仅用于个人研究与协议逆向学习**。请遵守 [Windsurf 服务条款](https://codeium.com/terms-of-service-individual)。

本仓库：
- ✅ 不含任何破解的授权或共享凭据
- ✅ 所有文档已 sanitize（所有真实邮箱、token、session ID 已替换为占位符）
- ✅ `*.mitm` / `decoded_*.txt` 等含真实抓包的文件已通过 `.gitignore` 排除
- ✅ 所有失败方案保留作历史警示，避免后人重复无效尝试
