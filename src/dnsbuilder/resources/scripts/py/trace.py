# trace.py
import os
import time
import glob
import subprocess
import socket
import json
from collections import Counter
from scapy.all import PcapReader, DNS, DNSRR, IP, UDP


class Colors:
    YELLOW = "\033[93m"
    GREEN = "\033[92m"
    RED = "\033[91m"  # Added red for deleted items
    RESET = "\033[0m"


# --- Manual Mappings for DNS ---
MANUAL_DNS_TYPES = {
    1: "A",
    2: "NS",
    5: "CNAME",
    6: "SOA",
    12: "PTR",
    15: "MX",
    16: "TXT",
    28: "AAAA",
    33: "SRV",
    255: "ANY",
}
MANUAL_DNS_RCODES = {
    0: "NOERROR",
    1: "FORMERR",
    2: "SERVFAIL",
    3: "NXDOMAIN",
    4: "NOTIMP",
    5: "REFUSED",
}

# --- Configuration ---
ATTACKER_IP = os.getenv("ATTACKER")
RECURSOR_IP = os.getenv("RECURSOR")
SOFTWARE = os.getenv("SOFTWARE")  # New: e.g., 'bind'
PCAP_DIR = os.getenv("ENV_PCAP_DIR", "/usr/local/etc/pcap")
POLL_INTERVAL = 5
CACHE_ANALYZER_PORT = 12345


def check_env_vars():
    """Checks if the required environment variables are set."""
    if not all([ATTACKER_IP, RECURSOR_IP, PCAP_DIR, SOFTWARE]):
        print(
            "[ERROR] Required env vars ATTACKER, RECURSOR, SOFTWARE, or ENV_PCAP_DIR are not set."
        )
        exit(1)
    print("--- DNS Recursive Analyzer ---")
    print(f"[INFO] Monitoring Directory: {PCAP_DIR}")
    print(f"[INFO] Attacker IP: {ATTACKER_IP}")
    print(f"[INFO] Recursor IP: {RECURSOR_IP}")
    print(f"[INFO] Target Software: {SOFTWARE}")
    print("[INFO] Ignoring packets captured before script start.")
    print("----------------------------------------------------------")


