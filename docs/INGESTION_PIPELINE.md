# MemoriaOS Local Ingestion Pipeline

1. Upload a document to Agent 01.
2. Receive and save the `NormalizedDocument` JSON response.
3. Configure `MEMORIA_OBSIDIAN_VAULT_PATH` on the local machine.
4. Run `python -m scripts.ingest_normalized_json <json-file>`.
5. The Obsidian writer validates the Pydantic schema, checks the SQLite idempotency ledger, renders Markdown, and atomically writes the note.
6. Open the vault in Obsidian and inspect `01-Raw-Documents`.

The current CLI is a deliberate local bridge. A future local worker can call `ObsidianWriter.ingest()` directly after Agent 01 completes, without routing through a public filesystem-writing API.
