#!/usr/bin/env python3
"""
MoJoAssistant - Easy Installation Script
=========================================

One-command installation for users with no GPU (CPU-only setup).

This script:
1. Checks system requirements
2. Sets up Python virtual environment
3. Installs all dependencies (including llama-cpp-python for CPU)
4. Downloads Qwen2.5-Coder-1.7B model (~1.2 GB)
5. Generates configuration files
6. Tests the installation
7. Provides next steps to start using MoJoAssistant

Usage:
    python3 install.py

Requirements:
    - Python 3.9 or higher
    - ~2 GB free disk space
    - Internet connection for downloads

No GPU required! This uses CPU-only inference.
"""

import os
import sys
import subprocess
import json
import platform
from pathlib import Path
from datetime import datetime

# ============================================================================
# Terminal Colors
# ============================================================================

class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    END = '\033[0m'


# ============================================================================
# Print Helpers
# ============================================================================

def print_header():
    """Print installation header"""
    print(f"""
{Colors.CYAN}{Colors.BOLD}
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║           MoJoAssistant - Easy Installation                  ║
║                                                              ║
║  CPU-Only Setup (No GPU Required)                            ║
║  Powered by Qwen2.5-Coder-1.7B                               ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
{Colors.END}
""")


def print_step(step_num, total_steps, message):
    """Print step header"""
    print(f"\n{Colors.BLUE}{Colors.BOLD}[{step_num}/{total_steps}] {message}{Colors.END}")
    print("━" * 60)


def print_success(message):
    """Print success message"""
    print(f"{Colors.GREEN}✓ {message}{Colors.END}")


def print_warning(message):
    """Print warning message"""
    print(f"{Colors.YELLOW}⚠ {message}{Colors.END}")


def print_error(message):
    """Print error message"""
    print(f"{Colors.RED}✗ {message}{Colors.END}")


def print_info(message):
    """Print info message"""
    print(f"  {message}")


# ============================================================================
# System Checks
# ============================================================================

def check_python_version():
    """Check if Python version is compatible"""
    print_step(1, 8, "Checking Python version")

    version = sys.version_info
    print_info(f"Python version: {version.major}.{version.minor}.{version.micro}")
    print_info(f"Platform: {platform.system()} {platform.machine()}")

    if version.major < 3 or (version.major == 3 and version.minor < 9):
        print_error("Python 3.9 or higher required")
        print_info("Please install Python 3.9+ and try again")
        return False

    print_success(f"Python {version.major}.{version.minor} is compatible")
    return True


def check_disk_space():
    """Check available disk space"""
    try:
        import shutil
        stat = shutil.disk_usage(Path.home())
        free_gb = stat.free / (1024**3)

        print_info(f"Available disk space: {free_gb:.1f} GB")

        if free_gb < 2:
            print_warning("Less than 2 GB free space. Installation may fail.")
            response = input("  Continue anyway? [y/N]: ").strip().lower()
            return response == 'y'

        return True
    except:
        print_warning("Could not check disk space")
        return True


# ============================================================================
# Virtual Environment Setup
# ============================================================================

def create_venv(venv_path="venv"):
    """Create Python virtual environment"""
    print_step(2, 8, "Setting up Python virtual environment")

    venv_path = Path(venv_path)

    if venv_path.exists():
        print_warning(f"Virtual environment already exists: {venv_path}")
        response = input("  Use existing environment? [Y/n]: ").strip().lower()
        if response == 'n':
            print_info("Removing existing environment...")
            import shutil
            shutil.rmtree(venv_path)
        else:
            print_success("Using existing environment")
            return True

    print_info(f"Creating virtual environment at: {venv_path}")
    try:
        subprocess.run([sys.executable, "-m", "venv", str(venv_path)], check=True)
        print_success(f"Virtual environment created")
        return True
    except subprocess.CalledProcessError as e:
        print_error(f"Failed to create virtual environment: {e}")
        return False


def get_venv_python(venv_path="venv"):
    """Get path to Python in virtual environment"""
    venv_path = Path(venv_path)

    if platform.system() == "Windows":
        return venv_path / "Scripts" / "python.exe"
    else:
        return venv_path / "bin" / "python"


