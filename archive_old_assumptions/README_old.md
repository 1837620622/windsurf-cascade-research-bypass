# Windsurf 逆向项目

研究 Windsurf Pro 在 0 额度下使用 Claude Opus 4.7 Max 的可行性。

## 入口文档（看这两份）

1. **[FINAL_零额度Opus路径.md](FINAL_零额度Opus路径.md)** — 当前结论 + 已失败方案 + 待探索方向
2. **[v7_总结与新方向.md](v7_总结与新方向.md)** — 上一轮（patch 客户端）方案的总结，所有路线都失败

## 项目结构

```
wf逆向/
├── FINAL_零额度Opus路径.md          ← 看这个
├── v7_总结与新方向.md                ← 上一轮总结
│
├── 01-总体架构分析.md                Windsurf 三个核心二进制
├── 02-Protobuf协议分析.md            ModelConfig / TeamSettings / ModelUsageStats schema
├── 04-API流量分析.md                 端点清单（旧版，新版见 capture_2026-05-16/）
├── 06-抓包方法问题记录.md            mitmproxy 排错经验
├── 07-可行性方案与测试计划.md        5 种抓包方案对比
├── 08-流量文件数据摘要.md            旧抓包的元数据
├── 09-测试日志.md                    第 1 轮 mitmdump 验证记录
├── 10-抓包配置完整指南.md            完整 SOP（重要）
│
├── all_model_uids.txt                144 行 model_name → model_uid 映射
├── GetCliModelConfigs_分析.txt       79 个模型的 protobuf 字段 dump
├── original_getchatmessage_req.bin   46KB 完整 GetChatMessage 请求
├── unleash_features.json             790KB Unleash 原始响应（旧版，新版见 capture_2026-05-16/）
│
├── capture_2026-05-16/               ⭐ 最新抓包（决定性证据）
│   ├── flows.mitm                    9.1MB / 169 flows
│   ├── decoded_traj.txt              含 quota 拒绝错误
│   ├── decoded_planstatus.txt        Pro 配额表 + 79 模型倍率
│   ├── decoded_gcm.txt               3 次 GetChatMessage 详细
│   ├── decoded_status.txt            GetUserStatus
│   ├── decoded_userstatus_codeium.txt 47KB 版本（含模型映射）
│   ├── decoded_generator.txt         RecordCortexGeneratorMetadata
│   ├── unleash_toggles.txt           220 个 toggle 实时状态
│   ├── mitm.log                      实时事件日志
│   ├── decode_flow.py                通用 Connect-RPC 解码器
│   ├── inventory.py                  端点统计
│   ├── dump_flow.py                  按 URL 提取
│   ├── dump_unleash.py               Unleash JSON (含 brotli)
│   ├── raw_gcm_resp.py               解错误信封
│   ├── probe_unleash.py              探测压缩格式
│   └── tag.py                        mitmdump addon
│
├── wf-bypass-go/                     已写好的 Go bypass 工具
│   ├── main.go                       拦截 Unleash + 修改请求
│   └── wf-bypass-go                  编译好的二进制
│
└── archive_old_assumptions/          ⚠️ 推论错误的旧文档（已归档）
    ├── 03-Unleash功能开关.md          (说 quota 开关 OFF, 实际 ON)
    ├── 05-billing_model三模型分离分析.md  (推测的三模型计费, 没抓到证据)
    ├── 11-零额度使用高级模型原理分析.md  (基于错误前提)
    └── 12-零额度使用高级模型的终极方案.md (基于错误前提)
```

## 核心结论（来自 capture_2026-05-16/）

1. **服务端 quota 检查是真实的** — `GetChatMessage` 在配额耗尽时返回 `failed_precondition`，错误响应有明确 trace ID
2. **配额数字封装在服务端签的 HS256 JWT 里** — 客户端 patch 改不动
3. **`CheckUserMessageRateLimit` ≠ quota** — 是另一层（按 RPM），抓包里返回通过
4. **唯一可行：切号** — A8 Helper 的实际作用

## 复现抓包

```bash
# 1) 启动 mitmdump
mitmdump --listen-port 8080 -w flows.mitm --set http2=true

# 2) 用代理变量启动 Windsurf（GUI 不继承 shell env，必须直接调二进制）
nohup env \
  HTTPS_PROXY=http://127.0.0.1:8080 \
  HTTP_PROXY=http://127.0.0.1:8080 \
  /Applications/Windsurf.app/Contents/MacOS/Windsurf \
  > /tmp/windsurf.log 2>&1 &

# 3) 在 Cascade 里发消息触发流量

# 4) 解码
python3 capture_2026-05-16/inventory.py flows.mitm
python3 capture_2026-05-16/decode_flow.py flows.mitm "GetChatMessage" 1
```

## 证书状态

- 本地 CA: `~/.mitmproxy/mitmproxy-ca-cert.pem`  serial=735716...609D, 2026-05-14 → 2036-05-13
- 系统 Keychain: 同一张已信任 (CN=mitmproxy)
- **不需要重新生成**（本次抓包已验证可用）
