"""Reader tests, against real OpenCPI components from the corpus."""
from pathlib import Path

import pytest

from ocpi2sca.reader import read_component

CORPUS = Path(__file__).resolve().parents[2] / "corpus" / "opencpi"


def test_untyped_property_defaults_to_ulong():
    """bias declares <Property Name="biasValue" Initial="true"/> with no type.

    OpenCPI's own generated header for this worker contains
        const uint32_t biasValue;
    which is ulong. The reader must reach the same conclusion.
    """
    comp = read_component(CORPUS / "bias" / "bias_spec.xml")

    prop = comp.property_by_name("biasValue")
    assert prop is not None
    assert prop.type == "ulong"
    assert prop.initial is True


def test_inferred_type_is_reported_not_silent():
    """A defaulted type must be visible, never applied quietly."""
    comp = read_component(CORPUS / "bias" / "bias_spec.xml")

    assert len(comp.inferences) == 1
    inf = comp.inferences[0]
    assert "biasValue" in inf.subject
    assert inf.field == "type"
    assert inf.value == "ulong"


def test_declared_type_produces_no_inference():
    """file_read declares every type, so nothing should be inferred."""
    comp = read_component(CORPUS / "file_read" / "file_read_spec.xml")

    assert comp.inferences == []
    assert comp.property_by_name("fileName").type == "string"
    assert comp.property_by_name("messagesInFile").type == "bool"
    assert comp.property_by_name("opcode").type == "uchar"


def test_mixed_case_type_is_normalised():
    """file_read spells one type 'uLongLong'. Case must not matter."""
    comp = read_component(CORPUS / "file_read" / "file_read_spec.xml")

    assert comp.property_by_name("bytesRead").type == "ulonglong"


def test_mixed_case_elements_and_attributes():
    """Real OpenCPI XML mixes <Property Name=...> and <property name=...>."""
    bias = read_component(CORPUS / "bias" / "bias_spec.xml")       # Property/Name
    fread = read_component(CORPUS / "file_read" / "file_read_spec.xml")  # property/name

    assert bias.property_by_name("biasValue") is not None
    assert fread.property_by_name("fileName") is not None


def test_string_length_is_captured():
    comp = read_component(CORPUS / "file_read" / "file_read_spec.xml")
    assert comp.property_by_name("fileName").string_length == 1024


def test_producer_flag_distinguishes_port_direction():
    comp = read_component(CORPUS / "bias" / "bias_spec.xml")

    ports = {p.name: p for p in comp.ports}
    assert ports["in"].producer is False
    assert ports["out"].producer is True


def test_worker_supplies_implementation():
    comp = read_component(
        CORPUS / "bias" / "bias_spec.xml",
        CORPUS / "bias" / "bias.xml",
    )

    assert len(comp.implementations) == 1
    impl = comp.implementations[0]
    assert impl.worker_name == "bias"
    assert impl.model == "rcc"
    assert impl.language == "c"


def test_specproperty_merges_onto_spec_property():
    """file_read's worker adds volatile='true' to messageSize.

    The spec declares it initial only; the merge must not create a duplicate.
    """
    spec_only = read_component(CORPUS / "file_read" / "file_read_spec.xml")
    assert spec_only.property_by_name("messageSize").volatile is False

    merged = read_component(
        CORPUS / "file_read" / "file_read_spec.xml",
        CORPUS / "file_read" / "file_read.xml",
    )
    prop = merged.property_by_name("messageSize")
    assert prop.volatile is True
    assert prop.initial is True          # spec attribute preserved
    assert len([p for p in merged.properties if p.name == "messageSize"]) == 1


def test_slaves_are_dropped_with_a_warning():
    """<slaves> has no SCA equivalent; it must be reported, not silently lost."""
    comp = read_component(
        CORPUS / "dgrdma_config_proxy" / "dgrdma_config_proxy-spec.xml",
        CORPUS / "dgrdma_config_proxy" / "dgrdma_config_proxy.xml",
    )

    assert any("slaves" in d for d in comp.dropped)
    assert comp.implementations[0].slaves == ["dgrdma_config_dev.hdl"]


def test_unresolved_protocol_include_is_reported():
    """bias pulls its protocol in via <include href=>, which is not chased yet."""
    comp = read_component(CORPUS / "bias" / "bias_spec.xml")

    assert any("stream32_protocol.xml" in d for d in comp.dropped)


def test_ocpi_prefixed_properties_are_hidden():
    """OpenCPI bookkeeping properties must not reach the SCA descriptor."""
    comp = read_component(CORPUS / "file_read" / "file_read_spec.xml")

    for p in comp.properties:
        if p.name.startswith("ocpi_"):
            assert p.hidden
    assert all(not p.hidden for p in comp.visible_properties())


def test_rejects_non_componentspec_root():
    with pytest.raises(ValueError, match="ComponentSpec"):
        read_component(CORPUS / "bias" / "bias.xml")      # OWD, not OCS
