"""
Golden-file tests: generated output must match a committed reference, byte for
byte.

Why this exists alongside the unit tests: the unit tests assert that individual
fields are correct, but they cannot notice an *unintended* change elsewhere in
the document. A mapping tweak that quietly alters every UUID, or reorders
elements, passes every field assertion and still changes what ships.

These tests make any such change visible as a diff that has to be looked at and
re-blessed deliberately.

When a change IS intended, regenerate the references:

    python tests/golden/regenerate.py

and review the resulting diff before committing it.
"""
from pathlib import Path

import pytest

from ocpi2sca import emit
from ocpi2sca.reader import read_component

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "corpus" / "opencpi"
EXPECTED = Path(__file__).parent / "expected"

COMPONENTS = [
    ("bias", "bias_spec.xml", "bias.xml"),
    ("file_read", "file_read_spec.xml", "file_read.xml"),
    ("file_write", "file_write_spec.xml", "file_write.xml"),
    ("dgrdma_config_proxy", "dgrdma_config_proxy-spec.xml", "dgrdma_config_proxy.xml"),
]


@pytest.mark.parametrize("name,spec,worker", COMPONENTS)
def test_output_matches_golden_reference(name, spec, worker):
    comp = read_component(CORPUS / name / spec, CORPUS / name / worker)
    produced = emit.emit_all(comp)

    for filename, content in produced.items():
        reference = EXPECTED / filename
        assert reference.exists(), (
            f"no golden reference for {filename}. "
            f"If this file is new, run tests/golden/regenerate.py."
        )
        assert content.decode() == reference.read_text(), (
            f"{filename} differs from its golden reference.\n"
            f"If the change is intended, run tests/golden/regenerate.py "
            f"and review the diff."
        )


@pytest.mark.parametrize("name,spec,worker", COMPONENTS)
def test_generation_is_reproducible(name, spec, worker):
    """Two runs must produce identical bytes.

    UUIDs are derived deterministically from names precisely so that
    regenerating a descriptor does not change its identity and break
    assemblies that reference it.
    """
    comp1 = read_component(CORPUS / name / spec, CORPUS / name / worker)
    comp2 = read_component(CORPUS / name / spec, CORPUS / name / worker)

    assert emit.emit_all(comp1) == emit.emit_all(comp2)
