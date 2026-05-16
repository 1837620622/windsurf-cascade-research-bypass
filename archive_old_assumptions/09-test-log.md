# 测试日志

## 状态
- 📝 = 待测试
- 🔄 = 测试中
- ✅ = 通过
- ❌ = 失败
- ⚠️ = 部分成功

---

## 第 1 轮测试: 无代理基线测试

## 第 1 轮测试: mitmdump 代理模式 ✅ (2026-05-16 19:22)

### 状态
- mitmdump 运行在端口 8080 ✅
- 系统代理已关闭 ✅
- 语言服务器自动重启并连接 ✅
- **API 流量正在通过 mitmdump 流动!** ✅

### 观察
- server.self-serve.windsurf.com 连接正常
- GetUserStatus / GetUserJwt / GetChatMessage 均已捕获
- 模型配置（model_configs）完整返回
- LLM 推理调用待确认

### 结论
- 语言服务器的代理检测来自扩展主机的缓存，不受系统代理开关影响
- 只要 mitmdump 在 8080 上持续运行，流量就能正常捕获
- **关键要点**: 在启动 Windsurf 之前，确保 8080 端口有服务监听
