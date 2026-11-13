# MemoriaOS Phase 2 — Obsidian Integration

## Scope

This module consumes Agent 01 `NormalizedDocument` JSON and writes faithful, provenance-rich Markdown notes into a local Obsidian vault. It does not summarize, call an LLM, generate embeddings, or write to Qdrant.

## Vault setup

Set an absolute local path in the environment:

**PowerShell**
```powershell
$env:MEMORIA_OBSIDIAN_VAULT_PATH = "E:\AI\MemoriaOS\vault"
python -m scripts.init_obsidian_vault
```

The initializer creates:

- `00-Inbox/`
- `01-Raw-Documents/`
- `02-Knowledge/`
- `03-Topics/`
- `04-Entities/`
- `05-Projects/`
- `06-Summaries/`
- `07-Relationships/`
- `08-System/`

Open the configured vault folder in Obsidian. The ingestion ledger is stored separately in the hidden `.memoria/ingestion.sqlite3` directory at the vault root.

Optional database override:

```powershell
$env:MEMORIA_OBSIDIAN_DATABASE_PATH = "E:\AI\MemoriaOS\data\obsidian-ingestion.sqlite3"
```

## Ingest a JSON export

Save the Agent 01 `NormalizedDocument` response as UTF-8 JSON. The CLI accepts either the document object directly or an AgentTaskResponse-style object with an `output` property.

```powershell
python -m scripts.ingest_normalized_json "E:\path\to\normalized-document.json"
```

The CLI reports whether a note was created or had already been ingested.

## Programmatic use

```python
from app.obsidian import ObsidianConfig, ObsidianWriter

writer = ObsidianWriter(ObsidianConfig.from_env())
result = writer.ingest(normalized_document)
print(result.vault_relative_path, result.status)
```

## Note behavior

- Notes are written to `01-Raw-Documents/` by default.
- YAML frontmatter records document ID, source filename, type, SHA-256 content hash, agent, extraction status, ingestion timestamp, MIME type, and byte size.
- Original normalized content is preserved verbatim in the Extracted Content section.
- Extracted tables are rendered as Markdown tables; section hierarchy is included as an outline.
- Source provenance and extraction warnings are included.
- The writer never overwrites an existing file. A collision receives a content-hash suffix.

## Idempotency and versioning

SQLite enforces a unique `(document_id, content_hash)` pair. Re-ingesting the same pair returns `already_ingested` and the original note path. If the same document ID arrives with a changed content hash, a new versioned note is created; the earlier note remains untouched.

The ledger is stored at `.memoria/ingestion.sqlite3` by default. Back it up along with the vault.

## Safety boundaries

- The vault path must be configured explicitly.
- Generated folder and note paths are resolved and checked to remain under the vault root.
- Filenames are sanitized.
- Writes use a temporary file in the destination directory followed by an atomic replace.
- Existing notes are never overwritten.
- The CLI is intended for local trusted use. Do not expose a general-purpose unauthenticated cloud endpoint that writes to a user's filesystem.

## Testing

```powershell
python -m pytest tests/test_obsidian.py -v
python -m pytest -v
```

Tests use temporary directories and SQLite databases; they do not modify a real vault.
