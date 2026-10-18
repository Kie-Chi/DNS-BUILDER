package main

import (
	"flag"
	"log"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"

	"github.com/miekg/dns"
)

// Config holds the authoritative server configuration
type Config struct {
	Domain      string        // Domain to respond for (e.g., example.com)
	ListenAddr  string        // Address to listen on (e.g., :53)
	Timeout     time.Duration // Time to wait before responding (per subdomain)
	ResponseLen int           // Response payload size in bytes
}

// PendingQuery represents a pending query waiting for timeout
type PendingQuery struct {
	QueryTime  time.Time
	Timer      *time.Timer
	Response   chan *dns.Msg
	Query      *dns.Msg
	QueryType  uint16 // Store the original query type
	RemoteAddr string
}

// AuthServer represents the authoritative DNS server
type AuthServer struct {
	config       *Config
	server       *dns.Server
	pending      map[string]*PendingQuery // subdomain -> pending query
	pendingMutex sync.RWMutex
}

// NewAuthServer creates a new authoritative DNS server
func NewAuthServer(cfg *Config) *AuthServer {
	return &AuthServer{
		config:  cfg,
		pending: make(map[string]*PendingQuery),
	}
}

// handleDNSRequest handles incoming DNS queries
func (s *AuthServer) handleDNSRequest(w dns.ResponseWriter, r *dns.Msg) {
	// Get the queried domain name
	qname := r.Question[0].Name
	qtype := r.Question[0].Qtype

	// Check if this is a query for our domain (wildcard match)
	if !s.matchDomain(qname) {
		m := new(dns.Msg)
		m.SetReply(r)
		m.SetRcode(r, dns.RcodeNameError)
		w.WriteMsg(m)
		return
	}

	// Check if we already have a pending query for this subdomain
	s.pendingMutex.Lock()
	pending, exists := s.pending[qname]

	if exists {
		// Query already pending, ignore this duplicate (from resolver retry)
		s.pendingMutex.Unlock()
		log.Printf("[Ignore] Duplicate query for %s (retry dropped)", qname)
		return
	}

	// Create new pending entry
	pending = &PendingQuery{
		QueryTime:  time.Now(),
		Response:   make(chan *dns.Msg, 1),
		Query:      r,
		QueryType:  qtype,
		RemoteAddr: w.RemoteAddr().String(),
	}
	s.pending[qname] = pending
	s.pendingMutex.Unlock()

	log.Printf("[Query] New subdomain: %s, Type: %s, From: %s",
		qname, dns.TypeToString[qtype], w.RemoteAddr().String())

	// Start timer for this query
	timer := time.AfterFunc(s.config.Timeout, func() {
		s.sendResponse(qname, pending)
	})
	pending.Timer = timer

	// Wait for response and send it
	select {
	case resp := <-pending.Response:
		w.WriteMsg(resp)
	case <-time.After(s.config.Timeout + 1*time.Second):
		// Fallback timeout
		log.Printf("[Timeout] No response generated for %s", qname)
	}
}

// sendResponse generates and sends the large response after timeout
func (s *AuthServer) sendResponse(qname string, pending *PendingQuery) {
	defer func() {
		// Clean up from pending map
		s.pendingMutex.Lock()
		delete(s.pending, qname)
		s.pendingMutex.Unlock()
	}()

	log.Printf("[Timeout] Building response for %s after %v, QueryType: %s",
		qname, s.config.Timeout, dns.TypeToString[pending.QueryType])

	// Build the response
	m := new(dns.Msg)
	m.SetReply(pending.Query)
	m.Authoritative = true

	// Build response based on query type
	switch pending.QueryType {
	case dns.TypeTXT:
		s.buildTXTResponse(m, qname)
	case dns.TypeA:
		s.buildAResponse(m, qname)
	default:
		// For other query types, return A records
		s.buildAResponse(m, qname)
	}

	// Set EDNS0 for large responses
	s.setEDNS0(pending.Query, m)

	log.Printf("[Response] Sending %d bytes for %s", m.Len(), qname)

	// Send response
	select {
	case pending.Response <- m:
	default:
	}
}

// matchDomain checks if the queried name matches our domain (including wildcard)
func (s *AuthServer) matchDomain(qname string) bool {
	return dns.IsSubDomain(s.config.Domain, qname)
}

