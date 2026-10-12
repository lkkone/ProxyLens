// ProxyLens agent: local adapters produce a versioned, credential-free telemetry report.
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"regexp"
	"runtime"
	"sort"
	"strings"
	"syscall"
	"time"

	"gopkg.in/yaml.v3"
)

const version = "0.1.0"

type Policy struct {
	ReportInterval int    `json:"report_interval"`
	ProbeInterval  int    `json:"probe_interval"`
	ProbeEnabled   bool   `json:"probe_enabled"`
	PrimaryGroup   string `json:"primary_group"`
	AirportLabel   string `json:"airport_label"`
	ProbeURL       string `json:"probe_url"`
}
type Config struct {
	ServerURL        string `json:"server_url"`
	Token            string `json:"token"`
	Adapter          string `json:"adapter"`
	ControllerURL    string `json:"controller_url"`
	ControllerSocket string `json:"controller_socket"`
	ControllerPipe   string `json:"controller_pipe"`
	ControllerSecret string `json:"controller_secret"`
	ClashConfigPath  string `json:"clash_config_path"`
	AllowHTTP        bool   `json:"allow_http"`
	Policy
}
type Probe struct {
	OK     bool   `json:"ok"`
	Delay  *int   `json:"delay_ms"`
	At     int64  `json:"at"`
	Node   string `json:"node"`
	Error  string `json:"error"`
	Target string `json:"target"`
}
type Group struct {
	Name     string `json:"name"`
	Type     string `json:"type"`
	Selected string `json:"selected"`
	Leaf     string `json:"leaf"`
}
type Node struct {
	Name    string `json:"name"`
	Type    string `json:"type"`
	Delay   *int   `json:"delay_ms"`
	DelayAt string `json:"delay_at"`
}
type Usage struct {
	Upload   *float64 `json:"upload"`
	Download *float64 `json:"download"`
	Total    *float64 `json:"total"`
	Expire   *float64 `json:"expire"`
}
type Provider struct {
	Name      string `json:"name"`
	Type      string `json:"type"`
	UpdatedAt string `json:"updated_at"`
	NodeCount int    `json:"node_count"`
	Usage     Usage  `json:"usage"`
}
type Report struct {
	SchemaVersion int        `json:"schema_version"`
	Adapter       string     `json:"adapter"`
	Hostname      string     `json:"hostname"`
	OS            string     `json:"os"`
	Arch          string     `json:"arch"`
	AgentVersion  string     `json:"agent_version"`
	CoreVersion   string     `json:"core_version"`
	CoreReachable bool       `json:"core_reachable"`
	CoreError     string     `json:"core_error"`
	Mode          string     `json:"mode"`
	TunEnabled    bool       `json:"tun_enabled"`
	SystemProxy   string     `json:"system_proxy"`
	PrimaryGroup  string     `json:"primary_group"`
	SelectedNode  string     `json:"selected_node"`
	Airport       string     `json:"airport"`
	Probe         *Probe     `json:"probe"`
	Groups        []Group    `json:"groups"`
	Providers     []Provider `json:"providers"`
	Nodes         []Node     `json:"nodes"`
}
type Adapter interface {
	Collect(context.Context, Config) Report
}
type Mihomo struct {
	controller  string
	socket      string
	pipe        string
	secret      string
	probe       *Probe
	lastProbe   time.Time
	fingerprint string
}
type Proxy struct {
	Name    string   `json:"name"`
	Type    string   `json:"type"`
	Now     string   `json:"now"`
	All     []string `json:"all"`
	History []struct {
		Time  string `json:"time"`
		Delay int    `json:"delay"`
	} `json:"history"`
}

func localClient(timeout time.Duration) *http.Client {
	return &http.Client{Timeout: timeout, Transport: &http.Transport{Proxy: nil}, CheckRedirect: func(req *http.Request, via []*http.Request) error { return http.ErrUseLastResponse }}
}

