import time
import random
import string
from dnslib import DNSHeader, RR, A, QTYPE, DNSLabel
from dnslib.server import DNSServer, DNSLogger

# --- Configs ---
ATTACKER_DOMAIN = "example.com"
MY_IP = "0.0.0.0"
PORT = 53
DELAY_SECONDS = 1.0


class DelayedResolver:
    """
        Delay when responsing to queries for ATTACKER_DOMAIN
    """

    def generate_random_ip(self):
        """Generate a random private IP address for response"""
        return "10.{}.{}.{}".format(
            random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)
        )

    def resolve(self, request, handler):
        """
        Core logic to handle DNS requests.
        """
        qname = request.q.qname
        qtype = request.q.qtype

        print(
            f"[+] Received query for: {qname} (Type: {QTYPE[qtype]}) from {handler.client_address[0]}"
        )

        # Subfix
        if qname.matchSuffix(DNSLabel(ATTACKER_DOMAIN)):
            # QTYPE.A
            if qtype == QTYPE.A:
                print(
                    f"[*] Query matches our domain. Waiting for {DELAY_SECONDS} second(s)..."
                )

                # Sleep
                time.sleep(DELAY_SECONDS)

                # Reply
                reply = request.reply()
                random_ip = self.generate_random_ip()

                reply.add_answer(RR(qname, QTYPE.A, rdata=A(random_ip)))

                print(f"[!] Responded to {qname} with IP {random_ip} after delay.")

                # no-Reply
                return reply

        print(f"[-] Query for {qname} does not match our rules. Replying empty.")
        return request.reply()


if __name__ == "__main__":
    logger = DNSLogger(prefix=False)
    resolver = DelayedResolver()
    server = DNSServer(resolver, port=PORT, address=MY_IP, logger=logger)

    print(f"[*] Starting Delayed DNS Server for *.{ATTACKER_DOMAIN}")
    print(f"[*] Listening on {MY_IP}:{PORT}")
    print(f"[*] Response delay is set to {DELAY_SECONDS} seconds.")

    try:
        server.start()
    except KeyboardInterrupt:
        print("\n[*] Server shutting down.")
        server.stop()