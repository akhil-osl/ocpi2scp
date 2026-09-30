# SCA → OpenCPI Reverse Generation — Open Questions

Decisions needed for the reverse direction (`ocpi2sca generate --reverse`):
SCA 2.2.2 descriptors (SPD / SCD / PRF) in, an OpenCPI component spec (OCS)
out. Where the generator already makes a provisional choice, the current
behaviour is noted so it can be changed in one place (`mapping.py`).

**Why this direction is harder.** The forward tool (`ocpi2sca generate`) works
because OpenCPI is the more expressive side: SCA is a lossy projection of it,
and every loss is already catalogued in `docs/OPEN-QUESTIONS.md` (Q1–Q7). Going
backward means starting from the lossy side. Nothing here can be more precise
than what was thrown away going forward, and several forward mappings are not
functions with inverses — one SCA `kindtype`/`mode` pair corresponds to more
than one OpenCPI attribute combination. Where that happens, the reverse reader
records an `Inference`, the same as the forward reader does for an untyped
property. A guessed OpenCPI attribute that is wrong produces a spec that is
confidently incorrect, which is worse than one that is visibly incomplete.

---

## RQ1 — Property type: SCA `string` is ambiguous

Forward mapping collapses two OpenCPI types onto one SCA type:

```
TYPE_MAP = { ..., "string": "string", "enum": "string", ... }
```

An SCA `<simple type="string">` could be OpenCPI `string` or OpenCPI `enum`.
The only signal that distinguishes them is `<enumerations>` in the PRF: its
presence means `enum`, its absence means `string`.

**Current behaviour:** `unmap_type` returns `enum` when the `<simple>` element
has an `<enumerations>` child, `string` otherwise. This is a derivation, not a
guess — no inference recorded.

All other SCA property types map onto exactly one OpenCPI type (`TYPE_MAP`
inverted 1:1), so RQ1 is the only ambiguous case in this table.

---

## RQ2 — `kindtype`/`mode` → OpenCPI access attributes

Forward mapping (`map_kind_and_mode`, `mapping.py`):

| OpenCPI | SCA kindtype | SCA mode |
|---|---|---|
| `parameter` | `execparam` | `readonly` |
| `volatile` only | `configure` | `readonly` |
| `initial` or `writable` | `configure` | `readwrite` |
| (none of the above) | `configure` | `readonly` |

This is not invertible. `configure`/`readwrite` could have come from `initial`
alone, `writable` alone, or both together — OpenCPI's own distinction between
"settable before start" and "settable while running" has no SCA-side signal
to recover it from.

**Options**

| | Approach | Trade-off |
|---|---|---|
| **A** | Always assume `writable` for `configure`/`readwrite`, never `initial` | Simple, but a component that only ever meant "settable before start" now looks runtime-settable too. |
| **B** | Always assume `initial` for `configure`/`readwrite` | Mirrors the forward tool's own contested choice (Q3 in the forward doc chose `initial → configure/readwrite`), so round-tripping a component through `ocpi2sca generate` then `--reverse` is closer to identity for components that started as `initial`. |
| **C** | Set both `initial` and `writable` | Recovers the union of legal callers, but is not what any single OpenCPI component actually declares — a fabricated combination. |

**Current behaviour: B**, with an `Inference` recorded every time
(`"kindtype=configure, mode=readwrite: assumed OpenCPI initial, not writable"`).
Chosen for round-trip symmetry with the forward tool's own Q3 choice, not
because it is more likely to be correct — flagged for the team to confirm.

`execparam`/`readonly` → `parameter` and `configure`/`readonly` (with no
writable path) → `volatile` are the only two cases with a single OpenCPI
attribute that produces them, so those are derivations, not inferences.

---

## RQ3 — Port `repid`: recovering a protocol name

Forward mapping synthesises `IDL:ocpi/protocol/<protocol-or-port-name>:1.0`
(Q2 in the forward doc — "the weakest mapping in the whole design"). Reversing
it:

- A repid matching `IDL:ocpi/protocol/<name>:1.0` came from this tool (or one
  following the same convention). `<name>` is recovered as the protocol name,
  derivation not inference.
- Any other repid — `IDL:BULKIO/dataFloat:1.0`, `IDL:CF/Resource:1.0`, a
  hand-written REDHAWK interface — names a real CORBA interface with no
  OpenCPI protocol behind it. There is nothing to recover. OpenCPI has no
  concept of "port implements this IDL interface" to receive it.

