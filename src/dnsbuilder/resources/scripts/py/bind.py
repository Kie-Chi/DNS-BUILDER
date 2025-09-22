import socketserver
import subprocess
import os
import json
import logging

try:
    # Attempt to import dnspython, a required library.
    from dns import name as dns_name, rdatatype, rdata, exception as dns_exception
except ImportError:
    # Provide a helpful error message if the library is not installed.
    print("Error: dnspython library not found.")
    print("Please install it using: pip install dnspython")
    exit(1)

# --- Configuration ---
HOST, PORT = "0.0.0.0", 12345
RNDC_KEY_FILE = "/usr/local/var/bind/rndc.key"
DUMP_FILE = "/usr/local/var/bind/named_dump.db"

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# --- Global State ---
# Stores the previous cache snapshot to compare against the current one.
previous_cache = {}


def run_rndc_dump():
    """Executes the `rndc dumpdb` command to generate a fresh cache dump."""
    recursor_ip = os.environ.get("RECURSOR")
    if not recursor_ip:
        logging.error("Environment variable RECURSOR is not set.")
        return False, "Environment variable RECURSOR is not set"

    command = ["rndc", "-s", recursor_ip, "-k", RNDC_KEY_FILE, "dumpdb", "-cache"]
    logging.info(f"Executing command: {' '.join(command)}")
    try:
        subprocess.run(command, capture_output=True, text=True, check=True)
        return True, "Success"
    except Exception as e:
        logging.error(f"rndc command failed: {e}")
        return False, str(e)


def parse_dump_file(file_path):
    """
    Parses the BIND cache dump file using a pre-parser for format quirks
    and dnspython for robust DNS object creation.
    """
    if not os.path.exists(file_path):
        logging.warning(f"Cache dump file {file_path} not found.")
        return {}

    cache_data = {}
    in_default_view_cache = False
    last_domain = None  # State to handle omitted domain names in subsequent lines.

    with open(file_path, "r") as f:
        for line in f:
            line = line.strip()

            # Process only lines within the '_default' view's cache section.
            if "; Start view _default" in line:
                in_default_view_cache = True
            if "; Address database dump" in line or "; Start view _bind" in line:
                in_default_view_cache = False
                last_domain = None  # Reset state when leaving the section.

            if not in_default_view_cache or line.startswith((";", "$")) or not line:
                continue

            parts = line.split()
            if len(parts) < 2:
                continue

            # Pre-parsing logic to reconstruct full record lines.
            current_domain_str, ttl_str, record_parts_start_index = None, None, -1
            if parts[0].isdigit():  # Line starts with TTL (domain is inherited).
                if last_domain:
                    current_domain_str, ttl_str, record_parts_start_index = (
                        last_domain,
                        parts[0],
                        1,
                    )
                else:
                    continue
            else:  # Line starts with a domain name.
                current_domain_str = parts[0]
                last_domain = current_domain_str
                if len(parts) > 1 and parts[1].isdigit():
                    ttl_str, record_parts_start_index = parts[1], 2
                else:
                    continue

            if record_parts_start_index == -1:
                continue

            try:
                ttl = int(ttl_str)
            except (ValueError, TypeError):
                continue

            # Extract record components.
            offset = record_parts_start_index
            if len(parts) > offset and parts[offset].upper() == "IN":
                offset += 1
            if len(parts) <= offset:
                continue

            rdtype_str, value_str = parts[offset], " ".join(parts[offset + 1 :])

            is_negative_cache = False
            if rdtype_str.startswith(
                "\\-"
            ):  # Handle BIND's negative cache syntax (e.g., \-AAAA).
                rdtype_str = rdtype_str[2:]
                is_negative_cache = True

            # Use dnspython to create structured objects.
            try:
                domain = dns_name.from_text(current_domain_str)
                rdtype_int = rdatatype.from_text(rdtype_str)

                record = (
                    f"NEGATIVE_CACHE:{value_str}"
                    if is_negative_cache
                    else rdata.from_text(1, rdtype_int, value_str)
                )

                key = (domain, rdtype_int)
                if key not in cache_data:
                    cache_data[key] = {"ttl": ttl, "records": set()}

                cache_data[key]["records"].add(record)
                cache_data[key]["ttl"] = ttl
            except dns_exception.DNSException as e:
                logging.debug(f"dnspython failed to parse line '{line}': {e}")
                continue

    logging.info(f"Parsed {len(cache_data)} unique record sets from {file_path}.")
    return cache_data


