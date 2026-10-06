# tilo-eval-nightly job image (EFF-05b). Build from the REPOSITORY ROOT: docker build -f evals/Dockerfile .
# (`just build-evals-image` does it on Cloud Build.) Same two-stage shape as services/harness/Dockerfile; the extra
# COPY is the eval cases, fixtures and schemas the replay reads. The job runs `python -m tilo_evals nightly`; the
# Cloud Run job sets the same command in Terraform (infra/envs/dev/eval_nightly.tf); this CMD is the local default.
# Build context filter: evals/Dockerfile.dockerignore (BuildKit reads it instead of the root .dockerignore).
FROM ghcr.io/astral-sh/uv:0.12.18-python3.12-trixie-slim AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PYTHON_PREFERENCE=only-system
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY services ./services
COPY evals ./evals
COPY config ./config
COPY contracts ./contracts
COPY prompts ./prompts
COPY templates ./templates
RUN uv sync --locked --no-dev --package tilo-evals

FROM python:3.12.15-slim-trixie AS runtime
ENV PATH="/app/.venv/bin:${PATH}" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN groupadd --system --gid 10001 tilo && useradd --system --uid 10001 --gid tilo --no-create-home tilo
WORKDIR /app
COPY --from=builder /app /app
USER 10001:10001
CMD ["python", "-m", "tilo_evals", "nightly"]
