"""Ingest a NormalizedDocument JSON export into a local Obsidian vault."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.obsidian.writer import ObsidianWriter


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Write a MemoriaOS NormalizedDocument JSON file into Obsidian."
    )
    parser.add_argument("json_file", type=Path, help="Path to the Agent 01 JSON response.")
    args = parser.parse_args()

    payload = json.loads(args.json_file.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "output" in payload:
        payload = payload["output"]
    if not isinstance(payload, dict):
        parser.error("Input JSON must contain a NormalizedDocument object.")

    result = ObsidianWriter.from_env().ingest(payload)
    print(f"Status: {result.status}")
    print(f"Document ID: {result.document_id}")
    print(f"Obsidian note: {result.vault_relative_path}")


if __name__ == "__main__":
    main()
