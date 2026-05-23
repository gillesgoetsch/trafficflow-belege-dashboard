# Stage 1: pull docker CLI + compose plugin from official docker image.
# Avoids Debian's missing/renamed packages on trixie.
FROM docker:27-cli AS dockerbins

# Stage 2: webhook runtime
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Bring in docker CLI + compose plugin
COPY --from=dockerbins /usr/local/bin/docker /usr/local/bin/docker
COPY --from=dockerbins /usr/local/libexec/docker/cli-plugins/docker-compose \
                       /usr/local/libexec/docker/cli-plugins/docker-compose

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
