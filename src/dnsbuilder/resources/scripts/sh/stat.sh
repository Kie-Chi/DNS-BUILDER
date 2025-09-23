#!/bin/bash

# --- Configuration ---
USED_IFACE=${USED_IFACE:-any}
TCPDUMP_FILTER=${FILTER:-"udp and port 53"}
REPORT_INTERVAL_MS=${POLL_GAP:-500}
packet_count=0
total_size=0

REPORT_INTERVAL_NS=$((REPORT_INTERVAL_MS * 1000000))
next_report_time_ns=$(($(date +%s%N) + REPORT_INTERVAL_NS))

# --- Graceful Shutdown ---
function shutdown() {
    echo -e "\n[INFO] Shutdown signal received. Exiting."
    exit 0
}
trap shutdown SIGINT SIGTERM

# --- Main ---
echo "--- PCAP Stats Monitor (Live Stream MS Edition) ---"
echo "[INFO] Monitoring Interface : $USED_IFACE"
echo "[INFO] TCPDump Filter       : \"$TCPDUMP_FILTER\""
echo "[INFO] Report Interval      : $REPORT_INTERVAL_MS ms"
echo "[INFO] Press Ctrl-C to stop."
echo "---------------------------------------------------------------------"

tcpdump -i "${USED_IFACE}" -n -l -q ${TCPDUMP_FILTER} | while IFS= read -r line; do
    current_time_ns=$(date +%s%N)

    if (( current_time_ns >= next_report_time_ns )); then
        timestamp_str=$(date '+%Y-%m-%d %H:%M:%S.%3N')
        printf "%s | New Packets: %-5s | Total Size: %-8s bytes\n" \
            "$timestamp_str" "$packet_count" "$total_size"
        packet_count=0
        total_size=0
        
        next_report_time_ns=$((next_report_time_ns + REPORT_INTERVAL_NS))

        if (( next_report_time_ns <= current_time_ns )); then
            next_report_time_ns=$(($(date +%s%N) + REPORT_INTERVAL_NS))
        fi
    fi

    ((packet_count++))
    
    size=$(echo "$line" | awk 'NF>1 && $(NF-1)=="length" {print $NF}')
    
    if [[ -n "$size" ]]; then
        total_size=$((total_size + size))
    fi
done

echo "[INFO] Monitor has been stopped."