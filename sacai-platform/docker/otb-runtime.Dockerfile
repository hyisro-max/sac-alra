# NOT YET BUILT on this deployment (unlike asp-runtime/ch2-runtime/isis-runtime,
# which already exist as loaded images). Build and verify this on the
# connected AlmaLinux builder the same way the other *-runtime images were
# built, before otb-worker can run.

FROM condaforge/miniforge3:24.9.2-0

ARG OTB_VERSION=9.1.0

RUN conda config --add channels conda-forge && \
    conda config --set channel_priority flexible

# Orfeo ToolBox (CNES) -- published on conda-forge as `otb`, includes the
# otbcli_* command-line applications and Python bindings.
RUN conda create -n otb -y \
      -c conda-forge \
      otb=${OTB_VERSION} \
    && conda clean -afy

# Same missing-libGL issue hit building isis-runtime/asp-runtime (Qt-based
# tools); apply proactively rather than rediscovering it the same way.
RUN conda install -n otb -y -c conda-forge libgl-devel \
    && conda clean -afy

ENV CONDA_DEFAULT_ENV=otb
ENV PATH=/opt/conda/envs/otb/bin:$PATH

ENV QT_QPA_PLATFORM=offscreen

# Verify with a real OTB command, not an assumed command name.
RUN /opt/conda/envs/otb/bin/otbcli_OrthoRectification --help >/dev/null

ENTRYPOINT ["/bin/bash"]
