"""
Build AgentSession from profile configuration.

This module handles converting AgentProfileConfig into a fully configured
AgentSession with all models, options, and room settings.
"""

import os
import logging
import inspect
import re
from typing import Any
import boto3
from botocore.exceptions import ClientError
from livekit import rtc
from livekit.agents import (
    AgentSession,
    inference,
    room_io,
)
from livekit.agents.voice.agent_session import SessionConnectOptions
from livekit.plugins import noise_cancellation
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from .config import (
    AgentProfileConfig,
    AudioInputOptions,
    AudioOutputOptions,
    TextInputOptions,
    TextOutputOptions,
    VideoInputOptions,
    PresetRef,
)

logger = logging.getLogger("session_builder")

# DynamoDB configuration
TABLE_NAME = os.getenv("DYNAMODB_TABLE_NAME", "logicall_agent_config")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# Lazy-loaded DynamoDB client
_dynamodb_client = None


def _construct_with_supported_kwargs(
    factory_name: str,
    factory: Any,
    kwargs: dict[str, Any],
):
    """
    Construct an inference object while gracefully handling SDK signature drift.

    Presets in DynamoDB may include parameters not supported by the installed
    LiveKit version. We filter using signature introspection when available and
    fallback to retrying without unsupported kwargs based on TypeError messages.
    """
    filtered_kwargs = dict(kwargs)

    # Best-effort static filtering via signature introspection.
    try:
        signature = inspect.signature(factory)
        supports_var_kwargs = any(
            p.kind == inspect.Parameter.VAR_KEYWORD
            for p in signature.parameters.values()
        )
        if not supports_var_kwargs:
            allowed = set(signature.parameters.keys())
            removed = [k for k in list(filtered_kwargs.keys()) if k not in allowed]
            for key in removed:
                filtered_kwargs.pop(key, None)
            if removed:
                logger.warning(
                    "%s dropping unsupported kwargs via signature: %s",
                    factory_name,
                    removed,
                )
    except (TypeError, ValueError):
        # Some callables may not expose signatures.
        pass

    # Runtime fallback filtering for callables that reject unknown kwargs.
    while True:
        try:
            return factory(**filtered_kwargs)
        except TypeError as err:
            msg = str(err)
            match = re.search(r"unexpected keyword argument '([^']+)'", msg)
            if not match:
                raise

            bad_key = match.group(1)
            if bad_key not in filtered_kwargs:
                raise

            logger.warning(
                "%s dropping unsupported kwarg at runtime: %s",
                factory_name,
                bad_key,
            )
            filtered_kwargs.pop(bad_key, None)

            if not filtered_kwargs:
                raise


def _get_dynamodb_client():
    """Get or create DynamoDB client."""
    global _dynamodb_client
    if _dynamodb_client is None:
        _dynamodb_client = boto3.client("dynamodb", region_name=AWS_REGION)
    return _dynamodb_client


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


