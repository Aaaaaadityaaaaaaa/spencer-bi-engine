# syntax=docker/dockerfile:1

# --- Stage 1: build the Vue SPA ---------------------------------------------
# VITE_API_BASE is baked in at build time. We pass "" so the app makes RELATIVE,
# same-origin API calls (Caddy proxies them to the backend), which sidesteps CORS
# entirely in production. `npm ci` uses the committed package-lock.json.
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_API_BASE=""
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build

# --- Stage 2: serve the static bundle with Caddy ----------------------------
# Caddy also reverse-proxies the API and terminates TLS. The Caddyfile is bind-
# mounted by compose (so the domain/routing can change without an image rebuild),
# and the base image's default CMD runs `caddy run` against it. Multi-arch base.
FROM caddy:2-alpine
COPY --from=build /app/dist /srv
EXPOSE 80 443
