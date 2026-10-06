# tilo-render image (P0-07a). Build from the REPOSITORY ROOT: docker build -f services/render/Dockerfile .
# The uv workspace needs the root pyproject.toml, uv.lock and packages/. Source stays at /app so the
# editable installs and the repo-relative config/ and contracts/ lookups resolve the same at run time.
FROM ghcr.io/astral-sh/uv:0.12.18-python3.12-trixie-slim AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PYTHON_PREFERENCE=only-system
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY services ./services
COPY evals/pyproject.toml ./evals/pyproject.toml
COPY config ./config
COPY contracts ./contracts
COPY prompts ./prompts
COPY templates ./templates
RUN uv sync --locked --no-dev --package tilo-render

FROM python:3.12.15-slim-trixie AS runtime
ENV PATH="/app/.venv/bin:${PATH}" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8080
RUN groupadd --system --gid 10001 tilo && useradd --system --uid 10001 --gid tilo --no-create-home tilo
WORKDIR /app
COPY --from=builder /app /app
USER 10001:10001
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn tilo_render.app:app --host 0.0.0.0 --port ${PORT}"]
