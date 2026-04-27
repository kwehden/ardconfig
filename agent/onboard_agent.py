"""ardconfig AI-powered board onboarding agent."""
import json
import sys
import os
import re

from strands import Agent
from strands.models.bedrock import BedrockModel
from agent.tools import (
    arduino_cli_search, read_file, write_file,
    validate_profile, run_setup, run_verify
)

SYSTEM_PROMPT = """You are an Arduino board identification agent. Given a USB device's vendor ID and product ID (and optionally a board name), research the board and produce a complete ardconfig board profile JSON.

The profile must contain ALL of these fields:
- id: short identifier (lowercase, hyphenated, e.g., "nucleo-f411re")
- name: human-readable name (e.g., "STM32 Nucleo-F411RE")
- fqbn: Fully Qualified Board Name for arduino-cli (e.g., "STMicroelectronics:stm32:Nucleo_64:pnum=NUCLEO_F411RE")
- core: arduino-cli core package (e.g., "STMicroelectronics:stm32")
- core_url: board manager URL (empty string "" if official Arduino core)
- usb_vendor_id: 4-digit hex USB vendor ID (e.g., "0483")
- usb_product_id: 4-digit hex USB product ID (e.g., "374b")
- usb_driver: Linux kernel driver (typically "cdc_acm" or "ch341-uart")
- serial_pattern: glob for serial device (typically "/dev/ttyACM*" or "/dev/ttyUSB*")
- network_discoverable: boolean (usually false)
- mac_oui_prefixes: array of MAC prefixes (usually empty [])
- blink_led_pin: "LED_BUILTIN" or a pin number
- notes: brief description of the board

Workflow:
1. Read an existing profile from profiles/ to understand the exact schema format
2. Use arduino_cli_search to find matching boards and cores (try 'board listall' with search terms)
3. If the board requires a third-party core, determine the board manager URL
4. Generate the complete profile JSON
5. Write it to profiles/<id>.json using write_file
6. Validate it with validate_profile
7. Run run_setup with the board id to install the core
8. Run run_verify with the board id to compile a test sketch
9. If setup or verify fails, analyze the error, adjust the profile, and retry (max 2 retries)

Output the final profile JSON as your last message, wrapped in ```json fences.
If you cannot determine all fields, set unknown fields to "TODO" and explain what's missing."""


def create_agent():
    model_id = os.environ.get(
        "ARDCONFIG_BEDROCK_MODEL",
        "us.anthropic.claude-sonnet-4-6"
    )
    region = os.environ.get(
        "ARDCONFIG_AWS_REGION",
        os.environ.get("AWS_DEFAULT_REGION", "us-west-2")
    )
    model = BedrockModel(model_id=model_id, region_name=region)
    return Agent(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        tools=[arduino_cli_search, read_file, write_file,
               validate_profile, run_setup, run_verify]
    )


def build_prompt(input_data):
    parts = ["Research and create a board profile for an Arduino-compatible board."]
    if input_data.get("vendor_id") and input_data.get("product_id"):
        parts.append(f"USB Vendor ID: {input_data['vendor_id']}")
        parts.append(f"USB Product ID: {input_data['product_id']}")
    if input_data.get("board_name"):
        parts.append(f"Board name: {input_data['board_name']}")
    if input_data.get("usb_model"):
        parts.append(f"USB model string: {input_data['usb_model']}")
    parts.append("Start by reading an existing profile from profiles/ to understand the schema.")
    return "\n".join(parts)


def parse_agent_output(result):
    text = str(result)
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            profile = json.loads(match.group(1))
            return {"status": "success", "profile": profile}
        except json.JSONDecodeError as e:
            return {"status": "failure", "error": f"Invalid JSON: {e}", "raw": text}
    if '"TODO"' in text:
        return {"status": "partial", "error": "Agent could not determine all fields", "raw": text}
    return {"status": "failure", "error": "Could not parse profile from agent response", "raw": text}


def main():
    input_data = json.loads(sys.stdin.read())
    agent = create_agent()
    prompt = build_prompt(input_data)
    result = agent(prompt)
    output = parse_agent_output(result)
    json.dump(output, sys.stdout, indent=2)


if __name__ == "__main__":
    main()
