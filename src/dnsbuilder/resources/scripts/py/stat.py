import subprocess
import multiprocessing
import time
import signal
import sys
import os

# --- Configuration ---
ATTACKER_IP = os.getenv("ATTACKER")
FILTER = os.getenv("FILTER", "udp and port 53")
INTERFACE = os.getenv("USED_IFACE", "any")
try:
    report_interval_ms = int(os.getenv("POLL_GAP", "1000"))
    REPORT_INTERVAL_S = report_interval_ms / 1000.0
except (ValueError, TypeError):
    print("[WARN] Invalid POLL_GAP value. Using default 1 second.", file=sys.stderr)
    REPORT_INTERVAL_S = 1.0
processes = []


def monitor_traffic(
    filter_str: str, output_queue: multiprocessing.Queue, interface: str
):
    """filter capture"""
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    cmd = ["tcpdump", "-i", interface, "-n", "-l", "-q", filter_str]
    try:
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        for line in iter(process.stdout.readline, ""):
            parts = line.strip().split()
            if len(parts) > 2 and parts[-2] == "length":
                try:
                    size = int(parts[-1])
                    output_queue.put(size)
                except (ValueError, IndexError):
                    continue
    except FileNotFoundError:
        print(f"[ERROR] 'sudo' or 'tcpdump' command not found.", file=sys.stderr)
    except Exception as e:
        print(
            f"[ERROR] Subprocess failed for filter '{filter_str}': {e}", file=sys.stderr
        )
    finally:
        if "process" in locals() and process.poll() is None:
            process.kill()


def shutdown_handler(signum, frame):
    """shutdown all child processes"""
    print("\n[INFO] Shutdown signal received. Cleaning up child processes...")
    for p in processes:
        if p.is_alive():
            p.terminate()
            p.join(timeout=1)
        if p.is_alive():
            p.kill()
    sys.exit(0)


def main():
    """main"""
    global processes

    if ATTACKER_IP:
        # --- MAF & PAF ---
        print("--- PCAP Stats Monitor (Amplification Analysis Mode) ---")
        REQ_FILTER = f"src host {ATTACKER_IP} and udp and dst port 53"
        RESP_FILTER = FILTER

        print(f"[INFO] Monitoring Interface : {INTERFACE}")
        print(f'[INFO] Attacker (Requests)  : "{REQ_FILTER}"')
        print(f'[INFO] Responses (from FILTER): "{RESP_FILTER}"')
        print(f"[INFO] Report Interval      : {REPORT_INTERVAL_S * 1000} ms")
        print("[INFO] Press Ctrl-C to stop.")
        print("-" * 85)
        print(
            f"{'Timestamp':<22} | {'Packets':>12} | {'Bytes':>12} | {'PAF':>8} | {'MAF':>8}"
        )
        print("-" * 85)

        req_queue = multiprocessing.Queue()
        resp_queue = multiprocessing.Queue()

        req_monitor = multiprocessing.Process(
            target=monitor_traffic, args=(REQ_FILTER, req_queue, INTERFACE)
        )
        resp_monitor = multiprocessing.Process(
            target=monitor_traffic, args=(RESP_FILTER, resp_queue, INTERFACE)
        )

        processes = [req_monitor, resp_monitor]
        for p in processes:
            p.start()

        while True:
            time.sleep(REPORT_INTERVAL_S)

            req_pkts, req_size = 0, 0
            while not req_queue.empty():
                req_pkts += 1
                req_size += req_queue.get_nowait()

            resp_pkts, resp_size = 0, 0
            while not resp_queue.empty():
                resp_pkts += 1
                resp_size += resp_queue.get_nowait()

            paf = resp_pkts / req_pkts if req_pkts > 0 else 0.0
            maf = resp_size / req_size if req_size > 0 else 0.0

            timestamp_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            if resp_pkts != 0:
                print(
                    f"{timestamp_str:<22} | {resp_pkts:12.2f} | {resp_size:12.2f} | {paf:8.2f} | {maf:8.2f}"
                )

    else:
        # ---  ---
        print("--- PCAP Stats Monitor (General Monitor Mode) ---")
        print(f"[INFO] Monitoring Interface : {INTERFACE}")
        print(f'[INFO] TCPDump Filter       : "{FILTER}"')
        print(f"[INFO] Report Interval      : {REPORT_INTERVAL_S * 1000} ms")
        print("[INFO] Press Ctrl-C to stop.")
        print("-" * 55)
        print(f"{'Timestamp':<22} | {'Packets':>12} | {'Bytes':>15}")
        print("-" * 55)

        data_queue = multiprocessing.Queue()
        monitor = multiprocessing.Process(
            target=monitor_traffic, args=(FILTER, data_queue, INTERFACE)
        )

        processes = [monitor]
        monitor.start()

        while True:
            time.sleep(REPORT_INTERVAL_S)

            packet_count, total_size = 0, 0
            while not data_queue.empty():
                packet_count += 1
                total_size += data_queue.get_nowait()

            timestamp_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            if packet_count != 0:
                print(f"{timestamp_str:<22} | {packet_count:12.2f} | {total_size:15.2f}")


if __name__ == "__main__":
    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)
    try:
        main()
    except KeyboardInterrupt:
        # shutdown_handler会处理退出
        pass