async def build_session(
    profile: AgentProfileConfig,
    vad: Any,  # silero.VAD
    job_context: Any,  # JobContext for userdata
) -> tuple[AgentSession, room_io.RoomOptions]:
    """
    Build AgentSession and RoomOptions from profile configuration.
    
    Args:
        profile: Complete agent profile configuration
        vad: Pre-loaded VAD instance
        job_context: JobContext for accessing userdata
    
    Returns:
        Tuple of (AgentSession, RoomOptions)
    """
    # Resolve models based on mode
    if profile.mode == "realtime":
        llm = await _resolve_realtime_model(profile.realtime_preset_ref)
        stt = None
        tts = None
    else:
        # Pipeline mode
        llm = await _resolve_llm_model(profile.llm_preset_ref)
        stt = await _resolve_stt_model(profile.stt_preset_ref, profile.language)
        tts = await _resolve_tts_model(profile.tts_preset_ref)
    
    # Build session behavior options
    behavior = profile.session_behavior
    
    # Build connection options
    conn_opts = SessionConnectOptions(
        max_unrecoverable_errors=profile.conn_options.max_unrecoverable_errors,
    )
    
    # Build turn detection
    turn_detection = _resolve_turn_detection(behavior.turn_detection, profile.mode)
    
    # Build TTS text transforms
    tts_transforms = behavior.tts_text_transforms
    if tts_transforms is None:
        # Use defaults
        tts_transforms = ["filter_markdown", "filter_emoji"]
    
    # Create AgentSession
    session = AgentSession(
        stt=stt,
        llm=llm,
        tts=tts,
        vad=vad,
        turn_detection=turn_detection,
        allow_interruptions=behavior.allow_interruptions,
        discard_audio_if_uninterruptible=behavior.discard_audio_if_uninterruptible,
        min_interruption_duration=behavior.min_interruption_duration,
        min_interruption_words=behavior.min_interruption_words,
        min_endpointing_delay=behavior.min_endpointing_delay,
        max_endpointing_delay=behavior.max_endpointing_delay,
        max_tool_steps=behavior.max_tool_steps,
        user_away_timeout=behavior.user_away_timeout,
        false_interruption_timeout=behavior.false_interruption_timeout,
        resume_false_interruption=behavior.resume_false_interruption,
        min_consecutive_speech_delay=behavior.min_consecutive_speech_delay,
        use_tts_aligned_transcript=behavior.use_tts_aligned_transcript,
        tts_text_transforms=tts_transforms,
        preemptive_generation=behavior.preemptive_generation,
        ivr_detection=behavior.ivr_detection,
        conn_options=conn_opts,
    )
    
    # Build RoomOptions
    room_opts = _build_room_options(profile.room_options)
    
    return session, room_opts


async def _fetch_preset(preset_type: str, preset_ref: PresetRef) -> dict[str, Any] | None:
    """
    Generic function to fetch preset from DynamoDB.
    
    Args:
        preset_type: One of "LLM", "STT", "TTS", "REALTIME"
        preset_ref: Preset reference with id and optional version
    
    Returns:
        Preset data as dict or None if not found
    """
    preset_id = preset_ref.id
    version = preset_ref.version or "1"  # Default to version 1 if not specified
    
    try:
        client = _get_dynamodb_client()
        response = client.get_item(
            TableName=TABLE_NAME,
            Key={
                "pk": {"S": f"PRESET#{preset_type}"},
                "sk": {"S": f"ID#{preset_id}#V#{version}"},
            },
        )
        
        if "Item" not in response:
            logger.warning(f"{preset_type} preset {preset_id} v{version} not found in DynamoDB")
            return None
        
        # Convert DynamoDB item to Python dict
        item = response["Item"]
        preset_data = _dynamodb_item_to_dict(item)
        
        logger.debug(f"Fetched {preset_type} preset {preset_id} v{version} from DynamoDB")
        return preset_data
        
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code == "ResourceNotFoundException":
            logger.warning(f"Table {TABLE_NAME} does not exist. Using defaults.")
        else:
            logger.error(f"Error fetching {preset_type} preset: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching {preset_type} preset: {e}")
        return None


async def _fetch_llm_preset(preset_ref: PresetRef) -> dict[str, Any] | None:
    """Fetch LLM preset from DynamoDB."""
    return await _fetch_preset("LLM", preset_ref)


async def _resolve_llm_model(preset_ref: PresetRef | None):  # type: ignore
    """Resolve LLM model from preset reference."""
    if preset_ref is None:
        # Default LLM
        return inference.LLM(model="openai/gpt-5.1")
    
    # Fetch preset from DynamoDB and build model
    preset_data = await _fetch_llm_preset(preset_ref)
    
    if preset_data is None:
        # Fallback to using preset ID as model string
        logger.warning(f"LLM preset not found, falling back to preset ID: {preset_ref.id}")
        model_string = f"openai/{preset_ref.id}"
        return inference.LLM(model=model_string)
    
    # Extract preset configuration
    provider = preset_data.get("provider", "openai")
    model = preset_data.get("model", preset_ref.id)
    params = preset_data.get("params", {})
    
    # Build model string
    model_id = _normalize_provider_model_id(model, provider)
    model_string = f"{provider}/{model_id}"
    
    # Extract LLM parameters
    llm_kwargs = {"model": model_string}
    if params:
        if "temperature" in params:
            llm_kwargs["temperature"] = float(params["temperature"])
        if "max_tokens" in params:
            llm_kwargs["max_tokens"] = int(params["max_tokens"])
        if "top_p" in params:
            llm_kwargs["top_p"] = float(params["top_p"])
        if "tool_calling_mode" in params:
            llm_kwargs["tool_calling_mode"] = params["tool_calling_mode"]
    
    logger.debug(f"Resolving LLM: {model_string} with params {llm_kwargs}")
    return _construct_with_supported_kwargs("inference.LLM", inference.LLM, llm_kwargs)


