# NOTE: unlike asp-worker.Dockerfile, the otb conda env's own Python version
# is NOT yet verified compatible with the offline wheelhouse (built for
# Python 3.11/linux-amd64). If `pip install --no-index` below fails on
# ABI/version mismatch, either pin otb-runtime.Dockerfile's Python
# explicitly (`conda create -n otb -c conda-forge otb=${OTB_VERSION}
# python=3.11`) and rebuild it, or run the SACAI service/Celery code in a
# plain scientific-service container instead and shell out to the otb
# conda env's binaries by absolute path -- decide this once otb-runtime is
# actually built and its Python version is known.
ARG OTB_BASE_IMAGE=sacai/otb-runtime:9.1.0-amd64
FROM ${OTB_BASE_IMAGE}

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
COPY sacai-platform/dem/otb_postprocess.py ./otb_postprocess.py
ENTRYPOINT []
CMD ["celery", "-A", "app.celery_app:celery_app", "worker", "--loglevel=INFO", "--queues=otb_cpu", "--concurrency=1", "--hostname=otb@%h"]
