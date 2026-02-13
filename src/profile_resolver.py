"""
Profile resolution logic for fetching and building agent configurations.

This module handles:
1. Resolving profile_id from room metadata or default pointer
2. Fetching profile from DynamoDB
3. Resolving referenced presets
4. Building complete configuration
"""

import os
import json
import logging
from typing import Any
import boto3
from botocore.exceptions import ClientError
from .config import (
    AgentProfileConfig,
    PresetRef,
    SessionBehaviorConfig,
    RoomIOConfig,
    AudioInputOptions,
    AudioOutputOptions,
    TextInputOptions,
    TextOutputOptions,
    VideoInputOptions,
    ProfileLimits,
    ConnectionOptions,
    get_default_profile,
)

logger = logging.getLogger("profile_resolver")

# DynamoDB configuration
TABLE_NAME = os.getenv("DYNAMODB_TABLE_NAME", "logicall_agent_config")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# Lazy-loaded DynamoDB client
_dynamodb_client = None


def _get_dynamodb_client():
    """Get or create DynamoDB client."""
    global _dynamodb_client
    if _dynamodb_client is None:
        _dynamodb_client = boto3.client("dynamodb", region_name=AWS_REGION)
    return _dynamodb_client


# In-memory cache for profiles (TTL could be added)
_PROFILE_CACHE: dict[str, dict[str, Any]] = {}


async def resolve_profile(
    tenant_id: str = "default",
    profile_id: str | None = None,
    profile_version: str | None = None,
) -> AgentProfileConfig:
    """
    Resolve agent profile configuration.
    
    Args:
        tenant_id: Tenant identifier
        profile_id: Profile ID from room metadata (None = use default)
        profile_version: Specific profile version (None = use latest)
    
    Returns:
        Complete AgentProfileConfig with all options
    """
    # Step 1: Determine profile_id
    if profile_id is None:
        profile_id = await _get_default_profile_id(tenant_id)
        if profile_id is None:
            logger.warning(f"No default profile found for tenant {tenant_id}, using defaults")
            return get_default_profile()
    
    # Step 2: Resolve profile version
    if profile_version is None:
        profile_version = await _get_latest_profile_version(tenant_id, profile_id)
        if profile_version is None:
            logger.warning(f"No version found for profile {profile_id}, using defaults")
            return get_default_profile()
    
    # Step 3: Fetch profile from DynamoDB
    profile_data = await _fetch_profile(tenant_id, profile_id, profile_version)
    if profile_data is None:
        logger.warning(f"Profile {profile_id} v{profile_version} not found, using defaults")
        return get_default_profile()
    
    # Step 4: Build configuration from profile data
    return _build_profile_config(profile_data)


async def _get_default_profile_id(tenant_id: str) -> str | None:
    """
    Fetch default profile pointer from DynamoDB.
    
    Key: pk = TENANT#<tenant_id>, sk = PROFILE_DEFAULT
    """
    try:
        client = _get_dynamodb_client()
        response = client.get_item(
            TableName=TABLE_NAME,
            Key={
                "pk": {"S": f"TENANT#{tenant_id}"},
                "sk": {"S": "PROFILE_DEFAULT"},
            },
        )
        
        if "Item" not in response:
            logger.debug(f"No default profile pointer found for tenant {tenant_id}")
            return None
        
        item = response["Item"]
        profile_id = item.get("profile_id", {}).get("S")
        logger.debug(f"Found default profile: {profile_id} for tenant {tenant_id}")
        return profile_id
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code == "ResourceNotFoundException":
            logger.warning(f"Table {TABLE_NAME} does not exist. Using defaults.")
        else:
            logger.error(f"Error fetching default profile pointer: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching default profile pointer: {e}")
        return None


