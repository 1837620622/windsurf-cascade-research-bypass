// Windsurf Cascade 配额绕过 — Go 版
// 功能: 拦截 Unleash 标志 + 修改 GetChatMessage 请求 + 修改 GetUserStatus 响应
package main

import (
	"bytes"
	"compress/gzip"
	"crypto/tls"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"runtime"
	"strings"
	"syscall"

	"github.com/elazarl/goproxy"
)

// ===== 配置 =====
const (
	ProxyPort  = 8080
	Field20Val = 0 // field 20 设为此值
	ModelUID   = "" // 留空不改模型
)

// ===== 假 Unleash 响应 =====

// chat-client 用的标志（包含用户选择的模型）
var fakeChatToggles = map[string]any{
	"toggles": []map[string]any{
		{"name": "CASCADE_ENFORCE_QUOTA", "enabled": false, "variant": nil, "impressionData": false},
		{"name": "trajectory-billing-system", "enabled": false, "variant": nil, "impressionData": false},
		{"name": "async-bill-cascade", "enabled": true, "variant": nil, "impressionData": false},
		{"name": "billing-use-quota-for-plg", "enabled": false, "variant": nil, "impressionData": false},
		{"name": "CASCADE_PREMIUM_CONFIG_OVERRIDE", "enabled": true, "variant": nil, "impressionData": false},
		{"name": "CASCADE_FREE_CONFIG_OVERRIDE", "enabled": true, "variant": nil, "impressionData": false},
		{"name": "SHOW_API_PRICING_CREDITS_USED", "enabled": false, "variant": nil, "impressionData": false},
	},
}

// codeium-extension 用的标志
var fakeExtToggles = map[string]any{
	"toggles": []map[string]any{
		{"name": "CASCADE_ENFORCE_QUOTA", "enabled": false, "variant": nil, "impressionData": false},
		{"name": "trajectory-billing-system", "enabled": false, "variant": nil, "impressionData": false},
		{"name": "async-bill-cascade", "enabled": true, "variant": nil, "impressionData": false},
		{"name": "billing-use-quota-for-plg", "enabled": false, "variant": nil, "impressionData": false},
	},
}

// /api/client/features 响应（旧版 Unleash SDK 用）
var fakeClientFeatures = map[string]any{
	"version": 1,
	"features": []map[string]any{
		{"name": "CASCADE_ENFORCE_QUOTA", "enabled": false, "type": "release", "project": "default", "stale": false, "variants": []any{}, "strategies": []map[string]any{{"name": "default", "id": "default", "constraints": []any{}, "parameters": map[string]any{}}}},
		{"name": "trajectory-billing-system", "enabled": false, "type": "release", "project": "default", "stale": false, "variants": []any{}, "strategies": []map[string]any{{"name": "default", "id": "default", "constraints": []any{}, "parameters": map[string]any{}}}},
		{"name": "async-bill-cascade", "enabled": true, "type": "release", "project": "default", "stale": false, "variants": []any{}, "strategies": []map[string]any{{"name": "default", "id": "default", "constraints": []any{}, "parameters": map[string]any{}}}},
		{"name": "billing-use-quota-for-plg", "enabled": false, "type": "release", "project": "default", "stale": false, "variants": []any{}, "strategies": []map[string]any{{"name": "default", "id": "default", "constraints": []any{}, "parameters": map[string]any{}}}},
	},
}

// ===== 工具函数 =====

// 解析 Connect-RPC 请求帧: flags(1) + length(4 big-endian) + [gzip_data]
func decodeConnectRPC(data []byte) (flags byte, body []byte, err error) {
	if len(data) < 5 {
		return 0, nil, fmt.Errorf("数据太短: %d 字节", len(data))
	}
	flags = data[0]
	length := int(data[1])<<24 | int(data[2])<<16 | int(data[3])<<8 | int(data[4])
	if 5+length > len(data) {
		return 0, nil, fmt.Errorf("长度溢出: %d > %d", 5+length, len(data))
	}
	payload := data[5 : 5+length]
	// 检查 gzip 魔数
	if len(payload) >= 2 && payload[0] == 0x1f && payload[1] == 0x8b {
		r, err := gzip.NewReader(bytes.NewReader(payload))
		if err != nil {
			return 0, nil, fmt.Errorf("gzip 解压失败: %w", err)
		}
		defer r.Close()
		body, err = io.ReadAll(r)
		if err != nil {
			return 0, nil, fmt.Errorf("gzip 读取失败: %w", err)
		}
		return flags, body, nil
	}
	return flags, payload, nil
}

