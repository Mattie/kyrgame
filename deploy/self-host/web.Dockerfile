FROM node:20-bookworm-slim AS frontend-build

WORKDIR /app

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
ENV VITE_API_BASE_URL="" \
    VITE_WS_URL=""
RUN npm run build

FROM caddy:2-alpine

COPY deploy/self-host/Caddyfile /etc/caddy/Caddyfile
COPY --from=frontend-build /app/dist /usr/share/caddy
