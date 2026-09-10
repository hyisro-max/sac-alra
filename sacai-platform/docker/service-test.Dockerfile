FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_INDEX=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/opt/sacai/service \
    SACAI_INTERNAL_TOKEN=test-token-at-least-16-characters
WORKDIR /opt/sacai
COPY sacai-platform/offline/apt-cache/rootfs/lib/x86_64-linux-gnu/ /usr/lib/x86_64-linux-gnu/
RUN ldconfig
COPY sacai-platform/offline/wheelhouse /wheelhouse
COPY sacai-platform/offline/isis_catalog.json /opt/sacai/isis_catalog.json
COPY sacai-platform/service/requirements.txt sacai-platform/service/test-requirements.txt ./
RUN pip install --no-index --find-links=/wheelhouse -r requirements.txt -r test-requirements.txt \
    && python -m pip check \
    && rm -rf /wheelhouse
COPY sacai-platform/service/app ./service/app
COPY sacai-platform/service/tests ./service/tests
COPY sacai-platform/openwebui_tools ./openwebui_tools
COPY sacai-platform/openwebui_functions ./openwebui_functions
CMD ["pytest", "-q", "/opt/sacai/service/tests"]
