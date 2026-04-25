"""Helper utilities for the Telegram bot."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import aiofiles
import aiohttp


async def download_telegram_file(file_url: str, suffix: str = ".ogg") -> Path:
    """Download a file from Telegram's servers to a temporary local file.

    Args:
        file_url: Full HTTPS URL of the file on Telegram servers.
        suffix:   File extension for the temporary file (default: ``.ogg``).

    Returns:
        Path to the downloaded temporary file.  The caller is responsible
        for deleting the file when it is no longer needed.
    """
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.close()
    dest = Path(tmp.name)

    async with aiohttp.ClientSession() as session:
        async with session.get(file_url) as resp:
            resp.raise_for_status()
            async with aiofiles.open(dest, "wb") as f:
                async for chunk in resp.content.iter_chunked(8192):
                    await f.write(chunk)

    return dest
