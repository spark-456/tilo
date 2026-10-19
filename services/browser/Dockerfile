# tilo-browser image (P0-07a). Build from the REPOSITORY ROOT: docker build -f services/browser/Dockerfile .
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
RUN uv sync --locked --no-dev --package tilo-browser
# The workspace packages are editable installs, so uv's bytecode step skips them and PYTHONDONTWRITEBYTECODE keeps the
# running container from writing any: compile them here, or every cold start compiles all of that source again.
RUN .venv/bin/python -m compileall -q -j 0 --invalidation-mode checked-hash services packages

FROM python:3.12.15-slim-trixie AS runtime
ENV PATH="/app/.venv/bin:${PATH}" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8080 PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN groupadd --system --gid 10001 tilo && useradd --system --uid 10001 --gid tilo --no-create-home tilo
WORKDIR /app
COPY --from=builder /app /app
RUN playwright install --with-deps chromium && chmod -R a+rX /ms-playwright
USER 10001:10001
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn tilo_browser.app:app --host 0.0.0.0 --port ${PORT}"]
