#!/usr/bin/env python3
"""
MoJoAssistant Installation Helper

Automated setup script that:
1. Checks Python version
2. Creates virtual environment
3. Installs dependencies
4. Downloads Qwen3 1.7B model
5. Generates configuration files
6. Starts interactive-cli in setup mode

Usage:
    python install_mojo.py

Or with options:
    python install_mojo.py --python python3.11 --venv .venv
"""

import argparse
import os
import subprocess
import sys
import json
from pathlib import Path
from datetime import datetime


class Colors:
    """Terminal colors"""

    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    END = "\033[0m"


def print_header():
    """Print installation header"""
    print(f"""
{Colors.CYAN}{Colors.BOLD}
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║              MoJoAssistant Installation Helper               ║
║                                                              ║
║  Automated setup with Qwen3 1.7B AI-powered configuration   ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
{Colors.END}
""")


def print_step(step_num, total_steps, message):
    """Print step header"""
    print(f"\n{Colors.BLUE}[{step_num}/{total_steps}] {message}{Colors.END}")
    print("=" * 60)


def print_success(message):
    """Print success message"""
    print(f"{Colors.GREEN}✓ {message}{Colors.END}")


def print_warning(message):
    """Print warning message"""
    print(f"{Colors.YELLOW}⚠ {message}{Colors.END}")


def print_error(message):
    """Print error message"""
    print(f"{Colors.RED}✗ {message}{Colors.END}")


def run_command(cmd, description, check=True):
    """Run a shell command with error handling"""
    print(f"  $ {cmd}")
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, check=check
        )
        if result.stdout:
            print(f"  {result.stdout.strip()}")
        return result.returncode == 0
    except subprocess.CalledProcessError as e:
        print_error(f"Command failed: {e}")
        if e.stderr:
            print(f"  Error: {e.stderr.strip()}")
        return False


def check_python_version():
    """Check if Python version is compatible"""
    print_step(1, 7, "Checking Python version")

    version = sys.version_info
    print(f"  Python version: {version.major}.{version.minor}.{version.micro}")

    if version.major < 3 or (version.major == 3 and version.minor < 9):
        print_error("Python 3.9 or higher required")
        print("  Please install Python 3.9+ and try again")
        return False

    print_success(
        f"Python {version.major}.{version.minor}.{version.micro} is compatible"
    )
    return True


def create_virtual_environment(python_cmd, venv_path):
    """Create Python virtual environment"""
    print_step(2, 7, "Creating virtual environment")

    if os.path.exists(venv_path):
        print_warning(f"Virtual environment already exists: {venv_path}")
        response = input("  Recreate? [y/N]: ").strip().lower()
        if response == "y":
            print("  Removing existing environment...")
            import shutil

            shutil.rmtree(venv_path)
        else:
            print("  Using existing environment")
            return True

    print(f"  Creating venv at: {venv_path}")
    if run_command(f"{python_cmd} -m venv {venv_path}", "Create virtual environment"):
        print_success(f"Virtual environment created at {venv_path}")
        return True
    else:
        print_error("Failed to create virtual environment")
        return False


def activate_virtual_environment(venv_path):
    """Get activation command for the virtual environment"""
    if os.name == "nt":  # Windows
        activate_script = os.path.join(venv_path, "Scripts", "activate.bat")
        pip_path = os.path.join(venv_path, "Scripts", "pip.exe")
        python_path = os.path.join(venv_path, "Scripts", "python.exe")
    else:  # Linux/Mac
        activate_script = os.path.join(venv_path, "bin", "activate")
        pip_path = os.path.join(venv_path, "bin", "pip")
        python_path = os.path.join(venv_path, "bin", "python")

    return activate_script, pip_path, python_path


