# Shim so `pip install -e .` works with setuptools versions predating PEP 660
# (the build_editable hook). All real configuration is in pyproject.toml.
from setuptools import setup

setup()
