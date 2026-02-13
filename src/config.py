"""
Configuration system for LiveKit Agents with full default values.

This module defines all configuration options that can be controlled via
DynamoDB profiles, with sensible defaults for all settings.
"""

from dataclasses import dataclass, field
from typing import Literal, Sequence, Any
from livekit import rtc


# ============================================================================
# Model Preset References
# ============================================================================

@dataclass
class PresetRef:
    """Reference to a model preset in DynamoDB."""
    id: str
    version: str | None = None  # None means use latest


# ============================================================================
# Session Behavior Configuration
# ============================================================================

@dataclass
class SessionBehaviorConfig:
    """AgentSession behavior configuration options."""
    
    # Interruption & Turn Detection
    allow_interruptions: bool = True
    discard_audio_if_uninterruptible: bool = True
    min_interruption_duration: float = 0.5  # seconds
    min_interruption_words: int = 0
    min_endpointing_delay: float = 0.5  # seconds
    max_endpointing_delay: float = 3.0  # seconds
    false_interruption_timeout: float | None = 2.0  # seconds, None to disable
    resume_false_interruption: bool = True
    min_consecutive_speech_delay: float = 0.0  # seconds
    
    # User State Management
    user_away_timeout: float | None = 15.0  # seconds, None to disable
    
    # Tool Execution
    max_tool_steps: int = 3
    
    # TTS Configuration
    use_tts_aligned_transcript: bool | None = None  # None = auto-detect
    tts_text_transforms: Sequence[str] | None = None  # None = use defaults ["filter_markdown", "filter_emoji"]
    
    # Advanced Features
    preemptive_generation: bool = False
    ivr_detection: bool = False
    
    # Turn Detection Mode
    # "stt" | "vad" | "realtime_llm" | "manual" | None (auto-select)
    turn_detection: Literal["stt", "vad", "realtime_llm", "manual"] | None = None


# ============================================================================
# Connection Options
# ============================================================================

@dataclass
class ConnectionOptions:
    """API connection options for STT, LLM, TTS."""
    
    max_unrecoverable_errors: int = 3
    # Note: stt_conn_options, llm_conn_options, tts_conn_options
    # are provider-specific and typically use defaults from SDK


# ============================================================================
# Room I/O Configuration
# ============================================================================

@dataclass
class AudioInputOptions:
    """Audio input configuration."""
    sample_rate: int = 24000
    num_channels: int = 1
    frame_size_ms: int = 50
    noise_cancellation: str | None = None  # Reference to noise cancellation preset
    pre_connect_audio: bool = True
    pre_connect_audio_timeout: float = 3.0  # seconds


@dataclass
class AudioOutputOptions:
    """Audio output configuration."""
    sample_rate: int = 24000
    num_channels: int = 1
    track_name: str | None = None  # None = use default "roomio_audio"
    # track_publish_options uses defaults (SOURCE_MICROPHONE)


@dataclass
class TextInputOptions:
    """Text input configuration."""
    enabled: bool = True
    # text_input_cb uses default (interrupt and generate reply)


@dataclass
class TextOutputOptions:
    """Text output (transcription) configuration."""
    enabled: bool = True
    sync_transcription: bool | None = None  # None = auto
    transcription_speed_factor: float = 1.0


@dataclass
class VideoInputOptions:
    """Video input configuration."""
    enabled: bool = False


@dataclass
class RoomIOConfig:
    """Complete Room I/O configuration."""
    text_input: TextInputOptions | bool = True
    audio_input: AudioInputOptions | bool = True
    video_input: VideoInputOptions | bool = False
    audio_output: AudioOutputOptions | bool = True
    text_output: TextOutputOptions | bool = True
    
    # Participant Management
    participant_kinds: list[str] | None = None  # None = use defaults [SIP, STANDARD, CONNECTOR]
    participant_identity: str | None = None  # None = link to first participant
    
    # Cleanup Options
    close_on_disconnect: bool = True
    delete_room_on_close: bool = False


# ============================================================================
# Profile Limits
# ============================================================================

