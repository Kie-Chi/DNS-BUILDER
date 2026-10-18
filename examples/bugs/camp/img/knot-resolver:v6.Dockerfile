# syntax=docker/dockerfile:1
FROM ubuntu:22.04

# install basic tools
RUN DEBIAN_FRONTEND=noninteractive apt-get update && apt-get install -y wget build-essential pkg-config tcpdump dnsutils

# install app dependencies
RUN DEBIAN_FRONTEND=noninteractive apt-get install -y iputils-ping net-tools iproute2
RUN DEBIAN_FRONTEND=noninteractive apt-get install -y xz-utils automake libtool gnutls-dev liburcu-dev liblmdb-dev libedit-dev meson ninja-build cmake libuv1-dev luajit libluajit-5.1-dev socat libfstrm-dev libprotobuf-dev libprotobuf-c-dev protobuf-c-compiler

# download source code
RUN DEBIAN_FRONTEND=noninteractive wget https://secure.nic.cz/files/knot-dns/knot-3.4.8.tar.xz & \
    wget https://secure.nic.cz/files/knot-resolver/knot-resolver-6.0.15.tar.xz

# extract the source code
RUN DEBIAN_FRONTEND=noninteractive tar -xf knot-3.4.8.tar.xz & tar -xf knot-resolver-6.0.15.tar.xz

# build from source code
RUN DEBIAN_FRONTEND=noninteractive cd knot-3.4.8 && autoreconf -i -f && ./configure && make -j4 && make install
RUN DEBIAN_FRONTEND=noninteractive cd knot-resolver-6.0.15 && meson build_dir --prefix=/tmp/kr --default-library=static && ninja -C build_dir && ninja install -C build_dir
RUN DEBIAN_FRONTEND=noninteractive mkdir -p /etc/knot-resolver/ && mkdir -p /var/cache/knot/