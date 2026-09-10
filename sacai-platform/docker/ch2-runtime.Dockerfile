FROM condaforge/miniforge3:24.9.2-0

# Official channels/versions per USGS Astrogeology's Chandrayaan-2 TMC-2
# ingestion guide. This is a release-candidate channel (label/RC), distinct
# from the stable usgs-astrogeology channel used for sacai/isis-runtime
# (ISIS 8.3.0). Same lesson as before: flexible priority, not strict.
#
# Also include the main (non-RC) usgs-astrogeology channel: the RC-only
# channel failed to solve with "nothing provides kakadu >=1,<2.0a0" even
# though kakadu resolved fine building ISIS 8.3.0 from the main channel.
# kakadu is proprietary (JPEG2000 support); it likely just hasn't been
# published to the RC prerelease channel yet, so let the solver fall back
# to the main channel for it specifically.
# To build use this command BUILD_PROXY_URL="http://http.docker.internal:3128"
#NO_PROXY_VALUE="localhost,127.0.0.1,chroma,redis,sacai-api,hubproxy.docker.internal"

#docker build --platform=linux/amd64 \
#  --build-arg "HTTP_PROXY=${BUILD_PROXY_URL}" \
#  --build-arg "HTTPS_PROXY=${BUILD_PROXY_URL}" \
#  --build-arg "NO_PROXY=${NO_PROXY_VALUE}" \
#  --build-arg "http_proxy=${BUILD_PROXY_URL}" \
#  --build-arg "https_proxy=${BUILD_PROXY_URL}" \
#  --build-arg "no_proxy=${NO_PROXY_VALUE}" \
#  -f docker/ch2-runtime.Dockerfile \
#  -t sacai/ch2-runtime:10.0.0rc2-amd64 \
# .



RUN conda config --add channels conda-forge && \
    conda config --add channels usgs-astrogeology && \
    conda config --add channels usgs-astrogeology/label/RC && \
    conda config --set channel_priority flexible

RUN conda create -n ch2 -y \
      -c usgs-astrogeology/label/RC \
      -c usgs-astrogeology \
      -c conda-forge \
      isis=10.0.0_RC2 \
      ale=1.1.3 \
      usgscsm=2.0.2 \
      spiceql \
      rclone \
      matplotlib \
    && conda clean -afy

# Same missing-libGL issue hit on the 8.3.0 build; apply proactively.
RUN conda install -n ch2 -y -c conda-forge libgl-devel \
    && conda clean -afy

ENV CONDA_DEFAULT_ENV=ch2
ENV PATH=/opt/conda/envs/ch2/bin:$PATH
ENV ISISROOT=/opt/conda/envs/ch2

# Separate ISISDATA mount point: ISIS 10 RC2 data area is not guaranteed
# compatible with the ISIS 8.3.0 data area used by sacai/isis-runtime.
# Keep them distinct until proven otherwise.
ENV ISISDATA=/opt/isisdata-ch2

ENV QT_QPA_PLATFORM=offscreen

# Verify with isisimport (real modern-ISIS command, confirmed working
# syntax from the 8.3.0 build) rather than assuming version-check syntax
# is identical between ISIS releases.
RUN /opt/conda/envs/ch2/bin/isisimport -HELP || \
    (echo "ISIS 10 RC2 install verification failed" && exit 1)

ENTRYPOINT ["/bin/bash"]
