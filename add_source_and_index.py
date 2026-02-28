from __future__ import annotations

import json
from pathlib import Path


def main() -> None:
    base = Path(__file__).resolve().parent
    path = base / "tanjing.json"

    data = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(data, list):
        for idx, item in enumerate(data, start=1):
            if isinstance(item, dict):
                item["source"] = "liuzutanjing"
                item["index"] = idx
    else:
        raise TypeError("Expected top-level JSON array in tanjing.json")

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

