"""One-shot, model-free fixture assessment. No writes to business state."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

from .evidence import assess_evidence, utc_timestamp


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--as-of", help="Explicit UTC clock for reproducible fixture replay")
    parser.add_argument("--output", type=Path, help="New assessment artifact; refuses overwrite")
    args = parser.parse_args(argv)
    try:
        raw = args.fixture.read_bytes()
        fixture = json.loads(raw)
        if fixture["schema_version"] != 1:
            raise ValueError("unsupported fixture schema_version")
        now = utc_timestamp(args.as_of) if args.as_of else datetime.now(timezone.utc)
        result = assess_evidence(
            fixture["observations"], order_id=fixture["order_id"],
            supported_case=fixture["supported_case"], now=now,
            trusted_sources=fixture["trusted_sources"],
            max_age_seconds=fixture["max_age_seconds"],
        )
        artifact = {
            "schema_version": 1, "kind": "commerce_evidence_assessment",
            "order_id": fixture["order_id"], "as_of": now.isoformat(),
            "fixture_sha256": hashlib.sha256(raw).hexdigest(),
            **result,
        }
        rendered = json.dumps(artifact, indent=2) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as output:
                output.write(rendered)
        print(rendered, end="")
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"event": "input_error", "error": str(error)}), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
