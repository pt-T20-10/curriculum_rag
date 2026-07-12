FROM python:3.11-slim-bookworm

ARG TYPST_VERSION=0.13.1
ARG PANDOC_VERSION=3.6.4

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl fontconfig fonts-liberation2 gosu xz-utils \
    && arch="$(dpkg --print-architecture)" \
    && case "$arch" in \
         amd64) typst_arch="x86_64-unknown-linux-musl"; pandoc_arch="amd64" ;; \
         arm64) typst_arch="aarch64-unknown-linux-musl"; pandoc_arch="arm64" ;; \
         *) echo "Unsupported architecture: $arch" >&2; exit 1 ;; \
       esac \
    && curl --fail --location --retry 3 \
       "https://github.com/typst/typst/releases/download/v${TYPST_VERSION}/typst-${typst_arch}.tar.xz" \
       --output /tmp/typst.tar.xz \
    && tar -xJf /tmp/typst.tar.xz -C /tmp \
    && install "/tmp/typst-${typst_arch}/typst" /usr/local/bin/typst \
    && curl --fail --location --retry 3 \
       "https://github.com/jgm/pandoc/releases/download/${PANDOC_VERSION}/pandoc-${PANDOC_VERSION}-linux-${pandoc_arch}.tar.gz" \
       --output /tmp/pandoc.tar.gz \
    && tar -xzf /tmp/pandoc.tar.gz -C /tmp \
    && install "/tmp/pandoc-${PANDOC_VERSION}/bin/pandoc" /usr/local/bin/pandoc \
    && rm -rf /var/lib/apt/lists/* /tmp/typst* /tmp/pandoc*

WORKDIR /app

COPY requirements-prod.lock /tmp/requirements-prod.lock
RUN python -m pip install --disable-pip-version-check \
        --no-cache-dir --retries 10 --timeout 120 \
        --upgrade pip setuptools wheel \
    && python -m pip install --disable-pip-version-check \
        --no-cache-dir --retries 10 --timeout 120 --prefer-binary \
    -r /tmp/requirements-prod.lock

COPY backend/ /app/

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/outputs /app/logs /app/data/chroma_db \
    && chown -R appuser:appuser /app \
    && chmod +x /app/docker-entrypoint.sh /app/start_railway.sh /app/predeploy_railway.sh

# The image starts as root only long enough for the entrypoint to repair
# ownership of runtime-mounted volumes. The application command itself always
# runs as the unprivileged appuser. Platforms that enforce a non-root UID can
# still start the image; the entrypoint simply skips the ownership repair.
ENTRYPOINT ["/app/docker-entrypoint.sh"]

EXPOSE 8000

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"${PORT:-8000}\" --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