// 编码 Connect-RPC 请求帧
func encodeConnectRPC(flags byte, body []byte) []byte {
	var compressed bytes.Buffer
	w := gzip.NewWriter(&compressed)
	w.Write(body)
	w.Close()

	result := make([]byte, 5+compressed.Len())
	result[0] = flags
	result[1] = byte((compressed.Len() >> 24) & 0xff)
	result[2] = byte((compressed.Len() >> 16) & 0xff)
	result[3] = byte((compressed.Len() >> 8) & 0xff)
	result[4] = byte(compressed.Len() & 0xff)
	copy(result[5:], compressed.Bytes())
	return result
}

// 读取 protobuf varint
func readVarint(data []byte, offset int) (int, int) {
	value := 0
	shift := 0
	pos := offset
	for pos < len(data) {
		b := data[pos]
		value |= int(b&0x7f) << shift
		shift += 7
		pos++
		if b&0x80 == 0 {
			break
		}
	}
	return value, pos - offset
}

// 编码 protobuf varint
func writeVarint(value int) []byte {
	var b []byte
	for value > 0x7f {
		b = append(b, byte((value&0x7f)|0x80))
		value >>= 7
	}
	b = append(b, byte(value))
	return b
}

// ===== CA 证书加载 =====

func loadMitmproxyCA() (tls.Certificate, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return tls.Certificate{}, fmt.Errorf("获取 home 目录失败: %w", err)
	}
	caPath := filepath.Join(home, ".mitmproxy", "mitmproxy-ca.pem")
	cert, err := tls.LoadX509KeyPair(caPath, caPath)
	if err != nil {
		return tls.Certificate{}, fmt.Errorf("加载 mitmproxy CA 失败 (路径: %s): %w", caPath, err)
	}
	return cert, nil
}

// ===== 系统代理管理 (macOS) =====

func setSystemProxy(enable bool) {
	if runtime.GOOS != "darwin" {
		return
	}
	action := "on"  // on/off
	state := "开启" // 开启/关闭
	if !enable {
		action = "off"
		state = "关闭"
	}

	// 先获取当前网络服务
	cmd := exec.Command("networksetup", "-listallnetworkservices")
	out, err := cmd.Output()
	if err != nil {
		log.Printf("[代理] 获取网络服务失败: %v", err)
		return
	}

	services := strings.Split(string(out), "\n")
	var targetService string
	for _, s := range services {
		s = strings.TrimSpace(s)
		if s == "" || strings.HasPrefix(s, "An asterisk") {
			continue
		}
		// 优先选 Wi-Fi，否则选第一个非蓝牙的服务
		if strings.Contains(s, "Wi-Fi") || strings.Contains(s, "Ethernet") {
			targetService = s
			break
		}
		if targetService == "" && !strings.Contains(s, "Bluetooth") {
			targetService = s
		}
	}

	if targetService == "" {
		log.Printf("[代理] 未找到网络服务")
		return
	}

	exec.Command("networksetup", "-setwebproxy", targetService, "127.0.0.1", fmt.Sprintf("%d", ProxyPort)).Run()
	exec.Command("networksetup", "-setsecurewebproxy", targetService, "127.0.0.1", fmt.Sprintf("%d", ProxyPort)).Run()
	exec.Command("networksetup", "-setwebproxystate", targetService, action).Run()
	exec.Command("networksetup", "-setsecurewebproxystate", targetService, action).Run()
	log.Printf("[代理] 已在 %s 上%ssystem http/https 代理", targetService, state)
}

// ===== JSON 辅助 =====

func mustMarshal(v any) []byte {
	b, _ := json.Marshal(v)
	return b
}

func toJSON(v any) string {
	b := mustMarshal(v)
	return string(b)
}

// ===== 主逻辑 =====

