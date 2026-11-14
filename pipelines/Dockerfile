# Dataflow Flex Template launcher image. Build context: repository root.
# Workers use Dataflow's standard Beam image; our code reaches them through setup.py.
FROM gcr.io/dataflow-templates-base/python311-template-launcher-base:latest

ARG BEAM_VERSION=2.77.0
WORKDIR /template

# Assemble one importable tree: cdp_common + cdp_beam + cdp_pipelines.
COPY libs/cdp_common/cdp_common cdp_common
COPY pipelines/cdp_beam cdp_beam
COPY pipelines/cdp_pipelines cdp_pipelines
COPY pipelines/dataflow/setup.py setup.py

# "pip install ." runs setup.py through setuptools: find_packages lists the three folders, setuptools
# builds a wheel from them, pip unpacks it into site-packages (launcher only; workers: see setup.py).
RUN pip install --no-cache-dir "apache-beam[gcp]==${BEAM_VERSION}" && pip install --no-cache-dir --no-deps .

# PY_FILE is required: the launcher runs this file to build the job graph. SETUP_FILE is optional
# for the launcher, but here it is the only way our packages reach the workers.
ENV FLEX_TEMPLATE_PYTHON_PY_FILE=/template/cdp_pipelines/care/main.py
ENV FLEX_TEMPLATE_PYTHON_SETUP_FILE=/template/setup.py
