"""
Mapping: OpenCPI concepts -> SCA concepts.

Every judgement call in the generator lives here, in one file, so each one
can be found, argued with, and changed in a single place. The reader knows
no SCA; the emitters make no decisions.

The rationale for each mapping is in docs/MAPPING.md. Where a mapping is a
policy choice rather than a derivation, it says so, and the corresponding
open question is named.
"""
from __future__ import annotations

import uuid
from typing import Optional

from .model import Component, Inference, Property

# A fixed namespace so that the same component always yields the same UUID.
#
# SCA identifies things by DCE UUID; OpenCPI identifies them by name. A random
# UUID per run would change a component's identity on every regeneration and
# break any assembly referencing it, so IDs are derived deterministically from
# the component or property name (open question Q4).
OCPI2SCA_NAMESPACE = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")


def dce_uuid(*parts: str) -> str:
    """Deterministic DCE-formatted UUID from stable name parts."""
    return "DCE:" + str(uuid.uuid5(OCPI2SCA_NAMESPACE, ":".join(parts)))


# ---------------------------------------------------------------------------
# Type mapping
# ---------------------------------------------------------------------------
#
# OpenCPI type names, lowercased by the reader, to SCA property types.
# SCA 2.2.2 property types are drawn from the CORBA basic types.
TYPE_MAP = {
    "bool":      "boolean",
    "boolean":   "boolean",
    "char":      "char",
    "uchar":     "octet",
    "short":     "short",
    "ushort":    "ushort",
    "long":      "long",
    "ulong":     "ulong",
    "longlong":  "longlong",
    "ulonglong": "ulonglong",
    "float":     "float",
    "double":    "double",
    "string":    "string",
    # SCA has no enumerated type. An enum becomes a string; the permitted
    # values are carried as <enumerations> in the PRF.
    "enum":      "string",
}


class UnmappableType(Exception):
    """Raised for an OpenCPI type with no SCA equivalent.

    Deliberately fatal rather than defaulted: emitting the wrong type silently
    produces a descriptor that is confidently incorrect.
    """


def map_type(ocpi_type: str) -> str:
    try:
        return TYPE_MAP[ocpi_type.lower()]
    except KeyError:
        raise UnmappableType(
            f"OpenCPI type {ocpi_type!r} has no SCA equivalent defined in TYPE_MAP"
        ) from None


# ---------------------------------------------------------------------------
# Property kind and mode
# ---------------------------------------------------------------------------
#
# POLICY, not derivation -- see open question Q3. OpenCPI's access attributes
# and SCA's kind/mode do not correspond one to one.
#
#   parameter  build-time constant       -> execparam, readonly
#   volatile   changes underneath us     -> configure, readonly
#   initial    settable before start     -> configure, readwrite
#   writable   settable while running    -> configure, readwrite
#
# `initial` is the contested one: it could equally map to execparam, since
# OpenCPI applies it before the worker starts. `configure` is chosen because
# SCA's configure() is the normal route for setting a component's properties,
# and execparam is narrower -- values passed on the command line at launch.
# Flagged in Q3 for the team to confirm.

def map_kind_and_mode(p: Property) -> tuple[str, str]:
    """Return (kindtype, mode) for a property."""
    if p.parameter:
        return "execparam", "readonly"
    if p.volatile and not (p.writable or p.initial):
        return "configure", "readonly"
    if p.writable or p.initial:
        return "configure", "readwrite"
    if p.volatile:
        # Both volatile and settable: readable and writable at runtime.
        return "configure", "readwrite"
    return "configure", "readonly"


# ---------------------------------------------------------------------------
# Component type
# ---------------------------------------------------------------------------
#
# SCA distinguishes a `resource` (ordinary processing component) from a
# `device` (one that owns and allocates hardware). OpenCPI does not label
# workers this way.
#
# Current rule: everything is a `resource`. A proxy worker with <slaves>
# arguably owns hardware and could be a `device`, but that is a decision the
# team has not made -- open question Q8. Until then, the conservative choice
# is the one that claims less.

def map_component_type(comp: Component) -> str:
    return "resource"


# ---------------------------------------------------------------------------
# Port interface IDs
# ---------------------------------------------------------------------------
#
# THE WEAKEST MAPPING IN THE GENERATOR -- open question Q2.
#
# SCA inherits from CORBA: every port carries an interface repository ID
# naming an interface defined in an IDL file, e.g.
#
#     repid="IDL:BULKIO/dataFloat:1.0"
#
# OpenCPI has no CORBA and no IDL. `stream32` is an OpenCPI protocol, not a
# CORBA interface, so there is no correct value to emit.
#
# What this does: synthesise a repid in a private namespace from the protocol
# name, or from the port name when the protocol is unresolved. It is
# deterministic and consistent, but it names an interface that no IDL file
# defines. Anything consuming these descriptors must understand that.
#
# The alternatives, neither obviously better:
#   - map onto a standard interface set such as BULKIO where the data shape
#     fits, which is interoperable but is sometimes a false claim;
#   - define and publish our own IDL, which is honest but is a larger
#     commitment than a generator.

