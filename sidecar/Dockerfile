# Stage 1: Build TypeScript
FROM node:22-bookworm-slim AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY tsconfig.json ./
COPY src/ ./src/
RUN npm run build

# Stage 2: Production image with Chromium
FROM node:22-bookworm-slim

# Use a fixed, shared browser path so root install is accessible to node user
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev

# Install Playwright Chromium + system deps using the project's playwright-core
RUN npx playwright-core install --with-deps chromium \
    && chmod -R o+rx /ms-playwright

COPY --from=builder /app/dist/ ./dist/

# Create data directory for profile persistence
RUN mkdir -p /data/profiles && chown -R node:node /data

ENV NODE_ENV=production
ENV PORT=3000
ENV DATA_DIR=/data

USER node
EXPOSE 3000
CMD ["node", "dist/server.js"]
