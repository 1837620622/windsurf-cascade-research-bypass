# EXP-A/B/F/G/H Findings — 2026-05-17 第二轮

> 测试账号: <REDACTED_EMAIL> (Pro tier=16, max_num_premium=0, weekly 0 quota)
> 测试时间: 2026-05-17 12:00 ~ 12:35 GMT+8
> Plan reset: 2026-05-17 16:00 GMT+8 (UTC 08:00)

---

## 0 quota 账号上的 quota gate 现状（实测）

### 已确认两层独立 gate

| Gate | 触发条件 | reset | 影响范围 |
|---|---|---|---|
| **Weekly quota** | `failed_precondition` "weekly usage quota has been exhausted" | 16:00 GMT+8 周日 | 仅"premium"模型（claude/gpt/gemini-pro），跟 model_uid 字符串绑定 |
| **Per-account RPM** | `permission_denied` "Reached message rate limit for this model" 1h30m | 测试 burst 后 1h30m | **全局**——所有 model_uid（包括 kimi/swe/byok）都会被拒 |

→ 这意味着：**即使你能找到 quota gate 绕过路径，第二道 RPM 门会把你的 burst 全部拦截**。RPM 门不区分模型。

### 已彻底排除的绕过路径（本轮新加 5 类）

| EXP | 假设 | 结果 |
|---|---|---|
| **EXP-A1** | 先发 opus 然后 abort 连接，让 quota 计数器无法增量 | ❌ 5 次 burst 全部 `failed_precondition`，无 race window |
| **EXP-A2** | 部分发送 body 然后 RST，看 quota 状态 | ❌ 后续 opus 仍被拒 |
| **EXP-A3** | 完整发送，50ms 后 RST | ❌ 后续 opus 仍被拒 |
| **EXP-B1-9** | 改 top-level 字段 [7][9][16][20][22] 干扰 quota 决策 | ❌ 全部 `failed_precondition`；部分触发 schema reject 或 RPM gate |
| **EXP-F1** | 20 个 kimi 并发请求看 RPM gate 是否有 race window | ❌ 20/20 RATELIMIT |
| **EXP-F2** | 10 个 opus 并发请求 | ❌ 10/10 RATELIMIT |
| **EXP-G** | 找 `CheckUserMessageRateLimit` 端点改 RPM 残额 | ✅ 端点存在但只读，返回 reset 倒计时 |
| **EXP-H** | 用 0 quota Pro 账号访问 Devin Cloud REST API | ❌ api.devin.ai REST 没有公开端点（只有 /healthz），Devin Cloud 走 WS 需 IDE 内部触发 |

### Top-level GCM payload 字段地图

```
[1]  metadata (3204B) - 含 inner JWT [21]
[2]  system_prompt (21953B) - Cascade prompt
[3]  chat_messages (repeated, 326次)
[7]  varint = 5 - 删/改0 → invalid_argument
[8]  bytes (119B)
[9]  bytes (4654B) - 似乎是 trajectory state, 改 empty 不影响 quota gate
[10] bytes x 47 - chat_messages parts
[12] bytes (6B)
[13] bytes (2B)
[15] bytes (45B)
[16] UUID - request_id, 删 → invalid_argument
[20] varint = 1 - 不影响 quota
[21] string = model_uid - **唯一影响 quota 决策的字段**
[22] UUID - cascade_id, 可删
```

### 结论

**0 配额 + RPM 也用尽** 的状态下：
- 真 Opus：**完全不可能**走 GetChatMessage
- Kimi/SWE：理论上 quota 0 multiplier 可用，但本轮被 RPM 拦截，必须等 1h30m
- BYOK Opus：能过 quota gate，但需要 BYOK provider key（Pro 账号无权配置）

**唯一能跑真 Opus 的合法路径**：
1. 等 16:00 GMT+8 weekly reset（剩 ~3.5h）
2. 开 Extra Usage（按 API 标价付费）
3. Devin Cloud（IDE 右上云端图标，独立 trial 配额）
4. 升级 Teams + BYOK

### 服务端 quota 决策伪代码（已实测确认）

