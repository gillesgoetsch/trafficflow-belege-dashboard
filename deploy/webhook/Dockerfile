FROM python:3.12-slim

# Need git + ssh client (for private repo) + docker CLI (to talk to host socket)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl gnupg git openssh-client docker.io docker-compose-v2 \
    && rm -rf /var/lib/apt/lists/*

# Pre-seed github.com host key so first git fetch doesn't hang on host-key prompt
RUN mkdir -p /root/.ssh && chmod 700 /root/.ssh && \
    ssh-keyscan -t rsa,ecdsa,ed25519 github.com >> /root/.ssh/known_hosts && \
    chmod 644 /root/.ssh/known_hosts

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py ./

EXPOSE 9000
CMD ["python", "server.py"]
