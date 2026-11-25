# syntax=docker/dockerfile:1.19@sha256:b6afd42430b15f2d2a4c5a02b919e98a525b785b1aaff16747d2f623364e39b6

FROM ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 AS uv
FROM python:3.12-slim-bookworm@sha256:44cf1793efa7c7a476bb0f2cff81443f4a072c90c1cb127e2924933daa3e8c64 AS python-base

FROM python-base AS wheels
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /build
ENV UV_LINK_MODE=copy UV_NO_CACHE=1 UV_CONCURRENT_DOWNLOADS=2 \
    UV_CONCURRENT_INSTALLS=2 UV_CONCURRENT_BUILDS=1
COPY pyproject.toml uv.lock ./
RUN uv venv --python 3.12 /opt/studio \
    && uv export --quiet --locked --only-group segmentation --no-header --no-annotate \
        --output-file /opt/studio/segmentation-runtime.txt \
    && python -m pip download --no-cache-dir --only-binary=:all: --no-deps \
        --require-hashes -r /opt/studio/segmentation-runtime.txt --dest /tmp/wheels \
    && (cd /tmp/wheels && sha256sum *.whl) > /opt/studio/segmentation-wheels.sha256 \
    && uv pip install --python /opt/studio/bin/python --no-deps --no-index /tmp/wheels/*.whl \
    && site=/opt/studio/lib/python3.12/site-packages \
    && find "$site/numpy" "$site/networkx" "$site/sympy" -type d -name tests -prune -exec rm -rf {} + \
    && rm -f "$site/torch/bin/test_interpreter_async.pt" "$site/networkx/generators/atlas.dat.gz" \
        "$site/distutils-precedence.pth" \
    && rm -rf /tmp/wheels

FROM wheels AS build
ARG SOURCE_DATE_EPOCH
COPY README.md LICENSE ./
COPY docker/studio-build-constraints.txt ./
COPY src/ ./src/
RUN uv build --wheel --no-sources --build-constraint studio-build-constraints.txt \
        --require-build-hashes --out-dir /tmp/app \
    && uv pip install --python /opt/studio/bin/python --no-deps --no-index /tmp/app/*.whl \
    && mkdir -p /tmp/studio-app \
    && cp -a /opt/studio/lib/python3.12/site-packages/haynes_studio* /tmp/studio-app/ \
    && uv export --quiet --locked --only-group segmentation --format cyclonedx1.5 \
        --output-file /tmp/segmentation-sbom.cdx.json \
    && python -c 'import json; from pathlib import Path; p=Path("/tmp/segmentation-sbom.cdx.json"); b=json.loads(p.read_text()); b.pop("serialNumber", None); b["metadata"].pop("timestamp", None); p.write_text(json.dumps(b, sort_keys=True) + "\n")'

FROM python-base AS runtime
RUN mkdir -p /segmentation /opt/studio-models \
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
# Keep the heavyweight CPU wheels reusable across Studio source revisions.
COPY --from=wheels /opt/studio /opt/studio
COPY --from=build /tmp/studio-app/ /opt/studio/lib/python3.12/site-packages/
COPY --from=build /opt/studio/bin/studio-segmentation /opt/studio/bin/studio-segmentation
COPY --from=build /tmp/segmentation-sbom.cdx.json /opt/studio/segmentation-sbom.cdx.json
ARG REVISION
LABEL org.opencontainers.image.source="https://github.com/thaynes43/haynes-studio" \
    org.opencontainers.image.revision="${REVISION}" \
    org.opencontainers.image.title="Haynes Studio Segmentation"
ENV PATH=/opt/studio/bin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    HOME=/segmentation TMPDIR=/segmentation LANG=C.UTF-8 \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    STUDIO_THREADS=2 OMP_NUM_THREADS=2 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 BLIS_NUM_THREADS=1 \
    TOKENIZERS_PARALLELISM=false HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_XET=1 \
    HF_HUB_DISABLE_TELEMETRY=1 HF_HUB_DISABLE_IMPLICIT_TOKEN=1 CUDA_VISIBLE_DEVICES="" \
    STUDIO_SEGMENTATION_REVISION="${REVISION}"
USER 10001:10001
WORKDIR /opt/studio
CMD ["studio-segmentation", "serve"]
