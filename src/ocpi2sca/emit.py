"""
Emitters: resolved Component -> SCA descriptor XML.

Makes no decisions. Every choice has already been made in mapping.py; this
module's only job is to produce well-formed, DTD-valid XML.

ELEMENT ORDER MATTERS. The SCA DTDs define content models as sequences, not
choices. From softpkg.dtd:

    <!ELEMENT softpkg
        ( title?, author+, description?, propertyfile?, descriptor?,
          implementation+, usesdevice* )>

Emitting the right elements in the wrong order fails validation just as
surely as omitting one. The builders below follow DTD order deliberately;
do not reorder them for readability.
"""
from __future__ import annotations

from lxml import etree

from . import mapping
from .model import Component, Property

# Public identifiers exactly as SCA 2.2.2 defines them. The system identifier
# is the bare DTD filename, matching how REDHAWK's own descriptors declare it,
# so validation resolves against a local DTD directory.
DOCTYPES = {
    "spd": ('softpkg', "-//JTRS//DTD SCA V2.2.2 SPD//EN", "softpkg.dtd"),
    "scd": ('softwarecomponent', "-//JTRS//DTD SCA V2.2.2 SCD//EN", "softwarecomponent.dtd"),
    "prf": ('properties', "-//JTRS//DTD SCA V2.2.2 PRF//EN", "properties.dtd"),
}


def _serialise(root: etree._Element, kind: str) -> bytes:
    name, public_id, system_id = DOCTYPES[kind]
    doctype = f'<!DOCTYPE {name} PUBLIC "{public_id}" "{system_id}">'
    return etree.tostring(
        root,
        xml_declaration=True,
        encoding="UTF-8",
        doctype=doctype,
        pretty_print=True,
    )


# ---------------------------------------------------------------------------
# PRF -- properties
# ---------------------------------------------------------------------------

def build_prf(comp: Component) -> etree._Element:
    root = etree.Element("properties")

    for p in comp.visible_properties():
        root.append(_simple_element(comp, p))

    return root


def _simple_element(comp: Component, p: Property) -> etree._Element:
    kindtype, mode = mapping.map_kind_and_mode(p)
    sca_type = mapping.map_type(p.type)

    # properties.dtd:
    #   <!ELEMENT simple
    #       ( description?, value?, units?, range?, enumerations?, kind*, action? )>
    el = etree.Element(
        "simple",
        id=mapping.dce_uuid(comp.name, "property", p.name),
        name=p.name,
        type=sca_type,
        mode=mode,
    )

    if p.default is not None:
        etree.SubElement(el, "value").text = p.default

    if p.enums:
        enums_el = etree.SubElement(el, "enumerations")
        for i, name in enumerate(p.enums):
            etree.SubElement(enums_el, "enumeration", label=name, value=str(i))

    etree.SubElement(el, "kind", kindtype=kindtype)
    return el


# ---------------------------------------------------------------------------
# SCD -- ports and component type
# ---------------------------------------------------------------------------

def build_scd(comp: Component) -> etree._Element:
    # softwarecomponent.dtd:
    #   <!ELEMENT softwarecomponent
    #       ( corbaversion, componentrepid, componenttype, componentfeatures,
    #         interfaces, propertyfile? )>
    root = etree.Element("softwarecomponent")

    etree.SubElement(root, "corbaversion").text = "2.2"
    etree.SubElement(root, "componentrepid", repid=mapping.COMPONENT_REPID)
    etree.SubElement(root, "componenttype").text = mapping.map_component_type(comp)

    features = etree.SubElement(root, "componentfeatures")
    # componentfeatures requires supportsinterface* then ports.
    etree.SubElement(
        features,
        "supportsinterface",
        repid=mapping.COMPONENT_REPID,
        supportsname="Resource",
    )
    ports_el = etree.SubElement(features, "ports")

    for port in comp.ports:
        repid = mapping.map_port_repid(port.name, port.protocol)
        if port.producer:
            # OpenCPI output == SCA "uses": it consumes another component's port.
            etree.SubElement(ports_el, "uses", usesname=port.name, repid=repid)
        else:
            etree.SubElement(ports_el, "provides", providesname=port.name, repid=repid)

    # Every repid referenced above must be declared as an interface.
    interfaces_el = etree.SubElement(root, "interfaces")
    _add_interface(interfaces_el, mapping.COMPONENT_REPID, "Resource")
    seen = {mapping.COMPONENT_REPID}
    for port in comp.ports:
        repid = mapping.map_port_repid(port.name, port.protocol)
        if repid not in seen:
            seen.add(repid)
            _add_interface(interfaces_el, repid, repid.split("/")[-1].split(":")[0])

    return root


