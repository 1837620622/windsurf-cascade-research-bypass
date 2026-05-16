# Protobuf 协议分析

## model_configs_v2.bin 解码

### 概要
从 `~/.cache/devin/cli/model_configs_v2.bin` 提取的 protobuf 定义。包含所有可用模型的完整配置。

### Protobuf 结构

```protobuf
message ModelConfig {
  // ===== 基础标识 =====
  optional string display_name = 1;          // 显示名称 (如 "Claude Opus 4.7")
  optional string model_uid = 2;             // 内部 ID
  optional string model = 3;                 // 模型标识符

  // ===== Token 限制 =====
  optional int32 context_length = 5;         // 上下文长度 (如 200000)
  optional int32 max_output_tokens = 6;      // 最大输出 Token

  // ===== 模型能力配置 =====
  optional int32 supports_vision = 9;        // 视觉支持
  optional int32 supports_audio = 116;       // 音频支持
  optional int32 supports_prompt_caching = 102; // Prompt 缓存

  // ===== 努力级别 =====
  message EffortLevel {
    optional string name = 1;                // "low" / "medium" / "high"
    optional int32 context_length = 2;       // 该级别上下文长度
  }
  repeated EffortLevel effort_levels = 14;

  // ===== 速度模式 =====
  optional bool fast_reasoning = 103;        // 快速推理模式
  optional string fast_model_uid = 104;      // 快速模式下使用的模型 ID

  // ===== 定价 =====
  message Pricing {
    optional string currency = 1;            // 货币 (如 "USD", "CREDITS")
    optional int32 input_per_1m_tokens = 2;  // 每百万 token 输入价格
    optional int32 output_per_1m_tokens = 3; // 每百万 token 输出价格
    optional int32 input_cache_hit_per_1m = 12;  // 缓存命中输入价格
    optional int32 output_per_1m_tokens_fast = 9;  // 快速模式输出价格
  }
  optional Pricing pricing = 16;

  // ===== 模型家族 =====
  optional string model_family = 106;        // 模型家族 (如 "claude", "gpt", "deepseek")

  // ===== Tokenizer =====
  enum TokenizerType {
    LLAMA_WITH_SPECIAL2 = 1;    // Claude, Kimi, SWE, DeepSeek
    CL100K_WITH_SPECIAL2 = 2;   // GPT 系列
  }
  optional TokenizerType tokenizer = 107;

  // ===== 后端路由 =====
  optional string handler = 108;             // 后端处理器代号
  optional int32 handler_version = 109;      // 处理器版本
}

// 顶层消息
message ModelConfigsWrapper {
  repeated ModelConfig configs = 1;          // 所有模型配置
  optional int32 version = 2;               // 配置文件版本
}
```

### Handler 命名约定

所有模型的后端处理器都命名为 `strawberry-pancake`，这是 Windsurf 内部的模型路由层代号，负责将请求转发到最终模型提供商（Anthropic、OpenAI、DeepSeek 等）。

### Tokenizer 类型映射

| Tokenizer 类型 | 值 | 适用模型 |
|---------------|-----|---------|
| LLAMA_WITH_SPECIAL2 | 1 | Claude, Kimi, SWE, DeepSeek |
| CL100K_WITH_SPECIAL2 | 2 | GPT 系列 (GPT-4o, GPT-4o-mini) |

---

## team_settings.bin 解码

### 概要
从 `~/.cache/devin/cli/team_settings.bin` 提取。包含当前用户的模型可用性列表。

### Protobuf 结构

```protobuf
message TeamSettings {
  message TeamModel {
    optional string model_uid = 1;    // 模型内部 ID
    optional int32 priority = 2;      // 优先级（数字越小优先级越高）
    optional bool enabled = 3;        // 是否启用
    optional string billing_model = 4; // 计费模型 ID（可选，覆盖默认计费）
  }
  repeated TeamModel models = 1;      // 模型列表
  optional string team_id = 2;        // 团队 ID
  optional int32 version = 3;         // 版本号
}
```

### 模型优先级列表（用户团队）

按优先级降序排列（数字越小表示优先级越高）：

1. **Claude Opus 4.7** — 6 个努力级别 × 2 种速度模式
   - `claude-opus-4-7-max-fast`
   - `claude-opus-4-7-max`
   - `claude-opus-4-7-high-fast`
   - `claude-opus-4-7-high`
   - `claude-opus-4-7-medium-fast`
   - `claude-opus-4-7-medium`
   - 每种 effort 还有 fast / normal 变体
2. **Claude Opus 4.6** — thinking / fast / 1M 变体
3. **GPT-5.4** — 6 个努力级别 + priority 变体
4. **GPT-5.5** — 6 个努力级别 + priority 变体
5. **Claude Sonnet 4.6**
6. **SWE-1.6**
7. **SWE-1.6-fast**
8. **DeepSeek V4**
9. **adaptive**（自动选择模型）
10. **Kimi K2.6**
11. **GLM-5-1**
12. **Gemini-3.1-Pro**
13. 遗留模型

---

## ModelUsageStats（关键发现）

### Protobuf 定义（从 extension.js 提取）

```protobuf
message ModelUsageStats {
  optional string model_uid = 1;             // 实际提供的模型（如 claude-opus-4-7-max-fast）
  optional string billing_model_uid = 2;     // 计费时使用的模型（核心字段！）
  optional string requested_model_uid = 3;   // 用户请求的模型
  optional int64 prompt_tokens = 4;          // 提示 token 数
  optional int64 completion_tokens = 5;      // 补全 token 数
  optional int64 total_tokens = 6;           // 总 token 数
  optional int64 credits_used = 7;           // 消耗的 credits
  optional int64 duration_ms = 8;            // 耗时（毫秒）
}
```

### 三模型分离架构（基于代码结构推理）

基于 extension.js 中的 `ModelUsageStats` protobuf 定义，推测其架构如下：

```
请求 →
  requested_model_uid: 用户选择的模型
  model_uid: 系统实际提供的模型 (流量中观察到 "claude-opus-4-7-max-fast")
  billing_model_uid: 计费基准 (存在此字段，但未在实际流量中捕获到具体值)
```

**注**: ⚠️ 此为推理。我们在 extension.js 中找到了 Protobuf 定义，字段名和类型是确定的，但 **尚未在实际流量中捕获到 `billing_model_uid` 的具体值**。该字段的存在证明了模型与计费解耦的架构意图，但其实际行为仍需流量验证。

### 架构意义

这是 Windsurf 的核心设计模式：
1. **requested_model_uid** — 用户想要什么模型
2. **model_uid** — 系统实际用什么模型提供服务（流量已确认）
3. **billing_model_uid** — 按哪个模型计费（存在于代码定义中，实际值待验证）
