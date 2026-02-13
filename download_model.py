#!/usr/bin/env python3
"""
MoJoAssistant Model Downloader and Converter

This script:
1. Downloads Qwen3 1.7B model from HuggingFace
2. Converts it to GGUF format using llama.cpp
3. Updates llm_config.json with the new model path
4. Skips download if model already exists

Usage:
    python download_model.py
"""

import os
import sys
import json
import subprocess
import shutil
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
    """Print download header"""
    print(f"""
{Colors.CYAN}{Colors.BOLD}
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║          MoJoAssistant Model Downloader & Converter         ║
║                                                              ║
║  Downloads Qwen3 1.7B and converts to GGUF format          ║
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


def check_model_exists():
    """
    Check if model already exists and if conversion is needed.

    Returns:
        tuple: (exists: bool, needs_conversion: bool)
        - exists=True, needs_conversion=False: GGUF file exists, no action needed
        - exists=True, needs_conversion=True: Safetensors model exists, needs conversion
        - exists=False, needs_conversion=False: Model not found at all
    """
    # Check for safetensors version
    hf_path = (
        Path.home() / ".cache" / "huggingface" / "hub" / "models--Qwen--Qwen3-1.7B"
    )
    if hf_path.exists() and (hf_path / "snapshots").exists():
        print_step(1, 4, "Checking for existing model...")
        print(f"  Model found at: {hf_path}")

        # Check if GGUF file already exists
        for snapshot in (hf_path / "snapshots").iterdir():
            if snapshot.is_dir():
                gguf_files = list(snapshot.glob("*.gguf"))
                if gguf_files:
                    print(f"  ✓ GGUF file found: {gguf_files[0].name}")
                    return (True, False)  # Exists and is ready

        # Safetensors model found but no GGUF
        print("  ⚠️  Safetensors model found, but no GGUF file")
        print("  Will convert the model...")
        return (True, True)  # Exists but needs conversion

    print("  Model not found, will download...")
    return (False, False)  # Doesn't exist at all

    print("  Model not found, will download...")
    return False


def download_model(hf_path):
    """Download Qwen3 1.7B model from HuggingFace"""
    print_step(2, 4, "Downloading Qwen3 1.7B model")

    print(f"  Model: Qwen/Qwen3-1.7B")
    print(f"  Cache directory: {hf_path}")
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
    """Convert safetensors model to GGUF format using llama.cpp"""
    print_step(3, 4, "Converting model to GGUF format")

    # Find the newest snapshot
    snapshots_dir = hf_path / "snapshots"
    snapshots = list(snapshots_dir.iterdir())
    if not snapshots:
        print_error("No snapshots found")
        return False

    newest_snapshot = max(snapshots, key=lambda x: x.stat().st_mtime)

    # Model output path (same location as current models)
    output_dir = Path.home() / ".cache" / "mojoassistant" / "models"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Find llama.cpp directory
    llama_cpp_dirs = [
        Path.home() / "Dev" / "Personal" / "llama.cpp",
        Path.home() / "Dev" / "llama.cpp",
        Path.home() / "llama.cpp",
        Path.cwd(),
    ]

    llama_cpp_dir = None
    for dir_path in llama_cpp_dirs:
        convert_script = dir_path / "convert-hf-to-gguf.py"
        if convert_script.exists():
            llama_cpp_dir = dir_path
            break

    if not llama_cpp_dir:
        print_error("llama.cpp not found!")
        print("  Please clone llama.cpp: https://github.com/ggerganov/llama.cpp")
        print(f"  Or update llama_cpp_dirs in {os.path.basename(__file__)}")
        return False

    print(f"  llama.cpp found at: {llama_cpp_dir}")

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

    # Convert command
    # Get the base model name from the directory name
    model_name = "Qwen3-1.7b"
    output_file = output_dir / f"{model_name}-q5_k_m.gguf"

    if output_file.exists():
        print(f"  ✓ GGUF file already exists: {output_file}")
        choice = input(f"  Re-download? [y/N]: ").strip().lower()
        if choice != "y":
            print("  Skipping conversion...")
            return True

    print(f"  Output file: {output_file}")

    # Prepare conversion command
    cmd = [
        "python",
        str(llama_cpp_dir / "convert-hf-to-gguf.py"),
        str(newest_snapshot),
        "--outfile",
        str(output_file),
        "--outtype",
        "q5_k_m",
    ]

    # Add tokenizer files if they exist
    for tokenizer_file in tokenizer_files:
        cmd.extend(["--tokenizer_file", str(tokenizer_file)])

    print(f"  Running conversion...")
    print(f"  Command: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)

        # Print conversion output
        if result.stdout:
            print(result.stdout)

        if result.stderr:
            # Filter out progress bars and verbose output
            for line in result.stderr.split("\n"):
                if line.strip() and not any(
                    x in line for x in ["iter=", "pl%", "loading:"]
                ):
                    print(f"    {line}")

        if output_file.exists() and output_file.stat().st_size > 0:
            file_size_gb = output_file.stat().st_size / (1024**3)
            print_success(
                f"Model converted to GGUF: {output_file} ({file_size_gb:.2f} GB)"
            )
            return True
        else:
            print_error("Conversion failed: output file not created")
            return False

    except subprocess.CalledProcessError as e:
        print_error(f"Conversion failed: {e}")
        if e.stderr:
            print(f"  Error output:\n{e.stderr}")
        return False
    except FileNotFoundError:
        print_error("llama.cpp python script not found")
        print("  Please ensure llama.cpp is installed and convert-hf-to-gguf.py exists")
        return False


def update_config_file(output_file):
    """Update llm_config.json with the new model path"""
    print_step(4, 4, "Updating llm_config.json")

    config_file = Path("config/llm_config.json")

    if not config_file.exists():
        print_error(f"Config file not found: {config_file}")
        return False

    # Read current config
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

    # Step 1: Check if model already exists
    model_exists, needs_conversion = check_model_exists()

    hf_path = (
        Path.home() / ".cache" / "huggingface" / "hub" / "models--Qwen--Qwen3-1.7B"
    )

    if not model_exists:
        # Step 2: Download model
        print_step(2, 4, "Downloading Qwen3 1.7B model")

        print(f"  Model: Qwen/Qwen3-1.7B")
        print(f"  Cache directory: {hf_path}")
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
        script_path = "download_model_download.py"
        with open(script_path, "w") as f:
            f.write(download_script)

        try:
            success = subprocess.run(
                ["python", script_path], capture_output=True, text=True, check=True
            )
            print(success.stdout)
            print_success("Qwen3 1.7B model downloaded")
        except subprocess.CalledProcessError as e:
            print_error(f"Download failed: {e}")
            if e.stderr:
                print(f"  Error: {e.stderr}")
            return 1
        finally:
            if os.path.exists(script_path):
                os.remove(script_path)

    # Step 3: Convert to GGUF (only if needed)
    if needs_conversion:
        if not convert_to_gguf(hf_path):
            print_error("Conversion failed, aborting")
            return 1

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
        print("  ⚠️  Ready for conversion (requires llama.cpp)")
    elif model_exists:
        print("  ✓ Model already exists in GGUF format")
    else:
        print("  ✓ Model downloaded successfully")

    print(Colors.BOLD + "Next Steps:" + Colors.END)
    print()
    print("  1. Install llama.cpp for model conversion:")
    print("     cd ~")
    print("     git clone https://github.com/ggerganov/llama.cpp")
    print("     cd llama.cpp")
    print("     git lfs install")
    print("     make")
    print()
    print("  2. Run the downloader again to convert the model:")
    print("     python download_model.py")
    print()
    print("  3. After conversion, run the setup wizard:")
    print("     python app/interactive-cli.py --setup")
    print()
    print(Colors.GREEN + "Enjoy MoJoAssistant! 🚀" + Colors.END)

    return 0


if __name__ == "__main__":
    sys.exit(main())
