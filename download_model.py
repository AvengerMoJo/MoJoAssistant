#!/usr/bin/env python3
"""
MoJoAssistant Model Downloader & Converter

Simplified version:
1. Downloads Qwen3 1.7B from HuggingFace
2. Downloads pre-compiled llama.cpp binary from GitHub releases
3. Converts to GGUF format
4. Updates llm_config.json

Usage:
    python download_model.py

Installation:
    macOS: brew install llama.cpp  (or download binary from GitHub releases)
    Linux: python -m pip install llama-cpp-python
    Windows: python -m pip install llama-cpp-python
"""

import os
import sys
import json
import subprocess
import shutil
from pathlib import Path
import platform
import urllib.request
import tarfile
import zipfile


class Colors:
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
    print(f"{Colors.GREEN}✓ {message}{Colors.END}")


def print_warning(message):
    print(f"{Colors.YELLOW}⚠ {message}{Colors.END}")


def print_error(message):
    print(f"{Colors.RED}✗ {message}{Colors.END}")


def detect_os():
    """Detect operating system"""
    system = platform.system().lower()
    machine = platform.machine().lower()

    if machine.startswith('arm') or machine.startswith('aarch'):
        machine = 'arm64'
    elif machine.startswith('x86'):
        machine = 'amd64'

    return system, machine


def check_llama_cpp():
    """Check if llama.cpp is installed"""
    print_step(0, 4, "Checking for llama.cpp binary")

    system, machine = detect_os()

    # Check for Homebrew (macOS)
    if system == "darwin":
        brew_paths = ["/opt/homebrew/bin/llama", "/usr/local/bin/llama"]
        for brew_path in brew_paths:
            if os.path.exists(brew_path):
                print(f"  ✓ Found Homebrew installation: {brew_path}")
                return brew_path
        print_warning("llama.cpp not found via Homebrew")
        return None

    # Check for llama-cli
    llama_paths = ["llama-cli", "llama"]
    for path in llama_paths:
        if shutil.which(path):
            print(f"  ✓ Found: {path}")
            return path

    print_error("llama.cpp binary not found!")
    return None


def download_llama_binary(system, machine):
    """Download pre-compiled binary from GitHub releases"""
    print_step(0.5, 4, "Downloading pre-compiled binary")

    print(f"  Detected: {system} {machine}")
    print()
    print("Downloading from GitHub releases...")
    print()

    # Download URL based on OS and architecture
    if system == "darwin":
        if machine == "arm64":
            filename = "llama-cli-darwin-arm64.tar.xz"
            url = "https://github.com/ggml-org/llama.cpp/releases/download/bb1fa4e/llama-cli-darwin-arm64.tar.xz"
        else:
            filename = "llama-cli-darwin-x86_64.tar.xz"
            url = "https://github.com/ggml-org/llama.cpp/releases/download/bb1fa4e/llama-cli-darwin-x86_64.tar.xz"

    elif system == "linux":
        if machine == "amd64":
            filename = "llama-cli-linux-x86_64.tar.xz"
            url = "https://github.com/ggml-org/llama.cpp/releases/download/bb1fa4e/llama-cli-linux-x86_64.tar.xz"
        else:
            filename = "llama-cli-linux-arm64.tar.xz"
            url = "https://github.com/ggml-org/llama.cpp/releases/download/bb1fa4e/llama-cli-linux-arm64.tar.xz"

    elif system == "windows":
        if machine == "amd64":
            filename = "llama-cli-windows-x86_64.zip"
            url = "https://github.com/ggml-org/llama.cpp/releases/download/bb1fa4e/llama-cli-windows-x86_64.zip"
        else:
            print_error("Windows ARM not supported yet")
            return None
    else:
        print_error(f"Unsupported system: {system}")
        return None

    print(f"  Download URL: {url}")
    print(f"  File: {filename}")
    print()

    # Download directory
    download_dir = Path.home() / "Downloads"
    download_dir.mkdir(exist_ok=True)

    local_file = download_dir / filename

    # Download file
    try:
        print(f"  Downloading {filename}...")
        urllib.request.urlretrieve(url, local_file)
        print(f"  ✓ Downloaded to: {local_file}")
    except Exception as e:
        print_error(f"Download failed: {e}")
        print()
        print("  Alternative: Download manually from:")
        print(f"  {url}")
        return None

    # Extract file
    print()
    print(f"  Extracting {filename}...")

    try:
        if filename.endswith(".tar.xz"):
            with tarfile.open(local_file, "r:xz") as tar:
                tar.extractall(path=download_dir)
        elif filename.endswith(".zip"):
            with zipfile.ZipFile(local_file, "r") as zip_ref:
                zip_ref.extractall(path=download_dir)

        print(f"  ✓ Extracted to: {download_dir}")

        # Find extracted binary
        extracted_dir = download_dir / filename.replace(".tar.xz", "").replace(".zip", "")

        # Look for llama-cli binary
        if extracted_dir.exists():
            binaries = list(extracted_dir.glob("llama-cli"))
            if binaries:
                return str(binaries[0])

        # If not found in subdirectory, look in download directory
        binaries = list(download_dir.glob("llama-cli"))
        if binaries:
            return str(binaries[0])

        print_error("Could not find extracted binary")
        return None

    except Exception as e:
        print_error(f"Extraction failed: {e}")
        return None


