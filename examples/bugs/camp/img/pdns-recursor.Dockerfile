# syntax=docker/dockerfile:1
FROM ubuntu:22.04

# install basic tools
RUN DEBIAN_FRONTEND=noninteractive apt-get update && apt-get install -y wget build-essential pkg-config tcpdump dnsutils

# install app dependencies
RUN DEBIAN_FRONTEND=noninteractive apt-get install -y iputils-ping net-tools iproute2
RUN DEBIAN_FRONTEND=noninteractive apt-get install -y libboost-dev libboost-filesystem-dev libboost-serialization-dev \
    libboost-system-dev libboost-thread-dev libboost-context-dev libboost-test-dev \
    libluajit-5.1-dev libssl-dev libfstrm-dev

# download source code
RUN DEBIAN_FRONTEND=noninteractive wget https://downloads.powerdns.com/releases/pdns-recursor-4.9.9.tar.bz2

# extract the source code
RUN DEBIAN_FRONTEND=noninteractive tar -xf pdns-recursor-4.9.9.tar.bz2

# build from source code
RUN DEBIAN_FRONTEND=noninteractive cd pdns-recursor-4.9.9 && ./configure --sysconfdir=/etc/powerdns/ --enable-dnstap && make -j4 && make install
RUN DEBIAN_FRONTEND=noninteractive mkdir -p /var/run/powerdns && mkdir -p /var/run/pdns-recursor

# copy the start script
