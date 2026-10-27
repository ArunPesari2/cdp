"""Packages the job code for Dataflow workers (copied to /template/setup.py by pipelines/Dockerfile).

Beam and the Google Cloud clients are already on Dataflow's worker image, so no install_requires.
"""

import setuptools

setuptools.setup(
    name="cdp-dataflow-job",
    version="0.1.0",
    packages=setuptools.find_packages(include=["cdp_common*", "cdp_beam*", "cdp_pipelines*"]),
)
