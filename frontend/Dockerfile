# Multi-stage build: install deps, build, serve via Caddy file_server.
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json ./
RUN npm install --no-audit --no-fund
COPY . .
ARG VITE_API_BASE=/api
ENV VITE_API_BASE=${VITE_API_BASE}
RUN npm run build

FROM caddy:2-alpine AS run
WORKDIR /srv
COPY --from=build /app/dist /srv
# Tiny Caddyfile so the container can serve standalone; the top-level Caddy in
# docker-compose still proxies in front. Useful for `docker run` debugging.
RUN printf ':80 {\n  root * /srv\n  encode gzip zstd\n  try_files {path} /index.html\n  file_server\n}\n' > /etc/caddy/Caddyfile
EXPOSE 80
