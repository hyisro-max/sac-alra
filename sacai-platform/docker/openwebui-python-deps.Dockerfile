FROM python:3.11-slim-bookworm

ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY


ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_HTTP_TIMEOUT=300

ENV HTTP_PROXY=${HTTP_PROXY} \
    HTTPS_PROXY=${HTTPS_PROXY} \
    NO_PROXY=${NO_PROXY} \
    http_proxy=${HTTP_PROXY} \
    https_proxy=${HTTPS_PROXY} \
    no_proxy=${NO_PROXY}

    
RUN apt-get update && apt-get install -y --no-install-recommends \
    git build-essential pandoc gcc netcat-openbsd curl jq ca-certificates \
    libmariadb-dev python3-dev ffmpeg libsm6 libxext6 zstd \
    && rm -rf /var/lib/apt/lists/*

COPY source-code/open-webui/backend/requirements.txt /tmp/openwebui-requirements.txt
COPY source-code/pystac-client /tmp/pystac-client
RUN pip install --no-cache-dir --retries 10 --timeout 300 uv \
    && pip install --no-cache-dir --retries 10 --timeout 300 'torch<=2.9.1' torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu \
    && uv pip install --system -r /tmp/openwebui-requirements.txt /tmp/pystac-client --no-cache-dir \
    && python -m pip check 









    
# RUN apt_proxy="${HTTP_PROXY:-false}" \
#     && apt-get -o Acquire::http::Proxy="${apt_proxy}" -o Acquire::https::Proxy="${apt_proxy}" -o Acquire::Retries=10 -o Acquire::https::Timeout=120 -o Acquire::http::Timeout=120 update \
#     && apt-get -o Acquire::http::Proxy="${apt_proxy}" -o Acquire::https::Proxy="${apt_proxy}" -o Acquire::Retries=10 -o Acquire::https::Timeout=120 -o Acquire::http::Timeout=120 install -y --no-install-recommends \
#     git build-essential pandoc gcc netcat-openbsd curl jq ca-certificates \
#     libmariadb-dev python3-dev ffmpeg libsm6 libxext6 zstd \
#     && rm -rf /var/lib/apt/lists/*
# COPY source-code/open-webui/backend/requirements.txt /tmp/openwebui-requirements.txt
# COPY source-code/pystac-client /tmp/pystac-client
# RUN pip install --no-cache-dir --retries 10 --timeout 300 uv \
#     && pip install --no-cache-dir --retries 10 --timeout 300 'torch<=2.9.1' torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu \
#     && uv pip install --system -r /tmp/openwebui-requirements.txt /tmp/pystac-client --no-cache-dir \
#     && python -m pip check
