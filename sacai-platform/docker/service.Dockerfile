FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_INDEX=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /opt/sacai
COPY sacai-platform/offline/apt-cache/rootfs/lib/x86_64-linux-gnu/ /usr/lib/x86_64-linux-gnu/
RUN ldconfig
COPY sacai-platform/offline/wheelhouse /wheelhouse
COPY sacai-platform/offline/isis_catalog.json /opt/sacai/isis_catalog.json
COPY sacai-platform/service/requirements.txt ./requirements.txt
RUN pip install --no-index --find-links=/wheelhouse -r requirements.txt \
    && python -m pip check \
    && rm -rf /wheelhouse
COPY sacai-platform/service/app ./app
EXPOSE 8000
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
