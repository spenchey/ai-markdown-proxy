#!/usr/bin/env python3
"""Copy the validated DealerOn handoff files into the deployable proxy image."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


SITE_SLUGS = ("motorinnautogroup", "motorinnofcarroll", "motorinntoyotaofcarroll")
FILES = ("llms.txt", "llms-full.txt", "dealership.md", "contact-hours.md", "service.md", "finance-trade.md", "policies.md")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "content")
    args = parser.parse_args()
    records = []
    for slug in SITE_SLUGS:
        source_dir = args.source / "sites" / slug / "publish-root"
        target_dir = args.output / slug
        target_dir.mkdir(parents=True, exist_ok=True)
        for filename in FILES:
            source = source_dir / filename
            if not source.is_file():
                raise SystemExit(f"missing validated file: {source}")
            target = target_dir / filename
            shutil.copy2(source, target)
            records.append({"site": slug, "file": filename, "sha256": sha256(target)})
    manifest = {
        "schema": "motorinn.aiReadableContentManifest.v1",
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "sourcePackage": args.source.name,
        "files": records,
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok", "files": len(records), "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
