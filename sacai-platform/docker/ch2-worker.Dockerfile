# Optional, mission-specific: only needed when a Chandrayaan-2 TMC-2 raw
# product cannot be ingested by the generic isis-worker (ISIS 8.3.0). Mirrors
# isis-worker.Dockerfile exactly, layered on ch2-runtime.Dockerfile's ISIS 10
# RC2 stack instead. Reuses the same generic isis_preprocess.py wrapper --
# it hardcodes no mission/version-specific ISIS commands either way, so the
# only difference between this worker and the default one is which
# CH2_ISIS_*_COMMAND environment variables the operator fills in, and which
# ISISDATA tree is mounted (ch2-runtime.Dockerfile uses a separate
# /opt/isisdata-ch2, not guaranteed compatible with the ISIS 8.3.0 data area).
ARG CH2_BASE_IMAGE=sacai/ch2-runtime:10.0.0rc2-amd64
FROM ${CH2_BASE_IMAGE}

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
CMD ["celery", "-A", "app.celery_app:celery_app", "worker", "--loglevel=INFO", "--queues=ch2_cpu", "--concurrency=1", "--hostname=ch2@%h"]
