# =================================================================
# Phase 1: Build environment (Builder)
# =================================================================
FROM fedora:37 AS builder

# Hickory DNS (formerly trust-dns) Git commit hash (corresponds to v0.22.0)
ARG VERSION=0b6fefea3fefe1086fed4df6781550462de51553
ARG PROGRAM=hickory-dns

# 1. Install build dependencies
RUN dnf install -y --setopt=tsflags=nodocs --setopt=install_weak_deps=False \
    git cargo rust openssl-devel gcc \
    && dnf clean all

WORKDIR /app

# 2. Clone the source code of the specified version from the new repository
RUN git clone https://github.com/hickory-dns/hickory-dns.git \
    && cd "${PROGRAM}" \
    && git checkout "${VERSION}"

# 3. Compile the release version binary
#    --features recursor enables the recursive resolver functionality
#    --bin hickory-dns specifies compiling the main program binary
RUN cd "${PROGRAM}" && cargo build --release --features recursor --bin trust-dns


# =================================================================
# Phase 2: Runtime environment (Final Image)
# =================================================================
FROM fedora:37

ARG PROGRAM=hickory-dns

# Install minimum runtime dependencies
RUN dnf install -y --setopt=tsflags=nodocs --setopt=install_weak_deps=False \
    openssl-libs ca-certificates \
    && dnf clean all

# 1. Copy the compiled binary from the builder stage
COPY --from=builder /app/${PROGRAM}/target/release/trust-dns /usr/local/sbin/hickory-dns

# 2. Prepare the configuration directory and root hints file required by hickory-dns
#    The file path in the repository has not changed, but we place it under the new configuration directory
RUN mkdir -p /etc/hickory-dns/ && \
    mkdir -p /usr/local/etc/hickory-dns

# 3. Create a directory for storing user custom configurations, and set it as VOLUME
RUN mkdir /config
VOLUME [ "/config" ]

# 4. Expose the standard DNS protocol ports
EXPOSE 53/tcp 53/udp

# 5. Set the entrypoint and default command
#    The program name has been updated to hickory-dns
ENTRYPOINT [ "/usr/local/sbin/hickory-dns" ]
CMD [ "--debug", "--config=/usr/local/etc/hickory-dns/hickory-dns.toml" ]