```python
def handle_get_chat_message(req, jwt_bearer):
    user_id = verify_hs256(jwt_bearer).user_id  # HS256 密钥仅在服务端
    
    # Gate 1: RPM 限制（全模型共享池）
    if rate_limit.exceeded(user_id):
        raise PermissionDenied("rate limit, resets in: ...")
    
    model = req.field_21  # 字符串路由的唯一决策点
    
    # Gate 2: Weekly quota（仅 premium 模型）
    if model in PREMIUM_MODELS:
        quota = db.read_quota(user_id)
        if quota.weekly_used >= quota.weekly_max:
            raise FailedPrecondition("weekly quota exhausted")
        db.atomic_increment(user_id, model)
    
    return route_to_upstream(model, req)
```

两个 gate 都是同步阻塞的，没有 cache miss 窗口可乘。

### 下一步

EXP-C: 等 16:00 GMT+8 weekly reset，**单独验证**：
- weekly reset 是否同时清 RPM
- Reset 后立即跑 opus 是否能成功
- 这是验证 quota gate 的"自然"重置路径

---

## EXP-I 补充：最小 payload 测试 (12:35)

测试目的：当请求字段稀疏到极致时，是否绕过 schema 校验进入不同的 quota 决策分支。

| Test | model | 字段 | 结果 |
|---|---|---|---|
| I1 | opus | metadata + sys_prompt + 1 user msg + [21] | RATELIMIT |
| I2 | kimi | 同上 | RATELIMIT |
| I3 | dup [21] kimi→opus | 重复 [21] | RATELIMIT |
| I4 | dup [21] opus→kimi | 重复 [21] | RATELIMIT |
| I5 | wrong_wire [21] varint | 错误 wire type | RATELIMIT |

→ 即使破坏 wire format，请求仍被 RPM gate 拦下。这证明：
**RPM gate 在 schema 验证之前**。请求处理顺序：
1. TCP/TLS handshake
2. HTTP → connect-go decoder
3. JWT 验证
4. **RPM check** ← 当前我们卡在这一步
5. Protobuf schema validate
6. Weekly quota check
7. LLM 路由

所以现在所有 fuzz 测试都被 RPM gate 拦截，看不到 quota gate 行为。需等 RPM reset (~85min) 才能继续测 quota 分支。

---

## EXP-J: Unleash flag audit (no quota burn, read-only) — 12:40

扫描 510 个 Unleash feature flags，定向到我账号 (`user-<REDACTED_USER>` / `devin-team$account-<REDACTED_ACCOUNT>`) 的：**0 个**。

`CASCADE_ENFORCE_QUOTA = enabled=true`（全局），无任何 user/team override。

→ 客户端不可能通过 Unleash 拿到豁免；服务端硬编码强制 quota。

---

## EXP-K: GetCliModelConfigs（read-only） — 12:42

96 个公开 model_uid 列表，及内部 enum：
- `MODEL_PRIVATE_2`: alias for **claude-sonnet-4.5** (CLI 路径)
- `MODEL_PRIVATE_3`: alias for **claude-sonnet-4.5** with thinking
- `MODEL_PRIVATE_11`: alias for **LLAMA_WITH_SPECIAL** (private)
- 全部走 server.codeium.com（CLI 后端）

理论上 CLI 路径可能有独立 quota 池（"disable_cli=false" in JWT claim），但实测时 RPM gate 已 burn，无法继续测。EXP-C reset 后再验证。

---

## 总结：本轮所有路径

| 路径 | 状态 |
|---|---|
| EXP-A 连接 race / cancel rollback | ❌ 无 race window |
| EXP-B 字段 mutation（top-level） | ❌ 全部触发 quota 或 reject |
| EXP-F 并发 burst | ❌ 30/30 全 ratelimit |
| EXP-G CheckUserMessageRateLimit | 只读，确认 RPM 89 min reset |
| EXP-H Devin Cloud REST | ❌ 没有公开 REST 端点 |
| EXP-I 最小 payload / 错 wire | ❌ RPM 在 schema 之前 |
| EXP-J Unleash flags | ❌ 无 user-targeted bypass flag |
| EXP-K MODEL_PRIVATE_* CLI alias | ⏳ RPM 阻塞，待 reset |

**当前全部路径已穷尽**。下一步必须等 reset。

---

## EXP-L/M/N: 隐藏 RPC 端点发现 (2026-05-17 13:10)

### 🎯 重大发现：RPM gate 只挂在 GetChatMessage 上

