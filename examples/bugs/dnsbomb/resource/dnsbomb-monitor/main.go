package main

import (
	"flag"
	"fmt"
	"log"
	"net"
	"os"
	"os/signal"
	"strings"
	"sync/atomic"
	"syscall"
	"time"

	"github.com/google/gopacket"
	"github.com/google/gopacket/layers"
	"github.com/google/gopacket/pcap"
	"github.com/vishvananda/netlink"
)

// TrafficStats holds traffic statistics
type TrafficStats struct {
	AttackerToResolver atomic.Uint64 // bytes
	ResolverToVictim   atomic.Uint64 // bytes
}

// Monitor represents the traffic monitor
type Monitor struct {
	attackerIP    net.IP
	resolverIP    net.IP
	victimIP      net.IP
	iface         string
	handle        *pcap.Handle
	stats         TrafficStats
	stopCh        chan struct{}
	logFile       *os.File
	lastStatsTime time.Time
	lastATR       uint64
	lastRTV       uint64
	interval      time.Duration // stats reporting interval
}

// findInterfaceBySubnet finds the network interface for a given subnet
func findInterfaceBySubnet(subnet string) (string, error) {
	// Parse the subnet
	var ipNet *net.IPNet
	var err error

	if strings.Contains(subnet, "/") {
		_, ipNet, err = net.ParseCIDR(subnet)
		if err != nil {
			return "", fmt.Errorf("invalid subnet: %s", err)
		}
	} else {
		// Single IP, find interface with this IP
		ip := net.ParseIP(subnet)
		if ip == nil {
			return "", fmt.Errorf("invalid IP: %s", subnet)
		}

		links, err := netlink.LinkList()
		if err != nil {
			return "", fmt.Errorf("failed to list links: %v", err)
		}

		for _, l := range links {
			addrs, err := netlink.AddrList(l, netlink.FAMILY_V4)
			if err != nil {
				continue
			}
			for _, addr := range addrs {
				if addr.IP.Equal(ip) {
					return l.Attrs().Name, nil
				}
			}
		}
		return "", fmt.Errorf("no interface found with IP: %s", subnet)
	}

	// Find interface whose IP falls in this subnet
	links, err := netlink.LinkList()
	if err != nil {
		return "", fmt.Errorf("failed to list links: %v", err)
	}

	for _, l := range links {
		addrs, err := netlink.AddrList(l, netlink.FAMILY_V4)
		if err != nil {
			continue
		}

		for _, addr := range addrs {
			if ipNet.Contains(addr.IP) {
				return l.Attrs().Name, nil
			}
		}
	}

	return "", fmt.Errorf("no interface found for subnet: %s", subnet)
}

// NewMonitor creates a new traffic monitor
func NewMonitor(subnet, attacker, resolver, victim, logPath string, interval time.Duration) (*Monitor, error) {
	// Find interface
	iface, err := findInterfaceBySubnet(subnet)
	if err != nil {
		return nil, err
	}
	log.Printf("[Monitor] Found interface: %s for subnet/IP: %s", iface, subnet)

	// Parse IPs
	attackerIP := net.ParseIP(attacker)
	resolverIP := net.ParseIP(resolver)
	victimIP := net.ParseIP(victim)

	if attackerIP == nil {
		return nil, fmt.Errorf("invalid attacker IP: %s", attacker)
	}
	if resolverIP == nil {
		return nil, fmt.Errorf("invalid resolver IP: %s", resolver)
	}
	if victimIP == nil {
		return nil, fmt.Errorf("invalid victim IP: %s", victim)
	}

	// Convert to 4-byte representation for comparison
	attackerIP = attackerIP.To4()
	resolverIP = resolverIP.To4()
	victimIP = victimIP.To4()

	// Open log file
	logFile, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err != nil {
		return nil, fmt.Errorf("failed to open log file: %v", err)
	}

	m := &Monitor{
		attackerIP:    attackerIP,
		resolverIP:    resolverIP,
		victimIP:      victimIP,
		iface:         iface,
		stopCh:        make(chan struct{}),
		logFile:       logFile,
		lastStatsTime: time.Now(),
		interval:      interval,
	}

	return m, nil
}

// Start begins packet capture
func (m *Monitor) Start() error {
	// Open pcap handle
	handle, err := pcap.OpenLive(m.iface, 65535, true, pcap.BlockForever)
	if err != nil {
		return fmt.Errorf("failed to open pcap on %s: %v", m.iface, err)
	}
	m.handle = handle

	// Set BPF filter to capture only relevant traffic
	filter := fmt.Sprintf("ip and (src host %s or dst host %s or src host %s or dst host %s)",
		m.attackerIP, m.resolverIP, m.resolverIP, m.victimIP)
	if err := handle.SetBPFFilter(filter); err != nil {
		log.Printf("[Warning] Failed to set BPF filter: %v, capturing all traffic", err)
	}

	log.Printf("[Monitor] Started capturing on interface: %s", m.iface)
	log.Printf("[Monitor] Attacker: %s -> Resolver: %s -> Victim: %s",
		m.attackerIP, m.resolverIP, m.victimIP)

	// Write log header
	m.logFile.WriteString(fmt.Sprintf("# DNSBOMB Traffic Monitor\n"))
	m.logFile.WriteString(fmt.Sprintf("# Interface: %s\n", m.iface))
	m.logFile.WriteString(fmt.Sprintf("# Attacker: %s, Resolver: %s, Victim: %s\n",
		m.attackerIP, m.resolverIP, m.victimIP))
	m.logFile.WriteString("# Timestamp, Attacker->Resolver (B/s), Resolver->Victim (B/s), ATR_Kbps, RTV_Kbps\n")

	// Start packet processing
	go m.processPackets()

	// Start stats reporter
	go m.reportStats()

	return nil
}

