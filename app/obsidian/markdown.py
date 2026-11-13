"""Convert NormalizedDocument payloads into Obsidian-compatible Markdown."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.schemas.document import NormalizedDocument


def safe_filename(value: str, *, fallback: str = "untitled") -> str:
    """Return a portable filename stem without path or control characters."""
    stem = Path(value).stem
    stem = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "-", stem)
    stem = re.sub(r"\s+", " ", stem).strip(" .-_")
    return (stem[:120] or fallback).strip()


def _yaml_string(value: str) -> str:
    """JSON quoted strings are valid YAML scalars and safely escape special text."""
    return json.dumps(value, ensure_ascii=False)


def _yaml_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return _yaml_string(str(value))


def _flatten_sections(sections: list[Any], depth: int = 0) -> list[str]:
    lines: list[str] = []
    for section in sections:
        title = str(section.title).replace("\n", " ").strip()
        lines.append(f'{"  " * depth}- {title} (level {section.level})')
        lines.extend(_flatten_sections(section.children, depth + 1))
    return lines


def _render_tables(document: NormalizedDocument) -> str:
    rendered: list[str] = []
    for index, table in enumerate(document.tables, start=1):
        title = table.name or f"Table {index}"
        rendered.extend([f"### {title}", ""])
        headers = table.headers
        rows = table.rows
        if not headers and table.records:
            headers = list(table.records[0].keys())
            rows = [[record.get(header, "") for header in headers] for record in table.records]
        if headers:
            rendered.append("| " + " | ".join(str(v).replace("|", "\\|").replace("\n", " ") for v in headers) + " |")
            rendered.append("| " + " | ".join("---" for _ in headers) + " |")
            for row in rows:
                values = [str(v).replace("|", "\\|").replace("\n", " ") for v in row]
                values = (values + [""] * len(headers))[: len(headers)]
                rendered.append("| " + " | ".join(values) + " |")
        else:
            rendered.append(f"_Table contains {table.row_count} rows and {table.column_count} columns._")
        if table.truncated:
            rendered.append(f"\n> [!warning] Table truncated: {table.total_row_count or table.row_count} total rows.")
        rendered.append("")
    return "\n".join(rendered).strip()


class MarkdownNoteBuilder:
    """Build deterministic notes while preserving extracted source text."""

    def build(self, document: NormalizedDocument, *, note_status: str = "ingested") -> str:
        title = document.metadata.title or Path(document.filename).stem
        timestamp = document.ingested_at.astimezone(timezone.utc).isoformat()
        tags = ["memoria/raw-document", document.document_type.value]
        fields = {
            "title": title,
            "document_id": document.document_id,
            "source_filename": document.source.filename,
            "document_type": document.document_type.value,
            "content_hash": document.source.content_hash,
            "agent": document.agent,
            "extraction_status": document.status.value,
            "ingestion_status": note_status,
            "ingested_at": timestamp,
            "source_mime_type": document.source.mime_type,
            "source_byte_size": document.source.byte_size,
        }
        frontmatter = ["---"]
        for key, value in fields.items():
            frontmatter.append(f"{key}: {_yaml_value(value)}")
        frontmatter.append("tags:")
        frontmatter.extend(f"  - {_yaml_string(tag)}" for tag in tags)
        frontmatter.append("---")

        sections = _flatten_sections(document.sections)
        lines = [
            *frontmatter,
            "",
            f"# {title}",
            "",
            "## Document information",
            "",
            f"- **Source:** {document.source.filename}",
            f"- **Format:** {document.document_type.value}",
            f"- **Pages:** {document.metadata.page_count if document.metadata.page_count is not None else 'Not applicable'}",
            f"- **Words:** {document.metadata.word_count}",
            f"- **Chunks:** {document.metadata.chunk_count}",
            f"- **Extractor:** {document.metadata.extractor_name}",
            "",
            "## Extracted content",
            "",
            document.content.rstrip(),
        ]
        if document.tables:
            lines.extend(["", "## Extracted tables", "", _render_tables(document)])
        if sections:
            lines.extend(["", "## Document section outline", "", *sections])
        lines.extend([
            "",
            "## Source provenance",
            "",
            f"- **Document ID:** `{document.document_id}`",
            f"- **Content hash:** `{document.source.content_hash}`",
            f"- **Original byte size:** {document.source.byte_size}",
            f"- **Ingested at:** {timestamp}",
            f"- **Reader agent:** {document.agent}",
            f"- **Schema version:** {document.schema_version}",
        ])
        if document.extraction_warnings:
            lines.extend(["", "## Extraction warnings", ""])
            lines.extend(f"- {warning}" for warning in document.extraction_warnings)
        lines.append("")
        return "\n".join(lines)
