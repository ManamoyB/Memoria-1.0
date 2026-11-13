# Obsidian Integration Configuration

| Environment variable | Required | Default |
| --- | --- | --- |
| `MEMORIA_OBSIDIAN_VAULT_PATH` | Yes | None |
| `MEMORIA_OBSIDIAN_DATABASE_PATH` | No | `<vault>/.memoria/ingestion.sqlite3` |

The default note folder is `01-Raw-Documents`. The standard vault folder structure is created automatically by `ObsidianConfig.ensure_vault()`.

Use absolute paths. Keep the vault and ingestion database outside Git unless you intentionally want to publish sanitized examples. Never commit personal notes or source documents.