def get_venv_pip(venv_path="venv"):
    """Get path to pip in virtual environment"""
    venv_path = Path(venv_path)

    if platform.system() == "Windows":
        return venv_path / "Scripts" / "pip.exe"
    else:
        return venv_path / "bin" / "pip"


# ============================================================================
# Dependencies Installation
# ============================================================================

def install_dependencies(venv_path="venv"):
    """Install Python dependencies"""
    print_step(3, 8, "Installing Python dependencies")

    pip = str(get_venv_pip(venv_path))

    # Upgrade pip first
    print_info("Upgrading pip...")
    try:
        subprocess.run([pip, "install", "--upgrade", "pip"], check=True, capture_output=True)
        print_success("Pip upgraded")
    except subprocess.CalledProcessError:
        print_warning("Could not upgrade pip, continuing...")

    # Install from requirements.txt
    if Path("requirements.txt").exists():
        print_info("Installing from requirements.txt...")
        try:
            subprocess.run([pip, "install", "-r", "requirements.txt"], check=True)
            print_success("Dependencies installed from requirements.txt")
        except subprocess.CalledProcessError as e:
            print_error(f"Failed to install from requirements.txt: {e}")
            return False
    else:
        print_warning("requirements.txt not found, installing core dependencies...")

        # Install core dependencies manually
        core_deps = [
            "anthropic",
            "openai",
            "fastapi",
            "uvicorn",
            "prompt_toolkit",
            "python-dotenv",
            "requests",
            "numpy",
            "tqdm",
        ]

        for dep in core_deps:
            print_info(f"Installing {dep}...")
            try:
                subprocess.run([pip, "install", dep], check=True, capture_output=True)
            except subprocess.CalledProcessError:
                print_warning(f"Failed to install {dep}")

    # Install llama-cpp-python (CPU-only)
    print_info("")
    print_info("Installing llama-cpp-python for CPU inference...")
    print_info("This may take a few minutes as it compiles C++ code...")

    try:
        # Install llama-cpp-python with server support
        subprocess.run(
            [pip, "install", "llama-cpp-python[server]"],
            check=True
        )
        print_success("llama-cpp-python installed (CPU version)")
    except subprocess.CalledProcessError as e:
        print_error(f"Failed to install llama-cpp-python: {e}")
        print_info("You may need to install build tools.")
        print_info("On Ubuntu/Debian: sudo apt-get install build-essential")
        print_info("On macOS: xcode-select --install")
        return False

    return True


# ============================================================================
# Model Download
# ============================================================================

def download_qwen_model(venv_path="venv"):
    """Download Qwen2.5-Coder-1.7B model"""
    print_step(4, 8, "Downloading Qwen2.5-Coder-1.7B model")

    python = str(get_venv_python(venv_path))

    print_info("Model size: ~1.2 GB")
    print_info("This may take several minutes depending on your connection...")
    print_info("")

    try:
        # Use the dreaming setup script to download the model
        result = subprocess.run(
            [python, "-m", "app.dreaming.setup", "install"],
            check=True
        )

        print_success("Model downloaded successfully")
        return True

    except subprocess.CalledProcessError as e:
        print_error(f"Failed to download model: {e}")
        return False


def validate_model(venv_path="venv"):
    """Validate the downloaded model"""
    print_info("Validating model...")

    python = str(get_venv_python(venv_path))

    try:
        subprocess.run(
            [python, "-m", "app.dreaming.setup", "validate"],
            check=True
        )
        print_success("Model validated successfully")
        return True
    except subprocess.CalledProcessError:
        print_warning("Model validation failed, but continuing...")
        return True  # Don't fail installation


# ============================================================================
# AI Setup Wizard
# ============================================================================