// processPackets processes captured packets
func (m *Monitor) processPackets() {
	packetSource := gopacket.NewPacketSource(m.handle, m.handle.LinkType())

	for {
		select {
		case <-m.stopCh:
			return
		case packet := <-packetSource.Packets():
			if packet == nil {
				continue
			}

			// Get IP layer
			ipLayer := packet.NetworkLayer()
			if ipLayer == nil {
				continue
			}

			ipv4, ok := ipLayer.(*layers.IPv4)
			if !ok {
				continue
			}

			srcIP := net.IP(ipv4.SrcIP).To4()
			dstIP := net.IP(ipv4.DstIP).To4()
			packetLen := uint64(len(packet.Data()))

			// Check direction and update stats
			if srcIP.Equal(m.attackerIP) && dstIP.Equal(m.resolverIP) {
				m.stats.AttackerToResolver.Add(packetLen)
			} else if srcIP.Equal(m.resolverIP) && dstIP.Equal(m.victimIP) {
				m.stats.ResolverToVictim.Add(packetLen)
			}
		}
	}
}

// reportStats reports traffic statistics periodically
func (m *Monitor) reportStats() {
	ticker := time.NewTicker(m.interval)
	defer ticker.Stop()

	for {
		select {
		case <-m.stopCh:
			return
		case now := <-ticker.C:
			// Get current values
			currentATR := m.stats.AttackerToResolver.Load()
			currentRTV := m.stats.ResolverToVictim.Load()

			// Calculate rates (bytes per second)
			elapsed := now.Sub(m.lastStatsTime).Seconds()
			atrRate := float64(currentATR - m.lastATR) / elapsed
			rtvRate := float64(currentRTV - m.lastRTV) / elapsed

			// Convert to Kbps
			atrKbps := atrRate * 8 / 1000
			rtvKbps := rtvRate * 8 / 1000

			// Calculate amplification (handle division by zero)
			var amp float64
			if atrRate > 0 {
				amp = rtvRate / atrRate
			}

			// Log to file
			line := fmt.Sprintf("%s, %.2f, %.2f, %.2f, %.2f\n",
				now.Format("2006-01-02 15:04:05.000"),
				atrRate, rtvRate, atrKbps, rtvKbps)
			m.logFile.WriteString(line)

			// Print to console
			log.Printf("[Stats] A->R: %.2f B/s (%.2f Kbps) | R->V: %.2f B/s (%.2f Kbps) | Amp: %.2fx",
				atrRate, atrKbps, rtvRate, rtvKbps, amp)

			// Update last values
			m.lastATR = currentATR
			m.lastRTV = currentRTV
			m.lastStatsTime = now
		}
	}
}

// Stop stops the monitor
func (m *Monitor) Stop() {
	close(m.stopCh)
	if m.handle != nil {
		m.handle.Close()
	}
	if m.logFile != nil {
		m.logFile.Close()
	}
	log.Println("[Monitor] Stopped")
}

func main() {
	subnet := flag.String("subnet", "", "Subnet or IP to find interface (e.g., 192.168.1.0/24 or 192.168.1.100)")
	attacker := flag.String("attacker", "", "Attacker IP address")
	resolver := flag.String("resolver", "", "Resolver (recursive DNS) IP address")
	victim := flag.String("victim", "", "Victim IP address")
	logPath := flag.String("log", "traffic.log", "Log file path")
	intervalMs := flag.Int("interval", 100, "Stats reporting interval in milliseconds (default 100ms)")
	flag.Parse()

	if *subnet == "" || *attacker == "" || *resolver == "" || *victim == "" {
		fmt.Println("Usage: dnsbomb-monitor -subnet <subnet/IP> -attacker <IP> -resolver <IP> -victim <IP> [-log <file>] [-interval <ms>]")
		fmt.Println("\nExample:")
		fmt.Println("  sudo ./dnsbomb-monitor -subnet 192.168.1.0/24 -attacker 10.0.0.1 -resolver 192.168.1.50 -victim 192.168.1.100 -interval 100")
		os.Exit(1)
	}

	// Validate interval
	if *intervalMs < 10 {
		log.Printf("[Warning] Interval too small (%dms), using 10ms minimum", *intervalMs)
		*intervalMs = 10
	}
	if *intervalMs > 5000 {
		log.Printf("[Warning] Interval too large (%dms), using 5000ms maximum", *intervalMs)
		*intervalMs = 5000
	}

	interval := time.Duration(*intervalMs) * time.Millisecond
	log.Printf("[Monitor] Stats interval: %v", interval)

	// Create monitor
	monitor, err := NewMonitor(*subnet, *attacker, *resolver, *victim, *logPath, interval)
	if err != nil {
		log.Fatalf("[Error] Failed to create monitor: %v", err)
	}

	// Handle signals
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	go func() {
		<-sigChan
		log.Println("\n[Monitor] Received interrupt signal, stopping...")
		monitor.Stop()
		os.Exit(0)
	}()

	// Start monitoring
	if err := monitor.Start(); err != nil {
		log.Fatalf("[Error] %v", err)
	}

	// Wait for stop
	<-monitor.stopCh
}