def _add_interface(parent: etree._Element, repid: str, name: str) -> None:
    el = etree.SubElement(parent, "interface", repid=repid, name=name)
    etree.SubElement(el, "inheritsinterface", repid="IDL:CF/PortSupplier:1.0")


# ---------------------------------------------------------------------------
# SPD -- the package
# ---------------------------------------------------------------------------

def build_spd(
    comp: Component,
    *,
    author: str = "Generated by ocpi2sca",
    prf_filename: str | None = None,
    scd_filename: str | None = None,
) -> etree._Element:
    prf_filename = prf_filename or f"{comp.name}.prf.xml"
    scd_filename = scd_filename or f"{comp.name}.scd.xml"

    # softpkg.dtd:
    #   ( title?, author+, description?, propertyfile?, descriptor?,
    #     implementation+, usesdevice* )
    root = etree.Element(
        "softpkg",
        id=mapping.dce_uuid(comp.name, "softpkg"),
        name=comp.name,
        type="sca_compliant",
    )

    etree.SubElement(root, "title").text = comp.name

    author_el = etree.SubElement(root, "author")
    etree.SubElement(author_el, "name").text = author

    if comp.spec_name:
        etree.SubElement(root, "description").text = (
            f"Generated from OpenCPI component {comp.spec_name}"
        )

    pf = etree.SubElement(root, "propertyfile")
    etree.SubElement(pf, "localfile", name=prf_filename)

    desc = etree.SubElement(root, "descriptor")
    etree.SubElement(desc, "localfile", name=scd_filename)

    # At least one implementation is required by the DTD. With no worker, emit
    # a single placeholder so the descriptor is structurally valid and the gap
    # is visible, rather than silently omitting a required element.
    impls = comp.implementations or [None]
    for impl in impls:
        root.append(_implementation_element(comp, impl))

    return root


def _implementation_element(comp: Component, impl) -> etree._Element:
    impl_id = f"{impl.model}_{impl.worker_name}" if impl else "unspecified"

    # softpkg.dtd implementation:
    #   ( description?, propertyfile?, code, compiler?, programminglanguage?,
    #     humanlanguage?, runtime?, (os | processor | dependency)+,
    #     usesdevice* )
    #
    # Note the '+': at least one os/processor/dependency is REQUIRED.
    el = etree.Element("implementation", id=impl_id)

    code = etree.SubElement(el, "code", type="SharedLibrary")
    # The built artifact path is a packaging concern, not a metadata one --
    # the filename is a convention here, to be confirmed (open question Q6).
    etree.SubElement(code, "localfile", name=f"{comp.name}.so")

    if impl and impl.language:
        etree.SubElement(el, "programminglanguage", name=impl.language.upper())

    # The DTD requires at least one of these. The target OS and processor are
    # properties of a *build*, not of the component metadata we read, so they
    # cannot be derived from the input. Emitting the SCA-conventional values
    # for a Linux RCC worker keeps the descriptor valid; supplying real build
    # targets is part of open question Q6.
    etree.SubElement(el, "os", name="Linux")
    etree.SubElement(el, "processor", name="x86_64")

    return el


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

def emit_all(comp: Component, author: str = "Generated by ocpi2sca") -> dict[str, bytes]:
    """Return {filename: xml bytes} for the full descriptor set."""
    return {
        f"{comp.name}.prf.xml": _serialise(build_prf(comp), "prf"),
        f"{comp.name}.scd.xml": _serialise(build_scd(comp), "scd"),
        f"{comp.name}.spd.xml": _serialise(build_spd(comp, author=author), "spd"),
    }
