"""Reverse-direction tests: SCA descriptors -> OpenCPI Component/OCS.

See docs/OPEN-QUESTIONS-REVERSE.md. Mirrors test_reader.py's discipline: an
inferred value must be visible, never applied silently, and a construct with
no SCA-side signal must not be fabricated.
"""
from pathlib import Path

import pytest

from ocpi2sca import emit, mapping
from ocpi2sca.reader import read_component_from_sca

GOLDEN = Path(__file__).resolve().parents[1] / "golden" / "expected"


def test_reads_properties_back_from_prf():
    comp = read_component_from_sca(GOLDEN / "bias.spd.xml")

    prop = comp.property_by_name("biasValue")
    assert prop is not None
    assert prop.type == "ulong"


def test_ambiguous_kind_mode_is_flagged_as_inference():
    """configure/readwrite has no unique OpenCPI source (RQ2): must be an
    Inference, not a silent assumption."""
    comp = read_component_from_sca(GOLDEN / "bias.spd.xml")

    assert len(comp.inferences) == 1
    inf = comp.inferences[0]
    assert "biasValue" in inf.subject
    assert inf.field == "initial/writable"


def test_ambiguous_kind_mode_assumes_initial_not_writable():
    """RQ2's current policy pick: symmetry with the forward tool's own Q3
    choice, not a claim of correctness."""
    comp = read_component_from_sca(GOLDEN / "bias.spd.xml")

    prop = comp.property_by_name("biasValue")
    assert prop.initial is True
    assert prop.writable is False


def test_unambiguous_kind_mode_produces_no_inference():
    """execparam/readonly -> parameter, and configure/readonly with no write
    path -> volatile, are each a single OpenCPI attribute: derivations, not
    inferences."""
    comp = read_component_from_sca(GOLDEN / "dgrdma_config_proxy.spd.xml")

    volatile_props = [p for p in comp.properties if p.name.startswith("ack_tracker_")]
    assert volatile_props
    for p in volatile_props:
        assert p.volatile is True
        assert p.initial is False

    volatile_inferences = [i for i in comp.inferences if any(
        p.name in i.subject for p in volatile_props
    )]
    assert volatile_inferences == []


def test_own_namespace_repid_recovers_protocol_name():
    """RQ3: a repid in this tool's own IDL:ocpi/protocol/ namespace names an
    OpenCPI protocol -- recovering it is a derivation."""
    comp = read_component_from_sca(GOLDEN / "bias.spd.xml")

    ports = {p.name: p for p in comp.ports}
    assert ports["in"].protocol == "in"
    assert ports["out"].protocol == "out"


def test_foreign_repid_is_dropped_not_fabricated():
    """RQ3: a repid outside our namespace (e.g. a real CORBA interface) names
    nothing on the OpenCPI side. Must be dropped with a warning, not guessed."""
    comp = _read_foreign_repid_fixture()

    port = comp.ports[0]
    assert port.protocol is None
    assert any("BULKIO" in d for d in comp.dropped)


def _read_foreign_repid_fixture():
    """Build a minimal SPD/SCD set with a foreign repid, in tmp files."""
    import tempfile
    from pathlib import Path as P

    spd = """<?xml version='1.0' encoding='UTF-8'?>
<!DOCTYPE softpkg PUBLIC "-//JTRS//DTD SCA V2.2.2 SPD//EN" "softpkg.dtd">
<softpkg id="DCE:00000000-0000-0000-0000-000000000000" name="foreign" type="sca_compliant">
  <title>foreign</title>
  <author><name>test</name></author>
  <descriptor><localfile name="foreign.scd.xml"/></descriptor>
  <implementation id="rcc_foreign">
    <code type="SharedLibrary"><localfile name="foreign.so"/></code>
    <os name="Linux"/><processor name="x86_64"/>
  </implementation>
</softpkg>
"""
    scd = """<?xml version='1.0' encoding='UTF-8'?>
<!DOCTYPE softwarecomponent PUBLIC "-//JTRS//DTD SCA V2.2.2 SCD//EN" "softwarecomponent.dtd">
<softwarecomponent>
  <corbaversion>2.2</corbaversion>
  <componentrepid repid="IDL:CF/Resource:1.0"/>
  <componenttype>resource</componenttype>
  <componentfeatures>
    <supportsinterface repid="IDL:CF/Resource:1.0" supportsname="Resource"/>
    <ports>
      <uses usesname="dataOut" repid="IDL:BULKIO/dataFloat:1.0"/>
    </ports>
  </componentfeatures>
  <interfaces>
    <interface repid="IDL:CF/Resource:1.0" name="Resource">
      <inheritsinterface repid="IDL:CF/PortSupplier:1.0"/>
    </interface>
    <interface repid="IDL:BULKIO/dataFloat:1.0" name="dataFloat">
      <inheritsinterface repid="IDL:CF/PortSupplier:1.0"/>
    </interface>
  </interfaces>
</softwarecomponent>
"""
    tmp = P(tempfile.mkdtemp())
    (tmp / "foreign.spd.xml").write_text(spd)
    (tmp / "foreign.scd.xml").write_text(scd)
    return read_component_from_sca(tmp / "foreign.spd.xml")