PORT_REPID_NAMESPACE = "IDL:ocpi/protocol"


def map_port_repid(port_name: str, protocol: Optional[str]) -> str:
    basis = protocol or port_name
    return f"{PORT_REPID_NAMESPACE}/{basis}:1.0"


# The component's own interface. A plain SCA resource implements CF::Resource.
COMPONENT_REPID = "IDL:CF/Resource:1.0"


# ===========================================================================
# Reverse mapping: SCA -> OpenCPI
# ===========================================================================
#
# See docs/OPEN-QUESTIONS-REVERSE.md. The forward mappings above are mostly
# not invertible -- SCA is the lossy side, so several OpenCPI states collapse
# onto one SCA state. Where that happens, the function returns its best
# choice AND an Inference recording that the value was assumed rather than
# derived, the same discipline the forward reader uses for an untyped
# property. A guessed OpenCPI attribute that is wrong produces a spec that is
# confidently incorrect, which is worse than one that is visibly incomplete.


# TYPE_MAP inverted. 1:1 except "string", which is ambiguous -- see
# unmap_type below (RQ1).
_REVERSE_TYPE_MAP = {v: k for k, v in TYPE_MAP.items() if k != "enum"}


def unmap_type(sca_type: str, *, has_enumerations: bool = False) -> str:
    """SCA property type -> OpenCPI type.

    RQ1: SCA has no enumerated type, so both OpenCPI 'string' and OpenCPI
    'enum' were mapped to SCA 'string' going forward. The PRF's own
    <enumerations> element is the one signal that tells them apart -- its
    presence means the property was an enum, so this is a derivation, not a
    guess. Every other SCA type maps onto exactly one OpenCPI type.
    """
    if sca_type == "string":
        return "enum" if has_enumerations else "string"
    try:
        return _REVERSE_TYPE_MAP[sca_type]
    except KeyError:
        raise UnmappableType(
            f"SCA type {sca_type!r} has no OpenCPI equivalent defined in TYPE_MAP"
        ) from None


def unmap_kind_and_mode(
    kindtype: str, mode: str, subject: str
) -> tuple[dict, list[Inference]]:
    """SCA (kindtype, mode) -> OpenCPI access attribute flags.

    RQ2: 'configure'/'readwrite' is genuinely ambiguous -- it could have come
    from 'initial' alone, 'writable' alone, or both. There is no SCA-side
    signal that recovers OpenCPI's own distinction between "settable before
    start" and "settable while running".

    Current choice: assume 'initial', for symmetry with the forward tool's
    own contested choice in Q3 (initial -> configure/readwrite), so a
    component that round-trips through generate then --reverse lands close
    to where it started. This is a policy pick, not a derivation -- flagged
    as an Inference every time it applies, not asserted silently.

    'execparam'/'readonly' -> parameter, and 'configure'/'readonly' -> a bare
    volatile with no write path, are each produced by exactly one OpenCPI
    attribute, so those two cases are derivations and carry no Inference.
    """
    flags = {"parameter": False, "volatile": False, "initial": False, "writable": False}
    inferences: list[Inference] = []

    if kindtype == "execparam" and mode == "readonly":
        flags["parameter"] = True
    elif kindtype == "configure" and mode == "readonly":
        flags["volatile"] = True
    elif kindtype == "configure" and mode == "readwrite":
        flags["initial"] = True
        inferences.append(
            Inference(
                subject=subject,
                field="initial/writable",
                value="initial",
                rule=(
                    "kindtype=configure, mode=readwrite has no unique OpenCPI "
                    "source; assumed 'initial' rather than 'writable' for "
                    "symmetry with the forward tool's own Q3 choice"
                ),
            )
        )
    else:
        raise UnmappableType(
            f"SCA (kindtype={kindtype!r}, mode={mode!r}) has no OpenCPI "
            f"equivalent defined in unmap_kind_and_mode"
        )

    return flags, inferences


def unmap_port_repid(repid: str) -> Optional[str]:
    """SCA port repid -> OpenCPI protocol name, where recoverable.

    RQ3: only repids in this tool's own synthesised namespace
    (IDL:ocpi/protocol/<name>:1.0) name an OpenCPI protocol at all -- that
    case is a derivation. Anything else (IDL:BULKIO/..., IDL:CF/Resource:1.0,
    a hand-written REDHAWK interface) names a real CORBA interface with
    nothing behind it on the OpenCPI side; there is no protocol name to
    recover, so this returns None rather than fabricating one.
    """
    prefix = f"{PORT_REPID_NAMESPACE}/"
    suffix = ":1.0"
    if repid.startswith(prefix) and repid.endswith(suffix):
        return repid[len(prefix): -len(suffix)]
    return None
