#!/usr/bin/env python3
"""Build the self-contained page; no npm, remote fonts, or CDN dependencies."""
from pathlib import Path
import argparse
import json
import os
import tempfile

ROOT = Path(__file__).resolve().parents[1]

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT/"site/index.html")
    parser.add_argument("--embed", type=Path, default=ROOT/"site/data/physics.json",
                        help="Counts snapshot. Demo stays explicitly labeled.")
    args = parser.parse_args()
    template = (ROOT/"scripts/index.template.html").read_text("utf-8")
    css = (ROOT/"scripts/style.css").read_text("utf-8")
    js = (ROOT/"scripts/app.js").read_text("utf-8")
    data = json.loads(args.embed.read_text("utf-8"))
    if data.get("schemaVersion") != 3 or data.get("period") != "month":
        parser.error("Run the Lite update_data.py first (--local-only reuses completed saved data).")
    serialized = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    page = template.replace("/*__CSS__*/", css).replace("/*__JS__*/", js).replace("/*__DATA__*/", serialized)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w",encoding="utf-8",dir=args.output.parent,delete=False) as f:
        f.write(page)
        tmp=f.name
    os.replace(tmp,args.output)
    print(f"Built {args.output} ({len(page.encode('utf-8')):,} bytes, mode={data['mode']})")

if __name__ == "__main__":
    main()
