"""Strands AI tool definitions for ardconfig board onboarding agent."""
import subprocess
import os

from strands import tool

ARDCONFIG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@tool
def arduino_cli_search(command: str) -> str:
    """Run an arduino-cli command. Allowed: 'board listall [search]', 'core search [query]', 'core list', 'config dump'."""
    allowed_prefixes = ["board listall", "core search", "core list", "config dump"]
    if not any(command.startswith(p) for p in allowed_prefixes):
        return f"Error: command '{command}' not allowed. Use: {allowed_prefixes}"
    result = subprocess.run(
        ["arduino-cli"] + command.split(),
        capture_output=True, text=True, timeout=30
    )
    return result.stdout if result.returncode == 0 else f"Error: {result.stderr}"


@tool
def read_file(path: str) -> str:
    """Read a file within the ardconfig project directory."""
    full_path = os.path.normpath(os.path.join(ARDCONFIG_ROOT, path))
    if not full_path.startswith(ARDCONFIG_ROOT):
        return "Error: path outside project directory"
    try:
        with open(full_path) as f:
            return f.read()
    except FileNotFoundError:
        return f"Error: file not found: {path}"


@tool
def write_file(path: str, content: str) -> str:
    """Write content to a file in the profiles/ directory only."""
    full_path = os.path.normpath(os.path.join(ARDCONFIG_ROOT, path))
    profiles_dir = os.path.join(ARDCONFIG_ROOT, "profiles")
    if not full_path.startswith(profiles_dir):
        return "Error: can only write to profiles/ directory"
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w") as f:
        f.write(content)
    return f"Written: {path}"


@tool
def validate_profile(profile_path: str) -> str:
    """Validate a board profile JSON file against the required schema."""
    full_path = os.path.normpath(os.path.join(ARDCONFIG_ROOT, profile_path))
    result = subprocess.run(
        ["jq", "-e", ".id and .fqbn and .core and .usb_vendor_id and .usb_product_id", full_path],
        capture_output=True, text=True
    )
    return "valid" if result.returncode == 0 else f"Invalid: {result.stderr or 'missing required fields'}"


@tool
def run_setup(board_id: str) -> str:
    """Run ardconfig-setup for a specific board to install its core."""
    setup_script = os.path.join(ARDCONFIG_ROOT, "bin", "ardconfig-setup")
    result = subprocess.run(
        [setup_script, "--boards", board_id, "--non-interactive", "--json"],
        capture_output=True, text=True, timeout=300
    )
    return result.stdout if result.returncode == 0 else f"Exit {result.returncode}: {result.stdout}\n{result.stderr}"


@tool
def run_verify(board_id: str) -> str:
    """Run ardconfig-verify for a specific board to compile a test sketch."""
    verify_script = os.path.join(ARDCONFIG_ROOT, "bin", "ardconfig-verify")
    result = subprocess.run(
        [verify_script, "--boards", board_id, "--json"],
        capture_output=True, text=True, timeout=120
    )
    return result.stdout if result.returncode == 0 else f"Exit {result.returncode}: {result.stdout}\n{result.stderr}"
