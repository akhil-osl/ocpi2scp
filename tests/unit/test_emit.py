"""Emitter and mapping tests, plus DTD validation of the generated output."""
from pathlib import Path

import pytest
from lxml import etree

from ocpi2sca import emit, mapping, validate
from ocpi2sca.model import Component, Implementation, Port, Property
from ocpi2sca.reader import read_component

CORPUS = Path(__file__).resolve().parents[2] / "corpus" / "opencpi"
COMPONENTS = [
    ("bias", "bias_spec.xml", "bias.xml"),
    ("file_read", "file_read_spec.xml", "file_read.xml"),
    ("file_write", "file_write_spec.xml", "file_write.xml"),
    ("dgrdma_config_proxy", "dgrdma_config_proxy-spec.xml", "dgrdma_config_proxy.xml"),
]


def _load(name, spec, worker):
    return read_component(CORPUS / name / spec, CORPUS / name / worker)


# ---------------------------------------------------------------------------
# The headline requirement: schema-valid output from real components.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,spec,worker", COMPONENTS)
def test_generated_descriptors_are_dtd_valid(tmp_path, name, spec, worker):
    comp = _load(name, spec, worker)

    for filename, content in emit.emit_all(comp).items():
        (tmp_path / filename).write_bytes(content)

    results = validate.validate_set(tmp_path, comp.name)
    assert results, "no descriptors were produced"
    for r in results:
        assert r.ok, f"{r.level} validation failed:\n" + "\n".join(r.errors)


@pytest.mark.parametrize("name,spec,worker", COMPONENTS)
def test_generated_set_is_semantically_consistent(tmp_path, name, spec, worker):
    comp = _load(name, spec, worker)
    for filename, content in emit.emit_all(comp).items():
        (tmp_path / filename).write_bytes(content)

    result = validate.validate_semantic(tmp_path / f"{comp.name}.spd.xml")
    assert result.ok, "\n".join(result.errors)


# ---------------------------------------------------------------------------
# Type mapping
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "ocpi,sca",
    [
        ("ulong", "ulong"),
        ("bool", "boolean"),
        ("uchar", "octet"),
        ("ulonglong", "ulonglong"),
        ("string", "string"),
        ("float", "float"),
        ("enum", "string"),      # SCA has no enum type
    ],
)
def test_type_mapping(ocpi, sca):
    assert mapping.map_type(ocpi) == sca


def test_unknown_type_raises_rather_than_defaulting():
    """A silent wrong type is worse than a loud failure."""
    with pytest.raises(mapping.UnmappableType):
        mapping.map_type("some_future_opencpi_type")


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

def test_uuids_are_deterministic():
    """Regenerating must not change a component's identity.

    A random UUID per run would break every assembly referencing it.
    """
    a = mapping.dce_uuid("bias", "softpkg")
    b = mapping.dce_uuid("bias", "softpkg")
    assert a == b
    assert a.startswith("DCE:")


def test_uuids_differ_per_subject():
    assert mapping.dce_uuid("bias", "softpkg") != mapping.dce_uuid("other", "softpkg")
    assert mapping.dce_uuid("bias", "property", "x") != mapping.dce_uuid("bias", "property", "y")


# ---------------------------------------------------------------------------
# Kind / mode policy (open question Q3)
# ---------------------------------------------------------------------------

def test_parameter_becomes_readonly_execparam():
    p = Property(name="p", type="ulong", parameter=True)
    assert mapping.map_kind_and_mode(p) == ("execparam", "readonly")


def test_initial_becomes_readwrite_configure():
    p = Property(name="p", type="ulong", initial=True)
    assert mapping.map_kind_and_mode(p) == ("configure", "readwrite")


def test_volatile_only_becomes_readonly_configure():
    p = Property(name="p", type="ulong", volatile=True)
    assert mapping.map_kind_and_mode(p) == ("configure", "readonly")


# ---------------------------------------------------------------------------
# Port direction
# ---------------------------------------------------------------------------

def test_producer_port_becomes_uses_and_consumer_becomes_provides():
    comp = Component(
        name="t",
        ports=[Port(name="in", producer=False), Port(name="out", producer=True)],
        implementations=[Implementation(worker_name="t", model="rcc", language="c")],
    )

    scd = emit.build_scd(comp)
    assert scd.find(".//ports/provides").get("providesname") == "in"
    assert scd.find(".//ports/uses").get("usesname") == "out"


def test_every_port_repid_is_declared_as_an_interface():
    """An undeclared repid passes the DTD but is semantically broken."""
    comp = _load("bias", "bias_spec.xml", "bias.xml")
    scd = emit.build_scd(comp)

    declared = {i.get("repid") for i in scd.findall(".//interface")}
    for port in scd.findall(".//ports/*"):
        assert port.get("repid") in declared


# ---------------------------------------------------------------------------
# Hidden properties
# ---------------------------------------------------------------------------

def test_hidden_properties_are_excluded_from_prf():
    comp = Component(
        name="t",
        properties=[
            Property(name="real", type="ulong", initial=True),
            Property(name="ocpi_debug", type="bool", hidden=True),
        ],
    )

    prf = emit.build_prf(comp)
    names = {s.get("name") for s in prf.findall("simple")}
    assert names == {"real"}


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

def test_spd_references_the_other_two_files():
    comp = _load("bias", "bias_spec.xml", "bias.xml")
    spd = emit.build_spd(comp)

    assert spd.find("propertyfile/localfile").get("name") == "bias.prf.xml"
    assert spd.find("descriptor/localfile").get("name") == "bias.scd.xml"


def test_doctype_is_emitted():
    """SCA descriptors are DTD-defined; the DOCTYPE must be present."""
    comp = _load("bias", "bias_spec.xml", "bias.xml")
    files = emit.emit_all(comp)

    assert b"-//JTRS//DTD SCA V2.2.2 PRF//EN" in files["bias.prf.xml"]
    assert b"-//JTRS//DTD SCA V2.2.2 SCD//EN" in files["bias.scd.xml"]
    assert b"-//JTRS//DTD SCA V2.2.2 SPD//EN" in files["bias.spd.xml"]


def test_property_default_becomes_a_value_element():
    comp = Component(
        name="t",
        properties=[Property(name="p", type="ulong", initial=True, default="7")],
    )

    prf = emit.build_prf(comp)
    assert prf.find("simple/value").text == "7"


def test_bias_prf_content_end_to_end():
    """The worked example, asserted field by field."""
    comp = _load("bias", "bias_spec.xml", "bias.xml")
    prf = emit.build_prf(comp)

    simples = prf.findall("simple")
    assert len(simples) == 1

    s = simples[0]
    assert s.get("name") == "biasValue"
    assert s.get("type") == "ulong"          # inferred, not declared
    assert s.get("mode") == "readwrite"
    assert s.get("id").startswith("DCE:")
    assert s.find("kind").get("kindtype") == "configure"
