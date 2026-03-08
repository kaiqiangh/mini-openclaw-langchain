FROM node:22.13.1-alpine3.21 AS base

ENV NEXT_TELEMETRY_DISABLED=1

WORKDIR /app

FROM base AS deps

COPY package.json package-lock.json ./

RUN npm ci

FROM deps AS builder

COPY . .

RUN npm run build

FROM base AS dev

ENV NODE_ENV=development

COPY package.json package-lock.json ./

RUN npm ci

COPY . .

EXPOSE 3000

CMD ["npx", "next", "dev", "-H", "0.0.0.0", "-p", "3000"]

FROM node:22.13.1-alpine3.21 AS runtime

ENV NODE_ENV=production \
    HOSTNAME=0.0.0.0 \
    PORT=3000

RUN addgroup -g 10001 -S app \
    && adduser -S -D -u 10001 -G app app

WORKDIR /app

COPY --from=builder --chown=app:app /app/.next/standalone ./
COPY --from=builder --chown=app:app /app/.next/static ./.next/static

USER app

EXPOSE 3000

CMD ["node", "server.js"]
