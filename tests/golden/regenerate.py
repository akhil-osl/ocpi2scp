#!/usr/bin/env python3
"""
Regenerate the golden reference descriptors in tests/golden/expected/.

Run this only when a change to the generator is INTENDED, then review the
resulting diff before committing. The whole point of the golden files is that
an unintended change shows up as a diff someone has to look at.

    python tests/golden/regenerate.py
    git diff tests/golden/expected/
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from ocpi2sca import emit                     # noqa: E402
from ocpi2sca.reader import read_component    # noqa: E402

CORPUS = ROOT / "corpus" / "opencpi"
EXPECTED = Path(__file__).parent / "expected"

COMPONENTS = [
    ("bias", "bias_spec.xml", "bias.xml"),
    ("file_read", "file_read_spec.xml", "file_read.xml"),
    ("file_write", "file_write_spec.xml", "file_write.xml"),
    ("dgrdma_config_proxy", "dgrdma_config_proxy-spec.xml", "dgrdma_config_proxy.xml"),
]


def main() -> int:
    EXPECTED.mkdir(parents=True, exist_ok=True)

    for name, spec, worker in COMPONENTS:
        comp = read_component(CORPUS / name / spec, CORPUS / name / worker)
        for filename, content in emit.emit_all(comp).items():
            (EXPECTED / filename).write_bytes(content)
            print(f"wrote {EXPECTED / filename}")

    print("\nReview the diff before committing:  git diff tests/golden/expected/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