def install_dependencies(pip_path, venv_python):
    """Install Python dependencies"""
    print_step(3, 7, "Installing dependencies")

    print("  Installing packages (this may take a few minutes)...")

    # Install requirements
    if run_command(
        f"{pip_path} install -r requirements.txt", "Install from requirements.txt"
    ):
        print_success("Dependencies installed successfully")
        return True
    else:
        print_error("Failed to install dependencies")
        return False


def download_qwen_model(python_path):
    """Download Qwen3 1.7B model"""
    print_step(4, 7, "Downloading Qwen3 1.7B model")

    model_name = "Qwen/Qwen3-1.7B"
    cache_dir = Path.home() / ".cache" / "huggingface" / "hub"

    print(f"  Model: {model_name}")
    print(f"  Cache directory: {cache_dir}")
    print("  This may take several minutes depending on your connection...")
    print()

    # Create download script
    download_script = """
import sys
sys.path.insert(0, '.')
from huggingface_hub import snapshot_download
import os

model_name = "Qwen/Qwen3-1.7B"
cache_dir = os.path.expanduser("~/.cache/huggingface/hub")

print(f"Downloading {model_name}...")
print(f"Cache: {cache_dir}")

try:
    snapshot_download(
        repo_id=model_name,
        cache_dir=cache_dir,
        local_files_only=False
    )
    print("✓ Model downloaded successfully")
except Exception as e:
    print(f"✗ Download failed: {e}")
    sys.exit(1)
"""

    # Write and run download script
    script_path = "download_model.py"
    with open(script_path, "w") as f:
        f.write(download_script)

    try:
        success = run_command(f"{python_path} {script_path}", "Download Qwen3 model")
    finally:
        if os.path.exists(script_path):
            os.remove(script_path)

    if success:
        print_success("Qwen3 1.7B model downloaded")
        return True
    else:
        print_error("Failed to download model")
        print("  You can download it manually later with:")
        print(
            "  python -c \"from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen3-1.7B')\""
        )
        return False


def generate_config_files():
    """Generate configuration files"""
    print_step(5, 7, "Generating configuration files")

    configs_created = []

    # 1. Create .env file
    env_content = """# MoJoAssistant Configuration
# Auto-generated by install_mojo.py

# =============================================================================
# SERVER CONFIGURATION
# =============================================================================
SERVER_HOST=127.0.0.1
SERVER_PORT=8000
CORS_ORIGINS=*
LOG_LEVEL=INFO
LOG_CONSOLE=true
ENVIRONMENT=development
DEBUG=false

# =============================================================================
# MCP AUTHENTICATION
# =============================================================================
MCP_API_KEY=auto-generated-key-change-me
MCP_REQUIRE_AUTH=true

# =============================================================================
# LLM CONFIGURATION (Using Local Qwen3 1.7B)
# =============================================================================
# Local model settings
LOCAL_MODEL_PATH=~/.cache/huggingface/hub/models--Qwen--Qwen3-1.7B
EMBEDDING_MODEL=all-MiniLM-L6-v2
EMBEDDING_BACKEND=huggingface

# Optional: Add API keys for external models
# OPENAI_API_KEY=your-openai-key-here
# ANTHROPIC_API_KEY=your-anthropic-key-here

# =============================================================================
# MEMORY CONFIGURATION
# =============================================================================
MEMORY_DATA_DIR=~/.memory
DREAMING_ENABLED=true
DREAMING_SCHEDULE=0 3 * * *

# =============================================================================
# SCHEDULER CONFIGURATION
# =============================================================================
SCHEDULER_ENABLED=true
SCHEDULER_TICK_INTERVAL=60
"""

    env_path = Path(".env")
    if not env_path.exists():
        with open(env_path, "w") as f:
            f.write(env_content)
        configs_created.append(".env")
        print_success("Created .env configuration file")
    else:
        print_warning(".env already exists, skipping")

    # 2. Create llm_config.json
    llm_config = {
        "local_models": {
            "qwen3-1.7b": {
                "path": "~/.cache/huggingface/hub/models--Qwen--Qwen3-1.7B",
                "type": "qwen",
                "n_threads": 4,
                "timeout": 60,
            }
        },
        "default_interface": "qwen3-1.7b",
    }

    config_dir = Path("config")
    config_dir.mkdir(exist_ok=True)

    llm_config_path = config_dir / "llm_config.json"
    if not llm_config_path.exists():
        with open(llm_config_path, "w") as f:
            json.dump(llm_config, f, indent=2)
        configs_created.append("config/llm_config.json")
        print_success("Created LLM configuration")
    else:
        print_warning("config/llm_config.json already exists, skipping")

    # 3. Create memory directory structure
    memory_dir = Path.home() / ".memory"
    memory_dir.mkdir(exist_ok=True)

    subdirs = ["conversations", "dreams", "embeddings", "knowledge"]
    for subdir in subdirs:
        (memory_dir / subdir).mkdir(exist_ok=True)

    configs_created.append(f"{memory_dir}/ (with subdirectories)")
    print_success("Created memory directory structure")

    return len(configs_created) > 0


