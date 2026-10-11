# Repository root build context. Ephemeral guest browsers only; no profile or remote desktop.
FROM mcr.microsoft.com/playwright/python:v1.52.0-noble
ENV DEBIAN_FRONTEND=noninteractive TILO_IN_CONTAINER=1 DISPLAY=:99 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb pulseaudio pulseaudio-utils fonts-noto-color-emoji \
    && mkdir -p /tmp/.X11-unix && chmod 1777 /tmp/.X11-unix \
    && rm -rf /var/lib/apt/lists/*
COPY meet-bot/docker/requirements.txt /tmp/requirements.txt
COPY meet-bot/docker/cloud-requirements.txt /tmp/cloud-requirements.txt
RUN pip install --break-system-packages --ignore-installed typing_extensions \
    -r /tmp/requirements.txt -r /tmp/cloud-requirements.txt
COPY packages/contracts-py/src /opt/tilo/packages/contracts-py/src
COPY packages/providers/src /opt/tilo/packages/providers/src
# Import only the pure OIDC boundary, rather than the connector broker or its stores.
COPY services/connectors/src/tilo_connectors/host_auth.py /opt/tilo/services/connectors/src/tilo_connectors/host_auth.py
RUN touch /opt/tilo/services/connectors/src/tilo_connectors/__init__.py
COPY config/models*.yaml /opt/tilo/config/
COPY config/prices*.yaml /opt/tilo/config/
COPY config/speech*.yaml /opt/tilo/config/
COPY config/voice*.yaml /opt/tilo/config/
COPY config/meeting*.yaml /opt/tilo/config/
COPY prompts/router /opt/tilo/prompts/router
COPY prompts/speech /opt/tilo/prompts/speech
ENV TILO_REPO_ROOT=/opt/tilo \
    PYTHONPATH=/opt/tilo/packages/contracts-py/src:/opt/tilo/packages/providers/src:/opt/tilo/services/connectors/src \
    BOT_JOIN_MODE=guest
WORKDIR /app
COPY --chown=pwuser:pwuser meet-bot/bot /app/bot
COPY --chown=pwuser:pwuser meet-bot/docker/cloud_entrypoint.py /cloud_entrypoint.py
COPY --chown=pwuser:pwuser meet-bot/docker/cloud_smoke.py /cloud_smoke.py
USER pwuser
EXPOSE 8080
ENTRYPOINT ["python3", "/cloud_entrypoint.py"]