**Current behaviour:** repids outside the `IDL:ocpi/protocol/` namespace are
dropped with a warning (`comp.dropped`), and the port is emitted with no
`Protocol=` attribute rather than a fabricated one. This matches the forward
tool's own principle (Q7): drop with a warning, do not invent.

---

## RQ4 — Component identity: UUID has no way back to a name

Forward mapping derives `id="DCE:<uuid>"` deterministically from the component
or property **name** (Q4 in the forward doc, UUIDv5 over a fixed namespace).
UUIDv5 is one-way; the SCA-side `id` cannot be inverted back to anything.

This is not actually a problem in practice: SPD and PRF both carry `name=`
attributes alongside the `id`, and OpenCPI identifies components by name, not
UUID. The reverse reader uses `name=` and ignores `id=` entirely.

**Current behaviour:** OpenCPI component/property names come from SCA `name=`
attributes. The DCE UUIDs are read only far enough to check they parse (for
`validate`-style sanity), never used as a source of the OpenCPI name.

---

## RQ5 — What worker (OWD) do we emit, if any?

SCA has no concept of OpenCPI's worker model: no RCC vs. HDL distinction, no
`language=`, no `<slaves>`, no control-operations list. The forward tool reads
these from the OWD (`_read_worker` in `reader.py`) and folds them into
`Implementation`; going backward there is no SCA element carrying this
information except:

- SPD `<implementation><programminglanguage name="..."/>` — a hint, but SCA
  languages (`C`, `C++`, `Java`, ...) don't map 1:1 onto OpenCPI's `model`
  (`rcc`/`hdl`) — `VHDL`/`Verilog` would imply `hdl`, anything else does not
  reliably imply `rcc`.
- SPD `<implementation><os>`/`<processor>` — build target, not worker model.

**Options**

| | Approach | Trade-off |
|---|---|---|
| **A** | Emit OCS (component spec) only; never emit an OWD | Honest: nothing in SCA reliably determines worker model. Matches "nothing unspecified is invented." |
| **B** | Emit an OWD skeleton with `model` guessed from `programminglanguage` | Produces a plausible-looking file that is frequently wrong for anything not VHDL. |

**Current behaviour: A.** The reverse generator emits only the OCS spec file.
Worker/implementation reconstruction is out of scope for the first slice — see
"Not implemented" below, not a silent gap.

---

## RQ6 — Hidden (`ocpi_*`) properties

The forward tool drops OpenCPI's own bookkeeping properties
(`ocpi_debug`, `ocpi_endian`, `ocpi_version`, ...) before they ever reach SCA
(`Component.visible_properties`, model.py). They are simply never present in
a PRF generated by this tool's own forward path.

A PRF from a different source could coincidentally have a property literally
named `ocpi_something` that means something else entirely in that context.

**Current behaviour:** the reverse reader does not treat any SCA property name
as hidden. Every `<simple>` in the input PRF becomes a visible OpenCPI
property. `hidden` is left `False` unconditionally; there is no SCA-side
signal that would justify guessing otherwise.

---

## RQ7 — `<slaves>`, `buffersize`, and other forward-dropped constructs

Per the forward tool's Q7, these have no SCA representation at all — they were
dropped with a warning before an SCA descriptor was ever written. There is
nothing on the SCA side to read back. This is not an open question so much as
a confirmation: the reverse reader does not attempt to reconstruct them, and
the round-trip test (`ocpi → sca → ocpi`) is expected to lose them, on
purpose, with that loss visible in the test's own diff against the original.

---

## Summary — decisions needed

| # | Question | Recommendation |
|---|---|---|
| RQ1 | SCA `string` → OpenCPI `string` or `enum` | derived from `<enumerations>` presence, not a guess |
| RQ2 | `kindtype`/`mode` → OpenCPI access attribute | **open** — currently assumes `initial` for symmetry with forward Q3, flagged as inference every time |
| RQ3 | Port repid → protocol name | only recoverable inside our own `IDL:ocpi/protocol/` namespace; drop with warning otherwise |
| RQ4 | UUID → component name | not needed; use `name=` directly |
| RQ5 | Worker (OWD) reconstruction | **open** — currently emits OCS only, no OWD, first slice |
| RQ6 | Hidden `ocpi_*` properties | no signal to detect them from SCA alone; none assumed hidden |
| RQ7 | `<slaves>`, `buffersize`, protocol detail | no SCA representation exists; permanently lost, not a bug |

RQ2 and RQ5 are the ones that need a team decision, not a derivation.