def offer_ai_wizard(venv_path="venv"):
    """Offer user the option to use AI setup wizard"""
    print("")
    print("━" * 60)
    print(f"{Colors.CYAN}{Colors.BOLD}Configuration Setup{Colors.END}")
    print("━" * 60)
    print("")
    print(f"{Colors.BOLD}Let's configure MoJoAssistant for your needs.{Colors.END}")
    print("")
    print(f"  {Colors.GREEN}AI Setup Wizard (Recommended){Colors.END}")
    print(f"  • Talk naturally with the AI to configure settings")
    print(f"  • Get explanations for each option")
    print(f"  • Choose models based on your use case")
    print(f"  • Learn what MoJoAssistant can do")
    print("")
    print(f"  {Colors.YELLOW}Quick Setup{Colors.END}")
    print(f"  • Skip to defaults (Qwen2.5-Coder, local CPU-only)")
    print(f"  • Customize later by editing config files")
    print("")

    while True:
        response = input(f"{Colors.BOLD}Use AI Wizard? [Y/n]: {Colors.END}").strip().lower()

        if response in ["", "y", "yes"]:
            print("")
            print_info("Starting AI Setup Wizard...")
            print_info("Tip: Ask questions! The AI knows all about MoJoAssistant")
            print("")
            return run_ai_wizard(venv_path)
        elif response in ["n", "no"]:
            print("")
            print_info("Using quick setup with defaults...")
            return False
        else:
            print(f"{Colors.RED}Please enter Y or n{Colors.END}")


