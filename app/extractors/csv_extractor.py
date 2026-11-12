"""Independent CSV extractor powered by Pandas with type inference and configurable row limits."""

from __future__ import annotations

import csv
import io
import re
import time
from pathlib import Path

import pandas as pd

from app.core.exceptions import (
    CorruptedDocumentError,
    EmptyDocumentError,
    ExtractionError,
)
from app.extractors.base import (
    BaseExtractor,
    ExtractedContent,
    ExtractionContext,
    RawBlock,
    RawStatistics,
    RawTable,
)
from app.schemas.common import BlockType, DocumentFormat
from app.utils.file_utils import sanitize_error_reason
from app.utils.text_utils import count_lines, count_words, decode_text_bytes

_INT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(r"^[+-]?(\d+\.\d*|\.\d+)([eE][+-]?\d+)?$")
_BOOL_VALS = {"true", "false", "yes", "no"}


class CsvExtractor(BaseExtractor):
    """Extracts columns, inferred data types, records, row counts, and bounded rows from CSV files."""

    name = "pandas_csv_extractor"
    supported_format = DocumentFormat.CSV
    supported_extensions = (".csv",)
    supported_mime_types = ("text/csv", "application/csv")
    supports_tables = True
    ocr_fallback_ready = False

    def extract(
        self,
        file_path: Path,
        context: ExtractionContext,
    ) -> ExtractedContent:
        """Parse CSV via Pandas, infer column data types, preserve records, and enforce row limits."""
        started = time.perf_counter()
        self.validate_file(file_path, context)

        try:
            raw_bytes = file_path.read_bytes()
        except OSError as exc:
            raise ExtractionError(
                f"Failed to read CSV file '{file_path.name}'.",
                details={"reason": sanitize_error_reason(exc, replacement_name=file_path.name)},
            ) from exc

        decoded_text, encoding, warnings = decode_text_bytes(
            raw_bytes, preferred=context.default_encoding
        )
        if not decoded_text.strip():
            raise EmptyDocumentError(f"CSV document '{file_path.name}' is empty.")

        delimiter = self._sniff_delimiter(decoded_text[:8192])
        self._validate_csv_structure(
            decoded_text,
            delimiter=delimiter,
            filename=file_path.name,
        )

        try:
            df = pd.read_csv(
                io.StringIO(decoded_text),
                sep=delimiter,
                dtype=str,
                keep_default_na=False,
                index_col=False,
                on_bad_lines="error",
            )
        except pd.errors.EmptyDataError as exc:
            raise EmptyDocumentError(
                f"CSV document '{file_path.name}' contains no rows or columns."
            ) from exc
        except pd.errors.ParserError as exc:
            raise CorruptedDocumentError(
                f"Malformed CSV syntax in '{file_path.name}'.",
                details={"reason": sanitize_error_reason(exc, replacement_name=file_path.name)},
            ) from exc
        except Exception as exc:
            raise ExtractionError(
                f"Unexpected error while parsing CSV '{file_path.name}'.",
                details={"reason": sanitize_error_reason(exc, replacement_name=file_path.name)},
            ) from exc

        headers = [str(col).strip() for col in df.columns.tolist()]
        if not headers:
            raise EmptyDocumentError(
                f"CSV document '{file_path.name}' contains no column headers."
            )

        total_row_count = int(len(df.index))
        row_limit = max(1, context.csv_max_rows)
        truncated = total_row_count > row_limit
        if truncated:
            warnings.append(
                f"CSV row count ({total_row_count}) exceeded configured limit ({row_limit}); truncated to {row_limit} rows."
            )
            df = df.iloc[:row_limit]

        column_types = {
            header: self._infer_column_type(df.iloc[:, idx].tolist())
            for idx, header in enumerate(headers)
        }
        missing_value_counts = {
            header: sum(
                1 for val in df.iloc[:, idx].tolist() if self._is_missing_value(val)
            )
            for idx, header in enumerate(headers)
        }
        if total_row_count == 0:
            warnings.append("CSV contains column headers but zero data rows.")

        rows = [
            [str(cell).strip() for cell in row]
            for row in df.values.tolist()
        ]
        records = [
            {
                headers[col_idx]: row[col_idx]
                for col_idx in range(len(headers))
            }
            for row in rows
        ]

        raw_table = RawTable(
            name=file_path.stem,
            headers=headers,
            rows=rows,
            column_types=column_types,
            records=records,
            total_row_count=total_row_count,
            truncated=truncated,
            metadata={
                "delimiter": delimiter,
                "missing_value_counts": missing_value_counts,
            },
        )

        blocks: list[RawBlock] = [
            RawBlock(
                type=BlockType.TABLE,
                text=" | ".join(headers),
                metadata={
                    "table_index": 0,
                    "columns": headers,
                    "column_types": column_types,
                    "row_count": len(rows),
                    "total_row_count": total_row_count,
                    "truncated": truncated,
                },
            )
        ]

        for row_idx, row in enumerate(rows, start=1):
            paired = "; ".join(
                f"{header}: {value}" for header, value in zip(headers, row, strict=False)
            )
            blocks.append(
                RawBlock(
                    type=BlockType.PARAGRAPH,
                    text=paired,
                    metadata={"row_index": row_idx},
                )
            )

        raw_text = "\n".join(b.text for b in blocks if b.text.strip())
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)

        return ExtractedContent(
            extractor_name=self.name,
            format=self.supported_format,
            raw_text=raw_text,
            blocks=blocks,
            tables=[raw_table],
            encoding=encoding,
            custom_properties={
                "delimiter": delimiter,
                "columns": headers,
                "column_types": column_types,
                "missing_value_counts": missing_value_counts,
                "row_count": len(rows),
                "total_row_count": total_row_count,
                "column_count": len(headers),
                "truncated": truncated,
            },
            statistics=RawStatistics(
                extraction_time_ms=elapsed_ms,
                char_count=len(raw_text),
                word_count=count_words(raw_text),
                line_count=count_lines(raw_text),
                block_count=len(blocks),
                table_count=1,
                records_extracted=len(records),
                truncated=truncated,
            ),
            warnings=warnings,
        )

    @staticmethod
    def _sniff_delimiter(sample_text: str) -> str:
        try:
            dialect = csv.Sniffer().sniff(sample_text, delimiters=",;\t|")
            return dialect.delimiter
        except csv.Error:
            return ","

    @staticmethod
    def _validate_csv_structure(
        text: str,
        *,
        delimiter: str,
        filename: str,
    ) -> None:
        """Strictly validate CSV quoting and consistent column counts across all non-empty rows."""
        reader = csv.reader(
            io.StringIO(text, newline=""),
            delimiter=delimiter,
            strict=True,
        )
        expected_columns: int | None = None
        record_number = 0

        try:
            for row in reader:
                if not row:
                    continue
                if expected_columns is None:
                    expected_columns = len(row)
                    continue
                record_number += 1
                if len(row) != expected_columns:
                    raise CorruptedDocumentError(
                        f"Malformed CSV structure in '{filename}': inconsistent column count "
                        f"at record {record_number} (expected {expected_columns}, found {len(row)}).",
                        details={
                            "filename": filename,
                            "expected_columns": expected_columns,
                            "actual_columns": len(row),
                            "record_number": record_number,
                        },
                    )
        except csv.Error as exc:
            raise CorruptedDocumentError(
                f"Malformed CSV syntax in '{filename}'.",
                details={"reason": sanitize_error_reason(exc, replacement_name=filename)},
            ) from exc

        if expected_columns is None or expected_columns == 0:
            raise EmptyDocumentError(
                f"CSV document '{filename}' contains no rows or columns."
            )

    @staticmethod
    def _is_missing_value(value: object) -> bool:
        return str(value).strip().lower() in {"", "na", "n/a", "null", "none", "nan"}

    @classmethod
    def _infer_column_type(cls, values: list[object]) -> str:
        """Infer a semantic column data type from non-missing string values."""
        non_empty = [
            str(v).strip() for v in values if not cls._is_missing_value(v)
        ]
        if not non_empty:
            return "empty"

        if all(_INT_RE.match(v) for v in non_empty):
            return "integer"
        if all(_INT_RE.match(v) or _FLOAT_RE.match(v) for v in non_empty):
            return "float"
        if all(v.lower() in _BOOL_VALS for v in non_empty):
            return "boolean"

        try:
            parsed = pd.to_datetime(pd.Series(non_empty), format="ISO8601", errors="raise")
            if len(parsed) == len(non_empty):
                return "datetime"
        except Exception:
            pass

        return "string"
