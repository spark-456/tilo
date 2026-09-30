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

COPY docker/requirements.txt /tmp/requirements.txt
RUN pip install --break-system-packages --ignore-installed typing_extensions -r /tmp/requirements.txt

# Profile volume mount point, owned by the non-root user so the named volume inherits it.
RUN mkdir -p /profile /app && chown pwuser:pwuser /profile /app

WORKDIR /app
COPY --chown=pwuser:pwuser bot /app/bot
COPY --chown=pwuser:pwuser docker/entrypoint.py /entrypoint.py

USER pwuser
EXPOSE 6080
ENTRYPOINT ["python3", "/entrypoint.py"]
CMD ["python", "-m", "bot.main", "--help"]
