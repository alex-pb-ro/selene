# Public tooling is provisioned before any application source is added.
FROM python@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534

RUN apt-get update && apt-get install --no-install-recommends -y nodejs git \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.11.13
WORKDIR /opt/selene
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
RUN uv pip install pyright==1.1.403 && .venv/bin/pyright --version

# Runtime source arrives after all installation commands have finished.
COPY LICENSE ./LICENSE
COPY src ./src
COPY containers/isolated/entrypoint.py ./container_entrypoint.py
ENV PATH="/opt/selene/.venv/bin:/usr/local/bin:/usr/bin:/bin" \
    PYTHONPATH="/opt/selene/src" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_OFFLINE=1
LABEL io.selene.isolation.profile="stdio-v1"
WORKDIR /workspace
USER 65534:65534
ENTRYPOINT ["python", "-I", "-S", "/opt/selene/container_entrypoint.py"]
