# Bundled DNSSEC build-tool image used by util_mode=docker.
# The registry is explicit so the default does not depend on an unknown mirror.
ARG BASE_IMAGE=docker.1ms.run/library/debian:12.11-slim
FROM ${BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends bind9-utils ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work
ENTRYPOINT ["/bin/sh"]
