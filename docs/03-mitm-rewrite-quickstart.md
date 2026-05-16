# Quickstart — mitm + model_uid 替换

> 5 分钟跑通。前提：mitmproxy 已装，Windsurf 已登录。

---

## 方案概要

| | 内容 |
|---|---|
| **你做的** | 启 mitmdump 加 addon → 用代理变量启动 Windsurf → 在 UI 选 Claude Opus 4.7 Max Fast |
| **后台发生** | mitm 把请求里的 `model_uid` 从 Opus 换成 `kimi-k2-6`（或 `swe-1-6`），把响应里的 model 名再换回去 |
| **结果** | UI 显示 "Opus 在回答"，**实际响应来自 Kimi K2.6**，**不消耗 Windsurf 周配额** |
| **限制** | 这**不是真 Opus**。能力强但风格不同。要真 Opus 见根 README 的"合法路径" |

---

## 一键启动

```bash
cd ~/Downloads/wf逆向

# 1. 收尾旧进程
pkill -f "mitmdump --listen-port 8080" 2>/dev/null
pkill -f "/Applications/Windsurf.app/Contents/MacOS/Windsurf" 2>/dev/null
sleep 1

# 2. 启 mitmdump 加载 rewrite addon
mkdir -p /tmp/wf_run
mitmdump --listen-port 8080 \
  -w /tmp/wf_run/flows.mitm \
  -s tools/rewrite_model.py \
  --set http2=true \
  > /tmp/wf_run/mitm.log 2>&1 &
sleep 2

# 3. 用代理变量起 Windsurf（GUI 不继承 shell env，必须直接调二进制）
nohup env \
  HTTPS_PROXY=http://127.0.0.1:8080 \
  HTTP_PROXY=http://127.0.0.1:8080 \
  /Applications/Windsurf.app/Contents/MacOS/Windsurf \
  > /tmp/wf_run/windsurf.log 2>&1 &

echo "✓ 跑起来了"
```

然后在 Cascade 里选 `Claude Opus 4.7 Max Fast`，发消息。

---

## 验证

```bash
# 看 mitm 是否触发改写
grep -E "REQ |RESP" /tmp/wf_run/mitm.log | tail -10
# 期望:
#   [REQ ] claude-opus-4-7-max-fast → kimi-k2-6
#   [RESP] kimi-k2-6 → claude-opus-4-7-max-fast

# 看 GetChatMessage 是否成功
python3 tools/scan_chat.py /tmp/wf_run/flows.mitm
# 期望: GetChatMessage [200] 有 resp > 1KB 的（真实回复）
```

---

## 调整目标模型

编辑 `tools/rewrite_model.py` 第 8 行：

```python
TARGET_MODEL = b"kimi-k2-6"   # 默认。Moonshot Kimi K2.6, 200k context
# TARGET_MODEL = b"swe-1-6"     # Windsurf 自家 SWE-1.6, 偏代码
```

实测**只有这两个真不计配额**（官方 docs 也写 `credit_multiplier: 0` 的就这俩）。`adaptive` / `claude-haiku-4-5` / `gpt-5.4-mini` / `swe-1-6-fast` 等都被 quota 拦。

---

## 关闭

```bash
pkill -f "mitmdump --listen-port 8080"
pkill -f "/Applications/Windsurf.app/Contents/MacOS/Windsurf"
```

证书已在系统钥匙串里，不用动。下次直接重启 mitmdump 即可。

---

## 排错

### 1. Cascade 发消息无响应

```bash
# 确认 mitm 在跑
lsof -nP -iTCP:8080 -sTCP:LISTEN

# 确认 Windsurf 走代理（看抓包文件有没有增长）
ls -lh /tmp/wf_run/flows.mitm

# 看 mitm 收没收到 GCM
python3 tools/scan_chat.py /tmp/wf_run/flows.mitm | grep GetChatMessage
```

### 2. 报 `weekly usage quota exhausted`

请求**没被拦截改写**。检查：
- 模型名变没变（Windsurf 升级后 model_uid 可能改）
- mitm addon 路径对不对
- HTTPS_PROXY 环境变量有没有继承到 Windsurf 子进程

```bash
# 看请求里实际带的 model_uid
python3 tools/full_compare.py /tmp/wf_run/flows.mitm | head -50
```

### 3. 报 `unauthenticated`

JWT 过期了。等 Windsurf 自动刷新（5 分钟一次），或重启 Windsurf。

---

## 局限

| 局限 | 影响 |
|---|---|
| 实际是 Kimi K2.6 而不是 Opus | 复杂代码任务可能不如 Opus |
| 客户端某些上报字段（trajectory analytics）会泄露真 model | 服务端记账是 Kimi。不影响 quota |
| 任意时刻 Windsurf 改 quota 逻辑 | 这个方案就废了（cat-and-mouse） |

---

## 想用真 Opus 的合法路径

见根 [README.md](../README.md) "真正可行的路径" 一节：
- 等 quota 重置
- 开 Windsurf Extra Usage（按 API 标价付费）
- Devin for Terminal（独立配额池）
- Devin in Windsurf（IDE 右上云端图标，2 周 free trial）
