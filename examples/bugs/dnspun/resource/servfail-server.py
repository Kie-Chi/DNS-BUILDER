import socket
from dnslib import DNSHeader, QTYPE, RCODE, DNSLabel
from dnslib.server import DNSServer, DNSLogger

# --- Configuration ---
# Target domain: return SERVFAIL for this domain and its subdomains
TARGET_DOMAIN = "victim.com"

# Listening IP and port
MY_IP = "0.0.0.0"
PORT = 53

class ServfailResolver:
    """
    A DNS resolver that returns SERVFAIL.
    Returns SERVFAIL for all queries for victim.com and its subdomains.
    """
    
    def resolve(self, request, handler):
        """
        Core logic for handling DNS requests.
        """
        qname = request.q.qname
        qtype = request.q.qtype
        
        print(f"[+] Received query for: {qname} (Type: {QTYPE[qtype]}) from {handler.client_address[0]}")

        # Check if the queried domain matches victim.com or its subdomains
        if qname.matchSuffix(DNSLabel(TARGET_DOMAIN)):
            print(f"[!] Query matches '{TARGET_DOMAIN}' - Returning SERVFAIL")
            
            # Create a reply packet and set RCODE to SERVFAIL (2)
            reply = request.reply()
            reply.header.rcode = RCODE.SERVFAIL
            
            return reply

        # For other queries, return a normal empty response (NOERROR)
        print(f"[-] Query for {qname} does not match '{TARGET_DOMAIN}'. Replying normally.")
        return request.reply()

# --- Main program entry point ---
if __name__ == '__main__':
    logger = DNSLogger(prefix=False)
    resolver = ServfailResolver()
    server = DNSServer(resolver, port=PORT, address=MY_IP, logger=logger)

    print(f"[*] Starting SERVFAIL DNS Server")
    print(f"[*] Listening on {MY_IP}:{PORT}")
    print(f"[*] Any query for *.{TARGET_DOMAIN} will receive SERVFAIL response")
    
    try:
        server.start()
    except KeyboardInterrupt:
        print("\n[*] Server shutting down.")
        server.stop()