def check_model_exists():
    """Check if model already exists"""
    hf_path = Path.home() / ".cache" / "huggingface" / "hub" / "models--Qwen--Qwen3-1.7B"
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
            ["python", script_path],
            capture_output=True,
            text=True,
            check=True
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


def convert_to_gguf(hf_path, llama_path):
    """Convert safetensors model to GGUF format"""
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
    print(f"  Using: {llama_path}")
    print()

    # Convert using llama.cpp binary
    try:
        # Check if llama.cpp binary exists and is executable
        if not os.path.exists(llama_path):
            print_error(f"Binary not found: {llama_path}")
            return False

        if not os.access(llama_path, os.X_OK):
            print_error(f"Binary not executable: {llama_path}")
            print("  Try: chmod +x", llama_path)
            return False

        print(f"  Running conversion...")

        # Prepare conversion command
        cmd = [
            llama_path,
            "--hf-repo", "Qwen/Qwen3-1.7B",
            "--hf-file", "README.md",  # Just to test
            "--verbose"
        ]

        print(f"  Command: {' '.join(cmd)}")
        print()

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True
        )

        print(result.stdout)
        if result.stderr:
            for line in result.stderr.split('\n'):
                if line.strip() and 'iter' not in line.lower():
                    print(f"    {line}")

        # Check if conversion completed
        if output_file.exists():
            size_gb = output_file.stat().st_size / (1024**3)
            print_success(f"Model converted to GGUF: {output_file} ({size_gb:.2f} GB)")
            return True
        else:
            print_error("Conversion failed: output file not created")
            return False

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
        with open(config_file, 'r') as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        print_error(f"Invalid JSON in config file: {e}")
        return False

    # Update local_models
    config["local_models"]["qwen3-1.7b"] = {
        "type": "llama",
        "path": str(output_file),
        "n_threads": 4,
        "timeout": 60
    }

    # Update default_interface
    config["default_interface"] = "qwen3-1.7b"

    # Add description
    config["local_models"]["qwen3-1.7b"]["description"] = "Qwen3-1.7B in GGUF format"

    # Write updated config
    try:
        with open(config_file, 'w') as f:
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
        # Install llama.cpp binary
        print()
        print("llama.cpp binary not found!")
        print()
        print("Installation options:")
        print()
        print("1. Install via Homebrew (macOS):")
        print(f"   {Colors.CYAN}brew install llama.cpp{Colors.END}")
        print()
        print("2. Download pre-compiled binary:")
        system, machine = detect_os()
        if system == "darwin":
            print(f"   {Colors.CYAN}brew install --cask llama{Colors.END}")
        else:
            print(f"   {Colors.CYAN}Download from: https://github.com/ggml-org/llama.cpp/releases{Colors.END}")
        print()
        print("3. Build from scratch (not recommended)")
        print(f"   {Colors.YELLOW}cd ~/llama.cpp && make{Colors.END}")
        print()

        return 1

    # Step 1: Check if model already exists
    model_exists, needs_conversion = check_model_exists()

    hf_path = Path.home() / ".cache" / "huggingface" / "hub" / "models--Qwen--Qwen3-1.7B"

    if not model_exists:
        if not download_model(hf_path):
            print_error("Download failed, aborting")
            return 1

    if needs_conversion:
        if not convert_to_gguf(hf_path, llama_path):
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
