"""
Gemini Live API WebSocket client wrapper.

Uses the google-genai SDK to establish a Live API session
for bidirectional audio streaming with function calling.
"""

import logging
from typing import Optional, List, Dict, Any, AsyncIterator

from google import genai
from google.genai import types as genai_types

from app.config import settings

logger = logging.getLogger(__name__)


class GeminiLiveClient:
    """Wraps a Gemini Live API session for audio + function-calling."""

    def __init__(self, model: str = None, text_mode: bool = False):
        self._text_mode = text_mode
        # Live API only supports native-audio model; text mode uses the same model
        # but discards audio output and reads output_transcription instead.
        self._model = model or "gemini-2.5-flash-native-audio-latest"
        self._client = genai.Client(api_key=settings.GOOGLE_GEMINI_API_KEY)
        self._session: Optional[genai.live.AsyncSession] = None
        self._ctx = None  # async context manager

    async def connect(
        self,
        system_instruction: str,
        tools: List[genai_types.Tool],
    ) -> None:
        """Establish a Live API session.

        Args:
            system_instruction: System prompt text.
            tools: List of Gemini Tool objects (function declarations + google_search).
        """
        system_content = genai_types.Content(
            parts=[genai_types.Part(text=system_instruction)]
        )

        # Both text and voice modes use AUDIO modality (only option for native-audio model).
        # Text mode discards audio bytes and uses output_transcription for text.
        config = genai_types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=system_content,
            tools=tools,
            input_audio_transcription=genai_types.AudioTranscriptionConfig(),
            output_audio_transcription=genai_types.AudioTranscriptionConfig(),
            thinking_config=genai_types.ThinkingConfig(
                thinking_budget=2048,
            ),
        )

        # connect() returns an async context manager
        self._ctx = self._client.aio.live.connect(
            model=self._model,
            config=config,
        )
        self._session = await self._ctx.__aenter__()
        logger.info("Gemini Live session connected (model=%s)", self._model)

    async def send_audio(self, pcm_bytes: bytes) -> None:
        """Send PCM 16kHz 16-bit LE mono audio to the session."""
        if not self._session:
            raise RuntimeError("Session not connected")

        await self._session.send_realtime_input(
            media=genai_types.Blob(data=pcm_bytes, mime_type="audio/pcm;rate=16000"),
        )

    async def send_text(self, text: str) -> None:
        """Send text input (e.g. from PC chat)."""
        if not self._session:
            raise RuntimeError("Session not connected")

        await self._session.send_client_content(
            turns=[
                genai_types.Content(
                    role="user",
                    parts=[genai_types.Part(text=text)],
                )
            ],
            turn_complete=True,
        )

    async def send_tool_response(self, function_responses: List[genai_types.FunctionResponse]) -> None:
        """Return tool execution results to the model."""
        if not self._session:
            raise RuntimeError("Session not connected")

        await self._session.send_tool_response(
            function_responses=function_responses,
        )

    async def receive(self) -> AsyncIterator[genai_types.LiveServerMessage]:
        """Async iterator over server messages (audio, text, tool calls, etc.).

        The SDK's session.receive() yields messages for a single turn and
        terminates after turn_complete. We restart it in a loop so callers
        get a seamless multi-turn stream.
        """
        if not self._session:
            raise RuntimeError("Session not connected")

        while self._session:
            async for message in self._session.receive():
                yield message

    async def close(self) -> None:
        """Close the Live API session."""
        if self._ctx:
            try:
                await self._ctx.__aexit__(None, None, None)
            except Exception as e:
                logger.warning("Error closing Gemini session: %s", e)
            self._session = None
            self._ctx = None
            logger.info("Gemini Live session closed")
