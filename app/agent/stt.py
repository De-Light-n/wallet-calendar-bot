"""Speech-to-Text module using OpenAI Whisper API."""
import os
from pathlib import Path

import httpx
from openai import AsyncOpenAI

_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


async def transcribe_audio(file_path: str | Path) -> str:
    """Transcribe an audio file to text using OpenAI Whisper.

    Args:
        file_path: Path to the audio file (.ogg, .mp3, .wav, etc.)

    Returns:
        Transcribed text string.
    """
    file_path = Path(file_path)
    with file_path.open("rb") as audio_file:
        response = await _client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            response_format="text",
        )
    return response.strip()