async def _get_latest_profile_version(tenant_id: str, profile_id: str) -> str | None:
    """
    Fetch latest profile version pointer.
    
    Key: pk = TENANT#<tenant_id>, sk = PROFILE_LATEST#<profile_id>
    """
    try:
        client = _get_dynamodb_client()
        response = client.get_item(
            TableName=TABLE_NAME,
            Key={
                "pk": {"S": f"TENANT#{tenant_id}"},
                "sk": {"S": f"PROFILE_LATEST#{profile_id}"},
            },
        )
        
        if "Item" not in response:
            logger.debug(f"No latest version pointer found for profile {profile_id}")
            return None
        
        item = response["Item"]
        latest_version = item.get("latest_version", {}).get("S")
        logger.debug(f"Found latest version: {latest_version} for profile {profile_id}")
        return latest_version
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code == "ResourceNotFoundException":
            logger.warning(f"Table {TABLE_NAME} does not exist. Using defaults.")
        else:
            logger.error(f"Error fetching latest profile version: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching latest profile version: {e}")
        return None


async def _fetch_profile(
    tenant_id: str, profile_id: str, version: str
) -> dict[str, Any] | None:
    """
    Fetch profile from DynamoDB.
    
    Key: pk = TENANT#<tenant_id>, sk = PROFILE#<profile_id>#V#<version>
    """
    # Check cache first
    cache_key = f"{tenant_id}:{profile_id}:{version}"
    if cache_key in _PROFILE_CACHE:
        logger.debug(f"Profile {profile_id} v{version} found in cache")
        return _PROFILE_CACHE[cache_key]
    
    try:
        client = _get_dynamodb_client()
        response = client.get_item(
            TableName=TABLE_NAME,
            Key={
                "pk": {"S": f"TENANT#{tenant_id}"},
                "sk": {"S": f"PROFILE#{profile_id}#V#{version}"},
            },
        )
        
        if "Item" not in response:
            logger.debug(f"Profile {profile_id} v{version} not found in DynamoDB")
            return None
        
        # Convert DynamoDB item to Python dict
        item = response["Item"]
        profile_data = _dynamodb_item_to_dict(item)
        
        # Cache the profile
        _PROFILE_CACHE[cache_key] = profile_data
        
        logger.debug(f"Profile {profile_id} v{version} loaded from DynamoDB")
        return profile_data
        
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code == "ResourceNotFoundException":
            logger.warning(f"Table {TABLE_NAME} does not exist. Using defaults.")
        else:
            logger.error(f"Error fetching profile: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching profile: {e}")
        return None


def _dynamodb_item_to_dict(item: dict) -> dict[str, Any]:
    """
    Convert DynamoDB item format to Python dict.
    
    DynamoDB uses type descriptors like {"S": "value"} for strings,
    {"N": "123"} for numbers, {"M": {...}} for maps, etc.
    """
    result = {}
    
    for key, value in item.items():
        if "S" in value:
            result[key] = value["S"]
        elif "N" in value:
            # Try to parse as int first, then float
            num_str = value["N"]
            try:
                if "." in num_str:
                    result[key] = float(num_str)
                else:
                    result[key] = int(num_str)
            except ValueError:
                result[key] = num_str
        elif "BOOL" in value:
            result[key] = value["BOOL"]
        elif "NULL" in value:
            result[key] = None
        elif "M" in value:
            result[key] = _dynamodb_item_to_dict(value["M"])
        elif "L" in value:
            result[key] = [
                _dynamodb_item_to_dict({"item": v})["item"] if "M" in v else
                v.get("S") or v.get("N") or v.get("BOOL") or None
                for v in value["L"]
            ]
        elif "SS" in value:
            result[key] = list(value["SS"])
        elif "NS" in value:
            result[key] = [int(n) if "." not in n else float(n) for n in value["NS"]]
        else:
            # Fallback: try to extract value
            result[key] = str(value)
    
    return result


