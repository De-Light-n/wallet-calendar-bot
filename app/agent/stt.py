"""Speech-to-Text module using OpenAI Whisper API."""
from pathlib import Path

from openai import AsyncOpenAI

from app.core.config import settings

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


async def transcribe_audio(file_path: str | Path) -> str:
    """Transcribe an audio file to text using OpenAI Whisper.

    Args:
        file_path: Path to the audio file (.ogg, .mp3, .wav, etc.)

    Returns:
        Transcribed text string.
    """
    file_path = Path(file_path)
    client = _get_client()
    with file_path.open("rb") as audio_file:
        response = await client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            response_format="text",
        )
    return response.strip()
