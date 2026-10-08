# Build context is the REPOSITORY ROOT (see docker-compose.yml and meet-bot/docker/Dockerfile.dockerignore): the bot calls
# Tilo's provider layer (FR-MTG-11), so the image carries packages/providers, packages/contracts-py and the config
# and prompts they read (not all of config/ and prompts/).
FROM mcr.microsoft.com/playwright/python:v1.52.0-noble

ENV DEBIAN_FRONTEND=noninteractive \
    TILO_IN_CONTAINER=1 \
    DISPLAY=:99 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Xvfb = virtual screen, PulseAudio = virtual audio, x11vnc + noVNC = a window into it from your browser,
# openbox = tiny window manager so keyboard focus behaves.
RUN apt-get update && apt-get install -y --no-install-recommends \
        xvfb x11vnc novnc websockify pulseaudio pulseaudio-utils openbox fonts-noto-color-emoji procps espeak-ng \
    && ln -sf /usr/share/novnc/vnc.html /usr/share/novnc/index.html \
    && mkdir -p /tmp/.X11-unix && chmod 1777 /tmp/.X11-unix \
    && rm -rf /var/lib/apt/lists/*

COPY meet-bot/docker/requirements.txt /tmp/requirements.txt
RUN pip install --break-system-packages --ignore-installed typing_extensions -r /tmp/requirements.txt

# Tilo's provider layer, in the repository's own layout under /opt/tilo so config/ and prompts/ resolve next to the
# packages exactly as in the repo (tilo_providers finds both four directories above its own files).
COPY packages/contracts-py/src /opt/tilo/packages/contracts-py/src
COPY packages/providers/src /opt/tilo/packages/providers/src
# Only what the bot's provider layer reads: the model, price, speech, voice and meeting-cap config, and the two
# prompt templates it loads (the schema-repair prompt and the transcribe prompt).
COPY config/models*.yaml /opt/tilo/config/
COPY config/prices*.yaml /opt/tilo/config/
COPY config/speech*.yaml /opt/tilo/config/
COPY config/voice*.yaml /opt/tilo/config/
COPY config/meeting*.yaml /opt/tilo/config/
COPY prompts/router /opt/tilo/prompts/router
COPY prompts/speech /opt/tilo/prompts/speech
ENV TILO_REPO_ROOT=/opt/tilo \
    PYTHONPATH=/opt/tilo/packages/contracts-py/src:/opt/tilo/packages/providers/src

# Profile volume mount point, owned by the non-root user so the named volume inherits it.
RUN mkdir -p /profile /app && chown pwuser:pwuser /profile /app

WORKDIR /app
COPY --chown=pwuser:pwuser meet-bot/bot /app/bot
COPY --chown=pwuser:pwuser meet-bot/docker/entrypoint.py /entrypoint.py

USER pwuser
EXPOSE 6080
ENTRYPOINT ["python3", "/entrypoint.py"]
CMD ["python", "-m", "bot.main", "--help"]
