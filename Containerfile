# Workstream Dashboard — Fedora-based container image
# Build:  podman build -t workstream:dev .
# Run:    podman run -p 8080:8080 --env-file .env workstream:dev

FROM registry.fedoraproject.org/fedora:41 AS base

RUN dnf install -y --setopt=install_weak_deps=False \
        python3 python3-pip git procps-ng curl && \
    dnf clean all && \
    rm -rf /var/cache/dnf

RUN useradd -r -m -s /sbin/nologin workstream

WORKDIR /app

COPY requirements.txt .
RUN python3 -m pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chown -R workstream:workstream /app

USER workstream

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/api/health || exit 1

ENV WORKSTREAM_HOST=0.0.0.0
ENV WORKSTREAM_PORT=8080

ENTRYPOINT ["python3", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