def test_reverse_emits_ocs_only_no_owd(tmp_path):
    """RQ5: nothing in SCA reliably determines OpenCPI worker model, so the
    reverse generator must not fabricate an OWD."""
    comp = read_component_from_sca(GOLDEN / "bias.spd.xml")

    files = emit.emit_ocs_file(comp)
    assert list(files.keys()) == ["bias_spec.xml"]


def test_reverse_ocs_has_no_worker_element():
    comp = read_component_from_sca(GOLDEN / "bias.spd.xml")
    ocs = emit.build_ocs(comp)

    assert ocs.tag == "ComponentSpec"
    assert ocs.find(".//RccWorker") is None
    assert ocs.find(".//HdlWorker") is None


def test_string_vs_enum_disambiguated_by_enumerations():
    """RQ1: SCA 'string' is ambiguous between OpenCPI string and enum; the
    PRF's own <enumerations> element is the signal, not a guess."""
    assert mapping.unmap_type("string", has_enumerations=False) == "string"
    assert mapping.unmap_type("string", has_enumerations=True) == "enum"


@pytest.mark.parametrize(
    "ocpi_type,expected",
    [
        ("ulong", "ulong"),
        ("bool", "boolean"),
        ("uchar", "uchar"),
        ("ulonglong", "ulonglong"),
        ("float", "float"),
        ("short", "short"),
        ("double", "double"),
    ],
)
def test_unmap_type_is_inverse_of_map_type_for_unambiguous_types(ocpi_type, expected):
    sca_type = mapping.map_type(ocpi_type)
    assert mapping.unmap_type(sca_type) == expected


def test_unmap_unknown_sca_type_raises():
    with pytest.raises(mapping.UnmappableType):
        mapping.unmap_type("some_future_sca_type")


def test_reads_component_name_from_spd_name_attribute():
    """RQ4: UUID has no way back to a name, but SPD/PRF already carry name=
    directly, so it is never needed."""
    comp = read_component_from_sca(GOLDEN / "bias.spd.xml")
    assert comp.name == "bias"


def test_no_kind_element_is_dropped_not_guessed():
    """A <simple> with no <kind> child has no derivable access attributes."""
    import tempfile
    from pathlib import Path as P

    prf = """<?xml version='1.0' encoding='UTF-8'?>
<!DOCTYPE properties PUBLIC "-//JTRS//DTD SCA V2.2.2 PRF//EN" "properties.dtd">
<properties>
  <simple id="DCE:00000000-0000-0000-0000-000000000001" name="bare" type="ulong" mode="readonly"/>
</properties>
"""
    spd = """<?xml version='1.0' encoding='UTF-8'?>
<!DOCTYPE softpkg PUBLIC "-//JTRS//DTD SCA V2.2.2 SPD//EN" "softpkg.dtd">
<softpkg id="DCE:00000000-0000-0000-0000-000000000000" name="bare_test" type="sca_compliant">
  <title>bare_test</title>
  <author><name>test</name></author>
  <propertyfile><localfile name="bare_test.prf.xml"/></propertyfile>
  <implementation id="rcc_bare_test">
    <code type="SharedLibrary"><localfile name="bare_test.so"/></code>
    <os name="Linux"/><processor name="x86_64"/>
  </implementation>
</softpkg>
"""
    tmp = P(tempfile.mkdtemp())
    (tmp / "bare_test.spd.xml").write_text(spd)
    (tmp / "bare_test.prf.xml").write_text(prf)

    comp = read_component_from_sca(tmp / "bare_test.spd.xml")
    prop = comp.property_by_name("bare")
    assert prop.parameter is False
    assert prop.volatile is False
    assert prop.initial is False
    assert prop.writable is False
    assert any("no <kind>" in d for d in comp.dropped)
