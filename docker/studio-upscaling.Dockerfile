# syntax=docker/dockerfile:1.19@sha256:b6afd42430b15f2d2a4c5a02b919e98a525b785b1aaff16747d2f623364e39b6

FROM ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 AS uv
FROM python:3.12-slim-bookworm@sha256:44cf1793efa7c7a476bb0f2cff81443f4a072c90c1cb127e2924933daa3e8c64 AS python-base

FROM python-base AS build
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /build
ARG SOURCE_DATE_EPOCH
ENV UV_LINK_MODE=copy UV_NO_CACHE=1 UV_CONCURRENT_DOWNLOADS=2 \
    UV_CONCURRENT_INSTALLS=2 UV_CONCURRENT_BUILDS=1
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY docker/studio-upscaling-runtime.txt docker/studio-build-constraints.txt ./
RUN uv venv --python 3.12 /opt/studio \
    && uv export --locked --only-group upscaling --output-file /tmp/upscaling-deps.txt \
    && uv export --locked --only-group upscaling --no-emit-package opencv-contrib-python-headless \
        --no-emit-package pillow --no-emit-package numpy --output-file /tmp/upscaling-python-deps.txt \
    && uv pip install --python /opt/studio/bin/python --no-deps --require-hashes \
        --only-binary :all: -r /tmp/upscaling-python-deps.txt \
    && python -m pip download --no-cache-dir --only-binary=:all: --no-deps \
        --require-hashes -r studio-upscaling-runtime.txt --dest /tmp/runtime \
    && cd /tmp/runtime \
    && sha256sum ./*.whl > /opt/studio/upscaling-wheels.sha256 \
    && (while read -r digest wheel; do grep -q "sha256:$digest" /tmp/upscaling-deps.txt || exit 1; done \
        < /opt/studio/upscaling-wheels.sha256) \
    && test "$(du -cb ./*.whl | tail -n 1 | cut -f1)" = 91974911 \
    && uv pip install --python /opt/studio/bin/python --no-deps --no-index ./*.whl
COPY src/ ./src/
RUN uv build --wheel --no-sources --build-constraint studio-build-constraints.txt \
        --require-build-hashes --out-dir /tmp/wheels \
    && uv pip install --python /opt/studio/bin/python --no-deps --no-index /tmp/wheels/*.whl \
    && site_packages=/opt/studio/lib/python3.12/site-packages \
    && find "$site_packages/numpy" -type d -name tests -prune -exec rm -rf {} + \
    && test "$(du -sc -B1 /build /tmp /opt/studio | tail -n 1 | cut -f1)" -le 2147483648

FROM python-base AS runtime
RUN groupadd --gid 10001 studio \
    && useradd --uid 10001 --gid 10001 --home-dir /upscaling --no-create-home \
        --shell /usr/sbin/nologin studio \
    && mkdir -p /upscaling /weights /store \
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

FROM scratch
COPY --from=runtime / /
COPY --from=build /opt/studio /opt/studio
COPY docker/fsrcnn-notice.txt /opt/studio/FSRCNN-NOTICE
ARG REVISION
LABEL org.opencontainers.image.source="https://github.com/thaynes43/haynes-studio" \
    org.opencontainers.image.revision="${REVISION}" \
    io.haynes-studio.upscaling.comparison="stored-proxy-frame-v2" \
    org.opencontainers.image.title="Haynes Studio Upscaling"
ENV PATH=/opt/studio/bin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    HOME=/upscaling TMPDIR=/upscaling LANG=C.UTF-8 \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    STUDIO_THREADS=2 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
    OPENCV_FOR_THREADS_NUM=2 OPENCV_OPENCL_RUNTIME=disabled OPENCV_LOG_LEVEL=SILENT \
    STUDIO_UPSCALING_REVISION="${REVISION}"
USER 10001:10001
WORKDIR /opt/studio
CMD ["studio-upscaling", "serve"]
