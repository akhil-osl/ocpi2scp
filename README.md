# ocpi2sca

Generate SCA 2.2.2 descriptors (SPD / SCD / PRF) from OpenCPI component
metadata, and the reverse: an OpenCPI component spec (OCS) from existing SCA
descriptors.

**Status: working first slice, both directions.** Forward produces DTD-valid
descriptors from real OpenCPI components. Reverse (`--reverse`) produces an
OCS from an SPD/SCD/PRF set — properties and ports only; see
[Reverse: SCA to OpenCPI](#reverse-sca-to-opencpi). Several mapping decisions
are provisional in both directions — see [Open questions](#open-questions).

---

## Quick start

```bash
./setup-venv.sh
source .venv/bin/activate
```

Then:

```bash
ocpi2sca generate path/to/mycomp_spec.xml -o out/
```

Against a component from the bundled corpus:

```bash
$ ocpi2sca generate corpus/opencpi/bias/bias_spec.xml -o out/
warning: property biasValue: type not declared, assumed 'ulong' (OpenCPI default ...)
warning: dropped -- port in: protocol include 'stream32_protocol.xml' not resolved ...
wrote out/bias.prf.xml
wrote out/bias.scd.xml
wrote out/bias.spd.xml

[PASS] dtd: bias.prf.xml
[PASS] dtd: bias.scd.xml
[PASS] dtd: bias.spd.xml
[PASS] semantic: bias.spd.xml
```

The worker descriptor is found automatically beside the spec; override with
`--worker`. Validate an existing set with `ocpi2sca validate <dir> <name>`.

---

## What it does

```
  specs/bias_spec.xml   (OCS — what the component is)
  bias.rcc/bias.xml     (OWD — how it is built)
             │
             ▼
        ┌─────────┐
        │ reader  │  parse, merge specproperty, apply OpenCPI defaults
        └────┬────┘
             ▼
        Component model  (fully typed, inferences recorded)
             │
        ┌────▼────┐
        │ mapping │  OpenCPI concepts → SCA concepts
        └────┬────┘   types, kind/mode, UUIDs, port repids
             ▼
        ┌─────────┐
        │  emit   │  XML in DTD element order, with DOCTYPE
        └────┬────┘
             ▼
  bias.spd.xml   bias.scd.xml   bias.prf.xml
             │
        ┌────▼─────┐
        │ validate │  DTD + semantic
        └──────────┘
```

Every judgement call lives in `mapping.py`. The reader knows no SCA; the
emitters make no decisions.

---

## Worked example

Input — everything OpenCPI states about `bias`:

```xml
<!-- bias_spec.xml -->
<ComponentSpec>
  <Property Name="biasValue" Initial="true"/>
  <DataInterfaceSpec Name="in"><include href="stream32_protocol.xml"/></DataInterfaceSpec>
  <DataInterfaceSpec Name="out" Producer="true"/>
</ComponentSpec>

<!-- bias.xml -->
<RccWorker name='bias' language='c' spec='bias_spec.xml'/>
```

Output — `bias.prf.xml`:

```xml
<!DOCTYPE properties PUBLIC "-//JTRS//DTD SCA V2.2.2 PRF//EN" "properties.dtd">
<properties>
  <simple id="DCE:da331a3a-..." name="biasValue" type="ulong" mode="readwrite">
    <kind kindtype="configure"/>
  </simple>
</properties>
```

Note `type`, `id`, `mode` and `kindtype` appear nowhere in the input. Supplying
them is the substance of the tool.

---

## Inference is never silent

`biasValue` is declared with no type. OpenCPI's rule is that an untyped
property is `ulong` — confirmed by OpenCPI's own generated header for this
worker:

```c
const uint32_t biasValue;    /* uint32_t == ulong */
```

The tool applies the same default **and says so**:

```
warning: property biasValue: type not declared, assumed 'ulong'
         (OpenCPI default for a property declared without Type)
```

Same for OpenCPI constructs with no SCA equivalent — `<slaves>`, unresolved
protocol includes. They are dropped, and reported. An assumption that is wrong
produces a descriptor that is confidently incorrect, which is worse than one
that is visibly incomplete.

---

## Validation

Two levels, reported separately:

| Level | What it checks | Bar |
|---|---|---|
| **DTD** | conformance to SCA 2.2.2 | must pass |
| **Semantic** | referenced files exist, SCD repids declared, IDs unique and DCE-formatted | must pass |

A third level — the namespaced XSD shipped with REDHAWK and the SCA IDE — is
**not** the acceptance bar. REDHAWK's own `GPP.spd.xml` passes DTD validation
and fails XSD validation:

```
Element 'softpkg': No matching global declaration available for the validation root.
```

because the DTD-form descriptors are un-namespaced while the XSD expects a
namespace. SCA 2.2.2 is DTD-defined; the XSD is a separate EMF-tooling dialect.
See open question Q5.

---

## Corpus

Real OpenCPI components, used as test input:

| Component | Exercises |
|---|---|
| `bias` | untyped property, two ports, protocol include |
| `file_read` / `file_write` | string with `stringLength`, bool, uchar, mixed-case types, `specproperty` merge |
| `dgrdma_config_proxy` | 22 properties, `<slaves>`, no ports |

---

## Reverse: SCA to OpenCPI

```bash
ocpi2sca generate --reverse path/to/mycomp.spd.xml -o out/
```

Companion SCD/PRF files are found beside the SPD by convention (from its own
`<descriptor>`/`<propertyfile>` elements), or given explicitly:

```bash
ocpi2sca generate -r mycomp.spd.xml --scd mycomp.scd.xml --prf mycomp.prf.xml -o out/
```

This writes `<name>_spec.xml` (an OCS) only — no worker descriptor. SCA
carries no reliable signal for OpenCPI's worker model (RCC vs HDL, language,
`<slaves>`, control operations), so nothing is fabricated to fill that gap;
see [`docs/OPEN-QUESTIONS-REVERSE.md`](docs/OPEN-QUESTIONS-REVERSE.md) RQ5.

SCA is the lossy side of the forward mapping, so reversing it means some
OpenCPI-side detail cannot be recovered, only guessed at with the guess
flagged:

```
$ ocpi2sca generate -r tests/golden/expected/bias.spd.xml -o out/
warning: property biasValue: initial/writable not declared, assumed 'initial' (kindtype=configure, mode=readwrite has no unique OpenCPI source; assumed 'initial' rather than 'writable' for symmetry with the forward tool's own Q3 choice)
wrote out/bias_spec.xml
```

A port `repid` only yields a protocol name when it was generated by this
tool's own forward path (`IDL:ocpi/protocol/<name>:1.0`); any other repid —
`BULKIO`, a hand-written REDHAWK interface — names a real CORBA interface with
nothing behind it on the OpenCPI side, and is dropped with a warning rather
than guessed.

Full accounting of every reverse-direction judgement call, resolved and
open, is in
[`docs/OPEN-QUESTIONS-REVERSE.md`](docs/OPEN-QUESTIONS-REVERSE.md).

## Open questions

Provisional decisions, listed in
[`docs/OPEN-QUESTIONS.md`](docs/OPEN-QUESTIONS.md) (forward direction) and
[`docs/OPEN-QUESTIONS-REVERSE.md`](docs/OPEN-QUESTIONS-REVERSE.md) (reverse
direction). The load-bearing one, forward:

**Port `repid`.** SCA inherits CORBA: every port names an IDL interface. OpenCPI
has neither. The tool synthesises `IDL:ocpi/protocol/<name>:1.0` — deterministic
and consistent, but it names an interface no IDL file defines. There is no
correct answer here, only a decision to be defended.

Also open: whether `initial` should map to `configure` or `execparam`, how
`os`/`processor` are supplied, and whether a proxy worker with slaves is an SCA
`device` rather than a `resource`.

---

## Not implemented

- **SAD** (assembly descriptors) — needs OpenCPI application XML, a different input
- **Protocol include resolution** — `<include href=>` is reported, not chased
- **Spec search path** — spec and worker must be given directly
- **Multiple implementations per SPD** — one is emitted; `os`/`processor` are
  conventional placeholders, not derived from a build

---

## Development

With the venv active:

```bash
pytest -q                        # 49 tests
```

Golden-file tests hold the generated output against committed references, so an
unintended change shows up as a diff rather than passing silently. When a change
is intended:

```bash
python tests/golden/regenerate.py
git diff tests/golden/expected/      # review before committing
```

```
src/ocpi2sca/
  model.py      Component / Property / Port / Inference
  reader.py     OpenCPI XML → model
  mapping.py    every judgement call, in one place
  emit.py       model → SCA XML (DTD element order matters)
  validate.py   DTD + semantic
  cli.py
schemas/dtd/    SCA 2.2.2 DTDs, vendored
corpus/opencpi/ real components as test input
tests/unit/     reader, mapping, emitter, validation
tests/golden/   generated output vs committed references
```