func main() {
	log.SetFlags(log.Ltime | log.Lmicroseconds)
	log.Println("=")
	log.Println("Windsurf 配额绕过 — Go 版")
	log.Println("  监听端口:", ProxyPort)
	log.Println("  field20:", Field20Val)
	log.Println("  Unleash 拦截: ✔")
	log.Println("  GetUserStatus 修改: ✔")
	log.Println("=")

	// 加载 CA 证书
	caCert, err := loadMitmproxyCA()
	if err != nil {
		log.Fatalf("[CA] 加载失败: %v\n请先运行 mitmproxy 安装证书: mitmdump", err)
	}
	log.Printf("[CA] ✓ 已加载 %s 的证书", caCert.Leaf.Issuer.CommonName)

	// 创建代理
	proxy := goproxy.NewProxyHttpServer()
	proxy.Verbose = false

	// MITM: 拦截 unleash.codeium.com 和 server.self-serve.windsurf.com
	proxy.OnRequest(goproxy.ReqHostIs("unleash.codeium.com")).HandleConnect(goproxy.AlwaysMitm)
	proxy.OnRequest(goproxy.ReqHostIs("server.self-serve.windsurf.com")).HandleConnect(goproxy.AlwaysMitm)
	proxy.OnRequest(goproxy.ReqHostIs("windsurf.com")).HandleConnect(goproxy.AlwaysMitm)

	// === Unleash 请求: 返回假响应 ===
	proxy.OnRequest(goproxy.ReqHostIs("unleash.codeium.com")).DoFunc(
		func(r *http.Request, ctx *goproxy.ProxyCtx) (*http.Request, *http.Response) {
			path := r.URL.Path

			// 阻止 metrics 上报
			if strings.Contains(path, "/metrics") {
				return nil, goproxy.NewResponse(r, "text/plain", 202, "")
			}

			// GET /api/frontend → chat-client 前端
			if r.Method == "GET" && strings.Contains(path, "/api/frontend") {
				q := r.URL.Query()
				appName := q.Get("appName")
				var respJSON string
				switch appName {
				case "chat-client":
					respJSON = toJSON(fakeChatToggles)
					log.Printf("[Unleash] ✅ /api/frontend (chat-client)")
				case "codeium-extension":
					respJSON = toJSON(fakeExtToggles)
					log.Printf("[Unleash] ✅ /api/frontend (codeium-ext)")
				default:
					return r, nil // 放过
				}
				return nil, goproxy.NewResponse(r, "application/json", 200, respJSON)
			}

			// GET /api/client/features → 旧版 extension SDK
			if r.Method == "GET" && strings.Contains(path, "/api/client/features") {
				log.Printf("[Unleash] ✅ /api/client/features (extension)")
				return nil, goproxy.NewResponse(r, "application/json", 200, toJSON(fakeClientFeatures))
			}

			return r, nil
		})

	// === GetChatMessage 请求: 修改 field20 + model_uid ===
	proxy.OnRequest(goproxy.ReqHostIs("server.self-serve.windsurf.com")).DoFunc(
		func(r *http.Request, ctx *goproxy.ProxyCtx) (*http.Request, *http.Response) {
			if !strings.Contains(r.URL.Path, "GetChatMessage") || r.Body == nil {
				return r, nil
			}

			raw, err := io.ReadAll(r.Body)
			r.Body.Close()
			if err != nil {
				log.Printf("[GetChatMessage] 读取 body 失败: %v", err)
				return r, nil
			}

			flags, body, err := decodeConnectRPC(raw)
			if err != nil {
				log.Printf("[GetChatMessage] 解码失败: %v", err)
				r.Body = io.NopCloser(bytes.NewReader(raw))
				return r, nil
			}

			modified := make([]byte, len(body))
			copy(modified, body)

			// 修改 field 20 (varint, tag 0xa0 0x01)
			f20Tag := []byte{0xa0, 0x01}
			if idx := lastIndex(modified, f20Tag); idx >= 0 {
				valPos := idx + 2
				if valPos < len(modified) {
					oldVal := modified[valPos]
					modified[valPos] = Field20Val
					if oldVal != Field20Val {
						log.Printf("[GetChatMessage] field20: %d → %d", oldVal, Field20Val)
					}
				}
			}

			// 替换 model_uid (如果配置了)
			if ModelUID != "" {
				f21Tag := []byte{0xaa, 0x01}
				if idx := lastIndex(modified, f21Tag); idx >= 0 {
					pos := idx + 2
					strLen, consumed := readVarint(modified, pos)
					pos += consumed
					newBytes := []byte(ModelUID)
					if len(newBytes) == strLen {
						copy(modified[pos:], newBytes)
						log.Printf("[GetChatMessage] model_uid → '%s'", ModelUID)
					} else {
						// 长度不同，重建
						remaining := modified[pos+strLen:]
						newVarint := writeVarint(len(newBytes))
						prefix := modified[:idx+2]
						modified = append(append(prefix, newVarint...), newBytes...)
						modified = append(modified, remaining...)
						log.Printf("[GetChatMessage] model_uid → '%s' (重建 protobuf)", ModelUID)
					}
				}
			}

			r.Body = io.NopCloser(bytes.NewReader(encodeConnectRPC(flags, modified)))
			r.ContentLength = int64(len(raw)) // 保持原长度？不对，需要更新
			// 修正 Content-Length
			newRaw := encodeConnectRPC(flags, modified)
			r.Body = io.NopCloser(bytes.NewReader(newRaw))
			r.ContentLength = int64(len(newRaw))
			r.Header.Del("Content-Length") // 让 Go 自动设置

			return r, nil
		})

	// === GetUserStatus 响应: 修改 JSON ===
	proxy.OnResponse().DoFunc(
		func(r *http.Response, ctx *goproxy.ProxyCtx) *http.Response {
			if r == nil || r.Body == nil {
				return r
			}
			host := r.Request.URL.Host
			path := r.Request.URL.Path

			if !strings.Contains(host, "self-serve.windsurf.com") && !strings.Contains(host, "windsurf.com") {
				return r
			}
			if !strings.Contains(path, "GetUserStatus") {
				return r
			}
			if r.Header.Get("Content-Type") != "application/json" &&
				r.Header.Get("content-type") != "application/json" {
				return r
			}

			raw, err := io.ReadAll(r.Body)
			r.Body.Close()
			if err != nil {
				return r
			}

			var j map[string]any
			if err := json.Unmarshal(raw, &j); err != nil {
				return r
			}

			changed := false
			if ps, ok := j["planStatus"].(map[string]any); ok {
				if pi, ok := ps["planInfo"].(map[string]any); ok {
					pi["billingStrategy"] = "BILLING_STRATEGY_FREE"
					pi["monthlyPromptCredits"] = -1
					changed = true
				}
				if w, ok := ps["weeklyQuotaRemainingPercent"]; ok {
					old := fmt.Sprintf("%v", w)
					ps["weeklyQuotaRemainingPercent"] = 100
					log.Printf("[GetUserStatus] weekly: %s%% → 100%%", old)
					changed = true
				}
				if d, ok := ps["dailyQuotaRemainingPercent"]; ok {
					old := d
					ps["dailyQuotaRemainingPercent"] = 100
					if old != 100 {
						changed = true
					}
				}
				if c, ok := ps["availablePromptCredits"]; ok {
					old := fmt.Sprintf("%v", c)
					ps["availablePromptCredits"] = 999999
					log.Printf("[GetUserStatus] credits: %s → 999999", old)
					changed = true
				}
				if _, ok := ps["cascadeModelConfigData"]; ok {
					// 清空模型限制
					ps["cascadeModelConfigData"] = map[string]any{}
					changed = true
				}
			}

			if changed {
				newBody, _ := json.Marshal(j)
				r.Body = io.NopCloser(bytes.NewReader(newBody))
				r.ContentLength = int64(len(newBody))
				r.Header.Set("Content-Length", fmt.Sprintf("%d", r.ContentLength))
				log.Printf("[GetUserStatus] ✓ 已修改配额数据")
			} else {
				r.Body = io.NopCloser(bytes.NewReader(raw))
			}

			return r
		})

	// 启动代理
	listener, err := net.Listen("tcp", fmt.Sprintf(":%d", ProxyPort))
	if err != nil {
		log.Fatalf("[代理] 监听失败: %v", err)
	}

	log.Printf("[代理] ✓ 监听 127.0.0.1:%d", ProxyPort)
	log.Println("[代理] 正在设置系统代理...")
	setSystemProxy(true)
	log.Println("[代理] ✓ 系统代理已开启，请在 Windsurf IDE 测试 Cascade")

	// 信号处理：退出时关闭系统代理
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
	go func() {
		<-sigCh
		log.Println("\n[代理] 正在关闭...")
		setSystemProxy(false)
		listener.Close()
		os.Exit(0)
	}()

	if err := http.Serve(listener, proxy); err != nil {
		log.Fatalf("[代理] 服务错误: %v", err)
	}
}

// 查找最后一个匹配位置
func lastIndex(data, pattern []byte) int {
	for i := len(data) - len(pattern); i >= 0; i-- {
		match := true
		for j := 0; j < len(pattern); j++ {
			if data[i+j] != pattern[j] {
				match = false
				break
			}
		}
		if match {
			return i
		}
	}
	return -1
}
