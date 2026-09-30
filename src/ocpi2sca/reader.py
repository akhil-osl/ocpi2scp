"""
Reader: OpenCPI OCS/OWD XML -> resolved Component model.

Knows nothing about SCA. Its whole job is to produce a faithful, fully
resolved view of what OpenCPI describes.

CASE HANDLING
-------------
Real OpenCPI XML is inconsistent about case, in both element and attribute
names, within the same project:

    <Property Name="biasValue" Initial="true"/>     (bias_spec.xml)
    <property name='fileName' type='string' .../>   (file_read_spec.xml)
    <property name='bytesRead' type='uLongLong'/>   (mixed-case type value)

So elements, attribute names, and type values are all matched case
insensitively. This is not defensive coding -- every one of these spellings
appears in the corpus.

INFERENCE
---------
Where OpenCPI applies an implicit default, the reader applies the same
default and records an Inference. Nothing is assumed silently.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from lxml import etree

from . import mapping
from .model import Component, Implementation, Inference, Port, Property

# OpenCPI's default for a property with no Type attribute.
#
# Verified against OpenCPI's own output: bias_spec.xml declares
#   <Property Name="biasValue" Initial="true"/>
# with no type, and the header OpenCPI generates for it contains
#   const uint32_t biasValue;
# uint32_t is ulong. See tests/unit/test_reader.py.
DEFAULT_PROPERTY_TYPE = "ulong"

_TRUE = {"true", "1", "yes"}


def _attr(el: etree._Element, *names: str) -> Optional[str]:
    """Fetch an attribute by any of several names, ignoring case."""
    lowered = {k.lower(): v for k, v in el.attrib.items()}
    for n in names:
        if n.lower() in lowered:
            return lowered[n.lower()]
    return None


def _flag(el: etree._Element, *names: str) -> bool:
    v = _attr(el, *names)
    return v is not None and v.strip().lower() in _TRUE


def _tag_is(el: etree._Element, *names: str) -> bool:
    if not isinstance(el.tag, str):
        return False                      # comment or processing instruction
    tag = etree.QName(el).localname.lower()
    return tag in {n.lower() for n in names}


def _int_or_none(v: Optional[str]) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v, 0)
    except ValueError:
        return None


def read_component(spec_path: Path, worker_path: Optional[Path] = None) -> Component:
    """Read an OpenCPI component spec, and optionally a worker descriptor.

    The spec supplies properties and ports; the worker supplies the
    implementation. A spec alone is a valid component -- it just has no
    implementations yet.
    """
    spec_path = Path(spec_path)
    comp = _read_spec(spec_path)

    if worker_path is not None:
        _read_worker(Path(worker_path), comp)

    return comp


def _read_spec(path: Path) -> Component:
    root = etree.parse(str(path)).getroot()
    if not _tag_is(root, "ComponentSpec"):
        raise ValueError(f"{path}: expected <ComponentSpec>, got <{root.tag}>")

    # Spec files are named <component>_spec.xml or <component>-spec.xml.
    name = path.stem
    for suffix in ("_spec", "-spec"):
        if name.lower().endswith(suffix):
            name = name[: -len(suffix)]
            break

    comp = Component(name=name)

    for el in root:
        if _tag_is(el, "Property", "SpecProperty"):
            comp.properties.append(_read_property(el, comp))
        elif _tag_is(el, "DataInterfaceSpec", "Port"):
            comp.ports.append(_read_port(el, comp))

    return comp


def _read_property(el: etree._Element, comp: Component) -> Property:
    name = _attr(el, "Name") or ""
    raw_type = _attr(el, "Type")

    if raw_type is None:
        ptype = DEFAULT_PROPERTY_TYPE
        comp.inferences.append(
            Inference(
                subject=f"property {name}",
                field="type",
                value=ptype,
                rule="OpenCPI default for a property declared without Type",
            )
        )
    else:
        # Types appear as 'ulong', 'uLongLong', 'ULong' -- normalise.
        ptype = raw_type.strip().lower()

    return Property(
        name=name,
        type=ptype,
        default=_attr(el, "Default"),
        initial=_flag(el, "Initial"),
        parameter=_flag(el, "Parameter"),
        volatile=_flag(el, "Volatile"),
        writable=_flag(el, "Writable"),
        readable=_flag(el, "Readable"),
        string_length=_int_or_none(_attr(el, "StringLength")),
        sequence_length=_int_or_none(_attr(el, "SequenceLength")),
        enums=[e.strip() for e in (_attr(el, "Enums") or "").split(",") if e.strip()],
        hidden=_flag(el, "Hidden") or name.lower().startswith("ocpi_"),
    )


def _read_port(el: etree._Element, comp: Component) -> Port:
    name = _attr(el, "Name") or ""
    protocol = _attr(el, "Protocol")

    # A spec may name its protocol inline, or pull it in with
    #   <include href="stream32_protocol.xml"/>
    # Following that include needs the project search path, which is not
    # implemented yet -- so record the reference and move on rather than
    # guessing at a protocol name.
    if protocol is None:
        for child in el:
            if _tag_is(child, "include", "xi:include"):
                href = _attr(child, "href")
                if href:
                    comp.dropped.append(
                        f"port {name}: protocol include {href!r} not resolved "
                        f"(include chasing not implemented)"
                    )
                break

    return Port(
        name=name,
        producer=_flag(el, "Producer"),
        protocol=protocol,
    )


def _read_worker(path: Path, comp: Component) -> None:
    root = etree.parse(str(path)).getroot()

    model = "rcc" if _tag_is(root, "RccWorker") else "hdl" if _tag_is(root, "HdlWorker") else "unknown"

    impl = Implementation(
        worker_name=_attr(root, "Name") or path.stem,
        model=model,
        language=_attr(root, "Language"),
        control_operations=[
            op.strip()
            for op in (_attr(root, "ControlOperations") or "").split(",")
            if op.strip()
        ],
    )

    for el in root:
        if _tag_is(el, "slaves"):
            for inst in el:
                if _tag_is(inst, "Instance"):
                    w = _attr(inst, "Worker")
                    if w:
                        impl.slaves.append(w)
        elif _tag_is(el, "SpecProperty"):
            # A worker may override attributes of a spec property. Merge onto
            # the existing property rather than adding a duplicate.
            pname = _attr(el, "Name") or ""
            existing = comp.property_by_name(pname)
            if existing is None:
                comp.dropped.append(
                    f"specproperty {pname!r} overrides a property not present "
                    f"in the spec (spec resolution not implemented)"
                )
                continue
            if _flag(el, "Volatile"):
                existing.volatile = True
            if _flag(el, "Writable"):
                existing.writable = True
            if _flag(el, "Readable"):
                existing.readable = True
            if _attr(el, "Default") is not None:
                existing.default = _attr(el, "Default")

    if impl.slaves:
        comp.dropped.append(
            f"worker {impl.worker_name}: <slaves> ({', '.join(impl.slaves)}) "
            f"has no SCA equivalent"
        )

    comp.implementations.append(impl)


# ---------------------------------------------------------------------------
# Reverse: SCA SPD/SCD/PRF -> Component
# ---------------------------------------------------------------------------
#
# See docs/OPEN-QUESTIONS-REVERSE.md. This reader knows no OpenCPI-specific
# XML syntax to write -- it only builds the same resolved Component model the
# forward reader builds, using mapping.py's inverse functions for every
# judgement call. Genuinely lossy or ambiguous choices are recorded as
# Inferences on the model, not asserted silently.
#
# First slice (RQ5): OCS (properties + ports) only. No OWD is emitted, since
# nothing in SCA reliably determines OpenCPI worker model -- see emit.py.

def read_component_from_sca(
    spd_path: Path,
    scd_path: Optional[Path] = None,
    prf_path: Optional[Path] = None,
) -> Component:
    """Read an SCA descriptor set into a resolved Component model.

    `spd_path` is required; it names the component and points at the SCD and
    PRF unless overridden. Either companion file may be absent -- an SPD
    alone still yields a Component, just with no properties or ports.
    """
    spd_path = Path(spd_path)
    spd_root = etree.parse(str(spd_path)).getroot()
    if not _tag_is(spd_root, "softpkg"):
        raise ValueError(f"{spd_path}: expected <softpkg>, got <{spd_root.tag}>")

    name = _attr(spd_root, "name") or spd_path.stem
    comp = Component(name=name, spec_name=name)

    base = spd_path.parent
    if prf_path is None:
        prf_path = _localfile_ref(spd_root, "propertyfile", base)
    if scd_path is None:
        scd_path = _localfile_ref(spd_root, "descriptor", base)

    if prf_path is not None and Path(prf_path).exists():
        _read_prf(Path(prf_path), comp)
    if scd_path is not None and Path(scd_path).exists():
        _read_scd(Path(scd_path), comp)

    return comp


def _localfile_ref(spd_root: etree._Element, tag: str, base: Path) -> Optional[Path]:
    for el in spd_root:
        if _tag_is(el, tag):
            for child in el:
                if _tag_is(child, "localfile"):
                    lf = _attr(child, "name")
                    if lf:
                        return base / lf
    return None


def _read_prf(path: Path, comp: Component) -> None:
    root = etree.parse(str(path)).getroot()
    if not _tag_is(root, "properties"):
        raise ValueError(f"{path}: expected <properties>, got <{root.tag}>")

    for el in root:
        if _tag_is(el, "simple"):
            comp.properties.append(_read_simple(el, comp))


def _read_simple(el: etree._Element, comp: Component) -> Property:
    name = _attr(el, "name") or ""
    sca_type = (_attr(el, "type") or "").strip().lower()
    mode = (_attr(el, "mode") or "readonly").strip().lower()

    enumerations = None
    default = None
    kindtype = None
    enum_values: list[str] = []
    for child in el:
        if _tag_is(child, "enumerations"):
            enumerations = child
            for enum_el in child:
                if _tag_is(enum_el, "enumeration"):
                    label = _attr(enum_el, "label")
                    if label:
                        enum_values.append(label)
        elif _tag_is(child, "value"):
            default = child.text
        elif _tag_is(child, "kind"):
            kindtype = _attr(child, "kindtype")

    ocpi_type = mapping.unmap_type(sca_type, has_enumerations=enumerations is not None)

    flags = {"parameter": False, "volatile": False, "initial": False, "writable": False}
    if kindtype is not None:
        flags, inferences = mapping.unmap_kind_and_mode(
            kindtype, mode, subject=f"property {name}"
        )
        comp.inferences.extend(inferences)
    else:
        comp.dropped.append(
            f"property {name}: <simple> has no <kind> element "
            f"(kindtype/mode not derivable, no access attributes set)"
        )

    return Property(
        name=name,
        type=ocpi_type,
        default=default,
        initial=flags["initial"],
        parameter=flags["parameter"],
        volatile=flags["volatile"],
        writable=flags["writable"],
        readable=True,
        enums=enum_values,
        # RQ6: no SCA-side signal distinguishes OpenCPI's own bookkeeping
        # properties from an ordinary one that happens to be named ocpi_*.
        # Nothing is assumed hidden on the way back.
        hidden=False,
    )


def _read_scd(path: Path, comp: Component) -> None:
    root = etree.parse(str(path)).getroot()
    if not _tag_is(root, "softwarecomponent"):
        raise ValueError(f"{path}: expected <softwarecomponent>, got <{root.tag}>")

    for features in root:
        if not _tag_is(features, "componentfeatures"):
            continue
        for child in features:
            if not _tag_is(child, "ports"):
                continue
            for port_el in child:
                comp.ports.append(_read_port_el(port_el, comp))


def _read_port_el(el: etree._Element, comp: Component) -> Port:
    is_uses = _tag_is(el, "uses")
    name = _attr(el, "usesname") if is_uses else _attr(el, "providesname")
    repid = _attr(el, "repid") or ""

    protocol = mapping.unmap_port_repid(repid)
    if protocol is None and repid:
        comp.dropped.append(
            f"port {name}: repid {repid!r} names a CORBA interface outside "
            f"this tool's own namespace, no OpenCPI protocol recoverable"
        )

    return Port(
        name=name or "",
        # OpenCPI's own naming: "producer" is an output port. SCA "uses"
        # consumes another component's port, i.e. it is this component's
        # output -- the same direction the forward mapping already treats
        # as producer (see emit.build_scd).
        producer=is_uses,
        protocol=protocol,
    )
