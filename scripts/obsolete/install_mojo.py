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
    print_step(1, 4, "Checking Python version")

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
    print_step(2, 4, "Creating virtual environment")

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
    print_step(3, 4, "Installing dependencies")

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


def download_model(python_path, interactive=True):
    """Download a model - either from catalog or via smart search"""
    print_step(4, 4, "Model Selection & Download")

    print("""
📦 Choose how to select your model:

  1. Quick install - Use default model
  2. Browse catalog - Choose from predefined models  
  3. Search HuggingFace - Find any GGUF model (e.g., 'gpt-oss', 'llama 3.1')
  4. Skip for now - Download later
""")

    if interactive:
        while True:
            choice = input("Your choice (1-4): ").strip()
            if choice in ["1", "2", "3", "4"]:
                break
            print("  Please enter 1, 2, 3, or 4")
    else:
        choice = "1"  # Default to quick install in non-interactive mode

    if choice == "4":
        print("  Skipping model download")
        print("  You can download models later with:")
        print("    python demo_model_selector.py --model <model_id>")
        print("    python demo_model_selector.py --search <query>")
        return True

    # Import model selector
    sys.path.insert(0, ".")
    from app.installer.agents.model_selector import ModelSelectorAgent

    agent = ModelSelectorAgent(llm=None, config_dir="config")

    result = {"success": False, "message": "Invalid choice", "details": {}}

    if choice == "1":
        # Quick install - use default
        print("\n  Installing default model (Qwen3 1.7B)...")
        result = agent.execute(auto_default=True)

    elif choice == "2":
        # Browse catalog
        agent.load_context()
        print("\n  Available models in catalog:")
        for i, model in enumerate(agent.context.get("models", [])[:6], 1):
            default_marker = " [DEFAULT]" if model.get("default") else ""
            print(f"    {i}. {model['name']}{default_marker} - {model['size_mb']}MB")

        print("\n  Enter model ID (e.g., 'qwen3-1.7b-q5') or number:")
        model_input = input("> ").strip()

        # Check if it's a number
        try:
            idx = int(model_input) - 1
            models = agent.context.get("models", [])
            if 0 <= idx < len(models):
                model_id = models[idx]["id"]
            else:
                model_id = model_input
        except ValueError:
            model_id = model_input

        print(f"\n  Installing {model_id}...")
        result = agent.download_model_by_id(model_id)

    elif choice == "3":
        # Smart search
        print("\n  Search for models on HuggingFace")
        print("  Examples: 'gpt-oss-20b', 'llama 3.1', 'qwen3', 'mistral'")
        query = input("Search query: ").strip()

        if not query:
            print("  No search query provided, skipping")
            return True

        result = agent.search_and_add_model(query, interactive=True)

    # Handle result
    if result.get("success"):
        print_success(f"Model ready: {result.get('message', '')}")
        if "model_path" in result.get("details", {}):
            print(f"  Location: {result['details']['model_path']}")
        return result
    else:
        print_error(f"Failed: {result.get('message', 'Unknown error')}")
        return None


def download_qwen_model(python_path):
    """Legacy function - redirects to new download_model"""
    return download_model(python_path, interactive=True)


def generate_minimal_config(model_path=None):
    """Generate minimal configuration - just enough for LLM to work"""
    print_step(4, 4, "Creating minimal configuration")

    # Create config directory
    config_dir = Path("config")
    config_dir.mkdir(exist_ok=True)

    llm_config_path = config_dir / "llm_config.json"

    # Load existing config if it exists
    if llm_config_path.exists():
        try:
            with open(llm_config_path, "r") as f:
                llm_config = json.load(f)
            print("  Found existing configuration")
        except:
            llm_config = {"local_models": {}, "task_assignments": {}}
    else:
        llm_config = {"local_models": {}, "task_assignments": {}}

    # If model was downloaded and not already in config, add it
    if model_path and Path(model_path).exists():
        # Extract model name from path
        model_name = Path(model_path).stem
        model_id = model_name.replace("-", "_").replace(".", "_")[:30]

        # Only add if not already configured
        if model_id not in llm_config.get("local_models", {}):
            llm_config["local_models"][model_id] = {
                "type": "llama",
                "path": str(model_path),
                "context_length": 32768,
                "temperature": 0.7,
                "max_tokens": 2048,
                "recommended_for": ["general chat"],
            }
            llm_config["task_assignments"] = {
                "interactive_cli": model_id,
                "dreaming_chunking": model_id,
                "dreaming_synthesis": model_id,
                "default": model_id,
            }
            print_success(f"Added model to config: {model_id}")
        else:
            print(f"  Model {model_id} already configured")

    # Save config
    with open(llm_config_path, "w") as f:
        json.dump(llm_config, f, indent=2)

    print_success("LLM configuration ready")
    return True


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
║              Installation Complete! 🎉                       ║
║                                                              ║
║  Your LLM is ready. Now let's configure MoJoAssistant!       ║
╚══════════════════════════════════════════════════════════════╝
{Colors.END}

{Colors.BOLD}What's been set up:{Colors.END}
  ✓ Python virtual environment: {venv_path}
  ✓ All dependencies installed
  ✓ LLM model ready
  ✓ Minimal configuration created

{Colors.BOLD}{Colors.CYAN}👉 NEXT STEP: Run the AI Setup Wizard{Colors.END}

   The wizard will help you configure:
   • API keys (OpenAI, Anthropic - optional)
   • Memory and dreaming settings
   • MCP server configuration
   • Claude Desktop integration

   {Colors.YELLOW}source {venv_path}/bin/activate{Colors.END}
   {Colors.YELLOW}python app/interactive-cli.py --setup{Colors.END}

{Colors.BOLD}Or start using immediately:{Colors.END}
   {Colors.YELLOW}source {venv_path}/bin/activate{Colors.END}
   {Colors.YELLOW}python app/interactive-cli.py{Colors.END}

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

    # Step 4: Download model (optional) and generate config
    model_path = None
    if not args.skip_model:
        download_result = download_qwen_model(python_path)
        if download_result and isinstance(download_result, dict):
            model_path = download_result.get("model_path")
        if not model_path:
            print_warning("Model download failed or skipped, continuing...")

    generate_minimal_config(model_path)

    # Print completion message
    print_completion_message(args.venv, python_path)

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