async def _fetch_stt_preset(preset_ref: PresetRef) -> dict[str, Any] | None:
    """Fetch STT preset from DynamoDB."""
    return await _fetch_preset("STT", preset_ref)


async def _resolve_stt_model(preset_ref: PresetRef | None, language: str):  # type: ignore
    """Resolve STT model from preset reference."""
    if preset_ref is None:
        # Default STT
        return inference.STT(model="deepgram/nova-3", language="multi")
    
    # Fetch preset from DynamoDB and build model
    preset_data = await _fetch_stt_preset(preset_ref)
    
    if preset_data is None:
        # Fallback to using preset ID as model string
        logger.warning(f"STT preset not found, falling back to preset ID: {preset_ref.id}")
        preset_id = _normalize_provider_model_id(str(preset_ref.id), "deepgram")
        model_string = f"deepgram/{preset_id}"
        return inference.STT(model=model_string, language=language)
    
    # Extract preset configuration
    provider = preset_data.get("provider", "deepgram")
    model = preset_data.get("model", preset_ref.id)
    params = preset_data.get("params", {})
    
    # Build model string
    model_id = _normalize_provider_model_id(model, provider)
    model_string = f"{provider}/{model_id}"
    
    # Extract STT parameters
    # Use language from params if available, otherwise use profile language
    stt_language = params.get("language") or language
    
    stt_kwargs = {"model": model_string, "language": stt_language}
    if params:
        if "punctuation" in params:
            stt_kwargs["punctuation"] = bool(params["punctuation"])
        if "diarization" in params:
            stt_kwargs["diarization"] = bool(params["diarization"])
    
    logger.debug(f"Resolving STT: {model_string} (language={stt_language})")
    return _construct_with_supported_kwargs("inference.STT", inference.STT, stt_kwargs)


async def _fetch_tts_preset(preset_ref: PresetRef) -> dict[str, Any] | None:
    """Fetch TTS preset from DynamoDB."""
    return await _fetch_preset("TTS", preset_ref)


async def _resolve_tts_model(preset_ref: PresetRef | None):  # type: ignore
    """Resolve TTS model from preset reference."""
    if preset_ref is None:
        # Default TTS
        return inference.TTS(
            model="cartesia/sonic-3",
            voice="9626c31c-bec5-4cca-baa8-f8ba9e84c8bc"
        )
    
    # Fetch preset from DynamoDB and build model with voice
    preset_data = await _fetch_tts_preset(preset_ref)
    
    if preset_data is None:
        # Fallback to using preset ID as model string
        logger.warning(f"TTS preset not found, falling back to preset ID: {preset_ref.id}")
        preset_id = _normalize_provider_model_id(str(preset_ref.id), "cartesia")
        model_string = f"cartesia/{preset_id}"
        return inference.TTS(model=model_string)
    
    # Extract preset configuration
    provider = preset_data.get("provider", "cartesia")
    model = preset_data.get("model", preset_ref.id)
    voice_id = preset_data.get("voice_id")
    
    # Build model string
    model_id = _normalize_provider_model_id(model, provider)
    model_string = f"{provider}/{model_id}"
    
    # Build TTS with voice_id if available
    if voice_id:
        logger.debug(f"Resolving TTS: {model_string} with voice {voice_id}")
        return _construct_with_supported_kwargs(
            "inference.TTS",
            inference.TTS,
            {"model": model_string, "voice": voice_id},
        )
    else:
        logger.debug(f"Resolving TTS: {model_string} (no voice_id in preset)")
        return _construct_with_supported_kwargs(
            "inference.TTS",
            inference.TTS,
            {"model": model_string},
        )


