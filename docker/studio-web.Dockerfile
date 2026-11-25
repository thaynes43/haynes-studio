# syntax=docker/dockerfile:1.19@sha256:b6afd42430b15f2d2a4c5a02b919e98a525b785b1aaff16747d2f623364e39b6

FROM node:24-bookworm-slim@sha256:873f586f3794f52281bd039bf02c048a0be08fde619338f9941bad1eb6b34530 AS build
WORKDIR /build
ARG SOURCE_DATE_EPOCH
ENV CI=true RAYON_NUM_THREADS=2 UV_THREADPOOL_SIZE=2
COPY web/package.json web/pnpm-lock.yaml ./
# Corepack reads the exact pnpm version in package.json's packageManager field.
RUN corepack pnpm install --frozen-lockfile --child-concurrency=1
COPY web/ ./
RUN corepack pnpm build

FROM nginxinc/nginx-unprivileged:stable-alpine-slim@sha256:5d8bb9437d74a600ec5dbf90c035451c724dc33eac8d3a71078f6f8612c345f6 AS runtime
USER 0:0
RUN rm -rf /usr/share/nginx/html /usr/share/man /docker-entrypoint.sh /docker-entrypoint.d \
        /etc/nginx/conf.d/default.conf /lib/apk/db/scripts.tar.gz \
        /etc/shadow* /etc/gshadow* /etc/ssl/cert.pem /etc/ssl1.1/cert.pem
COPY docker/studio-web.nginx.conf /etc/nginx/nginx.conf
COPY --from=build /build/dist/ /usr/share/nginx/html/

FROM scratch
COPY --from=runtime / /
ARG REVISION
LABEL org.opencontainers.image.source="https://github.com/thaynes43/haynes-studio" \
    org.opencontainers.image.revision="${REVISION}" \
    org.opencontainers.image.title="Haynes Studio Web"
USER 101:101
EXPOSE 8080
STOPSIGNAL SIGQUIT
CMD ["/usr/sbin/nginx", "-g", "daemon off;"]
