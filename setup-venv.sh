#!/usr/bin/env bash
#
# Create the development virtualenv and install ocpi2sca into it.
#
#   ./setup-venv.sh
#   source .venv/bin/activate
#   ocpi2sca generate corpus/opencpi/bias/bias_spec.xml -o out/
#
# Safe to re-run; it upgrades an existing .venv in place.
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d .venv ]; then
    echo "creating .venv"
    python3 -m venv .venv
fi

# Editable installs need PEP 660 support, which arrived in setuptools 64.
# Distro Pythons often ship something older, so upgrade inside the venv
# rather than relying on what the system provides.
echo "upgrading pip and setuptools"
.venv/bin/pip install --quiet --upgrade pip setuptools

echo "installing ocpi2sca (editable, with dev extras)"
.venv/bin/pip install --quiet -e ".[dev]"

echo
echo "done. Next:"
echo "    source .venv/bin/activate"
echo "    ocpi2sca generate corpus/opencpi/bias/bias_spec.xml -o out/"
echo "    pytest -q"
