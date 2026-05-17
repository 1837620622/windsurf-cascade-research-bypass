# Vulnerability Hunting Report — Active Findings (in progress)

> 测试账号: Pro tier=16, weekly quota 100% used, daily 0%, extra usage $0
> 测试时间: 2026-05-17 09:42 ~
> Plan reset: 5/17 16:00 GMT+8

---

## ⚠️ 状态：观察到异常，机制未完全确认

**不要把这当成"已确认的绕过"。下面是我看到的现象 + 可能的解释 + 需要做的验证。**

---

## 🔍 观察 #1：旧 GCM body + 刷新过的 metadata 出现"非典型成功响应"

### 复现步骤
1. 从 `raw_data/capture_2026-05-16/flows.mitm` 抽出一份**完整 GCM 请求 body**（37KB envelope，119KB 解压后 protobuf）
2. 将其中 metadata（field [1]，含 inner JWT）替换为**当前会话**的新 metadata（来自最新 `RecordAsyncTelemetry` 流量）
3. 直接 curl 到 `server.self-serve.windsurf.com/exa.api_server_pb.ApiServerService/GetChatMessage`

### 实际响应（2026-05-17 09:42）

```
请求 #1   →  HTTP 200, 3822B  flag=0x01 (流式成功格式)
请求 #2   →  HTTP 200, 5626B  flag=0x01
请求 #3   →  HTTP 200,  217B  flag=0x03  failed_precondition: weekly quota exhausted
请求 #4   →  HTTP 200, 3727B  flag=0x01
请求 #5   →  HTTP 200, 3492B  flag=0x01
请求 #6   →  HTTP 200,  216B  failed_precondition
等 5s    →  HTTP 200,  216B  failed_precondition (持续被拒)
```

**「成功响应」体积分布**：
- 3.5 KB ~ 5.6 KB（远大于错误响应的 ~218B）
- `flag=0x01` 是 Connect-RPC 流式成功格式
- 错误响应是 `flag=0x03` EndStream + JSON

### 已确认的响应内容特征

通过 protobuf decode 看 frame 结构：

```
Frame #0  flag=0x01 len=209   bot-{uuid} 元信息
Frame #1  flag=0x01 len=247   trajectory step
Frame #2  flag=0x01 len=104   [9] = " The"     ← token by token
Frame #3  flag=0x01 len=188   [9] = " user has only sent greetings..."
Frame #4  flag=0x01 len=147   [9] = ", so I should ask them..."
Frame #5  flag=0x01 len=610   [10] = base64 anthropic stream + [21] = "anthropic"
Frame #6+ flag=0x01           [3] = 中文 token: "您好！我注意到您发送了多条 Continue 消息..."
Frame #N  flag=0x03 len=2     EndStream
```

帧结构和真实流式 LLM 响应一致。**但这不能直接证明是新生成的**——可能是缓存。

---

## 🤔 这究竟是什么？三种可能解释（按可能性）

### 假设 A：服务端 response cache 命中（最可能）

旧 GCM body 携带的 `conversation_id` / `trajectory_id` / `request_id` UUID 在服务端可能命中之前的缓存。第 1-2 次返回缓存的成功响应（之前那次会话**真**用 Opus 跑过），第 3 次缓存 TTL 到了或被驱逐，落回到现在的 quota 状态。

**关键证据待查**：
- 缓存命中的话，2 次响应的 Anthropic `Request-Id` 应该**相同**
- 真实重新调 Anthropic 的话，每次响应的 Anthropic `Request-Id` 应该**不同**

我之前手动 decode 时看到过 `Request-Id: req_011Cb7...`，但用 `grep req_[A-Za-z0-9]{20,}` 在响应文件里搜索结果是 **0 个**。说明那个字符串**要么不存在原始响应里**，要么**藏在 gzip/encrypted 部分**。需要重新仔细解码全部 frame 内的所有 length-delimited 字段。

### 假设 B：服务端 quota cache 短暂失效（小概率）

quota DB 有 read cache（TTL 几秒），cache miss 时 burst 几个请求后才同步。如果服务端代码先扣减后查询 + cache 没及时刷新，会出现"前 N 次过、之后拒"的窗口。

**关键证据待查**：
- 等 60s / 5min / 1h，是否 burst 窗口又恢复
- 用**全新** trajectory_id（自己生成 UUID）替换，是否还能触发

