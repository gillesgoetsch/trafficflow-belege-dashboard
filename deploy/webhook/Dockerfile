FROM python:3.12-slim

# Need git + docker CLI to talk to the host docker socket
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl gnupg git docker.io docker-compose-v2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py ./

EXPOSE 9000
CMD ["python", "server.py"]
