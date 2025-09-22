import socketserver
import subprocess
import os
import json
import logging

try:
    # Attempt to import dnspython, a required library.
    from dns import name as dns_name, rdatatype, rdata, exception as dns_exception
except ImportError:
    print("Error: dnspython library not found.")
    print("Please install it using: pip install dnspython")
    exit(1)

# --- Configuration ---
HOST, PORT = "0.0.0.0", 12345
UNBOUND_CONFIG_FILE = os.environ.get("UNBOUND_CONFIG_FILE", "/usr/local/var/unbound/control.conf")

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

previous_cache = {}


def run_unbound_control_dump():
    """
    Executes the `unbound-control dump_cache` command and captures its output.
    Uses the UNBOUND_CONFIG_FILE environment variable if it is set.
    """
    recursor_ip = os.environ.get("RECURSOR")
    if not recursor_ip:
        logging.error("Environment variable RECURSOR is not set.")
        return False, "Environment variable RECURSOR is not set"

    # Base command
    command = ["unbound-control", "-c", UNBOUND_CONFIG_FILE]

    # Add server and action
    command.extend(["-s", recursor_ip, "dump_cache"])

    logging.info(f"Executing command: {' '.join(command)}")
    try:
        # unbound-control prints to stdout, so we capture it.
        result = subprocess.run(
            command, capture_output=True, text=True, check=True, encoding="utf-8"
        )
        return True, result.stdout
    except FileNotFoundError:
        logging.error(
            "unbound-control command not found. Is Unbound installed and in your PATH?"
        )
        return False, "unbound-control command not found"
    except subprocess.CalledProcessError as e:
        error_message = (
            f"unbound-control command failed with exit code {e.returncode}:\n{e.stderr}"
        )
        logging.error(error_message)
        return False, error_message
    except Exception as e:
        logging.error(f"unbound-control command failed: {e}")
        return False, str(e)


def parse_unbound_dump(dump_content):
    """
    Parses the Unbound cache dump content (from stdout) using dnspython
    for robust DNS object creation.
    """
    cache_data = {}
    in_rrset_cache = False

    for line in dump_content.splitlines():
        line = line.strip()

        # Process only lines within the RRset cache section.
        if line.startswith("START_RRSET_CACHE"):
            in_rrset_cache = True
            continue
        if line.startswith("END_RRSET_CACHE"):
            break  # We are done with the relevant section

        if not in_rrset_cache or line.startswith(";") or not line:
            continue

        parts = line.split()
        # Expecting: domain. ttl IN type value...
        if len(parts) < 5 or parts[2].upper() != "IN":
            continue

        domain_str, ttl_str, _, rdtype_str, *value_parts = parts
        value_str = " ".join(value_parts)

        try:
            ttl = int(ttl_str)
            domain = dns_name.from_text(domain_str)
            rdtype_int = rdatatype.from_text(rdtype_str)

            # Unbound dump can contain special values (e.g., '# 0') for A records
            try:
                record = rdata.from_text(1, rdtype_int, value_str)
            except dns_exception.DNSException:
                logging.debug(
                    f"Treating line as special record due to parse error: {line}"
                )
                record = f"SPECIAL_UNBOUND_RECORD:{value_str}"

            key = (domain, rdtype_int)
            if key not in cache_data:
                cache_data[key] = {"ttl": ttl, "records": set()}

            # Unbound lists each record on a new line, so we add to the set.
            cache_data[key]["records"].add(record)
            cache_data[key]["ttl"] = ttl
        except (ValueError, dns_exception.DNSException) as e:
            logging.debug(f"dnspython failed to parse line '{line}': {e}")
            continue

    logging.info(f"Parsed {len(cache_data)} unique record sets from Unbound cache.")
    return cache_data


def format_record(domain, rdtype_int, ttl, record_obj):
    """Safely formats a DNS record object into a human-readable string."""
    try:
        domain_str = domain.to_text()
        rdtype_str = rdatatype.to_text(rdtype_int)

        if isinstance(record_obj, str) and record_obj.startswith(
            "SPECIAL_UNBOUND_RECORD"
        ):
            value_str = record_obj.split(":", 1)[1]
            return f"{domain_str}\t{ttl}\tIN\t{rdtype_str}\t{value_str}"
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
    """Compares two structured cache snapshots to identify changes. (No changes from bind.py)"""
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

        success, dump_output = run_unbound_control_dump()
        if not success:
            self.request.sendall(
                json.dumps(
                    {
                        "error": "Failed to execute unbound-control dump_cache",
                        "details": dump_output,
                    },
                    indent=2,
                ).encode("utf-8")
            )
            return

        current_cache = parse_unbound_dump(dump_output)

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
        if UNBOUND_CONFIG_FILE:
            logging.info(f"Using Unbound config file: {UNBOUND_CONFIG_FILE}")
        else:
            logging.warning(
                "UNBOUND_CONFIG_FILE not set. Assuming default access without TLS."
            )

        logging.info(f"Server started at {HOST}:{PORT}, waiting for connections...")
        server.serve_forever()
    except Exception as e:
        logging.error(f"Failed to start server: {e}")