def run_ai_wizard(venv_path="venv"):
    """Run the AI setup wizard"""
    python = str(get_venv_python(venv_path))

    print("")
    print(f"{Colors.CYAN}{Colors.BOLD}")
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║                                                              ║")
    print("║              AI Setup Wizard                                 ║")
    print("║              Powered by Qwen2.5-Coder-1.7B                   ║")
    print("║                                                              ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print(f"{Colors.END}")
    print("")
    print_info("The AI will ask you questions to configure MoJoAssistant")
    print_info("Just chat naturally - it understands context!")
    print("")

    try:
        # Run the setup wizard
        result = subprocess.run(
            [python, "app/setup_wizard.py"],
            check=False  # Don't raise on non-zero exit (user might interrupt)
        )

        if result.returncode == 0:
            print("")
            print_success("AI Setup Wizard completed!")
            return True
        else:
            print("")
            print_warning("Setup wizard was interrupted or failed")
            print_info("Falling back to default configuration...")
            return False

    except Exception as e:
        print_error(f"Failed to run AI wizard: {e}")
        print_info("Falling back to default configuration...")
        return False


# ============================================================================
# Configuration
# ============================================================================

def create_config_files():
    """Create configuration files"""
    print_step(5, 8, "Generating configuration files")

    # Create config directory
    config_dir = Path("config")
    config_dir.mkdir(exist_ok=True)

    # Generate llm_config.json if it doesn't exist
    llm_config_path = config_dir / "llm_config.json"

    if llm_config_path.exists():
        print_warning(f"{llm_config_path} already exists")
    else:
        llm_config = {
            "comment": "MoJoAssistant LLM Configuration",
            "local_models": {
                "qwen-coder-small": {
                    "type": "llama",
                    "description": "Qwen2.5-Coder-1.7B - CPU-only, no GPU required",
                    "path": str(Path.home() / ".cache/mojoassistant/models/qwen2.5-coder-1.5b-instruct-q5_k_m.gguf"),
                    "context_length": 32768,
                    "temperature": 0.1,
                    "recommended_for": ["dreaming", "chunking", "basic_chat"]
                }
            },
            "task_assignments": {
                "interactive_cli": "qwen-coder-small",
                "dreaming_chunking": "qwen-coder-small",
                "dreaming_synthesis": "qwen-coder-small",
                "default": "qwen-coder-small"
            },
            "default_interface": "qwen-coder-small"
        }

        with open(llm_config_path, 'w') as f:
            json.dump(llm_config, f, indent=2)

        print_success(f"Created {llm_config_path}")

    # Create .env file if it doesn't exist
    env_path = Path(".env")

    if env_path.exists():
        print_warning(f"{env_path} already exists")
    else:
        env_content = f"""# MoJoAssistant Configuration
# Generated on {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

# ============================================================================
# LLM Configuration (CPU-Only Setup)
# ============================================================================
LLM_PROVIDER=local
LLM_MODEL=qwen-coder-small

# ============================================================================
# Memory Configuration
# ============================================================================
MEMORY_DATA_DIR={str(Path.home() / ".memory")}
DREAMING_ENABLED=true
DREAMING_SCHEDULE=0 3 * * *

# ============================================================================
# Scheduler Configuration
# ============================================================================
SCHEDULER_ENABLED=true
SCHEDULER_TICK_INTERVAL=60

# ============================================================================
# MCP Server Configuration
# ============================================================================
MCP_MODE=stdio
MCP_PORT=3000

# ============================================================================
# Optional: API Keys (for premium features)
# ============================================================================
# OPENAI_API_KEY=your-key-here
# ANTHROPIC_API_KEY=your-key-here
# GOOGLE_API_KEY=your-key-here
"""

        with open(env_path, 'w') as f:
            f.write(env_content)

        print_success(f"Created {env_path}")

    return True


def create_memory_dirs():
    """Create memory directories"""
    print_info("Creating memory directories...")

    memory_dir = Path.home() / ".memory"
    subdirs = ["conversations", "dreams", "embeddings", "git_repos"]

    for subdir in subdirs:
        (memory_dir / subdir).mkdir(parents=True, exist_ok=True)

    print_success(f"Memory directories created at {memory_dir}")
    return True


# ============================================================================
# Testing
# ============================================================================

def run_quick_test(venv_path="venv"):
    """Run a quick test to verify installation"""
    print_step(6, 8, "Testing installation")

    python = str(get_venv_python(venv_path))

    print_info("Running system check...")

    try:
        result = subprocess.run(
            [python, "-m", "app.dreaming.setup", "check"],
            check=True,
            capture_output=True,
            text=True
        )

        print_success("System check passed")
        return True

    except subprocess.CalledProcessError as e:
        print_warning("System check had warnings, but continuing...")
        return True


# ============================================================================
# Startup Scripts
# ============================================================================

def create_startup_scripts(venv_path="venv"):
    """Create convenient startup scripts"""
    print_step(7, 8, "Creating startup scripts")

    # Create run_cli.sh script for interactive CLI
    run_cli_script = """#!/bin/bash
# MoJoAssistant Interactive CLI Launcher
# Starts the interactive chat interface

set -e  # Exit on error

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\\033[0;31m'
GREEN='\\033[0;32m'
BLUE='\\033[0;34m'
NC='\\033[0m' # No Color

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  MoJoAssistant Interactive CLI${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo -e "${RED}✗ Virtual environment not found!${NC}"
    echo -e "  Please run: python3 install.py"
    exit 1
fi

# Activate virtual environment
echo -e "${GREEN}✓ Activating virtual environment${NC}"
source venv/bin/activate

# Check if interactive-cli.py exists
if [ ! -f "app/interactive-cli.py" ]; then
    echo -e "${RED}✗ app/interactive-cli.py not found!${NC}"
    exit 1
fi

# Start CLI
echo -e "${GREEN}✓ Starting interactive CLI${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

exec python app/interactive-cli.py "$@"
"""

    with open("run_cli.sh", 'w') as f:
        f.write(run_cli_script)
    os.chmod("run_cli.sh", 0o755)
    print_success("Created run_cli.sh")

    # Create run_mcp.sh script for MCP server
    run_mcp_script = """#!/bin/bash
# MoJoAssistant MCP Server Launcher
# Starts the MCP server in STDIO mode for Claude Desktop integration

set -e  # Exit on error

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\\033[0;31m'
GREEN='\\033[0;32m'
YELLOW='\\033[1;33m'
BLUE='\\033[0;34m'
NC='\\033[0m' # No Color

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  MoJoAssistant MCP Server${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo -e "${RED}✗ Virtual environment not found!${NC}"
    echo -e "  Please run: python3 install.py"
    exit 1
fi

# Activate virtual environment
echo -e "${GREEN}✓ Activating virtual environment${NC}"
source venv/bin/activate

# Check if unified_mcp_server.py exists
if [ ! -f "unified_mcp_server.py" ]; then
    echo -e "${RED}✗ unified_mcp_server.py not found!${NC}"
    echo -e "  Are you in the MoJoAssistant directory?"
    exit 1
fi

# Check configuration
if [ ! -f "config/llm_config.json" ]; then
    echo -e "${YELLOW}⚠ LLM configuration not found${NC}"
    echo -e "  Creating default configuration..."
    mkdir -p config
    python -c "
import json
config = {
    'local_models': {
        'qwen-coder-small': {
            'type': 'llama',
            'path': '~/.cache/mojoassistant/models/qwen2.5-coder-1.5b-instruct-q5_k_m.gguf',
            'context_length': 32768
        }
    },
    'default_interface': 'qwen-coder-small'
}
with open('config/llm_config.json', 'w') as f:
    json.dump(config, f, indent=2)
"
    echo -e "${GREEN}✓ Configuration created${NC}"
fi

# Start server
echo -e "${GREEN}✓ Starting MCP server in STDIO mode${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

exec python unified_mcp_server.py --mode stdio
"""

    with open("run_mcp.sh", 'w') as f:
        f.write(run_mcp_script)
    os.chmod("run_mcp.sh", 0o755)
    print_success("Created run_mcp.sh")

    return True


# ============================================================================
# Post-Installation
# ============================================================================

def print_next_steps():
    """Print next steps for the user"""
    print_step(8, 8, "Installation Complete!")

    print(f"""
{Colors.GREEN}{Colors.BOLD}
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║              🎉 Installation Successful! 🎉                  ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
{Colors.END}

{Colors.BOLD}What's Next:{Colors.END}

1. {Colors.CYAN}Test the Interactive CLI:{Colors.END}
   ./run_cli.sh

   This starts a chat interface where you can talk to Qwen2.5-Coder-1.7B

2. {Colors.CYAN}Start the MCP Server:{Colors.END}
   ./run_mcp.sh

   This starts the MCP server for Claude Desktop integration

3. {Colors.CYAN}Configure Claude Desktop:{Colors.END}
   Add to your Claude Desktop config (~/.config/claude/claude_desktop_config.json):

   {{
     "mcpServers": {{
       "mojoassistant": {{
         "command": "{Path.cwd() / 'run_mcp.sh'}",
         "args": []
       }}
     }}
   }}

4. {Colors.CYAN}Learn More:{Colors.END}
   - README.md - Full documentation
   - app/dreaming/setup.py - Model management
   - config/llm_config.json - LLM configuration

{Colors.BOLD}Features Available:{Colors.END}

✓ Dreaming (Memory Consolidation) - Automatically consolidates conversations
✓ Scheduler - Background task execution
✓ MCP Tools - 30+ tools for Claude Desktop
✓ OpenCode Manager - Remote development environments
✓ Multi-language Support - English, Chinese, and more

{Colors.BOLD}Need Help?{Colors.END}

- System check: python -m app.dreaming.setup check
- Model validation: python -m app.dreaming.setup validate
- View logs: Check server.log and mcp_server.log

{Colors.GREEN}Happy coding with MoJoAssistant!{Colors.END}
""")


# ============================================================================
# Main Installation Flow
# ============================================================================

def main():
    """Main installation process"""
    print_header()

    # Step 1: Check system
    if not check_python_version():
        return 1

    if not check_disk_space():
        print_error("Insufficient disk space")
        return 1

    # Step 2: Create venv
    if not create_venv():
        return 1

    # Step 3: Install dependencies
    if not install_dependencies():
        return 1

    # Step 4: Download model
    if not download_qwen_model():
        print_error("Model download failed")
        return 1

    validate_model()

    # Step 5: Configuration - AI wizard or default
    print("")
    print("")

    # Offer AI wizard for interactive configuration
    wizard_completed = offer_ai_wizard()

    # If wizard wasn't used or failed, create default config
    if not wizard_completed:
        if not create_config_files():
            return 1

    # Always create memory directories
    if not create_memory_dirs():
        return 1

    # Step 6: Run tests
    run_quick_test()

    # Step 7: Create startup scripts
    if not create_startup_scripts():
        return 1

    # Step 8: Show next steps
    print_next_steps()

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(f"\n\n{Colors.YELLOW}Installation interrupted by user{Colors.END}")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n{Colors.RED}Installation failed with error:{Colors.END}")
        print(f"{Colors.RED}{e}{Colors.END}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