def launch_software_analyzer():
    """Launches the corresponding cache analyzer script based on SOFTWARE env var."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    script_name = os.path.join(script_dir, f"{SOFTWARE}.py")
    if not os.path.exists(script_name):
        print(f"[ERROR] Analyzer script '{script_name}' not found.")
        exit(1)
    print(f"[INFO] Launching cache analyzer: {script_name}...")
    try:
        # Launch the script as a non-blocking background process
        process = subprocess.Popen(
            ["python3", script_name],
            stderr=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
        )
        print(
            f"[INFO] Cache analyzer started with PID: {process.pid}. Allowing it to initialize..."
        )
        time.sleep(2)  # Give the server a moment to start up
        return process
    except Exception as e:
        print(f"[ERROR] Failed to launch '{script_name}': {e}")
        exit(1)


def query_and_print_cache_changes():
    """Connects to the cache analyzer, gets changes, and prints them."""
    print(f"[INFO] Querying cache changes for {SOFTWARE}:")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect(("localhost", CACHE_ANALYZER_PORT))
            s.sendall(b"analyze")

            # Receive data in a loop until the server closes the connection
            response_data = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                response_data += chunk

        changes = json.loads(response_data.decode("utf-8"))

        if "error" in changes:
            print(
                f"{Colors.RED}[ERROR] Cache analyzer returned an error: {changes['details']}{Colors.RESET}"
            )
            return

        details = changes.get("details", {})
        added = details.get("added", [])
        modified = details.get("modified", [])
        removed = details.get("removed", [])

        if not any([added, modified, removed]):
            print("[INFO] No changes detected in the cache.")
            return

        for item in added:
            print(f"{Colors.GREEN}[cached]   {item}{Colors.RESET}")
        for item in removed:
            print(f"{Colors.RED}[deleted]  {item}{Colors.RESET}")
        for item in modified:
            reason = item.get("reason", "Unknown")
            # Assuming 'before' and 'after' are lists of strings
            before_str = " | ".join(item.get("before", []))
            after_str = " | ".join(item.get("after", []))
            print(
                f"{Colors.YELLOW}[modified] {before_str} -> {after_str} (Reason: {reason}){Colors.RESET}"
            )

    except ConnectionRefusedError:
        print(
            f"{Colors.RED}[ERROR] Could not connect to cache analyzer on port {CACHE_ANALYZER_PORT}. Is it running?{Colors.RESET}"
        )
    except Exception as e:
        print(
            f"{Colors.RED}[ERROR] An unexpected error occurred while analyzing cache: {e}{Colors.RESET}"
        )
    finally:
        print("---------------------")


def format_dns_details(pkt):
    """Formats DNS details using our robust, manually-defined mappings."""
    if not pkt.haslayer(DNS):
        return "[Non-DNS Packet]"
    dns = pkt[DNS]
    if dns.qr == 0:  # Query
        if dns.qdcount > 0 and dns.qd:
            qname = dns.qd.qname.decode(errors="ignore").strip(".")
            qtype_str = MANUAL_DNS_TYPES.get(dns.qd.qtype, str(dns.qd.qtype))
            return f"{qtype_str}? {qname}"
        return "[Query with no question]"
    else:  # Response
        details = []
        for sec_name, sec, count in [
            ("Answers", dns.an, dns.ancount),
            ("Authority", dns.ns, dns.nscount),
        ]:
            if count > 0 and sec:
                records = [
                    f"{MANUAL_DNS_TYPES.get(r.type, str(r.type))} {r.rdata.decode(errors='ignore') if isinstance(r.rdata, bytes) else r.rdata}"
                    for r in (sec if isinstance(sec, list) else [sec])
                    if isinstance(r, DNSRR)
                ]
                if records:
                    details.append(f"{sec_name}: [{', '.join(records)}]")
        if not details:
            return f"[{MANUAL_DNS_RCODES.get(dns.rcode, f'RCODE({dns.rcode})')}]"
        return " ".join(details)


def analyze_transaction(packets):
    """Analyzes a transaction and then triggers cache analysis."""
    if not packets:
        return

    print("\n" + "=" * 50)
    print(f"[INFO] New DNS Transaction: {format_dns_details(packets[0])}")
    print(f"[INFO] Initial Query from {ATTACKER_IP}")

    destination_counts = Counter()
    pending_queries = {}
    for pkt in packets[1:]:
        if not pkt.haslayer(IP) or not pkt.haslayer(DNS):
            continue
        src_ip, dst_ip, dns = pkt[IP].src, pkt[IP].dst, pkt[DNS]
        if src_ip == RECURSOR_IP and dst_ip != ATTACKER_IP and dns.qr == 0:
            destination_counts[dst_ip] += 1
            pending_queries[dns.id] = pkt
        elif dst_ip == RECURSOR_IP and src_ip != ATTACKER_IP and dns.qr == 1:
            if dns.id in pending_queries:
                query_pkt = pending_queries.pop(dns.id)
                print(
                    f"{Colors.YELLOW}       -> {query_pkt[IP].dst}: {format_dns_details(query_pkt)}{Colors.RESET}"
                )
                print(
                    f"{Colors.GREEN}         <- {src_ip}: {format_dns_details(pkt)}{Colors.RESET}"
                )
            else:
                print(
                    f"[WARN]   Unmatched reply from {src_ip}: {format_dns_details(pkt)}"
                )

    final_response_pkt = packets[-1]
    if (
        final_response_pkt.haslayer(IP)
        and final_response_pkt[IP].src == RECURSOR_IP
        and final_response_pkt[IP].dst == ATTACKER_IP
    ):
        print(
            f"[INFO] Response to {ATTACKER_IP}: {format_dns_details(final_response_pkt)}"
        )

    if pending_queries:
        print("[WARN] Unanswered Queries:")
        for pkt in pending_queries.values():
            print(f"[WARN]   -> To {pkt[IP].dst} ({format_dns_details(pkt)})")

    print(f"[INFO] Total recursive queries made: {sum(destination_counts.values())}")
    for ip, count in destination_counts.most_common():
        print(f"[INFO]   - {ip}: {count} time(s)")
    print("=" * 50)

    # *** NEW STEP: Query and print cache changes after analyzing the transaction ***
    query_and_print_cache_changes()


def main():
    """Main function to launch analyzer, loop, and monitor pcap files."""
    check_env_vars()
    analyzer_process = launch_software_analyzer()

    last_processed_timestamp = time.time()
    current_transaction_packets = []

    try:
        while True:
            all_pcap_files = sorted(glob.glob(os.path.join(PCAP_DIR, "*.pcap")))
            candidate_files = all_pcap_files[-2:]  # Check last 2 files for robustness
            new_packets_this_run = []
            for pcap_file in candidate_files:
                try:
                    with PcapReader(pcap_file) as pcap_reader:
                        for pkt in pcap_reader:
                            if pkt.time > last_processed_timestamp:
                                new_packets_this_run.append(pkt)
                except Exception as e:
                    print(f"[WARN] Error reading {pcap_file}: {e}. Retrying.")

            if not new_packets_this_run:
                time.sleep(POLL_INTERVAL)
                continue

            new_packets_this_run.sort(key=lambda p: p.time)

            for pkt in new_packets_this_run:
                if not all(layer in pkt for layer in [IP, UDP, DNS]):
                    continue

                src_ip, dst_ip = pkt[IP].src, pkt[IP].dst
                if src_ip == ATTACKER_IP and dst_ip == RECURSOR_IP and pkt[DNS].qr == 0:
                    if current_transaction_packets:
                        print(
                            "[WARN] New transaction started before previous one finished. Analyzing old one now."
                        )
                        analyze_transaction(current_transaction_packets)
                    current_transaction_packets = [pkt]
                elif current_transaction_packets:
                    current_transaction_packets.append(pkt)
                    if (
                        src_ip == RECURSOR_IP
                        and dst_ip == ATTACKER_IP
                        and pkt[DNS].qr == 1
                    ):
                        analyze_transaction(current_transaction_packets)
                        current_transaction_packets = []

            last_processed_timestamp = new_packets_this_run[-1].time
            time.sleep(POLL_INTERVAL)
    finally:
        print("\n[INFO] Shutting down cache analyzer...")
        analyzer_process.terminate()
        analyzer_process.wait()
        print("[INFO] Shutdown complete.")


if __name__ == "__main__":
    main()
