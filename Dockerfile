# Real-Time Driver Drowsiness Detection System — laptop-side detector.
#
# One image, three ways to run it (see docker-compose.yml):
#   validate  replay a recorded clip through the real pipeline (any OS)
#   headless  live detection from a network camera, alerts to the phone (any OS)
#   live      webcam + window + phone discovery (Linux / Raspberry Pi host)
#
# The Android alert app is not part of this image; build it from
# drowsiness_detector/android/DrowsinessAlertApp as described in README.md.

FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# OpenCV and MediaPipe runtime libraries. The X11/xcb ones are only used by
# the `live` mode's preview window; headless modes never load them.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libegl1 libgles2 libglib2.0-0 libgomp1 \
        libsm6 libxext6 libxrender1 libfontconfig1 libdbus-1-3 \
        libxkbcommon-x11-0 libxcb1 libxcb-icccm4 libxcb-image0 \
        libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 \
        libxcb-shape0 libxcb-xinerama0 libxcb-xkb1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first, so code edits don't reinstall them.
# MediaPipe and OpenCV are pinned to the versions the thesis was evaluated
# with, so the container reproduces those results rather than whatever is
# newest on the day it is built.
COPY drowsiness_detector/requirements.txt drowsiness_detector/requirements.txt
RUN pip install -r drowsiness_detector/requirements.txt \
        mediapipe==0.10.35 opencv-python==5.0.0.93

# Session logs are stamped with local time; containers default to UTC.
# Override with -e TZ=... if the demo is elsewhere.
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*
ENV TZ=Asia/Manila

COPY drowsiness_detector/ drowsiness_detector/
COPY inference/ inference/
COPY models/ models/
COPY tools/ tools/

# Session logs go to a mounted volume rather than inside the container.
ENV SESSION_LOG_DIR=/app/logs
RUN mkdir -p /app/logs

# 8080: MJPEG feed + calibrate endpoint for the phone app
# 9876/udp: phone discovery broadcast (only reachable with host networking)
EXPOSE 8080 9876/udp

WORKDIR /app/drowsiness_detector
CMD ["python", "main.py"]
