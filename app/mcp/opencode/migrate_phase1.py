#!/usr/bin/env python3
"""
Phase 1 Migration Script for OpenCode Manager

Migrates existing state and configuration files from project_name-based keys
to git_url-based keys.

Usage:
    python -m app.mcp.opencode.migrate_phase1 [--dry-run] [--memory-root PATH]

Options:
    --dry-run       Show what would be migrated without making changes
    --memory-root   Path to memory root directory (default: ~/.memory)

File: app/mcp/opencode/migrate_phase1.py
"""

import argparse
import os
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Migrate OpenCode Manager to Phase 1 (git_url-based keys)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be migrated without making changes",
    )
    parser.add_argument(
        "--memory-root",
        type=str,
        default=None,
        help="Path to memory root directory (default: ~/.memory)",
    )
    args = parser.parse_args()

    memory_root = args.memory_root or os.path.expanduser("~/.memory")

    print("=" * 70)
    print("OpenCode Manager - Phase 1 Migration")
    print("=" * 70)
    print(f"Memory root: {memory_root}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    print()

    # Import managers
    from app.mcp.opencode.state_manager import StateManager
    from app.mcp.opencode.config_manager import ConfigManager

    # Check if files exist
    state_file = Path(memory_root) / "opencode-state.json"
    config_file = Path(memory_root) / "opencode-mcp-tool-servers.json"

    state_exists = state_file.exists()
    config_exists = config_file.exists()

    print("Files to migrate:")
    print(f"  • State file: {state_file} {'✓ exists' if state_exists else '✗ not found'}")
    print(f"  • Config file: {config_file} {'✓ exists' if config_exists else '✗ not found'}")
    print()

    if not state_exists and not config_exists:
        print("No files to migrate. Exiting.")
        return 0

    if args.dry_run:
        print("DRY RUN MODE - No changes will be made")
        print()

    # Migrate state file
    if state_exists:
        print("-" * 70)
        print("Migrating State File")
        print("-" * 70)
        if args.dry_run:
            # Read and analyze state
            import json

            with open(state_file, "r") as f:
                state = json.load(f)

            projects = state.get("projects", {})
            if projects:
                first_key = next(iter(projects))
                if "@" in first_key or first_key.startswith("http"):
                    print("✓ State file already migrated (keys are git URLs)")
                else:
                    print(f"Found {len(projects)} projects to migrate:")
                    for project_name, project_data in projects.items():
                        git_url = project_data.get("git_url", "MISSING")
                        print(f"  • {project_name} → {git_url}")
            else:
                print("No projects found in state file")
        else:
            state_manager = StateManager(memory_root)
            # Migration runs automatically in __init__, but we can explicitly call it
            print("Running state migration...")
            state_manager.migrate_all()
        print()

    # Migrate config file
    if config_exists:
        print("-" * 70)
        print("Migrating Config File")
        print("-" * 70)
        if args.dry_run:
            # Read and analyze config
            import json

            with open(config_file, "r") as f:
                config = json.load(f)

            servers = config.get("servers", [])
            if servers:
                first_id = servers[0].get("id", "")
                if "@" in first_id or first_id.startswith("http"):
                    print("✓ Config file already migrated (IDs are git URLs)")
                else:
                    print(f"Found {len(servers)} servers to migrate:")
                    for server in servers:
                        old_id = server.get("id", "MISSING")
                        git_url = server.get("git_url", "MISSING")
                        print(f"  • {old_id} → {git_url}")
            else:
                print("No servers found in config file")
        else:
            config_manager = ConfigManager(memory_root)
            # Migration runs automatically in __init__, but we can explicitly call it
            print("Running config migration...")
            config_manager.migrate_all()
        print()

    # Summary
    print("=" * 70)
    if args.dry_run:
        print("DRY RUN COMPLETE - No changes were made")
        print()
        print("To perform the migration, run:")
        print(f"  python -m app.mcp.opencode.migrate_phase1")
    else:
        print("MIGRATION COMPLETE")
        print()
        print("Your state and configuration files have been migrated to use")
        print("git_url as the primary key instead of project_name.")
        print()
        print("All existing projects should continue to work. If you encounter")
        print("any issues, please file a bug report.")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
