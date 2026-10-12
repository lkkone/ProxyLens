package main

import (
	"context"
	"encoding/json"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"
)

func TestResolveAndPrimary(t *testing.T) {
	proxies := map[string]Proxy{"GLOBAL": {All: []string{"Proxy"}, Now: "Proxy"}, "Proxy": {Type: "Selector", All: []string{"auto"}, Now: "auto"}, "auto": {Type: "URLTest", All: []string{"HK"}, Now: "HK"}, "HK": {Type: "Shadowsocks"}, "balance": {Type: "LoadBalance", All: []string{"HK"}, Now: "HK"}, "loop": {All: []string{"loop"}, Now: "loop"}}
	if resolve("Proxy", proxies) != "HK" {
		t.Fatal("nested selection was not resolved")
	}
	for _, name := range []string{"loop", "balance", "missing"} {
		if resolve(name, proxies) != "" {
			t.Fatal("must not invent a stable exit", name)
		}
	}
	if primary(Config{}, "global", proxies, nil) != "GLOBAL" {
		t.Fatal("global mode must use GLOBAL")
	}
	if primary(Config{Policy: Policy{PrimaryGroup: "missing"}}, "rule", proxies, nil) != "" {
		t.Fatal("explicit missing group should not silently fall back")
	}
}

func TestUnixSocketDiscovery(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Unix socket test")
	}
	socket := filepath.Join(t.TempDir(), "core.sock")
	ln, err := net.Listen("unix", socket)
	if err != nil {
		t.Fatal(err)
	}
	server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer a#secret" {
			w.WriteHeader(401)
			return
		}
		w.Write([]byte(`{"version":"test"}`))
	})}
	go server.Serve(ln)
	defer server.Close()
	dir := t.TempDir()
	file := filepath.Join(dir, "clash-verge.yaml")
	os.WriteFile(file, []byte("external-controller: ''\nexternal-controller-unix: "+socket+"\nsecret: 'a#secret'\n"), 0600)
	os.WriteFile(filepath.Join(dir, "profiles.yaml"), []byte("current: active\nitems:\n- uid: other\n  type: remote\n  name: Other\n- uid: active\n  type: remote\n  name: Test Airport\n  url: https://secret.invalid/token\n"), 0600)
	c := Config{ClashConfigPath: file}
	m := &Mihomo{}
	if err = m.discover(context.Background(), c); err != nil {
		t.Fatal(err)
	}
	if m.socket != socket {
		t.Fatal("socket not selected")
	}
	if activeProfileName(c) != "Test Airport" {
		t.Fatal("active profile not matched by uid")
	}
}

func TestEmptySecretDoesNotConsumeNextLine(t *testing.T) {
	s := "secret: \nmode: rule\nexternal-controller: '127.0.0.1:9097'\n"
	if yamlValue(yamlSecret.FindStringSubmatch(s)) != "" {
		t.Fatal("empty secret consumed next YAML line")
	}
	if yamlValue(yamlController.FindStringSubmatch(s)) != "127.0.0.1:9097" {
		t.Fatal("controller parse failed")
	}
}

