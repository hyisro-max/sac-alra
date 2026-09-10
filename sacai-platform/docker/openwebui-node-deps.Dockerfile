FROM node:22-alpine3.20
WORKDIR /deps
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY

ENV HTTP_PROXY=${HTTP_PROXY} \
    HTTPS_PROXY=${HTTPS_PROXY} \
    NO_PROXY=${NO_PROXY} \
    http_proxy=${HTTP_PROXY} \
    https_proxy=${HTTPS_PROXY} \
    no_proxy=${NO_PROXY}

# RUN for attempt in 1 2 3 4 5; do \
#       apk add --no-cache python3 && exit 0; \
#       sleep $((attempt * 5)); \
#     done; \
#     exit 1
RUN apk add --no-cache python3
COPY source-code/open-webui/package.json source-code/open-webui/package-lock.json ./
# onnxruntime-node otherwise downloads an optional GPU binary during postinstall.
# Ollama owns GPU inference in this deployment, so no Node postinstall may use
# the connected builder's network.
# RUN npm_config_fetch_retries=10 \
#     npm_config_fetch_retry_mintimeout=10000 \
#     npm_config_fetch_retry_maxtimeout=120000 \
#     npm ci --force --ignore-scripts
RUN npm ci --force --ignore-scripts
COPY source-code/open-webui/scripts ./scripts
COPY source-code/open-webui/static ./static
RUN npm run pyodide:fetch
