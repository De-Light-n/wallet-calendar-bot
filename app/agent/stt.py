"""Speech-to-Text module using Groq Whisper API."""
import logging
from pathlib import Path

from openai import AsyncOpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)

_STT_MODEL = "whisper-large-v3"
_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        if not settings.groq_api_key:
            logger.warning(
                "GROQ_API_KEY is empty — STT calls will fail with 401 from Groq."
            )
        # Використовуємо Groq як OpenAI-сумісний API
        _client = AsyncOpenAI(
            api_key=settings.groq_api_key,
            base_url="https://api.groq.com/openai/v1",
        )
    return _client


async def transcribe_audio(file_path: str | Path) -> str:
    """Transcribe an audio file to text using Groq Whisper."""
    file_path = Path(file_path)
    file_size = file_path.stat().st_size if file_path.exists() else None
    logger.info(
        "STT: transcribing file=%s size=%s model=%s",
        file_path,
        file_size,
        _STT_MODEL,
    )

    client = _get_client()
    with file_path.open("rb") as audio_file:
        response = await client.audio.transcriptions.create(
            model=_STT_MODEL,
            file=audio_file,
            response_format="text",
        )
    text = response.strip()
    logger.info(
        "STT: completed file=%s text_len=%s",
        file_path,
        len(text),
    )
    return text