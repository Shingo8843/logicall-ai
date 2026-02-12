"""
Migration 002: Seed default profile and presets.

This migration seeds the DynamoDB table with:
1. Default profile pointer
2. Default agent profile (v1)
3. Default model presets (LLM, STT, TTS)
4. Profile latest pointer
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

# Load .env.local from project root
from dotenv import load_dotenv
env_path = project_root / ".env.local"
if env_path.exists():
    load_dotenv(str(env_path))
else:
    load_dotenv()  # Try current directory

from src.config import get_default_profile

TABLE_NAME = os.getenv("DYNAMODB_TABLE_NAME", "logicall_agent_config")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
TENANT_ID = os.getenv("TENANT_ID", "default")


def put_item(dynamodb, item: dict):
    """Put an item into DynamoDB."""
    try:
        dynamodb.put_item(TableName=TABLE_NAME, Item=item)
        return True
    except ClientError as e:
        print(f"ERROR: Error putting item: {e}")
        return False


def seed_default_profile_pointer(dynamodb):
    """Seed default profile pointer."""
    print("Seeding default profile pointer...")
    
    item = {
        "pk": {"S": f"TENANT#{TENANT_ID}"},
        "sk": {"S": "PROFILE_DEFAULT"},
        "entity_type": {"S": "latest_pointer"},
        "profile_id": {"S": "default"},
        "profile_version": {"S": "1"},
        "updated_at": {"S": datetime.now(timezone.utc).isoformat()},
    }
    
    if put_item(dynamodb, item):
        print("  [OK] Default profile pointer created")
        return True
    return False


def seed_default_profile(dynamodb):
    """Seed default agent profile."""
    print("Seeding default agent profile...")
    
    default_profile = get_default_profile()
    now = datetime.now(timezone.utc).isoformat()
    
    # Build profile item
    item = {
        "pk": {"S": f"TENANT#{TENANT_ID}"},
        "sk": {"S": f"PROFILE#{default_profile.profile_id}#V#{default_profile.version}"},
        "entity_type": {"S": "profile"},
        "profile_id": {"S": default_profile.profile_id},
        "version": {"S": default_profile.version},
        "tenant_id": {"S": default_profile.tenant_id},
        "mode": {"S": default_profile.mode},
        "system_prompt": {"S": default_profile.system_prompt},
        "language": {"S": default_profile.language},
        "status": {"S": default_profile.status},
        "created_at": {"S": now},
        "updated_at": {"S": now},
    }
    
    # Add preset references
    if default_profile.llm_preset_ref:
        item["llm_preset_ref"] = {
            "M": {
                "id": {"S": default_profile.llm_preset_ref.id},
                "version": {"S": default_profile.llm_preset_ref.version or "1"},
            }
        }
    
    if default_profile.stt_preset_ref:
        item["stt_preset_ref"] = {
            "M": {
                "id": {"S": default_profile.stt_preset_ref.id},
                "version": {"S": default_profile.stt_preset_ref.version or "1"},
            }
        }
    
    if default_profile.tts_preset_ref:
        item["tts_preset_ref"] = {
            "M": {
                "id": {"S": default_profile.tts_preset_ref.id},
                "version": {"S": default_profile.tts_preset_ref.version or "1"},
            }
        }
    
    # Add limits
    if default_profile.limits:
        limits_map = {}
        if default_profile.limits.max_minutes is not None:
            limits_map["max_minutes"] = {"N": str(default_profile.limits.max_minutes)}
        if default_profile.limits.max_tool_calls is not None:
            limits_map["max_tool_calls"] = {"N": str(default_profile.limits.max_tool_calls)}
        if default_profile.limits.max_tool_calls_per_minute is not None:
            limits_map["max_tool_calls_per_minute"] = {
                "N": str(default_profile.limits.max_tool_calls_per_minute)
            }
        if limits_map:
            item["limits"] = {"M": limits_map}
    
    # Add session behavior (simplified - store as JSON string for now)
    behavior = default_profile.session_behavior
    behavior_dict = {
        "allow_interruptions": behavior.allow_interruptions,
        "discard_audio_if_uninterruptible": behavior.discard_audio_if_uninterruptible,
        "min_interruption_duration": behavior.min_interruption_duration,
        "min_interruption_words": behavior.min_interruption_words,
        "min_endpointing_delay": behavior.min_endpointing_delay,
        "max_endpointing_delay": behavior.max_endpointing_delay,
        "false_interruption_timeout": behavior.false_interruption_timeout,
        "resume_false_interruption": behavior.resume_false_interruption,
        "min_consecutive_speech_delay": behavior.min_consecutive_speech_delay,
        "user_away_timeout": behavior.user_away_timeout,
        "max_tool_steps": behavior.max_tool_steps,
        "preemptive_generation": behavior.preemptive_generation,
        "ivr_detection": behavior.ivr_detection,
    }
    item["session_behavior"] = {"S": json.dumps(behavior_dict)}
    
    # Add room options (simplified - store as JSON string)
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
    
    # Add connection options
    conn_opts = {
        "max_unrecoverable_errors": default_profile.conn_options.max_unrecoverable_errors,
    }
    item["conn_options"] = {"S": json.dumps(conn_opts)}
    
    if put_item(dynamodb, item):
        print("  [OK] Default profile created")
        return True
    return False


def seed_profile_latest_pointer(dynamodb):
    """Seed profile latest version pointer."""
    print("Seeding profile latest pointer...")
    
    item = {
        "pk": {"S": f"TENANT#{TENANT_ID}"},
        "sk": {"S": "PROFILE_LATEST#default"},
        "entity_type": {"S": "latest_pointer"},
        "latest_version": {"S": "1"},
        "updated_at": {"S": datetime.now(timezone.utc).isoformat()},
    }
    
    if put_item(dynamodb, item):
        print("  [OK] Profile latest pointer created")
        return True
    return False


def seed_llm_preset(dynamodb):
    """Seed default LLM preset."""
    print("Seeding default LLM preset...")
    
    item = {
        "pk": {"S": "PRESET#LLM"},
        "sk": {"S": "ID#gpt-4.1-mini#V#1"},
        "entity_type": {"S": "preset"},
        "preset_id": {"S": "gpt-4.1-mini"},
        "version": {"S": "1"},
        "provider": {"S": "openai"},
        "model": {"S": "gpt-4.1-mini"},
        "params": {
            "M": {
                "temperature": {"N": "0.7"},
                "max_tokens": {"N": "4096"},
                "top_p": {"N": "1.0"},
            }
        },
        "created_at": {"S": datetime.now(timezone.utc).isoformat()},
        "updated_at": {"S": datetime.now(timezone.utc).isoformat()},
    }
    
    if put_item(dynamodb, item):
        print("  [OK] LLM preset created")
        return True
    return False


def seed_stt_preset(dynamodb):
    """Seed default STT preset."""
    print("Seeding default STT preset...")
    
    item = {
        "pk": {"S": "PRESET#STT"},
        "sk": {"S": "ID#nova-3#V#1"},
        "entity_type": {"S": "preset"},
        "preset_id": {"S": "nova-3"},
        "version": {"S": "1"},
        "provider": {"S": "deepgram"},
        "model": {"S": "nova-3"},
        "params": {
            "M": {
                "language": {"S": "multi"},
                "punctuation": {"BOOL": True},
                "diarization": {"BOOL": False},
            }
        },
        "created_at": {"S": datetime.now(timezone.utc).isoformat()},
        "updated_at": {"S": datetime.now(timezone.utc).isoformat()},
    }
    
    if put_item(dynamodb, item):
        print("  [OK] STT preset created")
        return True
    return False


def seed_tts_preset(dynamodb):
    """Seed default TTS preset."""
    print("Seeding default TTS preset...")
    
    item = {
        "pk": {"S": "PRESET#TTS"},
        "sk": {"S": "ID#sonic-3#V#1"},
        "entity_type": {"S": "preset"},
        "preset_id": {"S": "sonic-3"},
        "version": {"S": "1"},
        "provider": {"S": "cartesia"},
        "model": {"S": "sonic-3"},
        "voice_id": {"S": "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc"},
        "params": {
            "M": {
                "speed": {"N": "1.0"},
                "style": {"S": "default"},
            }
        },
        "created_at": {"S": datetime.now(timezone.utc).isoformat()},
        "updated_at": {"S": datetime.now(timezone.utc).isoformat()},
    }
    
    if put_item(dynamodb, item):
        print("  [OK] TTS preset created")
        return True
    return False


def run_migration():
    """Run the seed migration."""
    dynamodb = boto3.client("dynamodb", region_name=AWS_REGION)
    
    # Verify table exists
    try:
        dynamodb.describe_table(TableName=TABLE_NAME)
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            print(f"ERROR: Table {TABLE_NAME} does not exist. Run migration 001 first.")
            print(f"Run: python migrations/001_create_table.py")
            return False
        else:
            print(f"ERROR: {e}")
            return False
    
    print(f"\nSeeding defaults for tenant: {TENANT_ID}")
    print("=" * 60)
    
    success = True
    success &= seed_default_profile_pointer(dynamodb)
    success &= seed_default_profile(dynamodb)
    success &= seed_profile_latest_pointer(dynamodb)
    success &= seed_llm_preset(dynamodb)
    success &= seed_stt_preset(dynamodb)
    success &= seed_tts_preset(dynamodb)
    
    return success


if __name__ == "__main__":
    print("=" * 60)
    print("Migration 002: Seed Default Data")
    print("=" * 60)
    
    success = run_migration()
    
    if success:
        print("\n" + "=" * 60)
        print("[SUCCESS] Migration 002 completed successfully!")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("[FAILED] Migration 002 failed!")
        print("=" * 60)
        sys.exit(1)

