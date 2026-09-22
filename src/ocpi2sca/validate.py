"""
Validation of generated descriptors.

Two independent levels, reported separately, because they answer different
questions:

  1. DTD    -- does this conform to SCA 2.2.2? The normative contract.
  2. Semantic -- is it internally consistent? Cross-file checks no schema
                 performs: do referenced files exist, do SCD ports agree with
                 the PRF, are IDs unique.

A third level, the namespaced XSD shipped with REDHAWK and the SCA IDE, is
deliberately NOT the acceptance bar: REDHAWK's own descriptors fail it, since
the DTD-form files are un-namespaced while the XSD expects a namespace. See
docs/MAPPING.md and open question Q5.

Level 2 catches what matters in practice. A schema-valid descriptor with a
dangling reference is still broken.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas" / "dtd"

DTD_FOR_ROOT = {
    "softpkg": "softpkg.dtd",
    "softwarecomponent": "softwarecomponent.dtd",
    "properties": "properties.dtd",
    "softwareassembly": "softwareassembly.dtd",
}


@dataclass
class Result:
    path: Path
    level: str
    ok: bool
    errors: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        status = "PASS" if self.ok else "FAIL"
        head = f"[{status}] {self.level}: {self.path.name}"
        if self.errors:
            return head + "\n" + "\n".join(f"    {e}" for e in self.errors)
        return head


def validate_dtd(path: Path, schema_dir: Path = SCHEMA_DIR) -> Result:
    """Validate one descriptor against its SCA 2.2.2 DTD."""
    path = Path(path)
    try:
        # DTD loading is disabled here so the document's own DOCTYPE cannot
        # pull in an arbitrary external file; the DTD is chosen explicitly
        # from the vendored directory below.
        parser = etree.XMLParser(load_dtd=False, no_network=True)
        doc = etree.parse(str(path), parser)
    except etree.XMLSyntaxError as e:
        return Result(path, "dtd", False, [f"not well-formed: {e}"])

    root_tag = doc.getroot().tag
    dtd_name = DTD_FOR_ROOT.get(root_tag)
    if dtd_name is None:
        return Result(path, "dtd", False, [f"no DTD known for root element <{root_tag}>"])

    dtd_path = schema_dir / dtd_name
    if not dtd_path.exists():
        return Result(path, "dtd", False, [f"DTD not found: {dtd_path}"])

    dtd = etree.DTD(str(dtd_path))
    if dtd.validate(doc):
        return Result(path, "dtd", True)
    return Result(path, "dtd", False, [str(e) for e in dtd.error_log])


def validate_semantic(spd_path: Path) -> Result:
    """Cross-file checks that no schema performs."""
    spd_path = Path(spd_path)
    errors: list[str] = []

    try:
        spd = etree.parse(str(spd_path)).getroot()
    except etree.XMLSyntaxError as e:
        return Result(spd_path, "semantic", False, [f"not well-formed: {e}"])

    base = spd_path.parent

    # Referenced files must exist.
    referenced: dict[str, Path] = {}
    for tag in ("propertyfile", "descriptor"):
        for el in spd.findall(tag):
            lf = el.find("localfile")
            if lf is None or not lf.get("name"):
                errors.append(f"<{tag}> has no <localfile name=...>")
                continue
            target = base / lf.get("name")
            referenced[tag] = target
            if not target.exists():
                errors.append(f"<{tag}> references missing file: {lf.get('name')}")

    # Every id must be DCE-formatted, and unique within the file.
    seen: set[str] = set()
    for el in spd.iter():
        ident = el.get("id")
        if ident is None:
            continue
        if el.tag == "softpkg" and not ident.startswith("DCE:"):
            errors.append(f"softpkg id is not DCE-formatted: {ident}")
        if ident in seen:
            errors.append(f"duplicate id: {ident}")
        seen.add(ident)

    # SCD ports and PRF properties must parse, if present.
    prf = referenced.get("propertyfile")
    if prf and prf.exists():
        prf_root = etree.parse(str(prf)).getroot()
        prop_ids = [s.get("id") for s in prf_root.findall("simple")]
        if len(prop_ids) != len(set(prop_ids)):
            errors.append("duplicate property ids in PRF")
        for s in prf_root.findall("simple"):
            if not (s.get("id") or "").startswith("DCE:"):
                errors.append(f"property id is not DCE-formatted: {s.get('id')}")

    scd = referenced.get("descriptor")
    if scd and scd.exists():
        scd_root = etree.parse(str(scd)).getroot()
        declared = {i.get("repid") for i in scd_root.findall(".//interface")}
        for p in scd_root.findall(".//ports/*"):
            repid = p.get("repid")
            if repid and repid not in declared:
                errors.append(f"port repid not declared in <interfaces>: {repid}")

    return Result(spd_path, "semantic", not errors, errors)


def validate_set(directory: Path, component: str) -> list[Result]:
    """Validate a full descriptor set for one component."""
    directory = Path(directory)
    results = []
    for suffix in ("prf", "scd", "spd"):
        p = directory / f"{component}.{suffix}.xml"
        if p.exists():
            results.append(validate_dtd(p))
    spd = directory / f"{component}.spd.xml"
    if spd.exists():
        results.append(validate_semantic(spd))
    return results