def _build_profile_config(profile_data: dict[str, Any]) -> AgentProfileConfig:
    """
    Build AgentProfileConfig from DynamoDB profile data.
    
    Handles missing fields by using defaults.
    """
    # Extract core fields
    profile_id = profile_data.get("profile_id", "default")
    version = profile_data.get("version", "1")
    tenant_id = profile_data.get("tenant_id", "default")
    
    # Build preset references
    # Handle both dict and DynamoDB map format
    def _parse_preset_ref(preset_data_raw: Any, default_id: str) -> PresetRef | None:
        """Parse preset reference from DynamoDB format or dict."""
        if not preset_data_raw:
            return None
        
        # Check if it's DynamoDB format (has type descriptors)
        if isinstance(preset_data_raw, dict):
            # Check if any value is a DynamoDB type descriptor
            is_dynamodb_format = any(
                isinstance(v, dict) and any(k in v for k in ["S", "N", "BOOL", "M"])
                for v in preset_data_raw.values()
            )
            
            if is_dynamodb_format:
                preset_data = _dynamodb_item_to_dict({"preset": preset_data_raw})["preset"]
            else:
                preset_data = preset_data_raw
        else:
            preset_data = preset_data_raw
        
        return PresetRef(
            id=preset_data.get("id", default_id),
            version=preset_data.get("version"),
        )
    
    llm_ref = _parse_preset_ref(profile_data.get("llm_preset_ref"), "gpt-5.1")
    stt_ref = _parse_preset_ref(profile_data.get("stt_preset_ref"), "nova-3")
    tts_ref = _parse_preset_ref(profile_data.get("tts_preset_ref"), "sonic-3")
    realtime_ref = _parse_preset_ref(
        profile_data.get("realtime_preset_ref"),
        "amazon.nova-2-sonic-v1:0",
    )
    
    # Build limits
    # Handle both dict and DynamoDB map format
    limits_data_raw = profile_data.get("limits", {})
    if isinstance(limits_data_raw, dict):
        # Check if it's a DynamoDB map (has nested type descriptors)
        if any(isinstance(v, dict) and any(k in v for k in ["S", "N", "BOOL"]) for v in limits_data_raw.values()):
            limits_data = _dynamodb_item_to_dict({"limits": limits_data_raw})["limits"]
        else:
            limits_data = limits_data_raw
    else:
        limits_data = {}
    
    limits = ProfileLimits(
        max_minutes=limits_data.get("max_minutes"),
        max_tool_calls=limits_data.get("max_tool_calls"),
        max_tool_calls_per_minute=limits_data.get("max_tool_calls_per_minute"),
    )
    
    # Build session behavior
    # Handle both dict and JSON string formats
    behavior_data_raw = profile_data.get("session_behavior", {})
    if isinstance(behavior_data_raw, str):
        try:
            behavior_data = json.loads(behavior_data_raw)
        except json.JSONDecodeError:
            logger.warning("Failed to parse session_behavior JSON, using defaults")
            behavior_data = {}
    else:
        behavior_data = behavior_data_raw
    
    session_behavior = SessionBehaviorConfig(
        allow_interruptions=behavior_data.get("allow_interruptions", True),
        discard_audio_if_uninterruptible=behavior_data.get("discard_audio_if_uninterruptible", True),
        min_interruption_duration=behavior_data.get("min_interruption_duration", 0.5),
        min_interruption_words=behavior_data.get("min_interruption_words", 0),
        min_endpointing_delay=behavior_data.get("min_endpointing_delay", 0.5),
        max_endpointing_delay=behavior_data.get("max_endpointing_delay", 3.0),
        false_interruption_timeout=behavior_data.get("false_interruption_timeout", 2.0),
        resume_false_interruption=behavior_data.get("resume_false_interruption", True),
        min_consecutive_speech_delay=behavior_data.get("min_consecutive_speech_delay", 0.0),
        user_away_timeout=behavior_data.get("user_away_timeout", 15.0),
        max_tool_steps=behavior_data.get("max_tool_steps", 3),
        use_tts_aligned_transcript=behavior_data.get("use_tts_aligned_transcript"),
        tts_text_transforms=behavior_data.get("tts_text_transforms"),
        preemptive_generation=behavior_data.get("preemptive_generation", False),
        ivr_detection=behavior_data.get("ivr_detection", False),
        turn_detection=behavior_data.get("turn_detection"),
    )
    
    # Build room options
    # Handle both dict and JSON string formats
    room_data_raw = profile_data.get("room_options", {})
    if isinstance(room_data_raw, str):
        try:
            room_data = json.loads(room_data_raw)
        except json.JSONDecodeError:
            logger.warning("Failed to parse room_options JSON, using defaults")
            room_data = {}
    else:
        room_data = room_data_raw
    
    # Audio input options
    audio_input = True
    if isinstance(room_data.get("audio_input"), dict):
        audio_input_data = room_data["audio_input"]
        audio_input = AudioInputOptions(
            sample_rate=audio_input_data.get("sample_rate", 24000),
            num_channels=audio_input_data.get("num_channels", 1),
            frame_size_ms=audio_input_data.get("frame_size_ms", 50),
            noise_cancellation=audio_input_data.get("noise_cancellation"),
            pre_connect_audio=audio_input_data.get("pre_connect_audio", True),
            pre_connect_audio_timeout=audio_input_data.get("pre_connect_audio_timeout", 3.0),
        )
    elif room_data.get("audio_input") is False:
        audio_input = False
    
    # Audio output options
    audio_output = True
    if isinstance(room_data.get("audio_output"), dict):
        audio_output_data = room_data["audio_output"]
        audio_output = AudioOutputOptions(
            sample_rate=audio_output_data.get("sample_rate", 24000),
            num_channels=audio_output_data.get("num_channels", 1),
            track_name=audio_output_data.get("track_name"),
        )
    elif room_data.get("audio_output") is False:
        audio_output = False
    
    # Text input/output options
    text_input = True
    if isinstance(room_data.get("text_input"), dict):
        text_input_data = room_data["text_input"]
        text_input = TextInputOptions(
            enabled=text_input_data.get("enabled", True),
        )
    elif room_data.get("text_input") is False:
        text_input = False
    
    text_output = True
    if isinstance(room_data.get("text_output"), dict):
        text_output_data = room_data["text_output"]
        text_output = TextOutputOptions(
            enabled=text_output_data.get("enabled", True),
            sync_transcription=text_output_data.get("sync_transcription"),
            transcription_speed_factor=text_output_data.get("transcription_speed_factor", 1.0),
        )
    elif room_data.get("text_output") is False:
        text_output = False
    
    # Video input
    video_input = False
    if isinstance(room_data.get("video_input"), dict):
        video_input = VideoInputOptions()
    elif room_data.get("video_input") is True:
        video_input = VideoInputOptions()
    
    room_options = RoomIOConfig(
        text_input=text_input,
        audio_input=audio_input,
        video_input=video_input,
        audio_output=audio_output,
        text_output=text_output,
        participant_kinds=room_data.get("participant_kinds"),
        participant_identity=room_data.get("participant_identity"),
        close_on_disconnect=room_data.get("close_on_disconnect", True),
        delete_room_on_close=room_data.get("delete_room_on_close", False),
    )
    
    # Connection options
    # Handle both dict and JSON string formats
    conn_data_raw = profile_data.get("conn_options", {})
    if isinstance(conn_data_raw, str):
        try:
            conn_data = json.loads(conn_data_raw)
        except json.JSONDecodeError:
            logger.warning("Failed to parse conn_options JSON, using defaults")
            conn_data = {}
    else:
        conn_data = conn_data_raw
    
    conn_options = ConnectionOptions(
        max_unrecoverable_errors=conn_data.get("max_unrecoverable_errors", 3),
    )
    
    return AgentProfileConfig(
        profile_id=profile_id,
        version=version,
        tenant_id=tenant_id,
        mode=profile_data.get("mode", "realtime"),
        system_prompt=profile_data.get("system_prompt", "You are a helpful assistant."),
        language=profile_data.get("language", "en"),
        llm_preset_ref=llm_ref,
        stt_preset_ref=stt_ref,
        tts_preset_ref=tts_ref,
        realtime_preset_ref=realtime_ref,
        tool_refs=profile_data.get("tool_refs", []),
        limits=limits,
        session_behavior=session_behavior,
        room_options=room_options,
        conn_options=conn_options,
        created_at=profile_data.get("created_at"),
        updated_at=profile_data.get("updated_at"),
        status=profile_data.get("status", "active"),
    )