func (m *Mihomo) get(ctx context.Context, path string, out any, timeout time.Duration) error {
	req, err := http.NewRequestWithContext(ctx, "GET", m.controller+path, nil)
	if err != nil {
		return err
	}
	if m.secret != "" {
		req.Header.Set("Authorization", "Bearer "+m.secret)
	}
	client := localClient(timeout)
	transport := client.Transport.(*http.Transport)
	if m.socket != "" {
		transport.DialContext = func(ctx context.Context, _, _ string) (net.Conn, error) {
			return (&net.Dialer{}).DialContext(ctx, "unix", m.socket)
		}
	}
	if m.pipe != "" {
		transport.DialContext = func(ctx context.Context, _, _ string) (net.Conn, error) { return dialPipe(ctx, m.pipe) }
	}
	defer client.CloseIdleConnections()
	resp, err := client.Do(req)
	if err != nil {
		return errors.New("本地控制接口不可达")
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		if resp.StatusCode == 401 || resp.StatusCode == 403 {
			return errors.New("控制接口密钥错误，请检查 controller_secret")
		}
		return fmt.Errorf("控制接口返回 HTTP %d", resp.StatusCode)
	}
	return json.NewDecoder(io.LimitReader(resp.Body, 8<<20)).Decode(out)
}

// Read only controller + secret from known runtime files; never read or upload subscription URLs.
func discoverFiles(c Config) []string {
	if c.ClashConfigPath != "" {
		return []string{c.ClashConfigPath}
	}
	home, _ := os.UserHomeDir()
	dirs := []string{
		filepath.Join(home, ".config", "clash-verge"),
		filepath.Join(home, ".config", "io.github.clash-verge-rev.clash-verge-rev"),
		filepath.Join(home, ".config", "clash"),
		filepath.Join(home, ".config", "mihomo"),
		filepath.Join(home, "Library", "Application Support", "io.github.clash-verge-rev.clash-verge-rev"),
		filepath.Join(home, "Library", "Application Support", "io.github.clash-verge.clash-verge"),
	}
	if appdata := os.Getenv("APPDATA"); appdata != "" {
		dirs = append(dirs, filepath.Join(appdata, "io.github.clash-verge-rev.clash-verge-rev"), filepath.Join(appdata, "io.github.clash-verge.clash-verge"))
	}
	files := []string{}
	for _, dir := range dirs {
		for _, name := range []string{"clash-verge.yaml", "config.yaml", "clash.yaml"} {
			files = append(files, filepath.Join(dir, name))
		}
	}
	return files
}

var yamlController = regexp.MustCompile(`(?m)^external-controller:[ \t]*([^\r\n#]+)`)
var yamlSocket = regexp.MustCompile(`(?m)^external-controller-unix:[ \t]*([^\r\n#]*)`)
var yamlPipe = regexp.MustCompile(`(?m)^external-controller-pipe:[ \t]*([^\r\n#]*)`)
var yamlSecret = regexp.MustCompile(`(?m)^secret:[ \t]*([^\r\n#]*)`)

func yamlValue(match []string) string {
	if len(match) < 2 {
		return ""
	}
	return strings.Trim(strings.TrimSpace(match[1]), "\"'")
}

type ControllerConfig struct {
	Address string `yaml:"external-controller"`
	Socket  string `yaml:"external-controller-unix"`
	Pipe    string `yaml:"external-controller-pipe"`
	Secret  string `yaml:"secret"`
}

