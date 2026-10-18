# =================================================================
# Phase 1: Build environment (Builder)
# =================================================================
# Use the same Fedora 37 base image as the original file
FROM fedora:37 AS builder

# Git commit hash, can be modified as needed
ARG VERSION=463644c83a93db3d20d574450f1106a2d0b627b9
ARG PROGRAM=resolved

# 1. Install build dependencies
# - git: Used for cloning source code
# - cargo, rust: Rust toolchain
# - openssl-devel: Development files for the openssl library that resolved depends on
# - gcc: C language compiler, needed by some Rust dependency libraries during build
RUN dnf install -y --setopt=tsflags=nodocs --setopt=install_weak_deps=False \
    git cargo rust openssl-devel gcc \
    && dnf clean all

WORKDIR /app

# 2. Clone the source code of the specified version
RUN git clone https://github.com/barrucadu/resolved.git \
    && cd "${PROGRAM}" \
    && git checkout "${VERSION}"

# 3. Compile the release version binary
#    We compile directly in the Dockerfile, no longer need the build.sh script
RUN cd "${PROGRAM}" && cargo build --release --bin resolved


# =================================================================
# Phase 2: Runtime environment (Final Image)
# =================================================================
FROM fedora:37

ARG PROGRAM=resolved

# Install minimum runtime dependencies
# - openssl-libs: The openssl library that resolved dynamically links to
# - ca-certificates: Root certificates for TLS/HTTPS requests
RUN dnf install -y --setopt=tsflags=nodocs --setopt=install_weak_deps=False \
    openssl-libs ca-certificates tmux dnsutils tcpdump \
    && dnf clean all

# 1. Copy the compiled binary from the builder stage
COPY --from=builder /app/${PROGRAM}/target/release/resolved /usr/local/sbin/resolved

# 2. Prepare the configuration directory and root hints file required by resolved
#    This root.hints file is crucial for the recursive resolver
RUN mkdir -p /etc/resolved/zones/
# 3. Create a directory for storing user custom configurations, and set it as VOLUME
RUN mkdir /config
VOLUME [ "/config" ]

# 4. Expose the standard DNS protocol ports
EXPOSE 53/tcp 53/udp

# 5. Set the entrypoint and default command
#    The program reads /config/config.toml as its configuration
ENTRYPOINT [ "/usr/local/sbin/resolved" ]
CMD [ "-Z", "/etc/resolved/zones" ]