def _normalize_provider_model_id(model_id: str, provider: str) -> str:
    """Normalize preset IDs that may include a provider prefix."""
    provider_prefix = f"{provider}-"
    slash_prefix = f"{provider}/"

    if model_id.startswith(provider_prefix):
        return model_id[len(provider_prefix):]
    if model_id.startswith(slash_prefix):
        return model_id[len(slash_prefix):]
    return model_id


async def _fetch_realtime_preset(preset_ref: PresetRef) -> dict[str, Any] | None:
    """Fetch Realtime preset from DynamoDB."""
    return await _fetch_preset("REALTIME", preset_ref)


async def _resolve_realtime_model(preset_ref: PresetRef | None):  # type: ignore
    """Resolve realtime model from preset reference."""
    if preset_ref is None:
        # Default realtime model: Amazon Nova Sonic via AWS plugin.
        try:
            from livekit.plugins import aws

            return aws.realtime.RealtimeModel(model="amazon.nova-2-sonic-v1:0")
        except ImportError:
            logger.error("AWS plugin not installed for realtime model")
            raise
    
    # Fetch preset from DynamoDB and build model
    preset_data = await _fetch_realtime_preset(preset_ref)
    
    if preset_data is None:
        # Fallback to default Amazon Nova Sonic realtime.
        logger.warning(f"Realtime preset not found, falling back to default: {preset_ref.id}")
        try:
            from livekit.plugins import aws

            return aws.realtime.RealtimeModel(model="amazon.nova-2-sonic-v1:0")
        except ImportError:
            logger.error("AWS plugin not installed for realtime model")
            raise
    
    # Extract preset configuration
    provider = str(preset_data.get("provider", "aws")).lower()
    model = preset_data.get("model")
    voice = preset_data.get("voice")
    region = preset_data.get("region")
    params = preset_data.get("params", {})
    
    if provider in {"aws", "amazon", "bedrock"}:
        try:
            from livekit.plugins import aws

            realtime_kwargs: dict[str, Any] = {}
            if model:
                realtime_kwargs["model"] = str(model)
            if voice:
                realtime_kwargs["voice"] = str(voice)
            if region:
                realtime_kwargs["region"] = str(region)
            if params and isinstance(params, dict):
                if "temperature" in params:
                    realtime_kwargs["temperature"] = float(params["temperature"])
                if "top_p" in params:
                    realtime_kwargs["top_p"] = float(params["top_p"])
                if "max_tokens" in params:
                    realtime_kwargs["max_tokens"] = int(params["max_tokens"])

            if "model" not in realtime_kwargs:
                realtime_kwargs["model"] = "amazon.nova-2-sonic-v1:0"

            logger.debug(
                "Resolving Realtime model: aws model=%s voice=%s region=%s",
                realtime_kwargs.get("model"),
                realtime_kwargs.get("voice"),
                realtime_kwargs.get("region"),
            )
            return _construct_with_supported_kwargs(
                "aws.realtime.RealtimeModel",
                aws.realtime.RealtimeModel,
                realtime_kwargs,
            )
        except ImportError:
            logger.error("AWS plugin not installed for realtime model")
            raise

    if provider == "openai":
        try:
            from livekit.plugins import openai

            realtime_kwargs = {"voice": str(voice) if voice else "marin"}
            logger.debug("Resolving Realtime model: openai voice=%s", realtime_kwargs["voice"])
            return _construct_with_supported_kwargs(
                "openai.realtime.RealtimeModel",
                openai.realtime.RealtimeModel,
                realtime_kwargs,
            )
        except ImportError:
            logger.error("OpenAI plugin not installed for realtime model")
            raise

    logger.warning("Realtime provider %s not supported, falling back to AWS Nova Sonic", provider)
    try:
        from livekit.plugins import aws

        return aws.realtime.RealtimeModel(model="amazon.nova-2-sonic-v1:0")
    except ImportError:
        logger.error("AWS plugin not installed for realtime model")
        raise


