ARG ISIS_BASE_IMAGE=sacai/isis-runtime:8.3.0-amd64
FROM ${ISIS_BASE_IMAGE}

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_INDEX=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /opt/sacai
COPY sacai-platform/offline/apt-cache/rootfs/lib/x86_64-linux-gnu/ /usr/lib/x86_64-linux-gnu/
RUN ldconfig
COPY sacai-platform/offline/wheelhouse /wheelhouse
COPY sacai-platform/service/requirements.txt ./requirements.txt
COPY sacai-platform/offline/isis_catalog.json /opt/sacai/isis_catalog.json
RUN python -m pip install --no-index --find-links=/wheelhouse -r requirements.txt \
    && python -m pip check \
    && rm -rf /wheelhouse
COPY sacai-platform/service/app ./app
COPY sacai-platform/isis/isis_preprocess.py ./isis_preprocess.py
ENTRYPOINT []
CMD ["celery", "-A", "app.celery_app:celery_app", "worker", "--loglevel=INFO", "--queues=isis_cpu", "--concurrency=1", "--hostname=isis@%h"]
