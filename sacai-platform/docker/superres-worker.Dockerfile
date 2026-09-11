# Base image is the operator's existing sacai-super-res:latest (an SR4RS
# build, https://github.com/remicres/sr4rs -- OTB + TensorFlow), normally run
# via its own docker-compose file rather than as a bare image. That compose
# file's volumes/env (model weights under some mounted path, GPU device
# reservations if any, etc.) are NOT reproduced here -- check what it
# actually mounted and add the same volumes/environment to the
# superres-worker service in docker-compose.yml before relying on this.
#
# Same caution as otb-worker.Dockerfile: this image's own Python/pip are
# unconfirmed, so the diagnostic RUN steps below fail the build immediately
# with a named cause instead of a bare pip ABI error. If they fail: check
# what IS in the image (`docker run --rm sacai-super-res:latest sh -c
# 'which python3 python; cat /etc/os-release'`) and either install/upgrade
# Python inside a derived image, or run SACAI's service/Celery code in a
# plain scientific-service container that shells out to sacai-super-res's
# own docker-compose-driven scripts by absolute path instead.
ARG SUPERRES_BASE_IMAGE=sacai-super-res:latest
FROM ${SUPERRES_BASE_IMAGE}

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_INDEX=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /opt/sacai
COPY sacai-platform/offline/apt-cache/rootfs/lib/x86_64-linux-gnu/ /usr/lib/x86_64-linux-gnu/
RUN ldconfig
RUN command -v python3 >/dev/null && command -v pip3 >/dev/null || \
    (echo "sacai-super-res:latest has no usable python3/pip3 -- see this Dockerfile's header comment" >&2 && exit 1)
RUN python3 --version | grep -q "Python 3.11" || \
    (echo "sacai-super-res:latest's python3 is not 3.11, incompatible with the offline wheelhouse -- see this Dockerfile's header comment" >&2 && exit 1)
COPY sacai-platform/offline/wheelhouse /wheelhouse
COPY sacai-platform/service/requirements.txt ./requirements.txt
RUN python3 -m pip install --no-index --find-links=/wheelhouse -r requirements.txt \
    && python3 -m pip check \
    && rm -rf /wheelhouse
COPY sacai-platform/service/app ./app
COPY sacai-platform/superres/run_superres.py ./run_superres.py
ENTRYPOINT []
CMD ["celery", "-A", "app.celery_app:celery_app", "worker", "--loglevel=INFO", "--queues=superres_cpu", "--concurrency=1", "--hostname=superres@%h"]
