# GCMV school documents app.
# Claude Code itself is NOT in the image: the host's `claude` binary and login are bind-mounted
# (see docker-compose.yml), so the container always uses the same Claude as the host.
FROM python:3.13-slim-trixie

ARG TYPST_VERSION=0.14.2
ARG HOST_USER=aritra
ARG HOST_UID=1000
ARG HOST_GID=1000
ARG TARGETARCH

# poppler-utils: pdfinfo / pdftotext. xz-utils + curl: fetch typst.
RUN apt-get update \
 && apt-get install -y --no-install-recommends poppler-utils ca-certificates curl xz-utils \
 && rm -rf /var/lib/apt/lists/*

# typst: official static (musl) build for this CPU
RUN arch="$( [ "${TARGETARCH:-$(dpkg --print-architecture)}" = "arm64" ] && echo aarch64 || echo x86_64 )" \
 && curl -fsSL "https://github.com/typst/typst/releases/download/v${TYPST_VERSION}/typst-${arch}-unknown-linux-musl.tar.xz" \
    | tar -xJ -C /tmp \
 && install -m 0755 /tmp/typst-${arch}-unknown-linux-musl/typst /usr/local/bin/typst \
 && rm -rf /tmp/typst-* && typst --version

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv

WORKDIR /app
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

# Same user and home path as on the host, so the mounted ~/.claude and claude binary line up.
RUN groupadd -g ${HOST_GID} ${HOST_USER} && useradd -m -u ${HOST_UID} -g ${HOST_GID} -d /home/${HOST_USER} ${HOST_USER}

COPY . .
RUN mkdir -p /app/data && chown -R ${HOST_UID}:${HOST_GID} /app

USER ${HOST_USER}
ENV HOME=/home/${HOST_USER} \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Kolkata \
    DISABLE_AUTOUPDATER=1

EXPOSE 8765
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8765", "--proxy-headers", "--forwarded-allow-ips", "*"]
