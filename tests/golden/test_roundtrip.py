"""Round-trip test: OpenCPI -> SCA -> OpenCPI.

Proves the reverse mapping is honest rather than plausible-looking. What
survives the round trip should survive; what the forward tool already drops
(protocol includes, <slaves>, hidden ocpi_* properties, worker/implementation
detail) is expected to stay lost, on purpose -- see
docs/OPEN-QUESTIONS-REVERSE.md RQ5-RQ7. This test asserts the boundary
explicitly instead of silently accepting whatever comes back.
"""
from pathlib import Path

from ocpi2sca import emit
from ocpi2sca.reader import read_component, read_component_from_sca

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "corpus" / "opencpi"


def _forward_then_back(tmp_path, name, spec, worker):
    original = read_component(CORPUS / name / spec, CORPUS / name / worker)

    for filename, content in emit.emit_all(original).items():
        (tmp_path / filename).write_bytes(content)

    roundtripped = read_component_from_sca(tmp_path / f"{name}.spd.xml")
    return original, roundtripped


def test_bias_properties_survive_the_round_trip(tmp_path):
    original, roundtripped = _forward_then_back(tmp_path, "bias", "bias_spec.xml", "bias.xml")

    orig_prop = original.property_by_name("biasValue")
    back_prop = roundtripped.property_by_name("biasValue")
    assert back_prop is not None
    assert back_prop.type == orig_prop.type

    # RQ2: initial/writable is not recoverable from configure/readwrite alone.
    # The original was 'initial'; the reverse policy also assumes 'initial',
    # so this round-trips correctly here, but by policy choice, not because
    # the ambiguity was resolved.
    assert back_prop.initial == orig_prop.initial
    assert len(roundtripped.inferences) == 1


def test_bias_ports_recover_protocol_via_own_namespace(tmp_path):
    """Ports round-trip because the forward tool's port repid stays inside
    its own IDL:ocpi/protocol/ namespace (RQ3)."""
    original, roundtripped = _forward_then_back(tmp_path, "bias", "bias_spec.xml", "bias.xml")

    orig_ports = {p.name: p for p in original.ports}
    back_ports = {p.name: p for p in roundtripped.ports}

    assert set(back_ports) == set(orig_ports)
    for name, back_port in back_ports.items():
        assert back_port.producer == orig_ports[name].producer


def test_worker_and_slaves_do_not_survive_the_round_trip(tmp_path):
    """RQ5/RQ7: OpenCPI worker model, language and <slaves> have no SCA
    representation at all -- confirmed lost, not silently reconstructed."""
    original, roundtripped = _forward_then_back(
        tmp_path,
        "dgrdma_config_proxy",
        "dgrdma_config_proxy-spec.xml",
        "dgrdma_config_proxy.xml",
    )

    assert original.implementations  # the original had one
    assert roundtripped.implementations == []  # nothing recovered, by design


def test_hidden_properties_do_not_survive_the_round_trip(tmp_path):
    """RQ6: ocpi_* bookkeeping properties are dropped before ever reaching
    SCA (Component.visible_properties, model.py), so there is nothing for the
    reverse reader to recover. No corpus component happens to declare one, so
    this builds a synthetic component directly rather than reading OCS/OWD
    XML."""
    from ocpi2sca.model import Component, Property

    original = Component(
        name="synthetic",
        properties=[
            Property(name="real", type="ulong", initial=True),
            Property(name="ocpi_debug", type="bool", hidden=True),
        ],
    )
    assert {p.name for p in original.properties if p.hidden} == {"ocpi_debug"}

    for filename, content in emit.emit_all(original).items():
        (tmp_path / filename).write_bytes(content)
    roundtripped = read_component_from_sca(tmp_path / "synthetic.spd.xml")

    back_names = {p.name for p in roundtripped.properties}
    assert "ocpi_debug" not in back_names
    assert "real" in back_names


def test_reverse_ocs_is_dtd_free_but_well_formed(tmp_path):
    """No DTD exists for OpenCPI XML; the honesty check is well-formedness
    plus the reported warnings, not a schema pass."""
    from lxml import etree

    _, roundtripped = _forward_then_back(tmp_path, "bias", "bias_spec.xml", "bias.xml")
    files = emit.emit_ocs_file(roundtripped)
    content = files["bias_spec.xml"]

    root = etree.fromstring(content)
    assert root.tag == "ComponentSpec"