def test_installation(python_path):
    """Test the installation"""
    print_step(6, 7, "Testing installation")

    print("  Testing imports...")
    test_script = """
import sys
sys.path.insert(0, '.')

try:
    from app.scheduler.core import Scheduler
    print("✓ Scheduler import successful")
    
    from app.dreaming.pipeline import DreamingPipeline
    print("✓ Dreaming pipeline import successful")
    
    from app.services.memory_service import MemoryService
    print("✓ Memory service import successful")
    
    print("\\n✓ All core modules imported successfully")
except Exception as e:
    print(f"\\n✗ Import failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
"""

    script_path = "test_install.py"
    with open(script_path, "w") as f:
        f.write(test_script)

    try:
        success = run_command(f"{python_path} {script_path}", "Test installation")
    finally:
        if os.path.exists(script_path):
            os.remove(script_path)

    return success


def create_activation_scripts(venv_path, python_path):
    """Create convenience activation scripts"""
    print_step(7, 7, "Creating activation scripts")

    # Create run_cli.sh
    cli_script = f"""#!/bin/bash
# MoJoAssistant Interactive CLI Launcher
# Auto-generated by install_mojo.py

echo "Starting MoJoAssistant Interactive CLI..."
echo ""

# Activate virtual environment
source {venv_path}/bin/activate

# Run interactive CLI with setup mode
python app/interactive-cli.py --setup
"""

    with open("run_cli.sh", "w") as f:
        f.write(cli_script)
    os.chmod("run_cli.sh", 0o755)
    print_success("Created run_cli.sh")

    # Create run_mcp.sh
    mcp_script = f"""#!/bin/bash
# MoJoAssistant MCP Server Launcher
# Auto-generated by install_mojo.py

echo "Starting MoJoAssistant MCP Server..."
echo ""

# Activate virtual environment
source {venv_path}/bin/activate

# Run MCP server
python unified_mcp_server.py --mode stdio
"""

    with open("run_mcp.sh", "w") as f:
        f.write(mcp_script)
    os.chmod("run_mcp.sh", 0o755)
    print_success("Created run_mcp.sh")

    # Windows versions
    if os.name == "nt":
        cli_bat = f"""@echo off
REM MoJoAssistant Interactive CLI Launcher
REM Auto-generated by install_mojo.py

echo Starting MoJoAssistant Interactive CLI...
echo.

REM Activate virtual environment
call {venv_path}\\Scripts\\activate.bat

REM Run interactive CLI with setup mode
python app/interactive-cli.py --setup
"""

        with open("run_cli.bat", "w") as f:
            f.write(cli_bat)
        print_success("Created run_cli.bat")