@dataclass
class ProfileLimits:
    """Profile-level limits and constraints."""
    max_minutes: int | None = None  # None = no limit
    max_tool_calls: int | None = None  # None = no limit
    max_tool_calls_per_minute: int | None = None  # None = no limit


# ============================================================================
# Complete Agent Profile Configuration
# ============================================================================

@dataclass
class AgentProfileConfig:
    """
    Complete agent profile configuration with all options.
    
    This represents a profile loaded from DynamoDB with all configuration
    options that can be surfaced at the agent dispatch phase.
    """
    
    # Profile Identity
    profile_id: str
    version: str
    tenant_id: str = "default"
    
    # Core Configuration
    mode: Literal["pipeline", "realtime"] = "pipeline"
    system_prompt: str = "You are a helpful voice AI assistant."
    language: str = "en"
    
    # Model Preset References
    llm_preset_ref: PresetRef | None = None
    stt_preset_ref: PresetRef | None = None
    tts_preset_ref: PresetRef | None = None
    realtime_preset_ref: PresetRef | None = None
    
    # Tool References
    tool_refs: list[str] = field(default_factory=list)
    
    # Limits
    limits: ProfileLimits = field(default_factory=ProfileLimits)
    
    # Session Behavior
    session_behavior: SessionBehaviorConfig = field(default_factory=SessionBehaviorConfig)
    
    # Room I/O
    room_options: RoomIOConfig = field(default_factory=RoomIOConfig)
    
    # Connection Options
    conn_options: ConnectionOptions = field(default_factory=ConnectionOptions)
    
    # Metadata
    created_at: str | None = None
    updated_at: str | None = None
    status: str = "active"


# ============================================================================
# Default Profile
# ============================================================================

def get_default_profile() -> AgentProfileConfig:
    """
    Get a default profile configuration with all sensible defaults.
    
    This is used when no profile is found in DynamoDB or as a fallback.
    """
    return AgentProfileConfig(
        profile_id="default",
        version="1",
        tenant_id="default",
        mode="realtime",
        system_prompt="""You are a helpful voice AI assistant. 
        The user is interacting with you via voice, even if you perceive the conversation as text.
        Your responses are concise, to the point, and without any complex formatting or punctuation including emojis, asterisks, or other symbols.
        You are curious, friendly, and have a sense of humor.""",
        language="en",
        llm_preset_ref=PresetRef(id="gpt-5.1", version="1"),
        stt_preset_ref=PresetRef(id="nova-3", version="1"),
        tts_preset_ref=PresetRef(id="sonic-3", version="1"),
        realtime_preset_ref=PresetRef(id="amazon.nova-2-sonic-v1:0", version="1"),
        tool_refs=["http:weather_geocode@1", "http:weather_current@1"],
        limits=ProfileLimits(
            max_minutes=30,
            max_tool_calls=50,
            max_tool_calls_per_minute=10,
        ),
        session_behavior=SessionBehaviorConfig(
            allow_interruptions=True,
            discard_audio_if_uninterruptible=True,
            min_interruption_duration=0.5,
            min_interruption_words=0,
            min_endpointing_delay=0.5,
            max_endpointing_delay=3.0,
            false_interruption_timeout=2.0,
            resume_false_interruption=True,
            min_consecutive_speech_delay=0.0,
            user_away_timeout=15.0,
            max_tool_steps=3,
            use_tts_aligned_transcript=None,
            tts_text_transforms=None,  # Will use defaults
            preemptive_generation=False,
            ivr_detection=False,
            turn_detection=None,  # Auto-select
        ),
        room_options=RoomIOConfig(
            text_input=True,
            audio_input=AudioInputOptions(),
            video_input=False,
            audio_output=AudioOutputOptions(),
            text_output=TextOutputOptions(),
            participant_kinds=None,  # Use defaults
            participant_identity=None,
            close_on_disconnect=True,
            delete_room_on_close=False,
        ),
        conn_options=ConnectionOptions(
            max_unrecoverable_errors=3,
        ),
    )

