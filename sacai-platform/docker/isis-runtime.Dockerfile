FROM condaforge/miniforge3:24.9.2-0

ARG ISIS_VERSION=8.3.0
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY

ENV HTTP_PROXY=${HTTP_PROXY} \
    HTTPS_PROXY=${HTTPS_PROXY} \
    NO_PROXY=${NO_PROXY} \
    http_proxy=${HTTP_PROXY} \
    https_proxy=${HTTPS_PROXY} \
    no_proxy=${NO_PROXY}

# Correct, current channel order per USGS-Astrogeology / DOI-USGS docs:
# usgs-astrogeology first, then conda-forge. Flexible (not strict) priority
# is required: strict blocked qhull, a conda-forge dependency of isis, with
# "requires qhull >=2020.2,<2020.3.0a0, but none of the providers can be
# installed" even though a compatible build exists in conda-forge.
RUN conda config --add channels conda-forge && \
    conda config --add channels usgs-astrogeology && \
    conda config --set channel_priority flexible

# No python= pin: let isis's own dependency spec choose the Python version
# it was actually built against, rather than adding a second hard constraint
# for the solver to satisfy alongside qhull's version range.
RUN conda create -n isis -y \
      isis=${ISIS_VERSION} \
    && conda clean -afy

# ISIS's Qt-based tools link against OpenGL even for CLI/headless use.
# The conda-forge base doesn't ship libGL.so.1; conda-forge's own FAQ
# points to libgl-devel (libglvnd-feedstock) as the fix, kept in conda
# rather than apt so it doesn't need a separate system-package proxy path.
RUN conda install -n isis -y -c conda-forge libgl-devel \
    && conda clean -afy

ENV CONDA_DEFAULT_ENV=isis
ENV PATH=/opt/conda/envs/isis/bin:$PATH
ENV ISISROOT=/opt/conda/envs/isis

# ISISDATA is supplied at container run time via a bind mount, not baked in.
ENV ISISDATA=/opt/isisdata

# Headless container: avoid Qt trying to open a display/X11 connection.
ENV QT_QPA_PLATFORM=offscreen

# isisversion is a legacy ISIS3-era command that no longer exists in
# modern ISIS; isis_version.txt confirmed 8.3.0 and conda list agrees.
# Verify with a real tool instead: isisimport --help needs no data/network
# and proves libraries, ISISROOT and PATH are all correctly wired.
RUN /opt/conda/envs/isis/bin/isisimport -HELP || \
    (echo "ISIS install verification failed" && exit 1)

ENTRYPOINT ["/bin/bash"]





# FROM condaforge/miniforge3:24.9.2-0

# ARG ISIS_VERSION=8.3.0
# ARG HTTP_PROXY
# ARG HTTPS_PROXY
# ARG NO_PROXY

# ENV HTTP_PROXY=${HTTP_PROXY} \
#     HTTPS_PROXY=${HTTPS_PROXY} \
#     NO_PROXY=${NO_PROXY} \
#     http_proxy=${HTTP_PROXY} \
#     https_proxy=${HTTPS_PROXY} \
#     no_proxy=${NO_PROXY}

# # Correct, current channel order per USGS-Astrogeology / DOI-USGS docs:
# # usgs-astrogeology first, then conda-forge. Flexible (not strict) priority
# # is required: strict blocked qhull, a conda-forge dependency of isis, with
# # "requires qhull >=2020.2,<2020.3.0a0, but none of the providers can be
# # installed" even though a compatible build exists in conda-forge.
# RUN conda config --add channels conda-forge && \
#     conda config --add channels usgs-astrogeology && \
#     conda config --set channel_priority flexible

# # No python= pin: let isis's own dependency spec choose the Python version
# # it was actually built against, rather than adding a second hard constraint
# # for the solver to satisfy alongside qhull's version range.
# RUN conda create -n isis -y \
#       isis=${ISIS_VERSION} \
#     && conda clean -afy

# ENV CONDA_DEFAULT_ENV=isis
# ENV PATH=/opt/conda/envs/isis/bin:$PATH
# ENV ISISROOT=/opt/conda/envs/isis

# # ISISDATA is supplied at container run time via a bind mount, not baked in.
# ENV ISISDATA=/opt/isisdata

# # RUN isisversion || (echo "ISIS install verification failed" && exit 1)

# ENTRYPOINT ["/bin/bash"]