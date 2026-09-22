#!/usr/bin/env python3
"""Compare two resolved repo manifests independently of XML serialization."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


class ManifestError(RuntimeError):
    pass


def normalized(element: ET.Element) -> tuple:
    """Return a hashable representation with unordered attributes/children."""
    return (
        element.tag,
        tuple(sorted(element.attrib.items())),
        (element.text or "").strip(),
        tuple(sorted((normalized(child) for child in element), key=repr)),
    )


def load(path: Path) -> Counter:
    if path.is_symlink() or not path.is_file():
        raise ManifestError(f"missing or unsafe manifest: {path}")
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as error:
        raise ManifestError(f"invalid XML in {path}: {error}") from error
    if root.tag != "manifest" or (root.text or "").strip():
        raise ManifestError(f"unexpected manifest root: {path}")
    return Counter(normalized(child) for child in root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("expected", type=Path)
    parser.add_argument("actual", type=Path)
    args = parser.parse_args()
    expected = load(args.expected)
    actual = load(args.actual)
    if actual != expected:
        missing = sum((expected - actual).values())
        unexpected = sum((actual - expected).values())
        raise ManifestError(
            "resolved manifests differ semantically: "
            f"missing elements={missing}, unexpected elements={unexpected}"
        )
    print(
        "PASS: resolved manifests are semantically identical "
        f"({sum(expected.values())} top-level elements)"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ManifestError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
