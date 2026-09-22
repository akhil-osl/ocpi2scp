"""
Intermediate model: the resolved view of an OpenCPI component.

This sits between the reader (which parses OpenCPI XML) and the emitters
(which write SCA descriptors). Neither side knows about the other -- the
reader never mentions SCA, and the emitters never parse OpenCPI XML.

The model is *resolved*: by the time a Component exists, every implicit
OpenCPI default has been applied and every property carries a concrete type.
What the reader inferred rather than read is recorded in `inferences`, so a
defaulted value is never silently indistinguishable from a declared one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Inference:
    """One value the reader supplied that the source XML did not state.

    Recorded rather than applied silently: an inferred type that is wrong
    produces a descriptor that is confidently incorrect, which is worse than
    one that is obviously incomplete.
    """

    subject: str        # what it applies to, e.g. "property biasValue"
    field: str          # which field, e.g. "type"
    value: str          # what was assumed, e.g. "ulong"
    rule: str           # why, e.g. "OpenCPI default for untyped property"

    def __str__(self) -> str:
        return f"{self.subject}: {self.field} not declared, assumed {self.value!r} ({self.rule})"


@dataclass
class Property:
    """A component property, as OpenCPI describes it.

    Field names follow OpenCPI's vocabulary, not SCA's. Translation to SCA
    kind/mode happens in the mapping layer, where it can be justified in one
    place instead of being spread through the reader.
    """

    name: str
    type: str                          # OpenCPI type, lowercased: ulong, bool, string...
    default: Optional[str] = None

    # OpenCPI access attributes. These drive the SCA kind/mode mapping.
    initial: bool = False              # settable before start
    parameter: bool = False            # build-time constant
    volatile: bool = False             # may change underneath the reader
    writable: bool = False             # writable while running
    readable: bool = False

    # Type detail.
    string_length: Optional[int] = None    # for type == string
    sequence_length: Optional[int] = None  # non-None => a sequence
    enums: list[str] = field(default_factory=list)

    # True for OpenCPI's own bookkeeping properties (ocpi_debug, ocpi_endian...).
    hidden: bool = False

    @property
    def is_sequence(self) -> bool:
        return self.sequence_length is not None


@dataclass
class Port:
    """A data port.

    `producer` is OpenCPI's term for an output. SCA calls the two directions
    "uses" and "provides"; that renaming belongs in the mapping layer.
    """

    name: str
    producer: bool = False
    protocol: Optional[str] = None     # protocol name, when the spec names one


@dataclass
class Implementation:
    """One built form of a component: a worker.

    One spec may have several -- an RCC worker in C and an HDL worker in VHDL
    implement the same interface. SCA models this as multiple
    <implementation> elements inside one SPD.
    """

    worker_name: str
    model: str                         # "rcc" or "hdl"
    language: Optional[str] = None     # c, c++, vhdl
    control_operations: list[str] = field(default_factory=list)
    slaves: list[str] = field(default_factory=list)   # proxy workers only


@dataclass
class Component:
    """A resolved OpenCPI component: its spec plus the workers implementing it."""

    name: str
    spec_name: Optional[str] = None    # e.g. "ocpi.core.bias", when known
    properties: list[Property] = field(default_factory=list)
    ports: list[Port] = field(default_factory=list)
    implementations: list[Implementation] = field(default_factory=list)

    # Values the reader supplied that the source did not state.
    inferences: list[Inference] = field(default_factory=list)

    # OpenCPI constructs with no SCA equivalent, dropped but not hidden.
    dropped: list[str] = field(default_factory=list)

    def property_by_name(self, name: str) -> Optional[Property]:
        for p in self.properties:
            if p.name == name:
                return p
        return None

    def visible_properties(self) -> list[Property]:
        """Properties that reach the SCA descriptor.

        OpenCPI's own bookkeeping properties are excluded. That is a policy
        choice, not a fact about the data -- see docs/MAPPING.md.
        """
        return [p for p in self.properties if not p.hidden]
