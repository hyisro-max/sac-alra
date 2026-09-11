# Base image defaults to the operator's actual otb:otb (loaded on 254 from a
# pre-existing .tar.gz of unknown origin -- not built by
# docker/otb-runtime.Dockerfile, and its OS/Python are unconfirmed). The
# diagnostic RUN step below fails the build immediately with a clear message
# if python3/pip3 aren't usable, rather than letting a cryptic pip error be
# the first sign of trouble. If it fails: check what IS in the image
# (`docker run --rm otb:otb sh -c 'which python3 otbcli_OrthoRectification;
# cat /etc/os-release'`) and either install/upgrade Python inside a derived
# image first, or fall back to running SACAI's service/Celery code in a
# plain scientific-service container that shells out to otb:otb's binaries
# by absolute path instead of installing pip packages into it directly.
ARG OTB_BASE_IMAGE=otb:otb
FROM ${OTB_BASE_IMAGE}

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_INDEX=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /opt/sacai
COPY sacai-platform/offline/apt-cache/rootfs/lib/x86_64-linux-gnu/ /usr/lib/x86_64-linux-gnu/
RUN ldconfig
RUN command -v python3 >/dev/null && command -v pip3 >/dev/null || \
    (echo "otb:otb has no usable python3/pip3 -- see this Dockerfile's header comment" >&2 && exit 1)
RUN python3 --version | grep -q "Python 3.11" || \
    (echo "otb:otb's python3 is not 3.11, incompatible with the offline wheelhouse -- see this Dockerfile's header comment" >&2 && exit 1)
COPY sacai-platform/offline/wheelhouse /wheelhouse
COPY sacai-platform/service/requirements.txt ./requirements.txt
RUN python3 -m pip install --no-index --find-links=/wheelhouse -r requirements.txt \
    && python3 -m pip check \
    && rm -rf /wheelhouse
COPY sacai-platform/service/app ./app
COPY sacai-platform/dem/otb_postprocess.py ./otb_postprocess.py
ENTRYPOINT []
CMD ["celery", "-A", "app.celery_app:celery_app", "worker", "--loglevel=INFO", "--queues=otb_cpu", "--concurrency=1", "--hostname=otb@%h"]
