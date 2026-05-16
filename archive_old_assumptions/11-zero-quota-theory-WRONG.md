# 零额度使用高级模型原理分析

## 核心结论

**Windsurf 中即使在 credits = 0 的情况下，用户仍能使用 Claude Opus 4.7 Max Fast 等最高级模型。** 这不是漏洞，而是架构设计的结果。

## 核心机制: 三模型分离

`ModelUsageStats` protobuf 有三个独立的模型 UID 字段：

| 字段 | 含义 | 实际值 |
|------|------|--------|
| `requested_model_uid` | 用户请求的模型 | 用户选择的界面显示模型 |
| `model_uid` | 实际服务的模型 | `claude-opus-4-7-max-fast` |
| `billing_model_uid` | 计费基准模型 | 通常是一个免费或便宜的模型 |

**关键**: `billing_model_uid` 与 `model_uid` 完全解耦。系统可以：
- 用 `model_uid = claude-opus-4-7-max-fast` 提供服务
- 用 `billing_model_uid = MODEL_CHAT_GPT_4O_MINI` 计费
- 用户看到的是 GPT-4o-mini 级别的 credits 消耗

## 服务端开关确认

从 Unleash 特征开关数据确认，计费强制执行全部被禁用：

```
CASCADE_ENFORCE_QUOTA     = OFF  ← 配额检查不执行
trajectory-billing-system  = OFF  ← 轨迹计费系统未激活
billing-use-quota-for-plg  = OFF  ← PLG 用户配额不检查
SHOW_API_PRICING_CREDITS_USED = ON ← 仅 UI 显示，不强制执行
```

## 认证 vs 配额

**认证是会话级，不是模型级。**
- JWT 仅包含 `{"session_id": "windsurf-session-<uuid>"}`
- 没有模型授权信息
- 没有信用额度检查

## 流量证明

从捕获的 `CASCADE_STEP_COMPLETED` 响应确认：
```
model = "claude-opus-4-7-max-fast"
```

这是 Windsurf 当前可用的最高级模型。

## 架构图

```
用户看到: credits = 0
         │
         ▼
SHOW_API_PRICING_CREDITS_USED = ON
(仅 UI 展示消耗)
         │
         ▼
CASCADE_ENFORCE_QUOTA = OFF
(不检查配额)
         │
         ▼
billing_model_uid ≠ model_uid
(高级模型服务, 低级模型计费)
         │
         ▼
实际: Claude Opus 4.7 Max Fast 正常运行
```

## 结论

Windsurf 的架构设计保证了即使前端显示 credits = 0，只要服务端特征开关允许（目前确实允许），高级模型仍然可以正常使用。这是 Windsurf 的商业设计选择。