def _resolve_turn_detection(
    turn_detection: str | None,
    mode: str,
):  # type: ignore
    """
    Resolve turn detection mode.
    
    If None, auto-selects based on available models.
    """
    if turn_detection == "stt":
        return "stt"
    elif turn_detection == "vad":
        return "vad"
    elif turn_detection == "realtime_llm":
        return "realtime_llm"
    elif turn_detection == "manual":
        return "manual"
    elif turn_detection is None:
        # Auto-select: prefer MultilingualModel if available
        if mode == "pipeline":
            return MultilingualModel()
        return None
    else:
        logger.warning(f"Unknown turn_detection mode: {turn_detection}, using auto")
        return None


def _build_room_options(room_config: Any) -> room_io.RoomOptions:  # type: ignore
    """Build RoomOptions from room configuration."""
    
    # Audio input
    audio_input = room_config.audio_input
    if isinstance(audio_input, AudioInputOptions):
        # Build noise cancellation selector if needed
        noise_cancellation = None
        if audio_input.noise_cancellation:
            # TODO: Resolve noise cancellation preset
            # For now, use default selector
            noise_cancellation = lambda params: (
                noise_cancellation.BVCTelephony()
                if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                else noise_cancellation.BVC()
            )
        
        audio_input_opts = room_io.AudioInputOptions(
            sample_rate=audio_input.sample_rate,
            num_channels=audio_input.num_channels,
            frame_size_ms=audio_input.frame_size_ms,
            noise_cancellation=noise_cancellation,
            pre_connect_audio=audio_input.pre_connect_audio,
            pre_connect_audio_timeout=audio_input.pre_connect_audio_timeout,
        )
    elif audio_input is False:
        audio_input_opts = False
    else:
        audio_input_opts = True
    
    # Audio output
    audio_output = room_config.audio_output
    if isinstance(audio_output, AudioOutputOptions):
        audio_output_kwargs: dict[str, Any] = {
            "sample_rate": audio_output.sample_rate,
            "num_channels": audio_output.num_channels,
        }
        # Avoid passing None through to RTC create_audio_track(name=...), which expects str.
        if audio_output.track_name:
            audio_output_kwargs["track_name"] = audio_output.track_name
        audio_output_opts = room_io.AudioOutputOptions(**audio_output_kwargs)
    elif audio_output is False:
        audio_output_opts = False
    else:
        audio_output_opts = True
    
    # Text input
    text_input = room_config.text_input
    if isinstance(text_input, TextInputOptions):
        text_input_opts = room_io.TextInputOptions()
    elif text_input is False:
        text_input_opts = False
    else:
        text_input_opts = True
    
    # Text output
    text_output = room_config.text_output
    if isinstance(text_output, TextOutputOptions):
        text_output_opts = room_io.TextOutputOptions(
            sync_transcription=text_output.sync_transcription,
            transcription_speed_factor=text_output.transcription_speed_factor,
        )
    elif text_output is False:
        text_output_opts = False
    else:
        text_output_opts = True
    
    # Video input
    video_input = room_config.video_input
    if video_input is True or isinstance(video_input, VideoInputOptions):
        video_input_opts = True
    else:
        video_input_opts = False
    
    # Participant kinds
    participant_kinds = None
    if room_config.participant_kinds:
        # Convert string list to ParticipantKind enum list
        kind_map = {
            "PARTICIPANT_KIND_SIP": rtc.ParticipantKind.PARTICIPANT_KIND_SIP,
            "PARTICIPANT_KIND_STANDARD": rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD,
            "PARTICIPANT_KIND_CONNECTOR": rtc.ParticipantKind.PARTICIPANT_KIND_CONNECTOR,
        }
        participant_kinds = [
            kind_map[k] for k in room_config.participant_kinds if k in kind_map
        ]
    
    return room_io.RoomOptions(
        text_input=text_input_opts,
        audio_input=audio_input_opts,
        video_input=video_input_opts,
        audio_output=audio_output_opts,
        text_output=text_output_opts,
        participant_kinds=participant_kinds,
        participant_identity=room_config.participant_identity,
        close_on_disconnect=room_config.close_on_disconnect,
        delete_room_on_close=room_config.delete_room_on_close,
    )

