#!/bin/sh
set -e

# --- 1. env ---
if [ -z "$INET" ]; then
  echo "error: environment variable INET is not set." >&2
  echo "please provide it by -e INET=10.89.0.0/24." >&2
  exit 1
fi

echo "info: looking for network interface for CIDR [${INET}]..."

# --- 2. iface ---
IFACE=$(ip addr | awk -v cidr="$INET" '
  BEGIN {
      split(cidr, a, "/");
      l = a[2];
      split(a[1], i, ".");
      if (l >= 24) p = i[1]"."i[2]"."i[3]".";
      else if (l >= 16) p = i[1]"."i[2]".";
      else p = i[1]".";
      m = "/"l
  }
  /^[0-9]+:/ {
      iface = $2;
      sub(/:$/, "", iface)
  }
  /inet / && $2 ~ m && $2 ~ "^"p {
      print iface;
      exit
  }')

# --- 3. error ---
if [ -z "$IFACE" ]; then
  echo "error: cannot find network interface for CIDR [${INET}]." >&2
  echo "--- current 'ip addr' output ---" >&2
  /sbin/ip addr >&2
  echo "--------------------------------" >&2
  exit 1
fi

export USED_IFACE=${IFACE}
export PCAP_DIR="/usr/local/etc/pcap"
mkdir -p ${PCAP_DIR}

echo "info: supervisord pcap and logs start..."
exec supervisord -c /usr/local/etc/supervisord.conf