func activeProfileName(c Config) string {
	seen := map[string]bool{}
	for _, file := range discoverFiles(c) {
		path := filepath.Join(filepath.Dir(file), "profiles.yaml")
		if seen[path] {
			continue
		}
		seen[path] = true
		data, e := os.ReadFile(path)
		if e != nil {
			continue
		}
		var profiles struct {
			Current string `yaml:"current"`
			Items   []struct {
				UID  string `yaml:"uid"`
				Name string `yaml:"name"`
				Type string `yaml:"type"`
			} `yaml:"items"`
		}
		if yaml.Unmarshal(data, &profiles) != nil {
			continue
		}
		for _, item := range profiles.Items {
			if item.UID == profiles.Current && (item.Type == "remote" || item.Type == "local") {
				return item.Name
			}
		}
	}
	return ""
}
func validateController(raw string) bool {
	u, e := url.Parse(raw)
	return e == nil && u.Scheme == "http" && (u.Hostname() == "127.0.0.1" || u.Hostname() == "localhost" || u.Hostname() == "::1") && u.User == nil && u.RawQuery == "" && u.Fragment == "" && (u.Path == "" || u.Path == "/")
}
func (m *Mihomo) discover(ctx context.Context, c Config) error {
	type candidate struct{ address, secret, socket, pipe string }
	candidates := []candidate{}
	explicit := c.ControllerURL != "" || c.ControllerSocket != "" || c.ControllerPipe != ""
	if explicit {
		address := strings.TrimRight(c.ControllerURL, "/")
		if address == "" {
			address = "http://localhost"
		}
		candidates = append(candidates, candidate{address, c.ControllerSecret, c.ControllerSocket, c.ControllerPipe})
	} else {
		for _, file := range discoverFiles(c) {
			data, e := os.ReadFile(file)
			if e != nil {
				continue
			}
			var cfg ControllerConfig
			if yaml.Unmarshal(data, &cfg) != nil {
				continue
			}
			host := cfg.Address
			secret := cfg.Secret
			if c.ControllerSecret != "" {
				secret = c.ControllerSecret
			}
			socket := cfg.Socket
			pipe := cfg.Pipe
			if socket != "" && runtime.GOOS != "windows" {
				candidates = append(candidates, candidate{"http://localhost", secret, socket, ""})
			}
			if pipe != "" && runtime.GOOS == "windows" {
				candidates = append(candidates, candidate{"http://localhost", secret, "", pipe})
			}
			host = strings.Replace(host, "0.0.0.0:", "127.0.0.1:", 1)
			if host != "" && !strings.Contains(host, "://") {
				host = "http://" + host
			}
			if host != "" {
				candidates = append(candidates, candidate{host, secret, "", ""})
			}
		}
		candidates = append(candidates, candidate{"http://127.0.0.1:9097", c.ControllerSecret, "", ""}, candidate{"http://127.0.0.1:9090", c.ControllerSecret, "", ""})
	}
	last := errors.New("未发现 Clash Verge/Mihomo 控制接口，请检查客户端运行与 API 设置")
	for _, candidate := range candidates {
		if !validateController(candidate.address) {
			continue
		}
		m.controller, m.secret, m.socket, m.pipe = candidate.address, candidate.secret, candidate.socket, candidate.pipe
		var v map[string]any
		if e := m.get(ctx, "/version", &v, 2*time.Second); e == nil {
			return nil
		} else {
			last = e
		}
	}
	m.controller = ""
	m.socket = ""
	m.pipe = ""
	return last
}
func resolve(name string, proxies map[string]Proxy) string {
	seen := map[string]bool{}
	for i := 0; i < 32; i++ {
		if seen[name] {
			return ""
		}
		seen[name] = true
		p, ok := proxies[name]
		if !ok {
			return ""
		}
		if len(p.All) == 0 {
			return name
		}
		if p.Type == "LoadBalance" || p.Type == "Relay" {
			return ""
		} // no single stable exit
		if p.Now == "" {
			return ""
		}
		name = p.Now
	}
	return ""
}
func primary(c Config, mode string, proxies map[string]Proxy, groups []Group) string {
	if mode == "direct" {
		return ""
	}
	if mode == "global" {
		if _, ok := proxies["GLOBAL"]; ok {
			return "GLOBAL"
		}
	}
	if c.PrimaryGroup != "" {
		if _, ok := proxies[c.PrimaryGroup]; ok {
			return c.PrimaryGroup
		}
		return ""
	}
	for _, name := range []string{"🚀 节点选择", "节点选择", "PROXY", "Proxy", "代理", "🚀 手动切换"} {
		if _, ok := proxies[name]; ok {
			return name
		}
	}
	for _, g := range groups {
		if g.Name != "GLOBAL" && g.Type == "Selector" {
			return g.Name
		}
	}
	for _, g := range groups {
		if g.Name != "GLOBAL" {
			return g.Name
		}
	}
	return ""
}
func command(ctx context.Context, name string, args ...string) (string, error) {
	timeout, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	b, e := exec.CommandContext(timeout, name, args...).Output()
	return string(b), e
}
func systemProxy(ctx context.Context) string {
	switch runtime.GOOS {
	case "darwin":
		s, e := command(ctx, "scutil", "--proxy")
		if e != nil {
			return "unknown"
		}
		if regexp.MustCompile(`(?m)(HTTPEnable|HTTPSEnable|SOCKSEnable|ProxyAutoConfigEnable)\s*:\s*1`).MatchString(s) {
			return "enabled"
		}
		return "disabled"
	case "windows":
		s, e := command(ctx, "powershell.exe", "-NoProfile", "-NonInteractive", "-Command", `$p=Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'; if ($p.ProxyEnable -eq 1 -or $p.AutoConfigURL) { 'enabled' } else { 'disabled' }`)
		if e != nil {
			return "unknown"
		}
		return strings.TrimSpace(s)
	case "linux":
		s, e := command(ctx, "gsettings", "get", "org.gnome.system.proxy", "mode")
		if e != nil {
			return "unknown"
		}
		if strings.Contains(s, "manual") || strings.Contains(s, "auto") {
			return "enabled"
		}
		return "disabled"
	}
	return "unknown"
}
func (m *Mihomo) Collect(ctx context.Context, c Config) Report {
	host, _ := os.Hostname()
	r := Report{SchemaVersion: 1, Adapter: "mihomo", Hostname: host, OS: runtime.GOOS, Arch: runtime.GOARCH, AgentVersion: version, SystemProxy: systemProxy(ctx), Groups: []Group{}, Providers: []Provider{}, Nodes: []Node{}}
	fail := func(e error) Report { r.CoreError = e.Error(); m.probe = nil; m.fingerprint = ""; return r }
	if m.controller == "" {
		if e := m.discover(ctx, c); e != nil {
			return fail(e)
		}
	}
	var v struct {
		Version string `json:"version"`
	}
	if e := m.get(ctx, "/version", &v, 3*time.Second); e != nil {
		m.controller = ""
		return fail(e)
	}
	r.CoreVersion = v.Version
	var settings struct {
		Mode string `json:"mode"`
		Tun  struct {
			Enable bool `json:"enable"`
		} `json:"tun"`
	}
	if e := m.get(ctx, "/configs", &settings, 3*time.Second); e != nil {
		return fail(e)
	}
	var all struct {
		Proxies map[string]Proxy `json:"proxies"`
	}
	if e := m.get(ctx, "/proxies", &all, 3*time.Second); e != nil {
		return fail(e)
	}
	r.CoreReachable = true
	r.Mode = settings.Mode
	r.TunEnabled = settings.Tun.Enable
	names := []string{}
	for name := range all.Proxies {
		names = append(names, name)
	}
	sort.Strings(names)
	for _, name := range names {
		p := all.Proxies[name]
		if len(p.All) > 0 {
			if len(r.Groups) < 200 {
				r.Groups = append(r.Groups, Group{name, p.Type, p.Now, resolve(name, all.Proxies)})
			}
		} else if len(r.Nodes) < 2000 {
			n := Node{Name: name, Type: p.Type}
			if len(p.History) > 0 {
				h := p.History[len(p.History)-1]
				if h.Delay > 0 {
					d := h.Delay
					n.Delay = &d
				}
				n.DelayAt = h.Time
			}
			r.Nodes = append(r.Nodes, n)
		}
	}
	r.PrimaryGroup = primary(c, r.Mode, all.Proxies, r.Groups)
	if r.Mode == "direct" {
		r.SelectedNode = "DIRECT"
	} else if r.PrimaryGroup != "" {
		r.SelectedNode = resolve(r.PrimaryGroup, all.Proxies)
	}
	var providers struct {
		Providers map[string]struct {
			VehicleType      string  `json:"vehicleType"`
			UpdatedAt        string  `json:"updatedAt"`
			SubscriptionInfo Usage   `json:"subscriptionInfo"`
			Proxies          []Proxy `json:"proxies"`
		} `json:"providers"`
	}
	if e := m.get(ctx, "/providers/proxies", &providers, 3*time.Second); e == nil {
		airports := []string{}
		providerNames := []string{}
		for name := range providers.Providers {
			providerNames = append(providerNames, name)
		}
		sort.Strings(providerNames)
		for _, name := range providerNames {
			p := providers.Providers[name]
			// Compatible is the synthetic aggregate, not an airport subscription.
			if strings.EqualFold(p.VehicleType, "Compatible") {
				continue
			}
			if len(r.Providers) < 100 {
				r.Providers = append(r.Providers, Provider{name, p.VehicleType, p.UpdatedAt, len(p.Proxies), p.SubscriptionInfo})
			}
			for _, node := range p.Proxies {
				if node.Name == r.SelectedNode {
					airports = append(airports, name)
					break
				}
			}
		}
		r.Airport = strings.Join(airports, " / ")
	}
	if r.Airport == "" {
		r.Airport = activeProfileName(c)
	}
	if c.AirportLabel != "" {
		r.Airport = c.AirportLabel
	}
	fp := r.SelectedNode + "|" + r.Mode + "|" + c.ProbeURL + "|" + r.Airport
	if !c.ProbeEnabled || r.SelectedNode == "" || r.SelectedNode == "DIRECT" || strings.HasPrefix(r.SelectedNode, "REJECT") {
		m.probe = nil
		m.fingerprint = fp
		r.Probe = nil
		return r
	}
	if fp != m.fingerprint {
		m.probe = nil
	}
	// Never test every node; at most one selected leaf every interval, 60s floor on switches.
	due := m.probe == nil || time.Since(m.lastProbe) >= time.Duration(c.ProbeInterval)*time.Second
	if due && (m.lastProbe.IsZero() || time.Since(m.lastProbe) >= 60*time.Second) {
		result := Probe{At: time.Now().Unix(), Node: r.SelectedNode, Target: c.ProbeURL}
		var delay struct {
			Delay int `json:"delay"`
		}
		path := "/proxies/" + url.PathEscape(r.SelectedNode) + "/delay?timeout=5000&url=" + url.QueryEscape(c.ProbeURL)
		if e := m.get(ctx, path, &delay, 7*time.Second); e != nil {
			result.Error = e.Error()
		} else if delay.Delay <= 0 {
			result.Error = "节点延迟探测失败"
		} else {
			result.OK = true
			result.Delay = &delay.Delay
		}
		m.lastProbe = time.Now()
		m.probe = &result
	}
	m.fingerprint = fp
	r.Probe = m.probe
	return r
}

