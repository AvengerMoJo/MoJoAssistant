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
- `examples/plugins/sample-persona-plugin/`

## Packaging / Publish Workflow

1. Scaffold plugin:

```bash
python3 scripts/plugin_sdk.py scaffold \
  --name my-persona-plugin \
  --provider-type persona \
  --output-dir plugins
```

2. Implement provider class in `src/<pkg>/provider.py`.
3. Validate plugin package:

```bash
python3 scripts/plugin_sdk.py validate --path plugins/my-persona-plugin
```

4. Package for distribution (example):

```bash
cd plugins/my-persona-plugin
tar -czf my-persona-plugin-0.1.0.tar.gz module.json src README.md
```

5. Install in MoJo repo:
- copy/unpack into `submodules/` or a plugin directory
- ensure `module.json` is discoverable by registry scanning
- run conformance + smoke tests before enabling in production.
