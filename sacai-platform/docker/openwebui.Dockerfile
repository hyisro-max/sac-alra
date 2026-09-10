ARG NODE_DEPS_IMAGE=sacai/openwebui-node-deps:v0.11.3-sacalra1-amd64
ARG PYTHON_DEPS_IMAGE=sacai/openwebui-python-deps:v0.11.3-sacalra1-amd64
ARG PROJECT_NAME=SAC-ALRA
ARG OPENWEBUI_VERSION=0.11.3

FROM ${NODE_DEPS_IMAGE} AS frontend
ARG PROJECT_NAME
ARG OPENWEBUI_VERSION
WORKDIR /app
COPY source-code/open-webui/ ./
COPY sacai-platform/branding/sacai-logo.svg /opt/sacai/sacai-logo.svg
COPY sacai-platform/branding/apply_branding.py /opt/sacai/apply_branding.py
COPY sacai-platform/branding/verify_branding_overlay.py /opt/sacai/verify_branding_overlay.py
ENV NODE_OPTIONS="--max-old-space-size=8192"
RUN rm -rf node_modules static/pyodide \
    && cp -a /deps/node_modules ./node_modules \
    && cp -a /deps/static/pyodide ./static/pyodide \
    && test "$(node -p "require('./package.json').version")" = "${OPENWEBUI_VERSION}" \
    && python3 /opt/sacai/apply_branding.py /app --project-name "${PROJECT_NAME}" --openwebui-version "${OPENWEBUI_VERSION}" --logo /opt/sacai/sacai-logo.svg \
    && python3 /opt/sacai/verify_branding_overlay.py /app --expected-version "${OPENWEBUI_VERSION}" \
    && export npm_package_version="${OPENWEBUI_VERSION}" \
    && ./node_modules/.bin/vite build \
    && test -s /app/build/static/sacai-logo.svg

FROM ${PYTHON_DEPS_IMAGE}
# Proxy settings belong only to the connected AlmaLinux build. Clear both case
# variants in the runtime image so Chroma and Ollama traffic stays direct on
# the disconnected RHEL hosts.
ENV HTTP_PROXY="" \
    HTTPS_PROXY="" \
    NO_PROXY="" \
    http_proxy="" \
    https_proxy="" \
    no_proxy=""
ARG PROJECT_NAME
ENV ENV=prod \
    PORT=8080 \
    WEBUI_NAME=${PROJECT_NAME} \
    NODE_OPTIONS=--max-old-space-size=8192 \
    OFFLINE_MODE=true \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    SCARF_NO_ANALYTICS=true \
    DO_NOT_TRACK=true \
    ANONYMIZED_TELEMETRY=false \
    ENABLE_VERSION_UPDATE_CHECK=false \
    ENABLE_PIP_INSTALL_FRONTMATTER_REQUIREMENTS=false \
    OLLAMA_BASE_URL= \
    VECTOR_DB=chroma \
    CHROMA_HTTP_HOST=chroma \
    CHROMA_HTTP_PORT=8000
WORKDIR /app/backend
COPY --from=frontend /app/build /app/build
COPY --from=frontend /app/CHANGELOG.md /app/CHANGELOG.md
COPY --from=frontend /app/package.json /app/package.json
COPY --from=frontend /app/backend ./
EXPOSE 8080
HEALTHCHECK CMD curl --silent --fail http://localhost:8080/health | jq -e '.status == true' >/dev/null || exit 1
CMD ["bash", "start.sh"]