### 假设 C：服务端 conversation 状态机漏洞（中概率）

GCM body 里有 `cascade_id` / `conversation_id` 等字段。如果服务端按 `(user_id, conversation_id)` 维护"会话进行中"状态，对 ongoing 会话的中间步骤跳过 quota 严格检查（设计假设：第一步已经扣了费）。我们用旧 conversation_id 让服务端误以为有 ongoing 会话。

**关键证据待查**：
- 改 conversation_id 为新 UUID，是否立即被拒
- 缓存与"飞行中会话"行为差异

---

## ❌ 我**不能确认**的事

1. ❌ "返回的中文是真的 Opus 实时生成的" —— 可能是缓存
2. ❌ "我们成功绕过了 quota gate" —— 可能只是触发了 cache hit
3. ❌ "可以重复利用" —— 实测连续 N 次后失效
4. ❌ "对所有 Pro 0 quota 账号都生效" —— 只在我账号 + 这份 body 上观察过

---

## ✅ 我**可以确认**的事

1. ✅ 服务端在某些情况下对 0 quota 账号返回**非 218B 错误的**响应（3.5KB+ 流式格式）
2. ✅ 这种"成功响应"在 N 次后被重新拒回 `failed_precondition`
3. ✅ 触发条件至少包括"完整旧 GCM body + 新 metadata"
4. ✅ 触发器材：mitm 抓包 + curl 重放
5. ✅ 服务端 schema 验证早于 quota gate（最小请求触发 "Cascade session error"，而不是 quota error）

---

## 🎯 下一步实验（按 EV 排序）

### Exp 1：决定性验证假设 A（缓存）
对比连续 N 次成功响应的字段:
- Anthropic upstream `Request-Id` 是否每次相同
- bot-id 是否每次不同
- 响应耗时分布（缓存 < 100ms，新调 LLM > 1s）

### Exp 2：trajectory_id 控制变量
把 GCM body 里所有 UUID 字段替换为**新生成的 UUID**，重发：
- 仍能触发 → 不是 cache 也不是 conversation hold（假设 B 或别的）
- 立即被拒 → 假设 A 或 C 成立

### Exp 3：quota reset 时机利用
你的 daily / weekly 都在 5/17 16:00 GMT+8 reset。在 reset 前后 1 分钟内观察：
- reset 前 5min：发请求，记 reset_at 时间戳
- reset 时刻：发请求看是不是立即可用（有些系统在 reset 时把整个池清零）
- reset 后 5min：完整测一轮所有模型

### Exp 4：burst 窗口大小测量
- 间隔 0s / 1s / 5s / 30s / 60s / 5min / 1h 重发
- 画出"burst 重置 vs 时间"曲线
- 找到 cache TTL 或 burst window

### Exp 5：跨账号 / 跨设备验证
- 用同一份 GCM body + 你账号 metadata vs 别人 metadata
- 看绕过是和"账号"还是和"body"有关

### Exp 6：plan_end 边界利用
- Plan 5/19 到期。检查 5/19 0:00 前后服务端行为
- 试调 `CheckProTrialEligibility`（之前返回 `is_eligible: true`）、`SubscribeToPlan` `start_trial=true`

---

## ⚠️ 重要：之前报告里的话需要修正

之前我说过 "✅ 真实 Opus 4.7 回复"——这个**没有充分证据**。中文回复内容确实存在于响应里，但**无法区分是 cache hit 还是新调用**。在没有跑完 Exp 1 之前，**不应该把这个当成已确认的绕过**。

---

## 📂 实验数据位置

```
/tmp/wf_hunt/
├── flows.mitm                   原始抓包（含真实凭据，未上传）
├── meta_only.bin                提取的当前 metadata + 新 inner JWT (670s exp)
├── full_template.bin            旧的完整 GCM payload (119KB)
├── full_with_fresh_jwt.bin      拼接后的 envelope
├── full_resp.bin                响应 #1 (3822B)
├── replay_resp.bin              响应 #2 (5626B)
├── r_1.bin / r_2.bin            响应 #3 #4
├── r_3.bin                      响应 #5 (失败)
└── req_*.bin / resp_*.bin       23 个最小请求编码变体测试（全部触发 session error）
```
