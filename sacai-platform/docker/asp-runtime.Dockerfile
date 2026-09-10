FROM condaforge/miniforge3:24.9.2-0

ARG ASP_VERSION=3.5.0

# Official channel order matters here (per NeoGeographyToolkit/StereoPipeline
# INSTALLGUIDE): nasa-ames-stereo-pipeline, then usgs-astrogeology, then
# conda-forge. Flexible priority, not strict -- same lesson learned building
# isis-runtime: strict blocked a conda-forge dependency (qhull) even though
# a compatible build existed there.
RUN conda config --add channels conda-forge && \
    conda config --add channels usgs-astrogeology && \
    conda config --add channels nasa-ames-stereo-pipeline && \
    conda config --set channel_priority flexible

# ASP 3.5.0 installs ISIS 8.3.0 alongside it (same version already verified
# working in sacai/isis-runtime), so this environment is self-contained.
RUN conda create -n asp -y \
      -c nasa-ames-stereo-pipeline \
      -c usgs-astrogeology \
      -c conda-forge \
      stereo-pipeline=${ASP_VERSION} \
    && conda clean -afy

# Same missing-libGL issue ISIS hit is likely here too (Qt-based tools);
# apply proactively rather than rediscovering it the same way.
RUN conda install -n asp -y -c conda-forge libgl-devel \
    && conda clean -afy

ENV CONDA_DEFAULT_ENV=asp
ENV PATH=/opt/conda/envs/asp/bin:$PATH
ENV ISISROOT=/opt/conda/envs/asp

# ISISDATA supplied at container run time via bind mount, matching
# sacai/isis-runtime -- not baked into the image.
ENV ISISDATA=/opt/isisdata

ENV QT_QPA_PLATFORM=offscreen

# Verify with real ASP tools, not an assumed command name.
RUN /opt/conda/envs/asp/bin/stereo --version && \
    /opt/conda/envs/asp/bin/point2dem --version

ENTRYPOINT ["/bin/bash"]