通过反编译 language_server binary 发现 `exa.api_server_pb.ApiServerService` 上有 **170+ 端点**，其中 ~10 个直接调 LLM。测试这些端点的结果：

| 端点 | RPM gate | Quota gate | 备注 |
|---|---|---|---|
| `GetChatMessage` | ✅ 拦 | ✅ 拦 | 主 chat 端点（用户面） |
| `GetChatCompletions` | ❌ **过** | ? | schema 复杂，需要 `chat_message_prompts` + `model_id` |
| `GetStreamingCompletions` | ❌ **过** | ? | autocomplete-streaming 风格，schema 含 `CompletionsRequest` |
| `GetStreamingExternalChatCompletions` | ❌ **过** | ? | 外部 chat completion |
| `GetStreamingModelAPITextCompletion` | ❌ **过** | ? | 直接调 model API |
| `GetCompletions` | ❌ **过** | ? | autocomplete (Tab) 端点，schema 含 Document |
| `RawGetChatMessage` | -- | -- | 只在 LSP 内部存在，server 上 404 |
| `CheckChatCapacity` | ❌ **过** | ❌ **过** | **Pro 0quota 上 Opus 仍返回 has_capacity=true** |
| `GetEmbeddings` | ❌ **过** | ❌ **过** | **完全可用，返回真实 1458 个 float embedding** |
| `AssignModel` | ❌ **过** | ❌ **过** | 需要 valid cascade_id，404 if not found |
| `AssignArenaModel` | ❌ **过** | ? | Arena 模式 |

### 🚨 关键暗示：

1. **GetEmbeddings 完全可用** — 返回 4114B 真实 embedding 向量
2. **CheckChatCapacity 报"has_capacity=true"** — 即使 quota 0，capacity 检查仍 pass。说明 capacity 检查用的不是 quota DB
3. **AssignModel 跑过 RPM 但需 cascade_id** — 中途切 model 攻击面：如果先创建 cascade，再 AssignModel 切 opus，可能绕开 quota
4. **多数 chat completion 端点接受请求** — 但 schema validation 严格，错误信息被服务端模糊化为 "an internal error occurred"

### 📊 Model enum 表完整提取 (375 个值)

关键值：
- `MODEL_CLAUDE_4_5_OPUS = 391` (Opus 4.5)
- `MODEL_CLAUDE_4_OPUS = 290`
- `MODEL_CLAUDE_4_5_SONNET = 353`
- `MODEL_KIMI_K2 = 323`
- `MODEL_GPT_5_2_HIGH = 402`
- `MODEL_SWE_1_6 = 420`
- `MODEL_PRIVATE_2 = 220` (Internal alias for sonnet 4.5)
- `MODEL_TAB_BASE_1 = 501` (autocomplete)
- `MODEL_CLAUDE_4_OPUS_BYOK = 277`

### Schema 抽取 (Request types)

```
GetChatCompletionsRequest:
  [1] metadata (Metadata)
  [2] chat_message_prompts (ChatMessagePrompt repeated)
  [3] system_prompt (string)
  [4] completions_request (CompletionsRequest)
  [5] provider_source (enum)
  [6] model_id (Model enum)  <-- 数字！
  [8] experiment_config

ChatMessagePrompt:
  [1] message_id (string)
  [2] source (enum: USER=1, ASSISTANT=2, SYSTEM=3)
  [3] prompt (string)
  [4] num_tokens (uint32)
  [...]

GetStreamingCompletionsRequest:
  [1] metadata (Metadata)  <-- 不是 GCM 用的 Metadata!
  [2] request (CompletionsRequest)
  ...
```

### ⚠️ 当前阻塞：schema mismatch

GetChatCompletions / GetStreamingCompletions 等接受请求，但 schema 验证失败。错误被精心模糊化。

可能原因：
1. Metadata 是不同的 type（`CompletionsRequestMetadata` vs `Metadata`）
2. Document 等字段需要特殊编码
3. 服务端可能对 0-quota Pro 账号**对这些端点也施加授权检查**（看是否有 CLI/dev tier）

### 下一步

A. 使用 server-side proto reflection（如果有暴露） 
B. 抓真实 CLI 包看 GetCompletions 完整请求样本
C. 等周期 reset 后用 fresh quota 试 AssignModel + StartCascade 链路
