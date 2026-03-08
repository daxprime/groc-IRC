# groc-IRC Dockerfile
# Multi-stage: builder compiles optional Assembly module, runtime is slim

# ── Stage 1: build assembly module ──────────────────────────────────────────
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    nasm gcc make \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY assembly/ ./assembly/

# Always produce a .so file so the COPY in the next stage never fails.
# If nasm compilation succeeds the real module is used; otherwise a zero-byte
# placeholder is created that the Python loader handles gracefully.
RUN cd assembly && \
    chmod +x build.sh && \
    ./build.sh 2>&1 && echo "ASM build OK" \
    || (echo "ASM build skipped, using placeholder" && touch grocbot_asm.so)

# ── Stage 2: runtime image ───────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="groc-IRC"
LABEL org.opencontainers.image.description="Grok AI IRC bot (Python + Tcl + Assembly)"
LABEL org.opencontainers.image.source="https://github.com/daxprime/groc-IRC"
LABEL org.opencontainers.image.authors="daxprime"

# Install Tcl for the optional Tcl bot
RUN apt-get update && apt-get install -y --no-install-recommends \
    tcl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY python/   ./python/
COPY tcl/      ./tcl/
COPY config/   ./config/
COPY .env.example .env.example

# Copy compiled assembly module from builder
RUN mkdir -p assembly
COPY --from=builder /build/assembly/grocbot_asm.so ./assembly/grocbot_asm.so

# Runtime dirs
RUN mkdir -p logs

# Non-root user for security
RUN useradd -m -s /bin/sh -u 1001 grocbot && chown -R grocbot:grocbot /app
USER grocbot

# HTTP bridge port
EXPOSE 5580

CMD ["python3", "-m", "python.main"]
