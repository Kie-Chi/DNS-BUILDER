#!/usr/bin/env python3

import socket
from dnslib import DNSRecord

# --- Configuration ---
LISTEN_IP = "0.0.0.0"
LISTEN_PORT = 12345       # Must match the target port of your C program
BUFFER_SIZE = 38192        # Must be large enough to hold the reassembled packet

# --- Color Codes ---
GREEN = '\033[92m'
RED = '\033[91m'
BLUE = '\033[94m'
YELLOW = '\033[93m'
ENDC = '\033[0m'

def main():
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    try:
        udp_socket.bind((LISTEN_IP, LISTEN_PORT))
        print(f"[*] DNS packet listener listening on {LISTEN_IP}:{LISTEN_PORT}...")
        print("[*] Waiting to receive a packet...")
    except OSError as e:
        print(f"{RED}[-] Error binding to port {LISTEN_PORT}: {e}{ENDC}")
        return

    try:
        _iter = 0
        while True:
            data, addr = udp_socket.recvfrom(BUFFER_SIZE)
            _iter += 1
            print(f"\n{GREEN}[+] Packet received from {addr[0]}:{addr[1]} ({len(data)} bytes){ENDC}")

            dns_record = DNSRecord.parse(data)

            print("\n" + "-"*20 + " Parsed DNS Packet " + "-"*20)
            print(str(dns_record))

            # --- Fix section here ---
            # rr.rtype is an integer, we directly compare it with the integer value of the corresponding type
            cname_count = len([rr for rr in dns_record.rr if rr.rtype == 5])  # 5 is CNAME
            a_record_count = len([rr for rr in dns_record.rr if rr.rtype == 1]) # 1 is A

            print("\n--- Summary ---")
            print(f"  Total CNAME records found: {GREEN}{cname_count}{ENDC}")
            print(f"  Total A records found: {GREEN}{a_record_count}{ENDC}")
            print(f"    This is the {_iter} packet since start")
    except KeyboardInterrupt:
        print("\n[*] Listener shutting down.")
    except Exception as e:
        print(f"\n{RED}[-] An error occurred while receiving or parsing: {e}{ENDC}")
    finally:
        udp_socket.close()

if __name__ == '__main__':
    main()