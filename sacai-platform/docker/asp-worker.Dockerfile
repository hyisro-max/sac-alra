# Mirrors isis-worker.Dockerfile exactly: layer the SACAI service/Celery
# code on top of the pinned scientific runtime image rather than the plain
# service.Dockerfile base, so the worker process has direct PATH access to
# the runtime's own binaries (here: ASP's stereo/point2dem, plus the ISIS
# 8.3.0 asp-runtime.Dockerfile already installs alongside it). The
# no-index pip install below targets the asp conda env's own `python`
# (PATH is set by asp-runtime.Dockerfile); this is the same install used by
# the already-verified isis-worker image, and asp-runtime.Dockerfile installs
# the same ISIS 8.3.0 release that image already proved compatible with the
# offline wheelhouse's Python 3.11 wheels.
ARG ASP_BASE_IMAGE=sacai/asp-runtime:3.5.0-amd64
FROM ${ASP_BASE_IMAGE}

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_INDEX=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /opt/sacai
COPY sacai-platform/offline/apt-cache/rootfs/lib/x86_64-linux-gnu/ /usr/lib/x86_64-linux-gnu/
RUN ldconfig
COPY sacai-platform/offline/wheelhouse /wheelhouse
COPY sacai-platform/service/requirements.txt ./requirements.txt
RUN python -m pip install --no-index --find-links=/wheelhouse -r requirements.txt \
    && python -m pip check \
    && rm -rf /wheelhouse
COPY sacai-platform/service/app ./app
COPY sacai-platform/dem/asp_stereo.py ./asp_stereo.py
ENTRYPOINT []
CMD ["celery", "-A", "app.celery_app:celery_app", "worker", "--loglevel=INFO", "--queues=asp_cpu", "--concurrency=1", "--hostname=asp@%h"]
