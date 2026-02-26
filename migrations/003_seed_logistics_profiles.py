"""
Migration 003: Seed logistics agent profiles.

Creates DynamoDB profile items for each prompt in prompts/:
- carrier-checkup, delivery-reschedule, delivery-reminder, post-delivery,
  inbound-triage, claims-intake, carrier-onboarding

All use realtime mode with Amazon Nova. Prompt text is loaded from
prompts/prompt_*.txt and supports {{logistics_company}}, {{agent_name}}, etc.
"""

import os
import sys
import json
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

# Add parent directory to path for imports
script_dir = Path(__file__).parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

env_path = project_root / ".env.local"
if env_path.exists():
    load_dotenv(str(env_path))
else:
    load_dotenv()

TABLE_NAME = os.getenv("DYNAMODB_TABLE_NAME", "logicall_agent_config")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
TENANT_ID = os.getenv("TENANT_ID", "default")
PROMPTS_DIR = project_root / "prompts"

# Map profile_id -> prompt filename (without path)
PROFILE_PROMPTS = [
    ("carrier-checkup", "prompt_check_up.txt"),
    ("delivery-reschedule", "prompt_delivery_reschedule.txt"),
    ("delivery-reminder", "prompt_delivery_reminder.txt"),
    ("post-delivery", "prompt_post_delivery.txt"),
    ("inbound-triage", "prompt_inbound_triage.txt"),
    ("claims-intake", "prompt_claims_intake.txt"),
    ("carrier-onboarding", "prompt_carrier_onboarding.txt"),
]


def put_item(dynamodb, item: dict) -> bool:
    """Put an item into DynamoDB."""
    try:
        dynamodb.put_item(TableName=TABLE_NAME, Item=item)
        return True
    except ClientError as e:
        print(f"ERROR: Error putting item: {e}")
        return False


def load_prompt(filename: str) -> str:
    """Load prompt text from prompts dir. Returns placeholder if file missing."""
    path = PROMPTS_DIR / filename
    if not path.exists():
        return f"[Prompt not found: {filename}. Add prompts/{filename} and re-run.]"
    return path.read_text(encoding="utf-8").strip()


def seed_profile(dynamodb, profile_id: str, system_prompt: str) -> bool:
    """Seed one logistics profile (realtime, Amazon Nova, no tools)."""
    print(f"  Seeding profile: {profile_id}...")
    now = datetime.now(timezone.utc).isoformat()
    version = "1"

    item = {
        "pk": {"S": f"TENANT#{TENANT_ID}"},
        "sk": {"S": f"PROFILE#{profile_id}#V#{version}"},
        "entity_type": {"S": "profile"},
        "profile_id": {"S": profile_id},
        "version": {"S": version},
        "tenant_id": {"S": TENANT_ID},
        "mode": {"S": "realtime"},
        "system_prompt": {"S": system_prompt},
        "language": {"S": "en"},
        "status": {"S": "active"},
        "created_at": {"S": now},
        "updated_at": {"S": now},
    }

    # Realtime preset only (Amazon Nova)
    item["realtime_preset_ref"] = {
        "M": {
            "id": {"S": "amazon-nova"},
            "version": {"S": "1"},
        }
    }

    # Limits: 30 min, no tool limits (no tools enabled)
    item["limits"] = {
        "M": {
            "max_minutes": {"N": "30"},
        }
    }

    # No tool refs for these voice-only logistics profiles
    # item["tool_refs"] omitted -> profile_resolver treats as []

    # SIP outbound trunk for phone calls (env override optional)
    sip_trunk = os.getenv("SIP_OUTBOUND_TRUNK_ID", "ST_wCPfwPCXu7HV")
    if sip_trunk:
        item["sip_outbound_trunk_id"] = {"S": sip_trunk}

    # Session behavior (same defaults as default profile)
    behavior_dict = {
        "allow_interruptions": True,
        "discard_audio_if_uninterruptible": True,
        "min_interruption_duration": 0.5,
        "min_interruption_words": 0,
        "min_endpointing_delay": 0.5,
        "max_endpointing_delay": 3.0,
        "false_interruption_timeout": 2.0,
        "resume_false_interruption": True,
        "min_consecutive_speech_delay": 0.0,
        "user_away_timeout": 15.0,
        "max_tool_steps": 3,
        "preemptive_generation": False,
        "ivr_detection": False,
    }
    item["session_behavior"] = {"S": json.dumps(behavior_dict)}

    # Room options
    room_opts = {
        "text_input": True,
        "audio_input": True,
        "video_input": False,
        "audio_output": True,
        "text_output": True,
        "close_on_disconnect": True,
        "delete_room_on_close": False,
    }
    item["room_options"] = {"S": json.dumps(room_opts)}

    # Connection options
    item["conn_options"] = {"S": json.dumps({"max_unrecoverable_errors": 3})}

    if put_item(dynamodb, item):
        print(f"    [OK] {profile_id} v{version}")
        return True
    return False


def seed_profile_latest_pointer(dynamodb, profile_id: str) -> bool:
    """Seed PROFILE_LATEST#<profile_id> so latest version resolves to 1."""
    item = {
        "pk": {"S": f"TENANT#{TENANT_ID}"},
        "sk": {"S": f"PROFILE_LATEST#{profile_id}"},
        "entity_type": {"S": "latest_pointer"},
        "latest_version": {"S": "1"},
        "updated_at": {"S": datetime.now(timezone.utc).isoformat()},
    }
    if put_item(dynamodb, item):
        return True
    return False


def run_migration() -> bool:
    """Run the logistics profiles seed."""
    dynamodb = boto3.client("dynamodb", region_name=AWS_REGION)

    try:
        dynamodb.describe_table(TableName=TABLE_NAME)
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            print(f"ERROR: Table {TABLE_NAME} does not exist. Run migration 001 and 002 first.")
            return False
        raise

    if not PROMPTS_DIR.exists():
        print(f"ERROR: Prompts directory not found: {PROMPTS_DIR}")
        return False

    print(f"\nSeeding logistics profiles for tenant: {TENANT_ID}")
    print("=" * 60)

    success = True
    for profile_id, filename in PROFILE_PROMPTS:
        prompt_text = load_prompt(filename)
        success &= seed_profile(dynamodb, profile_id, prompt_text)
        success &= seed_profile_latest_pointer(dynamodb, profile_id)

    return success


if __name__ == "__main__":
    print("=" * 60)
    print("Migration 003: Seed Logistics Agent Profiles")
    print("=" * 60)

    success = run_migration()

    if success:
        print("\n" + "=" * 60)
        print("[SUCCESS] Migration 003 completed.")
        print("Profiles: carrier-checkup, delivery-reschedule, delivery-reminder,")
        print("         post-delivery, inbound-triage, claims-intake, carrier-onboarding")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("[FAILED] Migration 003 failed!")
        print("=" * 60)
        sys.exit(1)
