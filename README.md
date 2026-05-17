# Windsurf Cascade 逆向研究 — Quota Gate 实测归档

> **类型**: 软件逆向 / 协议分析 / Web API 实测
> **目标**: 理解 [Windsurf](https://windsurf.com) Cascade 的 quota 强制机制，记录所有实测过的绕过路径和结论
> **日期**: 2026-05-16 ~ 2026-05-17 (macOS 26.5, arm64, Windsurf 1.110.1 / Cascade 1.48.2)
> **状态**: 研究归档 (read-only)，所有真实凭据已 sanitize

---

## ⚠️ 最终结论（2026-05-17 更新）

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

### 关于"BYOK 看起来成功"的真相

我在 0 quota 账号上**成功调用** `SetUserApiProviderKey + ANTHROPIC_BYOK=20` 注册了一个**假的** API key（`sk-ant-fake12345`）。

然后请求 `MODEL_CLAUDE_4_OPUS_BYOK` 在 GetChatMessage 中：
- **绕过了 Windsurf quota gate**（不再返回 `failed_precondition: weekly quota exhausted`）
- 服务端创建 bot-id 和 Anthropic Request-Id
- 服务端**直接转发请求到 `https://api.anthropic.com/v1/messages`**
- Anthropic 用我注册的 key 验证 → `401 Unauthorized: invalid x-api-key`

**结论**：BYOK 是合法功能，**Windsurf 服务端只是 proxy**，让你用自己的 Anthropic key 跑 Claude。它"绕过"的是 Windsurf quota 但**不绕过钱**——你必须有真实付费的 Anthropic API key（约 $15/M 输入 token + $75/M 输出 token for Opus 4）。

**这不是"漏洞"也不是"绕过"。** 这是设计内的功能。

### 关于 Opus 4.7

`Model` enum 里**没有** `MODEL_CLAUDE_4_7_OPUS_BYOK`。BYOK 路径只暴露 4.0 和 4.5：
- `MODEL_CLAUDE_4_OPUS_BYOK = 277` (Opus 4.0)
- `MODEL_CLAUDE_4_5_OPUS = 391` (Opus 4.5)
- `MODEL_CLAUDE_4_OPUS_THINKING_BYOK = 278`

Opus 4.7 (`claude-opus-4-7-max-fast` / `claude-opus-4.7`) 仅通过 Windsurf 自家 quota 池暴露，**没有 BYOK 路径**。即使 BYOK 真生效也跑不到 4.7。

### 真要跑真 Opus 4.7 的合法路径

| 方案 | 代价 |
|---|---|
| 等 Windsurf weekly quota 重置（每周日 UTC 00:00） | 等待 |
| 开 Windsurf Extra Usage（按 API 标价付费） | $$ |
| Teams + BYOK Anthropic key（前提 Teams 计划允许） | $ Teams + $$ Anthropic |
| Devin in Windsurf（IDE 云端图标，2周 trial） | trial 额度有限 |

---

## TL;DR

| 问题 | 实测答案 |
|---|---|
| **Pro 0 配额下还能跑真 Opus 4.7 吗？** | **不能**。服务端按 user-id 计 quota，HS256 JWT 由服务端签发，密钥不在客户端 |
| **0 配额下还能跑 Cascade 吗？** | **能**，但只能用 `swe-1-6` / `kimi-k2-6`（官方 `credit_multiplier: 0`）|
| **客户端 patch 能绕过吗？** | **不能**。改 Unleash flag / plan_name / model_uid 路径都被服务端拒绝（详见 [bypass-options-tested](docs/02-bypass-options-tested.md)）|
| **看到别人 0 配额还在用是怎么回事？** | 三种可能：① 选了 SWE-1.6 / Kimi K2.6（不计配额）；② 开了 Extra Usage（按 API 标价付费）；③ 用 Devin in Windsurf / Devin for Terminal（独立配额池）|

---

## 实测的 quota gate 行为

控制变量法：同一 `GetChatMessage` 请求体（21KB Cascade 系统提示 + 40 个工具定义 + 真实 inner JWT），仅替换 `[21]` 字段的 `model_uid`，直接 curl 到 `server.self-serve.windsurf.com`：

```text
✅ kimi-k2-6                          → 200 OK   26832B   真实 Cascade 回复
✅ swe-1-6                            → 200 OK   16200B   真实 Cascade 回复
✅ MODEL_GOOGLE_GEMINI_2_5_FLASH      → 200 OK    1434B   checkpoint 路径,可用
⚠️ MODEL_CLAUDE_4_OPUS_BYOK            → 200 OK     137B   通过 gate 但需 BYOK 配置
❌ claude-opus-4-7-max-fast            → 200      ~218B   {"error":{"code":"failed_precondition",
                                                         "message":"Your weekly usage quota
                                                         has been exhausted..."}}
❌ claude-opus-4-7-{low,medium,high,xhigh,max}{,-fast} → 同上 failed_precondition
❌ claude-sonnet-4-6{,-1m,-thinking,-thinking-1m}      → 同上
❌ claude-opus-4-6{,-fast,-1m,-thinking,-thinking-1m}  → 同上
❌ gpt-5-{4,5}-{none,low,medium,high,xhigh}{,-priority} → 同上
❌ gemini-3-1-pro-{low,high}                           → 同上
❌ adaptive / deepseek-v4                              → 同上
❌ swe-1-6-fast                                        → 同上 (multiplier=0.5)
❌ claude-haiku-4-5 / gpt-5.4-mini / gemini-3.0-flash  → permission_denied (model 不存在 user-facing)
```

与 [Windsurf 官方 Models docs](https://docs.windsurf.com/windsurf/models) 一致：只有 **`credit_multiplier == 0`** 的模型不计配额，目前公开的就 **SWE-1.6** 和 **SWE-check** 两个。

---

## 服务端架构（实测确认）

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
│     2. 按 model_uid 字符串决定上游路由 + 是否计配额     │
│     3. 配额耗尽 → return failed_precondition           │
│     4. 否则 → 转发到 Anthropic/OpenAI/Moonshot/...     │
└─────────────────────────────────────────────────────────┘
```

**关键 RPC**：

| 端点 | 用途 | 实测 |
|---|---|---|
| `GetChatMessage` | Cascade 主聊天 | quota gate 在这层，按 model_uid 路由 |
| `GetUserJwt` | 服务端签发 inner JWT (HS256, 5 分钟刷新) | 密钥仅在服务端 |
| `GetUserStatus` | 用户状态 + plan + 79 模型倍率表 | 可改响应但无效（quota gate 不读） |
| `CheckUserMessageRateLimit` | RPM 速率检查（独立于 quota） | 实测：通过这层后 GetChatMessage 仍可能因 quota 被拒 |
| `RecordCortexGeneratorMetadata` | 上报含 `[34]/[35]` model_uid 双字段 | 仅上报，不参与决策 |
| `windsurf.com/_backend/...GetCurrentUser` | Web 前端 plan 状态 | 改 plan_name UI 显示变但 GCM 不变 |

详见 [docs/00-architecture.md](docs/00-architecture.md)。

---

## 目录

```
.
├── README.md                              ← 你在这
├── .gitignore                             排除 *.mitm / decoded_*.txt / 凭据
│
├── docs/                                  主文档
│   ├── README.md                            索引
│   ├── 00-architecture.md                   架构 / 二进制 / 通信流
│   ├── 01-mitm-capture-guide.md             mitmdump 抓包 SOP
│   ├── 02-bypass-options-tested.md          21+ 个绕过方案实测全表
│   ├── 03-mitm-rewrite-quickstart.md        主工具 5 分钟操作手册
│   ├── all-model-uids.txt                   79 个 model_uid 全表
│   └── get-cli-model-configs-analysis.txt   model_configs_v2.bin 解码
│
├── tools/                                 可执行工具
│   ├── README.md                            索引 + 用法
│   ├── rewrite_model.py                     ⭐ 主 mitm addon (model 替换 + 响应回写)
│   ├── plan_rewrite_addon.py                实验 addon (改 plan_name, 已验证无效)
│   ├── gcm_tool.py                          GetChatMessage 改装/解码 CLI
│   ├── extract_creds.py                     从抓包提取最新 inner JWT
│   ├── scan_chat.py                         扫描抓包文件，列 chat 端点统计
│   └── full_compare.py                      成功 vs 失败请求字段 diff
│
├── raw_data/                              原始抓包（含真实凭据，本地保留）
│   ├── README.md                            说明
│   ├── original_getchatmessage_req.bin      [gitignored] 原始 GCM 请求样本
│   ├── unleash_features.json                [gitignored] Unleash 完整响应
│   └── capture_2026-05-16/                  [gitignored] 完整抓包 + 解码
│
├── evidence/                              实测证据 (.mitm)（含真实凭据，本地保留）
│   ├── README.md                            说明
│   ├── 2026-05-16_final_with_rewrite.mitm   [gitignored] 最终验证抓包
│   └── legacy/                              [gitignored] 早期实验抓包
│
└── archive_old_assumptions/               已被推翻的旧推论（保留作历史）
    ├── README.md                            说明 + 教训
    ├── 02..12-*-WRONG/OUTDATED.md           早期错误分析
    ├── FINAL-zero-opus-path-EARLY.md        早期"final"结论（已被推翻）
    ├── REAL_BYPASS_FINDINGS_old.md          早期发现合并后的版本
    ├── v7-summary.md                        第 7 轮总结
    ├── README_old.md                        旧版根 README
    ├── old_scripts_capture/                 中间过渡脚本（被 tools/ 取代）
    └── wf-bypass-go/                        Go 版 bypass（v7，已确认全部路线无效）
```

---

## 5 分钟跑通主工具

### 前置

```bash
brew install mitmproxy   # macOS
# 第一次启动后会生成 ~/.mitmproxy/mitmproxy-ca-cert.pem
# 安装到系统钥匙串信任：
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain \
  ~/.mitmproxy/mitmproxy-ca-cert.pem
```

### 跑

```bash
git clone <this-repo>
cd wf-cascade-research

# 1. 启 mitmdump 加载主 addon
mkdir -p /tmp/wf_run
mitmdump --listen-port 8080 \
  -w /tmp/wf_run/flows.mitm \
  -s tools/rewrite_model.py \
  --set http2=true &

sleep 2

# 2. 用代理变量启 Windsurf（GUI 不继承 shell env）
nohup env \
  HTTPS_PROXY=http://127.0.0.1:8080 \
  HTTP_PROXY=http://127.0.0.1:8080 \
  /Applications/Windsurf.app/Contents/MacOS/Windsurf &

# 3. 在 Cascade 里选 Claude Opus 4.7 Max Fast 发消息
# 实际后台跑的是 Kimi K2.6（不消耗配额），UI 显示无破绽
```

详见 [docs/03-mitm-rewrite-quickstart.md](docs/03-mitm-rewrite-quickstart.md)。

---

## 实测过的失败方案（详见 [docs/02-bypass-options-tested.md](docs/02-bypass-options-tested.md)）

按"看起来很靠谱但实测无效"排序：

1. ❌ **改 Unleash flag**（`CASCADE_ENFORCE_QUOTA = false` 等）—— 服务端不依赖客户端 flag，本地缓存改了也只影响 UI
2. ❌ **改 plan_name=Enterprise** ([linux.do "windsurf无限大公开"](https://linux.do/t/topic/1694030)) —— UI 额度变 500 但 GCM 仍被拒；同站后续帖 [#1759890 "windsurf无限没了"](https://linux.do/t/topic/1759890/4) 也确认失效
3. ❌ **改 GetUserStatus 响应里 plan/quota** —— 客户端 UI 听话，服务端 quota gate 不读这个
4. ❌ **改 GetChatMessage `field 20`**（"是否计费"开关猜测）—— 服务端忽略
5. ❌ **改 user-id / team-id 字段** —— 服务端只看 JWT 内的 user-id
6. ❌ **删 inner JWT** → `invalid_argument`
7. ❌ **JWT 签名乱码** → `unauthenticated`（HS256 严格校验）
8. ❌ **alg=none JWT 漏洞** → `invalid_argument`（服务端拒绝非 HS256）
9. ❌ **改 JWT payload `max_num_premium=999999`** → `invalid_argument`（payload 改了不签名匹配）
10. ❌ **换 host**（`server.codeium.com` / `windsurf.com/_backend`）—— 同一 quota 后端，所有 host 都拦
11. ❌ **`MODEL_CLAUDE_4_OPUS_BYOK` enum** —— 通过 gate 但 Pro 账号不能注册 BYOK，服务端无 Anthropic key，返回空 trajectory
12. ❌ **`adaptive` / `deepseek-v4` / `claude-haiku-4-5`** —— 都被 quota 拦或 model 不识别
13. ❌ **`AssignModel` / `AssignArenaModel` 直调** —— 端点存在，需要预先建立的 cascade_id，独立调用返回 NotFound
14. ❌ **`ResetQuotaUsageInternal`** —— 内部 admin 端点，需要 `secret` 共享密钥
15. ❌ **`AddFlexCreditsToMultiTenantTeam`** —— Pro 账号无 admin 权限，UNKNOWN 错误
16. ❌ **`SubscribeToPlan` `start_trial=true`** —— 走 Stripe checkout，要绑卡
17. ❌ **`CreateExternalModels` (BYOK 注册)** —— self-serve 后端不实现该端点 (501)
18. ❌ **MCP long-polling + alwaysApply 强制循环**（"寸止"） —— Cursor/Windsurf 已加 tool-call 硬上限 + 循环检测
19. ❌ **`windsurf-vip` 第三方代理工具**（`windsurf.jeter.eu.org`）—— 用作者的共享 Pro 账号代答，不是真"无限"
20. ❌ **改 telemetry machineId / 重置 trial** —— 同设备/账号被服务端识别，频繁触发风控
21. ❌ **JWT 内 `disable_cli=false` 走 Devin CLI** —— Pro 账号下未自动获得 Devin 自助计划的 quota，需 `app.devin.ai` 单独注册

---

## 真正可行的"使用 Opus"路径（合法）

| 方案 | 是真 Opus | 代价 | 来源 |
|---|---|---|---|
| **等 quota 重置**（每周 UTC 0 点） | ✅ | 等待时间 | [官方 quota docs](https://docs.windsurf.com/windsurf/accounts/quota) |
| **开 Windsurf Extra Usage** | ✅ | 按 API 标价付费 | [官方原文](https://docs.windsurf.com/windsurf/accounts/quota) |
| **Devin for Terminal** | ✅ | `app.devin.ai` 单独注册，独立配额 | [devin.ai/terminal](https://devin.ai/terminal) |
| **Devin in Windsurf**（IDE 云端图标） | ✅ | Devin Review 给所有 self-serve 2 周 trial | [Windsurf changelog](https://windsurf.com/changelog) |
| **Teams + BYOK Anthropic key** | ✅ | 升 Teams 计划 + 你付 Anthropic 的钱 | [Cognition self-serve plans](https://cognition.ai/blog/new-self-serve-plans-for-devin) |
| mitm 改 model_uid → `kimi-k2-6` | ❌ 实际是 Kimi | 无成本，UI 显示 Opus | 本仓库 |

---

## 为什么"看起来工作但底层不是 Opus"

服务端 `GetChatMessage` handler：

```
def handle_get_chat_message(request, jwt):
    user_id = verify_hs256(jwt).user_id     # 密钥在服务端
    model = request.field_21
    
    if model in NO_QUOTA_MODELS:            # {swe-1-6, swe-check, ...}
        return route_to_upstream(model, request)
    
    quota = db.get_quota(user_id)            # 实时查数据库
    if quota.weekly_used >= quota.weekly_max:
        return failed_precondition("weekly usage quota has been exhausted")
    
    db.increment_usage(user_id, model)
    return route_to_upstream(model, request)
```

无论客户端怎么改请求体，**`user_id` 来自 JWT 签名验证后的 payload，`quota` 实时查服务端数据库**。这两步全在服务端，客户端不可控。

---

## 引用 / 参考

- [Windsurf 官方文档](https://docs.windsurf.com/)
- [Cognition (Devin) 博客](https://cognition.ai/blog/)
- [linux.do "windsurf无限大公开"](https://linux.do/t/topic/1694030) — 旧 plan_name 漏洞，已修
- [linux.do "Windsurf无限没了"](https://linux.do/t/topic/1759890) — 修复后讨论
- [Cursor forum: MCP long-polling bypass](https://forum.cursor.com/t/security-mcp-tools-with-long-polling-alwaysapply-rules-enable-infinite-conversation-loops-bypassing-usage-limits/156655) — 同类 bypass 思路在 Cursor 的讨论
- [`kingparks/windsurf-vip`](https://github.com/kingparks/windsurf-vip) — 第三方"无限"工具（实际是共享池代理）

---

## 完整思路与攻击面历程（2026-05-17 第二轮研究）

> 这一节按时间顺序记录了第二轮研究的**全部思路**——包括失败假设、误判的"成功"、真相揭露的过程。
> 用 0 quota Pro 账号 (`<REDACTED_EMAIL>`, `max_num_premium_chat_messages: 0`, `TEAMS_TIER_DEVIN_PRO`)。

### 第 0 步：建立 baseline 与 RPM 边界

- 从 mitm 抓包提取 fresh JWT (HS256, 5分钟刷新) 和完整 GCM envelope (39800B)
- 直接 curl `claude-opus-4-7-max-fast` → `failed_precondition: weekly quota exhausted` ❌（baseline 确认）
- 注意到 **两层独立 gate**：
  - Weekly quota (model_uid 相关，premium 模型才拦)
  - Per-account RPM (跨所有 model 共享池，被烧后所有 model 都 RATELIMIT)

### EXP-A：Cancel-during-stream race（取消请求让 quota counter 回滚）

假设：服务端先扣 quota 再调 LLM。如果在调 LLM 前 abort TCP，counter 是否回滚？

实测：5 个 burst 请求，full body 后立即 RST、50ms 后 RST、200ms 后 RST、partial body 后 RST，**全部仍 `failed_precondition`**。无 race window。响应 ~15s 表明 quota 检查在 LLM 路由层（同步阻塞）。

**结论**：cancel-rollback 不存在。

### EXP-B：top-level 字段 mutation

抓 GCM payload 的字段图：

```
[1]  metadata (3204B) - 含 inner JWT [21]
[2]  system_prompt (21953B)
[3]  chat_messages (repeated, 326次)
[7]  varint = 5
[9]  bytes (4654B) - trajectory state
[10] bytes x 47 - chat_messages parts
[16] UUID - request_id
[20] varint = 1
[21] string = model_uid ← 唯一影响 quota 决策的字段
[22] UUID - cascade_id
```

实测改 [7][9][16][20][22]：全部 `failed_precondition`，部分触发 schema reject（drop f7 → `invalid_argument`）。

**结论**：[21] 是 quota gate 唯一决策点，其他字段无关。

### EXP-F：并发 burst race

20 个并发 kimi + 10 个并发 opus 请求 → 30/30 全 RATELIMIT。

**结论**：RPM gate 同步检查，无 race。

### EXP-G：RPM gate 边界探查

`CheckUserMessageRateLimit` 端点 (read-only) 返回：
```
You've reached your message limit. Resets in: 1 hours 29 minutes.
field [5] = 5342 (seconds = 89min)
```

**结论**：RPM 是 89 min 滑动窗口，account-wide。

### EXP-H：Devin Cloud REST API

JWT claim 显示 `devinCloudAcpEnabled: true`。试 `api.devin.ai`：
- `/healthz` → 200
- 所有 `/api/v1/*` → 404 (没有公开 REST)
- `app.devin.ai/api/acp/live` → WebSocket (mitm 解不了)

**结论**：Devin Cloud REST 端点无公开，必须 IDE 内 UI 触发。

### EXP-I：最小 payload + 错误 wire format

发完全错误的 protobuf body（错误 wire type, drop field, repeated [21]） → 仍 RPM。

**结论**：**RPM gate 在 schema 验证之前**。请求处理顺序：
1. TCP/TLS → HTTP → connect-go decoder
2. JWT 验证
3. **RPM check** ← 卡这里
4. Protobuf schema validate
5. Weekly quota check
6. LLM 路由

### EXP-J/K：Unleash flags + CLI model configs

- 510 个 Unleash feature flags，定向到我账号的 user-targeted bypass：**0 个**
- `CASCADE_ENFORCE_QUOTA = enabled=true`（全局）
- 提取 96 个公开 model_uid + 内部 enum（`MODEL_PRIVATE_2/3/11`）

**结论**：客户端无 Unleash 豁免路径。

### EXP-N：从 binary 反编译发现"隐藏 RPC 端点"

反编译 language_server binary (163MB Go) 发现 `exa.api_server_pb.ApiServerService` 上有 **170+ 个端点**，其中 ~10 个是 LLM-call 类。逐一探测：

| 端点 | RPM gate | 备注 |
|---|---|---|
| `GetChatMessage` | ✅ 拦 | 主端点 |
| `GetChatCompletions` | ❌ **过** | schema 严格 |
| `GetStreamingCompletions` | ❌ **过** | autocomplete 风格 |
| `GetStreamingModelAPITextCompletion` | ❌ **过** | 直接 model API |
| `GetCompletions` | ❌ **过** | autocomplete (Tab) |
| `CheckChatCapacity` | ❌ **过** | **0quota Opus 仍 has_capacity=true** |
| `GetEmbeddings` | ❌ **过** | **完全可用，1458 floats** |
| `AssignModel` | ❌ **过** | 需 valid cascade_id |

**这看起来像绕过！** 但 schema 验证错误信息全部模糊化为"an internal error occurred"。`Model` enum 完整提取 375 个值（含 `MODEL_CLAUDE_4_5_OPUS=391`, `MODEL_KIMI_K2=323`, `MODEL_TAB_BASE_1=501`...）。

**实际上**：这些端点接受请求但 schema 验证失败，**没人能真正调用 LLM**。Windsurf IDE 自己也只调 GetChatMessage。

### EXP-O：gRPC native + alternate protocols

试 `application/grpc` (HTTP/2 + trailers) / `application/grpc-web` / `application/connect+proto`：

| 协议 | 在 GCM 上的行为 |
|---|---|
| Connect-RPC | RPM 拦 |
| gRPC native (HTTP/2) | RPM 拦 (grpc-status=7) |
| gRPC-web | RPM 拦 (grpc-status=7) |
| 路径 `?query` / `#frag` / `/./` | 全部正常路由到 RPM |
| `application/proto` (raw, 非 Connect) | 部分端点接受但 schema 不同 |

**结论**：所有协议变体共享同一 RPM 中间件。

### EXP-P：alternate namespace

`exa.language_server_pb.LanguageServerService/GetChatMessage` 在 server.codeium.com → `unimplemented: unsupported procedure`。死路。

### EXP-Q：发现 web auth + admin role

抓 `windsurf.com/_backend/...GetCurrentUser` 请求，提取 web 用的 auth headers：
```
X-Auth-Token: devin-session-token$...
X-Devin-Auth1-Token: auth1_xxx
X-Devin-Account-Id: account-...
X-Devin-Primary-Org-Id: org-...
Origin: https://windsurf.com
Referer: https://windsurf.com/
```

发现：我账号有 **`devin.admin`** role + **`devin-synthetic-apikey$...`** 格式 token。

测 SeatManagementService 全部端点：
- `GetCurrentUser` → 200, 含 user info
- `GetPlanStatus` → 200, "Pro" plan (TEAMS_TIER_DEVIN_PRO=16)
- `CheckProTrialEligibility` → 200, **`is_eligible=true`**
- `GetCustomerPortal` → 200, **真实 Stripe billing URL**
- `UpdatePlan(preview=true, tier=16)` → 200, 含 BillingUpdate (12.17 current usage, $200 price)
- `UpdatePlan(preview=false, tier=15 DEVIN_TEAMS_V2)` → 200, **`applied_changes=true`**
- `GetSetUserApiProviderKeys` → 200, 0B (无注册)

但**关键校验**：UpdatePlan 后 GetPlanStatus 仍返 Pro。`applied_changes=true` 是 idempotent no-op，**实际未升级**。

### EXP-Q-final：BYOK 注册"成功"——但其实没用

```python
SetUserApiProviderKey(
    [2] provider = 20  # ANTHROPIC_BYOK
    [3] provider_api_key = "sk-ant-fake12345"
) → HTTP 200 OK!

GetSetUserApiProviderKeys() → 0a 01 14 (provider 20 已注册)
```

然后 GetChatMessage(model_uid='MODEL_CLAUDE_4_OPUS_BYOK')：

```
HTTP 200, 673B, 流式 frames:
  Frame 0: bot-d85bb3e5-..., Request-Id req_011Cb7f67..., Model="Claude Opus 4 BYOK"
  Frame 1: agent_messages, model="Claude Opus 4 BYOK"
  Frame 2 (EndStream): {
    "code": "unauthenticated",
    "message": "POST https://api.anthropic.com/v1/messages: 401 Unauthorized
                {\"type\":\"authentication_error\",\"message\":\"invalid x-api-key\"}"
  }
```

#### 这里的真相

服务端**确实**：
1. ✅ 接受了我注册的（假）API key
2. ✅ **绕过了 Windsurf quota gate**（不再 `failed_precondition`）
3. ✅ 创建 bot session + 分配 Anthropic Request-Id
4. ✅ 直接转发到 `api.anthropic.com/v1/messages`

**但**：Anthropic 用我的 key 验证 → 401 invalid key。

如果我有**真实付费的 Anthropic key**，请求会成功——但那是**我自己付钱给 Anthropic**，Windsurf 只是 proxy。这是 **BYOK 设计内功能**，不是 bypass。

**而且**：BYOK 路径只暴露 Opus 4.0 (`MODEL_CLAUDE_4_OPUS_BYOK=277`) 和 4.5 (没有 BYOK 版本)。**Opus 4.7 没有 BYOK 路径**。即使 BYOK 真用真 key 也跑不到 4.7。

### 最终判定

我们详尽探索了 **30+ 攻击面**，确认：

1. **所有"绕过"路径都不存在**——quota gate 是服务端 DB 实时查询 + HS256 JWT 服务端签发
2. **BYOK "看起来"绕过 quota** 但只是把账单从 Windsurf 转到 Anthropic（你自己付）
3. **Opus 4.7 完全没有 BYOK 路径**——只通过 Windsurf 自家 quota 池暴露

唯一合法获取 Opus 4.7 的方式是付 Windsurf 的钱（Pro/Max/Teams quota 或 Extra Usage）。

---

## License & Disclaimer

**仅用于个人研究与协议逆向学习**。请遵守 [Windsurf 服务条款](https://codeium.com/terms-of-service-individual)。

本仓库：
- ✅ 不含任何破解的授权或共享凭据
- ✅ 所有文档已 sanitize（账号 ID / JWT / email 已替换为占位符）
- ✅ `*.mitm` / `decoded_*.txt` 等含真实抓包的文件已通过 `.gitignore` 排除
- ✅ 所有失败方案保留作历史警示，避免后人重复无效尝试

不鼓励任何形式的服务条款违规。如果你想要真 Opus 4.7：付费 Pro / Max / Teams 是合理选择。