func defaults() Policy { return Policy{30, 300, true, "", "", "https://www.gstatic.com/generate_204"} }
func validatePolicy(p Policy) error {
	if p.ReportInterval < 15 || p.ReportInterval > 300 || p.ProbeInterval < 60 || p.ProbeInterval > 86400 {
		return errors.New("上报间隔需为 15–300 秒，探测间隔需为 60–86400 秒")
	}
	u, e := url.Parse(p.ProbeURL)
	if e != nil || u.Scheme != "https" || u.Hostname() == "" || u.User != nil {
		return errors.New("probe_url 必须是 HTTPS 地址")
	}
	return nil
}
func loadConfig(path string) (Config, error) {
	c := Config{Adapter: "mihomo", Policy: defaults()}
	b, e := os.ReadFile(path)
	if e != nil {
		return c, e
	}
	if e = json.Unmarshal(b, &c); e != nil {
		return c, e
	}
	c.ServerURL = strings.TrimRight(c.ServerURL, "/")
	u, e := url.Parse(c.ServerURL)
	if e != nil || u.Hostname() == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || (u.Path != "" && u.Path != "/") {
		return c, errors.New("server_url 应为服务根地址，例如 https://proxy.example.com")
	}
	loopback := u.Hostname() == "localhost" || u.Hostname() == "127.0.0.1" || u.Hostname() == "::1"
	if u.Scheme != "https" && !(u.Scheme == "http" && (loopback || c.AllowHTTP)) {
		return c, errors.New("远程上报地址必须使用 HTTPS；局域网调试可设置 allow_http=true")
	}
	if c.Token == "" {
		return c, errors.New("缺少设备 token，请从面板下载配置")
	}
	if c.Adapter != "mihomo" {
		return c, errors.New("当前版本支持 mihomo 适配器（Clash Verge）")
	}
	if c.ControllerURL != "" && !validateController(c.ControllerURL) {
		return c, errors.New("controller_url 必须是本地 http://127.0.0.1:端口 地址")
	}
	return c, validatePolicy(c.Policy)
}
func send(ctx context.Context, c Config, r Report) (*Policy, error) {
	payload, e := json.Marshal(r)
	if e != nil {
		return nil, e
	}
	req, e := http.NewRequestWithContext(ctx, "POST", c.ServerURL+"/api/v1/report", bytes.NewReader(payload))
	if e != nil {
		return nil, e
	}
	req.Header.Set("Authorization", "Bearer "+c.Token)
	req.Header.Set("Content-Type", "application/json")
	client := localClient(15 * time.Second) // reporting bypasses local proxy environment to avoid monitoring recursion
	defer client.CloseIdleConnections()
	resp, e := client.Do(req)
	if e != nil {
		return nil, errors.New("上报地址不可达，请检查网络与 server_url")
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("上报 HTTP %d；401 表示设备凭证失效", resp.StatusCode)
	}
	var ack struct {
		Policy Policy `json:"policy"`
	}
	if e = json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&ack); e != nil {
		return nil, e
	}
	if e = validatePolicy(ack.Policy); e != nil {
		return nil, e
	}
	return &ack.Policy, nil
}
func main() {
	configPath := flag.String("config", "agent.json", "配置文件路径")
	once := flag.Bool("once", false, "采集并上报一次后退出")
	showVersion := flag.Bool("version", false, "显示版本")
	flag.Parse()
	if *showVersion {
		fmt.Println("ProxyLens Agent " + version + " " + runtime.GOOS + "/" + runtime.GOARCH)
		return
	}
	c, e := loadConfig(*configPath)
	if e != nil {
		log.Fatal(e)
	}
	if c.AllowHTTP {
		log.Print("已启用 HTTP 调试上报，请仅用于可信局域网")
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	adapters := map[string]Adapter{"mihomo": &Mihomo{}}
	adapter := adapters[c.Adapter]
	log.Printf("ProxyLens Agent %s 已启动；上报 %ds，延迟探测 %ds", version, c.ReportInterval, c.ProbeInterval)
	failures := 0
	for {
		r := adapter.Collect(ctx, c)
		if ctx.Err() != nil {
			return
		}
		p, e := send(ctx, c, r)
		if e != nil {
			failures++
			log.Printf("上报失败：%v", e)
		} else {
			failures = 0
			c.Policy = *p
			log.Printf("已上报：内核=%t 模式=%s", r.CoreReachable, r.Mode)
		}
		if *once {
			if e != nil {
				os.Exit(1)
			}
			return
		}
		wait := time.Duration(c.ReportInterval) * time.Second
		if failures > 0 {
			shift := failures
			if shift > 4 {
				shift = 4
			}
			wait *= time.Duration(1 << shift)
			if wait > 5*time.Minute {
				wait = 5 * time.Minute
			}
		}
		timer := time.NewTimer(wait)
		select {
		case <-ctx.Done():
			timer.Stop()
			return
		case <-timer.C:
		}
	}
}
