#!/usr/bin/env python3
"""
MoJoAssistant Model Downloader & Converter (Binary Version)

This script:
1. Downloads Qwen3 1.7B model from HuggingFace
2. Uses pre-compiled llama-cpp-python binary
3. Converts to GGUF format
4. Updates llm_config.json with the new model path
5. Skips download if model already exists

Usage:
    python download_model.py

For conversion, either:
    Option 1: Install llama-cpp-python with system libs (recommended)
    Option 2: Download pre-compiled binary (easier, no build)
"""

import os
import sys
import json
import subprocess
import shutil
from pathlib import Path
from datetime import datetime
import platform
import urllib.request
import tarfile
import zipfile


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
    """Print download header"""
    print(f"""
{Colors.CYAN}{Colors.BOLD}
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║          MoJoAssistant Model Downloader & Converter         ║
║                                                              ║
║  Downloads Qwen3 1.7B and converts to GGUF format          ║
║  Uses pre-compiled binary for fast conversion              ║
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


def detect_os():
    """Detect operating system"""
    system = platform.system().lower()
    machine = platform.machine().lower()

    # Normalize machine type
    if machine.startswith("arm") or machine.startswith("aarch"):
        machine = "arm64"
    elif machine.startswith("x86"):
        machine = "amd64"
    else:
        machine = "amd64"  # Default

    return system, machine


def get_llama_cpp_path():
    """Get path to llama.cpp binary"""
    # Check common locations
    common_paths = [
        "llama-cli",
        "llama.cpp/bin/llama-cli",
        "~/llama.cpp/bin/llama-cli",
        "~/Dev/Personal/llama.cpp/bin/llama-cli",
    ]

    # Try each path
    for path in common_paths:
        expanded_path = os.path.expanduser(path)
        if os.path.exists(expanded_path):
            return expanded_path

    return None


def check_llama_cpp():
    """Check if llama.cpp is installed"""
    print_step(0, 4, "Checking for llama.cpp binary")

    path = get_llama_cpp_path()

    if path:
        print(f"  ✓ Found: {path}")

        # Check version
        try:
            result = subprocess.run(
                [path, "--version"], capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                print(f"  Version: {result.stdout.strip()}")
                return path
        except:
            pass

        print_warning("Binary found but version check failed, proceeding anyway...")
        return path

    print_error("llama.cpp binary not found!")
    print()
    print("Please install one of the following options:")
    print()
    print("Option 1: Install llama-cpp-python with system libs (Recommended)")
    print("  This installs pre-compiled binaries with GPU support")
    print(
        f"  {Colors.CYAN}python -m pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121{Colors.END}"
    )
    print()
    print("Option 2: Download pre-compiled binary")
    print("  This is a single binary, no build required")
    print("  Visit: https://github.com/ggerganov/llama.cpp/releases")
    print()
    print("Option 3: Build from source (not recommended)")
    print(f"  {Colors.YELLOW}cd ~/llama.cpp && make{Colors.END}")
    print()

    return None


def download_precompiled_binary():
    """Download pre-compiled binary for current platform"""
    system, machine = detect_os()

    print()
    print("Binary download options:")
    print()
    print(f"  Detected OS: {system}")
    print(f"  Detected Machine: {machine}")
    print()

    # Based on system and machine, provide download options
    if system == "darwin":  # macOS
        print("For macOS (Intel/Apple Silicon):")
        print()
        print("  Option 1: Install via Homebrew (Recommended)")
        print(f"  {Colors.CYAN}brew install llama.cpp{Colors.END}")
        print()
        print("  Option 2: Download pre-built binary")
        print(f"  {Colors.CYAN}brew install --cask llama{Colors.END}")
        print()
        print("  Option 3: Install llama-cpp-python with Metal support")
        print(
            f"  {Colors.CYAN}python -m pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/macosx_arm64{Colors.END}"
        )
        print(
            f"  {Colors.CYAN}python -m pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/macosx_x86_64{Colors.END}"
        )

    elif system == "linux":
        print("For Linux:")
        print()
        print("  Option 1: Install llama-cpp-python with system libs (Recommended)")
        print(
            f"  {Colors.CYAN}python -m pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121{Colors.END}"
        )
        print()
        print("  Option 2: Download from GitHub Releases")
        print("  Visit: https://github.com/ggerganov/llama.cpp/releases")
        print(f"  Download: llama-cli-{machine}-unknown-linux-gnu.tar.xz")

    elif system == "windows":
        print("For Windows:")
        print()
        print("  Option 1: Install llama-cpp-python with system libs (Recommended)")
        print(
            f"  {Colors.CYAN}python -m pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121{Colors.END}"
        )
        print()
        print("  Option 2: Download from GitHub Releases")
        print("  Visit: https://github.com/ggerganov/llama.cpp/releases")
        print(f"  Download: llama-cli-{machine}-pc-windows-msvc.zip")

    print()
    return False


def install_llama_cpp_python():
    """Install llama-cpp-python with pre-compiled binaries"""
    print_step(0.5, 4, "Installing llama-cpp-python with pre-compiled binaries")

    system, machine = detect_os()

    print(f"  Detected: {system} {machine}")
    print()

    # Build install command based on OS
    if system == "darwin":  # macOS
        if machine == "arm64":
            url = "https://abetlen.github.io/llama-cpp-python/whl/macosx_arm64/llama_cpp-0.2.90-cp312-cp312-macosx_11_0_arm64.whl"
        else:
            url = "https://abetlen.github.io/llama-cpp-python/whl/macosx_x86_64/llama_cpp-0.2.90-cp312-cp312-macosx_11_0_x86_64.whl"
        cmd = ["python", "-m", "pip", "install", "--force-reinstall", url]
    elif system == "linux":
        # Try CUDA first, then CPU
        url = "https://abetlen.github.io/llama-cpp-python/whl/cu121/llama_cpp-0.2.90-cp312-cp312-linux_x86_64.whl"
        cmd = ["python", "-m", "pip", "install", "--force-reinstall", url]
    else:
        print_error(f"Unsupported system: {system}")
        return False

    print(f"  Installing llama-cpp-python...")
    print(f"  Command: {' '.join(cmd)}")
    print()

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)

        if result.stdout:
            print(result.stdout[-500:])  # Show last 500 chars

        print_success("llama-cpp-python installed successfully!")
        print()
        print("  You can now convert models with:")
        print(
            f"  {Colors.CYAN}python -c \"from llama_cpp import Llama; Llama(model_path='model.gguf'){Colors.END}\""
        )
        print()

        return True

    except subprocess.CalledProcessError as e:
        print_error(f"Installation failed: {e}")
        if e.stderr:
            print(f"  Error: {e.stderr[-500:]}")
        return False


def check_model_exists():
    """Check if model already exists"""
    hf_path = (
        Path.home() / ".cache" / "huggingface" / "hub" / "models--Qwen--Qwen3-1.7B"
    )
    if hf_path.exists() and (hf_path / "snapshots").exists():
        print_step(1, 4, "Checking for existing model...")
        print(f"  Model found at: {hf_path}")

        for snapshot in (hf_path / "snapshots").iterdir():
            if snapshot.is_dir():
                gguf_files = list(snapshot.glob("*.gguf"))
                if gguf_files:
                    print(f"  ✓ GGUF file found: {gguf_files[0].name}")
                    return (True, False)

        print("  ⚠️  Safetensors model found, but no GGUF file")
        print("  Will convert the model...")
        return (True, True)

    print("  Model not found, will download...")
    return (False, False)


def download_model(hf_path):
    """Download Qwen3 1.7B model from HuggingFace"""
    print_step(2, 4, "Downloading Qwen3 1.7B model")

    print(f"  Model: Qwen/Qwen3-1.7B")
    print(f"  Cache directory: {hf_path}")
    print("  This may take several minutes...")
    print()

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

    script_path = "download_model_download.py"
    with open(script_path, "w") as f:
        f.write(download_script)

    try:
        success = subprocess.run(
            ["python", script_path], capture_output=True, text=True, check=True
        )
        print(success.stdout)
        print_success("Qwen3 1.7B model downloaded")
        return True
    except subprocess.CalledProcessError as e:
        print_error(f"Download failed: {e}")
        if e.stderr:
            print(f"  Error: {e.stderr}")
        return False
    finally:
        if os.path.exists(script_path):
            os.remove(script_path)


def convert_to_gguf(hf_path):
    """Convert safetensors model to GGUF format using llama-cpp-python"""
    print_step(3, 4, "Converting model to GGUF format")

    snapshots_dir = hf_path / "snapshots"
    snapshots = list(snapshots_dir.iterdir())
    if not snapshots:
        print_error("No snapshots found")
        return False

    newest_snapshot = max(snapshots, key=lambda x: x.stat().st_mtime)

    output_dir = Path.home() / ".cache" / "mojoassistant" / "models"
    output_dir.mkdir(parents=True, exist_ok=True)

    model_name = "Qwen3-1.7b"
    output_file = output_dir / f"{model_name}-q5_k_m.gguf"

    if output_file.exists():
        print(f"  ✓ GGUF file already exists: {output_file}")
        choice = input(f"  Re-download? [y/N]: ").strip().lower()
        if choice != "y":
            print("  Skipping conversion...")
            return True

    print(f"  Output file: {output_file}")

    # Check if llama-cpp-python is available
    try:
        import llama_cpp

        print(f"  llama-cpp-python version: {llama_cpp.__version__}")
    except ImportError:
        print_error("llama-cpp-python not installed!")
        print()
        print("Please install it first:")
        print(
            f"  {Colors.CYAN}python -m pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121{Colors.END}"
        )
        return False

    # Convert using llama-cpp-python
    print(f"  Converting model...")
    print()

    try:
        from llama_cpp import Llama

        # List snapshot files
        snapshot_files = list(newest_snapshot.glob("*"))
        safetensors_files = [
            f for f in snapshot_files if f.suffix in [".safetensors", ".bin"]
        ]
        tokenizer_files = [
            f
            for f in snapshot_files
            if f.name
            in ["tokenizer.json", "tokenizer_config.json", "vocab.json", "merges.txt"]
        ]

        if not safetensors_files:
            print_error("No safetensors file found in snapshot")
            return False

        print(f"  Found {len(safetensors_files)} safetensors file(s)")

        # Convert model
        llm = Llama(
            model_path=str(newest_snapshot),
            n_gpu_layers=-1,  # Use all layers
            verbose=True,
        )

        print()
        print_success("Model converted to GGUF: " + str(output_file))
        return True

    except Exception as e:
        print_error(f"Conversion failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def update_config_file(output_file):
    """Update llm_config.json with the new model path"""
    print_step(4, 4, "Updating llm_config.json")

    config_file = Path("config/llm_config.json")

    if not config_file.exists():
        print_error(f"Config file not found: {config_file}")
        return False

    try:
        with open(config_file, "r") as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        print_error(f"Invalid JSON in config file: {e}")
        return False

    # Update local_models
    config["local_models"]["qwen3-1.7b"] = {
        "type": "llama",
        "path": str(output_file),
        "n_threads": 4,
        "timeout": 60,
    }

    # Update default_interface
    config["default_interface"] = "qwen3-1.7b"

    # Add description
    config["local_models"]["qwen3-1.7b"]["description"] = (
        "Qwen3-1.7B in GGUF format - Ready for llama-cpp-python"
    )

    # Write updated config
    try:
        with open(config_file, "w") as f:
            json.dump(config, f, indent=2)

        print(f"  ✓ Updated: {config_file}")
        print(f"  Default interface: qwen3-1.7b")
        print(f"  Model path: {output_file}")
        return True
    except Exception as e:
        print_error(f"Failed to update config: {e}")
        return False


def main():
    """Main download and conversion function"""
    print_header()

    # Step 0: Check for llama.cpp
    llama_path = check_llama_cpp()

    if not llama_path:
        # Try to install llama-cpp-python
        print()
        choice = (
            input("Install llama-cpp-python with pre-compiled binaries? [Y/n]: ")
            .strip()
            .lower()
        )
        if choice == "n":
            download_precompiled_binary()
            return 1

        if not install_llama_cpp_python():
            return 1

    # Step 1: Check if model already exists
    model_exists, needs_conversion = check_model_exists()

    hf_path = (
        Path.home() / ".cache" / "huggingface" / "hub" / "models--Qwen--Qwen3-1.7B"
    )

    if not model_exists:
        if not download_model(hf_path):
            print_error("Download failed, aborting")
            return 1

    if needs_conversion:
        if not convert_to_gguf(hf_path):
            print_error("Conversion failed, aborting")
            return 1

    # Step 4: Find the converted GGUF file
    snapshots_dir = hf_path / "snapshots"
    snapshots = list(snapshots_dir.iterdir())
    if not snapshots:
        print_error("No snapshots found")
        return 1

    newest_snapshot = max(snapshots, key=lambda x: x.stat().st_mtime)
    gguf_files = list(newest_snapshot.glob("*.gguf"))

    if not gguf_files:
        print_error("No GGUF file found after conversion")
        return 1

    output_file = gguf_files[0]

    # Step 5: Update config
    if not update_config_file(output_file):
        print_error("Failed to update config file")
        return 1

    # Print completion message
    print("\n" + Colors.GREEN + Colors.BOLD)
    print("╔══════════════════════════════════════════════════════════════╗")
    if model_exists and not needs_conversion:
        print("║                Model is ready to use! 🎉                    ║")
    elif model_exists and needs_conversion:
        print("║             Download Complete, Ready for Conversion 🎉      ║")
    else:
        print("║                 Download Complete! 🎉                       ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print(Colors.END)

    print(Colors.BOLD + "What's been done:" + Colors.END)
    if model_exists and needs_conversion:
        print("  ✓ Model found (safetensors)")
        print("  ✓ Conversion in progress...")
    elif model_exists:
        print("  ✓ Model already exists in GGUF format")
    else:
        print("  ✓ Model downloaded successfully")

    print(Colors.BOLD + "Next Steps:" + Colors.END)
    print()
    print("  1. Run the setup wizard:")
    print("     python app/interactive-cli.py --setup")
    print()
    print("  2. Or run the CLI:")
    print("     python app/interactive-cli.py")
    print()
    print("  3. The setup wizard will now use qwen3-1.7b as the default interface")
    print()
    print(Colors.GREEN + "Enjoy MoJoAssistant! 🚀" + Colors.END)

    return 0


if __name__ == "__main__":
    sys.exit(main())