// buildAResponse builds response with multiple A records to reach target size
func (s *AuthServer) buildAResponse(m *dns.Msg, qname string) {
	// Calculate how many A records we need to reach target size
	// Each A record is approximately 16 bytes in the response
	// Start with base response overhead ~40 bytes
	targetSize := s.config.ResponseLen
	if targetSize > 4096 {
		targetSize = 4096
	}

	// Add A records until we reach target size
	recordCount := 0
	for m.Len() < targetSize && recordCount < 500 {
		a := &dns.A{
			Hdr: dns.RR_Header{
				Name:   qname,
				Rrtype: dns.TypeA,
				Class:  dns.ClassINET,
				Ttl:    300,
			},
			A: []byte{10, byte(recordCount / 256), byte(recordCount % 256), 1},
		}
		m.Answer = append(m.Answer, a)
		recordCount++
	}

	log.Printf("[Build] Added %d A records, total size: %d bytes", recordCount, m.Len())
}

// buildTXTResponse builds response with large TXT record
func (s *AuthServer) buildTXTResponse(m *dns.Msg, qname string) {
	targetSize := s.config.ResponseLen
	if targetSize > 4096 {
		targetSize = 4096
	}

	// Calculate TXT content size (account for record overhead)
	// TXT record overhead: name + type + class + ttl + rdlength + txt length prefix
	txtSize := targetSize - 50 // Leave room for overhead
	if txtSize < 100 {
		txtSize = 100
	}

	// Generate TXT content in 255-byte chunks (TXT record limit per string)
	var txtChunks []string
	remaining := txtSize
	for remaining > 0 {
		chunkSize := min(remaining, 255)
		txtChunks = append(txtChunks, generatePadding(chunkSize))
		remaining -= chunkSize
	}

	txt := &dns.TXT{
		Hdr: dns.RR_Header{
			Name:   qname,
			Rrtype: dns.TypeTXT,
			Class:  dns.ClassINET,
			Ttl:    300,
		},
		Txt: txtChunks,
	}
	m.Answer = append(m.Answer, txt)

	log.Printf("[Build] TXT record size: %d bytes, total: %d bytes", txtSize, m.Len())
}

// setEDNS0 sets EDNS0 options for large responses
func (s *AuthServer) setEDNS0(query, response *dns.Msg) {
	var clientUDPSize uint16 = 512

	for _, rr := range query.Extra {
		if opt, ok := rr.(*dns.OPT); ok {
			clientUDPSize = opt.UDPSize()
			break
		}
	}

	if clientUDPSize > 512 {
		opt := &dns.OPT{
			Hdr: dns.RR_Header{
				Name:   ".",
				Rrtype: dns.TypeOPT,
				Class:  clientUDPSize,
			},
		}
		response.Extra = append(response.Extra, opt)
	}
}

// generatePadding generates a padding string of specified size
func generatePadding(size int) string {
	if size <= 0 {
		return ""
	}
	result := make([]byte, size)
	for i := range result {
		result[i] = 'A'
	}
	return string(result)
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

// Start starts the DNS server
func (s *AuthServer) Start() error {
	dns.HandleFunc(".", s.handleDNSRequest)

	s.server = &dns.Server{
		Addr: s.config.ListenAddr,
		Net:  "udp",
	}

	go func() {
		log.Printf("[Server] Starting authoritative DNS server on %s", s.config.ListenAddr)
		log.Printf("[Config] Domain: %s, Timeout: %v, ResponseSize: %d bytes",
			s.config.Domain, s.config.Timeout, s.config.ResponseLen)
		if err := s.server.ListenAndServe(); err != nil {
			log.Fatalf("[Error] Failed to start server: %v", err)
		}
	}()

	return nil
}

// Stop stops the DNS server
func (s *AuthServer) Stop() {
	if s.server != nil {
		s.server.Shutdown()
	}
}

// Stats prints current pending queries
func (s *AuthServer) Stats() {
	s.pendingMutex.RLock()
	count := len(s.pending)
	s.pendingMutex.RUnlock()
	log.Printf("[Stats] Pending queries: %d", count)
}

func main() {
	domain := flag.String("domain", "example.com", "Domain to respond for (wildcard *.domain)")
	listen := flag.String("listen", ":5353", "Address to listen on")
	timeoutMs := flag.Int("timeout", 5000, "Time to wait before responding per subdomain (milliseconds)")
	responseSize := flag.Int("size", 4096, "Response payload size in bytes (max 4096)")
	flag.Parse()

	if *domain == "" {
		log.Fatal("Domain is required")
	}
	if *responseSize > 4096 {
		log.Printf("[Warning] Response size %d exceeds EDNS0 max (4096), capping to 4096", *responseSize)
		*responseSize = 4096
	}

	cfg := &Config{
		Domain:      dns.Fqdn(*domain),
		ListenAddr:  *listen,
		Timeout:     time.Duration(*timeoutMs) * time.Millisecond,
		ResponseLen: *responseSize,
	}

	server := NewAuthServer(cfg)
	if err := server.Start(); err != nil {
		log.Fatalf("Failed to start server: %v", err)
	}

	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
	<-sigChan

	log.Println("[Server] Shutting down...")
	server.Stop()
}