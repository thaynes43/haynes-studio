# syntax=docker/dockerfile:1.19@sha256:b6afd42430b15f2d2a4c5a02b919e98a525b785b1aaff16747d2f623364e39b6

FROM ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 AS uv
FROM python:3.12-slim-bookworm@sha256:44cf1793efa7c7a476bb0f2cff81443f4a072c90c1cb127e2924933daa3e8c64 AS python-base

FROM python-base AS build
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /build
ARG SOURCE_DATE_EPOCH
ENV UV_PROJECT_ENVIRONMENT=/opt/studio \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    UV_CONCURRENT_DOWNLOADS=2 \
    UV_CONCURRENT_INSTALLS=2 \
    UV_CONCURRENT_BUILDS=1
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --locked --no-dev --no-install-project --no-build
COPY docker/studio-build-constraints.txt ./
COPY src/ ./src/
RUN uv build --wheel --no-sources --build-constraint studio-build-constraints.txt \
        --require-build-hashes --out-dir /tmp/wheels \
    && uv pip install --python /opt/studio/bin/python --no-deps /tmp/wheels/*.whl

# Upstream scientific wheels ship sample media, arrays and Sobol tables. Studio
# uses ndimage, and none of its runtime paths use those test packages or QMC data.
RUN site_packages=/opt/studio/lib/python3.12/site-packages \
    && find "$site_packages/numpy" "$site_packages/scipy" \
        -type d -name tests -prune -exec rm -rf {} + \
    && rm "$site_packages/scipy/stats/_sobol_direction_numbers.npz"

FROM python-base AS runtime
RUN groupadd --gid 10001 studio \
    && useradd --uid 10001 --gid 10001 --home-dir /tmp --no-create-home \
        --shell /usr/sbin/nologin studio \
    && rm -rf /usr/local/include /usr/local/bin/idle* /usr/local/bin/pip* \
        /usr/local/bin/python*-config /usr/local/lib/python3.12/config-* \
        /usr/local/lib/python3.12/ensurepip /usr/local/lib/python3.12/idlelib \
        /usr/local/lib/python3.12/site-packages/pip* \
        /etc/shadow* /etc/gshadow* /usr/lib/ssl/cert.pem \
        /usr/share/man /usr/share/info /usr/share/pixmaps \
        /var/lib/apt/lists/* /var/cache/apt/* \
    && find /usr/share/doc /etc/alternatives /var/lib/dpkg/alternatives \
        -name '*.gz' -delete \
    && find /etc/ssl/certs -type l -delete

# Copy the prepared filesystem so removed files are absent from the shipped layers.
FROM scratch
COPY --from=runtime / /
COPY --from=build /opt/studio /opt/studio
COPY docs/reference/model-licences.json /opt/studio/docs/reference/model-licences.json
ARG REVISION
LABEL org.opencontainers.image.source="https://github.com/thaynes43/haynes-studio" \
    org.opencontainers.image.revision="${REVISION}" \
    org.opencontainers.image.title="Haynes Studio"
ENV PATH=/opt/studio/bin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    HOME=/tmp \
    TMPDIR=/tmp \
    LANG=C.UTF-8 \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STUDIO_THREADS=2 \
    OMP_NUM_THREADS=2 \
    OPENBLAS_NUM_THREADS=1
USER 10001:10001
WORKDIR /opt/studio
EXPOSE 8000
CMD ["studio-api", "serve", "--host", "0.0.0.0", "--port", "8000"]
