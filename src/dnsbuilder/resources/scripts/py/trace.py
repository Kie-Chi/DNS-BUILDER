import os
import time
import glob
from collections import Counter
from scapy.all import PcapReader, DNS, DNSRR, IP, UDP


class Colors:
    YELLOW = "\033[93m"
    GREEN = "\033[92m"
    RESET = "\033[0m"  # Resets the color to default


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
PCAP_DIR = os.getenv("ENV_PCAP_DIR", "/usr/local/etc/pcap")
POLL_INTERVAL = 5


def check_env_vars():
    """Checks if the required environment variables are set."""
    if not all([ATTACKER_IP, RECURSOR_IP, PCAP_DIR]):
        print(
            "[ERROR] Environment variables ATTACKER, RECURSOR, or ENV_PCAP_DIR are not set."
        )
        exit(1)

    print("--- DNS Recursive Analyzer ---")
    print(f"[INFO] Monitoring Directory: {PCAP_DIR}")
    print(f"[INFO] Attacker IP: {ATTACKER_IP}")
    print(f"[INFO] Recursor IP: {RECURSOR_IP}")
    print("[INFO] Ignoring packets captured before script start.")
    print("----------------------------------------------------------")


def format_dns_details(pkt):
    """Formats DNS details using our robust, manually-defined mappings."""
    if not pkt.haslayer(DNS):
        return "[Non-DNS Packet]"
    dns_layer = pkt[DNS]
    if dns_layer.qr == 0:
        if dns_layer.qdcount > 0 and dns_layer.qd:
            qname = dns_layer.qd.qname.decode(errors="ignore").strip(".")
            qtype = dns_layer.qd.qtype
            qtype_str = MANUAL_DNS_TYPES.get(qtype, str(qtype))
            return f"{qtype_str}? {qname}"
        return "[Query with no question]"
    else:
        details = []
        for section_name, section, count in [
            ("Answers", dns_layer.an, dns_layer.ancount),
            ("Authority", dns_layer.ns, dns_layer.nscount),
        ]:
            if count > 0 and section:
                records = []
                section_records = section if isinstance(section, list) else [section]
                for rec in section_records:
                    if isinstance(rec, DNSRR):
                        rr_type = MANUAL_DNS_TYPES.get(rec.type, str(rec.type))
                        rdata = rec.rdata
                        if isinstance(rdata, bytes):
                            rdata = rdata.decode(errors="ignore")
                        records.append(f"{rr_type} {rdata}")
                if records:
                    details.append(f"{section_name}: [{', '.join(records)}]")
        if not details:
            rcode = dns_layer.rcode
            rcode_str = MANUAL_DNS_RCODES.get(rcode, f"RCODE({rcode})")
            return f"[{rcode_str}]"
        return " ".join(details)


def analyze_transaction(packets):
    """Analyzes a transaction, highlighting only the core query/response dialogue."""
    if not packets:
        return
    initial_query_pkt = packets[0]
    initial_details = format_dns_details(initial_query_pkt)
    destination_counts = Counter()
    pending_queries = {}
    print("\n")
    print(f"[INFO] New DNS Transaction: {initial_details}")
    print(f"[INFO] Initial Query from {ATTACKER_IP}")
    for pkt in packets[1:]:
        if not pkt.haslayer(DNS):
            continue
        src_ip, dst_ip = pkt[IP].src, pkt[IP].dst
        dns_layer = pkt[DNS]
        if src_ip == RECURSOR_IP and dst_ip != ATTACKER_IP and dns_layer.qr == 0:
            destination_counts[dst_ip] += 1
            pending_queries[dns_layer.id] = pkt
        elif dst_ip == RECURSOR_IP and src_ip != ATTACKER_IP and dns_layer.qr == 1:
            dns_id = dns_layer.id
            if dns_id in pending_queries:
                query_pkt = pending_queries.pop(dns_id)
                query_details = format_dns_details(query_pkt)
                reply_details = format_dns_details(pkt)
                print(
                    f"{Colors.YELLOW}       -> {query_pkt[IP].dst}: {query_details}{Colors.RESET}"
                )
                print(
                    f"{Colors.GREEN}         <- {src_ip}: {reply_details}{Colors.RESET}"
                )
            else:
                print(
                    f"[WARN]   Unmatched reply from {src_ip}: {format_dns_details(pkt)}"
                )
    final_response_pkt = packets[-1]
    if (
        final_response_pkt[IP].src == RECURSOR_IP
        and final_response_pkt[IP].dst == ATTACKER_IP
    ):
        final_details = format_dns_details(final_response_pkt)
        print(f"[INFO] Response to {ATTACKER_IP}: {final_details}")
    if pending_queries:
        print("[WARN] Unanswered Queries :")
        for dns_id, pkt in pending_queries.items():
            print(
                f"[WARN]   No response for query to {pkt[IP].dst} ({format_dns_details(pkt)})"
            )
    total_queries = sum(destination_counts.values())
    print(f"[INFO] Total recursive queries made: {total_queries}")
    if destination_counts:
        for ip, count in destination_counts.most_common():
            print(f"[INFO]   - {ip}: {count} time(s)")
    print("\n")


def main():
    """Main function to loop and monitor pcap files."""
    check_env_vars()
    # Initialize with current time to ignore pre-existing pcap files on startup.
    last_processed_timestamp = time.time()
    current_transaction_packets = []
    while True:
        all_pcap_files = sorted(glob.glob(os.path.join(PCAP_DIR, "*.pcap")))
        if not all_pcap_files:
            time.sleep(POLL_INTERVAL)
            continue
        candidate_files = all_pcap_files[-2:]
        new_packets_this_run = []
        for pcap_file in candidate_files:
            try:
                with PcapReader(pcap_file) as pcap_reader:
                    for pkt in pcap_reader:
                        if pkt.time > last_processed_timestamp:
                            new_packets_this_run.append(pkt)
            except Exception as e:
                print(
                    f"[WARN] Temporary error reading {pcap_file}: {e}. Will retry on next poll."
                )
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
                        "[WARN] New transaction started but previous one seems incomplete. Analyzing cached packets..."
                    )
                    analyze_transaction(current_transaction_packets)
                current_transaction_packets = [pkt]
            elif current_transaction_packets:
                current_transaction_packets.append(pkt)
                if src_ip == RECURSOR_IP and dst_ip == ATTACKER_IP and pkt[DNS].qr == 1:
                    analyze_transaction(current_transaction_packets)
                    current_transaction_packets = []
        if new_packets_this_run:
            last_processed_timestamp = new_packets_this_run[-1].time
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
