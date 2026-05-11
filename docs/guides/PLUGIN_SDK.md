# Plugin SDK Guide

`scripts/plugin_sdk.py` provides baseline tooling for third-party module authors.

## Commands

Scaffold a new plugin:

```bash
python3 scripts/plugin_sdk.py scaffold \
  --name my-memory-plugin \
  --provider-type memory \
  --output-dir plugins
```

Validate plugin structure:

```bash
python3 scripts/plugin_sdk.py validate --path plugins/my-memory-plugin
```

## Required Files

At minimum:

- `module.json`
- `src/<package>/provider.py`

`module.json` required keys:

- `name`
- `version`
- `provider_type`
- `entry_point`
- `contract_version`

## Sample Plugin

Reference package:

- `examples/plugins/sample-memory-plugin/`