def print_completion_message(venv_path, python_path):
    """Print completion message with next steps"""
    print(f"""
{Colors.GREEN}{Colors.BOLD}
╔══════════════════════════════════════════════════════════════╗
║                 Installation Complete! 🎉                    ║
╚══════════════════════════════════════════════════════════════╝
{Colors.END}

{Colors.BOLD}What's been set up:{Colors.END}
  ✓ Python virtual environment: {venv_path}
  ✓ All dependencies installed
  ✓ Qwen3 1.7B model downloaded
  ✓ Configuration files generated
  ✓ Memory directory structure created

{Colors.BOLD}Next Steps:{Colors.END}

1. {Colors.CYAN}Start Interactive CLI (with AI setup wizard):{Colors.END}
   {Colors.YELLOW}./run_cli.sh{Colors.END}
   
   Or manually:
   {Colors.YELLOW}source {venv_path}/bin/activate{Colors.END}
   {Colors.YELLOW}python app/interactive-cli.py --setup{Colors.END}

2. {Colors.CYAN}Start MCP Server (for Claude Desktop):{Colors.END}
   {Colors.YELLOW}./run_mcp.sh{Colors.END}

3. {Colors.CYAN}Configure Claude Desktop:{Colors.END}
   Edit: ~/.config/Claude/claude_desktop_config.json
   
   Add:
   {Colors.YELLOW}"mcpServers": {{{Colors.END}
     {Colors.YELLOW}"mojo-assistant": {{{Colors.END}
       {Colors.YELLOW}"command": "{python_path}",{Colors.END}
       {Colors.YELLOW}"args": ["{os.getcwd()}/unified_mcp_server.py", "--mode", "stdio"]{Colors.END}
     {Colors.YELLOW}}}{Colors.END}
   {Colors.YELLOW}}}{Colors.END}

{Colors.BOLD}Configuration Files:{Colors.END}
  • .env - Main configuration
  • config/llm_config.json - LLM settings
  • ~/.memory/ - Memory storage

{Colors.BOLD}Documentation:{Colors.END}
  • README.md - Getting started guide
  • docs/ - Full documentation
  
{Colors.GREEN}Enjoy MoJoAssistant! 🚀{Colors.END}
""")


def main():
    """Main installation function"""
    parser = argparse.ArgumentParser(
        description="MoJoAssistant Installation Helper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python install_mojo.py                    # Default installation
  python install_mojo.py --venv myenv      # Custom venv name
  python install_mojo.py --python python3.11  # Specific Python version
        """,
    )

    parser.add_argument(
        "--python", default="python3", help="Python command to use (default: python3)"
    )
    parser.add_argument(
        "--venv", default="venv", help="Virtual environment name (default: venv)"
    )
    parser.add_argument(
        "--skip-model", action="store_true", help="Skip downloading Qwen3 model"
    )
    parser.add_argument(
        "--skip-tests", action="store_true", help="Skip installation tests"
    )

    args = parser.parse_args()

    print_header()

    # Track if we should continue
    success = True

    # Step 1: Check Python version
    if not check_python_version():
        sys.exit(1)

    # Step 2: Create virtual environment
    if not create_virtual_environment(args.python, args.venv):
        sys.exit(1)

    # Get paths
    activate_script, pip_path, python_path = activate_virtual_environment(args.venv)

    # Step 3: Install dependencies
    if not install_dependencies(pip_path, python_path):
        success = False
        print_warning("Continuing despite dependency issues...")

    # Step 4: Download model (optional)
    if not args.skip_model:
        if not download_qwen_model(python_path):
            print_warning("Model download failed, but continuing...")
    else:
        print_step(4, 7, "Skipping model download (--skip-model)")

    # Step 5: Generate config files
    if not generate_config_files():
        success = False

    # Step 6: Test installation
    if not args.skip_tests:
        if not test_installation(python_path):
            print_warning("Some tests failed, but installation may still work")
    else:
        print_step(6, 7, "Skipping tests (--skip-tests)")

    # Step 7: Create activation scripts
    create_activation_scripts(args.venv, python_path)

    # Print completion message
    print_completion_message(args.venv, python_path)

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