func TestCollectionPrivacyAndProbeBudget(t *testing.T) {
	calls := 0
	core := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer local-secret" {
			w.WriteHeader(401)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		switch {
		case r.URL.Path == "/version":
			w.Write([]byte(`{"version":"test"}`))
		case r.URL.Path == "/configs":
			w.Write([]byte(`{"mode":"rule","tun":{"enable":true},"secret":"do-not-upload"}`))
		case r.URL.Path == "/proxies":
			w.Write([]byte(`{"proxies":{"Proxy":{"type":"Selector","all":["HK"],"now":"HK"},"HK":{"name":"HK","type":"Shadowsocks","server":"private-server","password":"private-password","history":[]}}}`))
		case r.URL.Path == "/providers/proxies":
			w.Write([]byte(`{"providers":{"Airport":{"vehicleType":"HTTP","url":"https://private-subscription/token","subscriptionInfo":{"Upload":10,"Download":20,"Total":100,"Expire":2000000000},"proxies":[{"name":"HK"}]}}}`))
		case strings.HasSuffix(r.URL.Path, "/delay"):
			calls++
			w.Write([]byte(`{"delay":42}`))
		default:
			w.WriteHeader(404)
		}
	}))
	defer core.Close()
	c := Config{Policy: defaults(), ControllerURL: core.URL, ControllerSecret: "local-secret"}
	m := &Mihomo{}
	r := m.Collect(context.Background(), c)
	if !r.CoreReachable || r.SelectedNode != "HK" || r.Airport != "Airport" || r.Probe == nil || !r.Probe.OK {
		t.Fatalf("unexpected report: %#v", r)
	}
	if r.Providers[0].Usage.Total == nil || *r.Providers[0].Usage.Total != 100 {
		t.Fatal("subscription usage missing")
	}
	r = m.Collect(context.Background(), c)
	if calls != 1 || r.Probe == nil || *r.Probe.Delay != 42 {
		t.Fatal("cached probe or sampling budget violated")
	}
	b, _ := json.Marshal(r)
	for _, secret := range []string{"local-secret", "do-not-upload", "private-server", "private-password", "private-subscription"} {
		if strings.Contains(string(b), secret) {
			t.Fatal("credential leaked", secret)
		}
	}
	c.ProbeEnabled = false
	if m.Collect(context.Background(), c).Probe != nil || calls != 1 {
		t.Fatal("disabled probe still exposed or ran")
	}
}

func TestConfigValidation(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "agent.json")
	for _, tc := range []struct {
		url          string
		allow, valid bool
	}{{"http://127.0.0.1:18790", false, true}, {"https://proxy.example.com", false, true}, {"http://remote.example.com", false, false}, {"http://192.168.1.2", true, true}, {"https://user:password@proxy.example.com", false, false}} {
		c := Config{ServerURL: tc.url, Token: "token", Adapter: "mihomo", AllowHTTP: tc.allow, Policy: defaults()}
		b, _ := json.Marshal(c)
		os.WriteFile(path, b, 0600)
		_, err := loadConfig(path)
		if (err == nil) != tc.valid {
			t.Fatalf("URL validation mismatch %s: %v", tc.url, err)
		}
	}
	for _, s := range []string{"http://0.0.0.0:9090", "http://remote.example.com:9090", "https://127.0.0.1:9090"} {
		if validateController(s) {
			t.Fatal("unsafe controller accepted", s)
		}
	}
}

func TestProbeClearedWhenNodeChanges(t *testing.T) {
	selected := "A"
	core := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/version":
			w.Write([]byte(`{"version":"test"}`))
		case "/configs":
			w.Write([]byte(`{"mode":"rule"}`))
		case "/proxies":
			json.NewEncoder(w).Encode(map[string]any{"proxies": map[string]any{"Proxy": map[string]any{"type": "Selector", "all": []string{"A", "B"}, "now": selected}, "A": map[string]any{"type": "Shadowsocks"}, "B": map[string]any{"type": "Shadowsocks"}}})
		case "/providers/proxies":
			w.Write([]byte(`{"providers":{}}`))
		default:
			w.Write([]byte(`{"delay":12}`))
		}
	}))
	defer core.Close()
	m := &Mihomo{}
	c := Config{ControllerURL: core.URL, Policy: defaults()}
	if m.Collect(context.Background(), c).Probe == nil {
		t.Fatal("initial probe missing")
	}
	selected = "B"
	r := m.Collect(context.Background(), c)
	if r.Probe != nil {
		t.Fatal("old node delay survived a node switch")
	}
	m.lastProbe = time.Now().Add(-61 * time.Second)
	if r = m.Collect(context.Background(), c); r.Probe == nil || r.Probe.Node != "B" {
		t.Fatal("new node wasn't sampled after cooldown")
	}
}