def format_record(domain, rdtype_int, ttl, record_obj):
    """Safely formats a DNS record object into a human-readable string."""
    try:
        domain_str = domain.to_text()
        rdtype_str = rdatatype.to_text(rdtype_int)

        if isinstance(record_obj, str) and record_obj.startswith("NEGATIVE_CACHE"):
            value_str = record_obj.split(":", 1)[1]
            full_rdtype_str = f"\\-{rdtype_str}"
            return f"{domain_str}\t{ttl}\tIN\t{full_rdtype_str}\t{value_str}"
        elif isinstance(record_obj, rdata.Rdata):
            value_str = record_obj.to_text()
            return f"{domain_str}\t{ttl}\tIN\t{rdtype_str}\t{value_str}"
        else:
            logging.warning(
                f"format_record received an unknown record_obj type: {type(record_obj)}"
            )
            return f"{domain_str}\t{ttl}\tIN\t{rdtype_str}\t[FORMATTING ERROR: UNKNOWN TYPE]"
    except Exception as e:
        logging.error(
            f"Error in format_record for key=({domain}, {rdatatype.to_text(rdtype_int)}): {e}"
        )
        return f"[FORMATTING ERROR: {e}]"


def compare_caches(old_cache, new_cache):
    """Compares two structured cache snapshots to identify changes."""
    changes = {"added": [], "removed": [], "modified": []}
    old_keys = set(old_cache.keys())
    new_keys = set(new_cache.keys())

    # Find added records.
    for key in new_keys - old_keys:
        domain, rdtype_int = key
        for rec in new_cache[key]["records"]:
            changes["added"].append(
                format_record(domain, rdtype_int, new_cache[key]["ttl"], rec)
            )

    # Find removed records.
    for key in old_keys - new_keys:
        domain, rdtype_int = key
        for rec in old_cache[key]["records"]:
            changes["removed"].append(
                format_record(domain, rdtype_int, old_cache[key]["ttl"], rec)
            )

    # Find modified records (data change or TTL increase).
    for key in old_keys.intersection(new_keys):
        domain, rdtype_int = key
        old_entry, new_entry = old_cache[key], new_cache[key]

        records_changed = old_entry["records"] != new_entry["records"]
        ttl_increased = new_entry["ttl"] > old_entry["ttl"]

        if records_changed or ttl_increased:
            # *** Simplified reason generation ***
            reasons = []
            if records_changed:
                reasons.append("Data changed")
            if ttl_increased:
                reasons.append("TTL increased")

            changes["modified"].append(
                {
                    "key": f"{domain.to_text()} {rdatatype.to_text(rdtype_int)}",
                    "reason": ", ".join(reasons),
                    "before": sorted(
                        [
                            format_record(domain, rdtype_int, old_entry["ttl"], r)
                            for r in old_entry["records"]
                        ]
                    ),
                    "after": sorted(
                        [
                            format_record(domain, rdtype_int, new_entry["ttl"], r)
                            for r in new_entry["records"]
                        ]
                    ),
                }
            )

    return changes


class CacheAnalysisHandler(socketserver.BaseRequestHandler):
    """Handles incoming TCP requests to trigger a cache analysis."""

    def handle(self):
        global previous_cache
        data = self.request.recv(1024).strip()
        logging.info(
            f"Received request from {self.client_address[0]}: {data.decode('utf-8', 'ignore')}"
        )

        success, message = run_rndc_dump()
        if not success:
            self.request.sendall(
                json.dumps(
                    {"error": "Failed to execute rndc dumpdb", "details": message},
                    indent=2,
                ).encode("utf-8")
            )
            return

        current_cache = parse_dump_file(DUMP_FILE)

        if not previous_cache:
            logging.info("First run. Establishing baseline cache snapshot.")
            all_added = []
            for (domain, rdtype_int), entry in current_cache.items():
                for rec in entry["records"]:
                    all_added.append(
                        format_record(domain, rdtype_int, entry["ttl"], rec)
                    )
            changes = {
                "status": "Initial run",
                "details": {"added": sorted(all_added), "modified": [], "removed": []},
            }
        else:
            logging.info("Comparing new cache against previous snapshot...")
            diff = compare_caches(previous_cache, current_cache)
            changes = {
                "status": "Cache diff calculated",
                "summary": {
                    "added": len(diff["added"]),
                    "modified": len(diff["modified"]),
                    "removed": len(diff["removed"]),
                },
                "details": diff,
            }

        response_json = json.dumps(changes, indent=2, ensure_ascii=False)
        self.request.sendall(response_json.encode("utf-8"))
        logging.info("Analysis result sent to client.")

        previous_cache = current_cache


if __name__ == "__main__":
    if not os.environ.get("RECURSOR"):
        print("Error: Please set the 'RECURSOR' environment variable before running.")
        print("Example: export RECURSOR=127.0.0.1")
        exit(1)
    try:
        server = socketserver.TCPServer((HOST, PORT), CacheAnalysisHandler)
        logging.info(f"Server started at {HOST}:{PORT}, waiting for connections...")
        server.serve_forever()
    except Exception as e:
        logging.error(f"Failed to start server: {e}")
