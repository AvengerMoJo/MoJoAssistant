# Storage Backend Runtime Guide

This guide defines how to run storage backends for memory persistence with safe dual-write validation.

## Backends

- `local_fs`: JSON files on local filesystem.
- `duckdb`: key-value JSON records in DuckDB.
- `mirror`: read from one primary backend, write to primary + one/more mirrors.

## Config Pattern

Storage backend selection is passed through memory config:

```json
{
  "storage": {
    "backend": "local_fs",
    "backend_config": {
      "base_path": "~/.memory"
    }
  }
}
```

DuckDB example:

```json
{
  "storage": {
    "backend": "duckdb",
    "backend_config": {
      "db_path": "~/.memory/storage/mojo.duckdb"
    }
  }
}
```

Mirror mode example (recommended for migration/validation):

```json
{
  "storage": {
    "backend": "mirror",
    "backend_config": {
      "primary": {
        "name": "local_fs",
        "config": { "base_path": "~/.memory" }
      },
      "mirrors": [
        {
          "name": "duckdb",
          "config": { "db_path": "~/.memory/storage/mojo.duckdb" }
        }
      ],
      "compare_on_read": false
    }
  }
}
```

## Conversation Integrity Requirements

Conversation records must preserve linkage semantics:

- `conversation_id`
- `message_id`
- `turn_index` (ordered within conversation)
- `role`
- `content`
- `created_at`
- optional: `parent_message_id`, `pair_id`, `status`

Assistant turns must not be orphaned from context.

## Parity Validation

Run read-only parity checker:

```bash
python3 scripts/storage_parity_check.py \
  --primary-name local_fs \
  --primary-config '{"base_path":"~/.memory"}' \
  --mirror-name duckdb \
  --mirror-config '{"db_path":"~/.memory/storage/mojo.duckdb"}'
```

Reports are written to:

- `~/.memory/reports/storage_parity/`

## Cutover Policy

Recommended sequence:

1. Enable `mirror` with `local_fs` primary and `duckdb` mirror.
2. Run parity checks repeatedly during normal usage windows.
3. Confirm zero drift and zero orphan-turn issues.
4. Switch primary to `duckdb` only after explicit operator decision.

Do not auto-cutover.
