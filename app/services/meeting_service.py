"""
Meeting Service - orchestrates slide generation, TTS, and Q&A during meetings.
"""
import asyncio
import base64
import json
import logging
from typing import Optional

import aiohttp
from app.config import settings
from app.models.meeting_schemas import (
    MeetingPhase, MeetingState, SlideContent,
    WsSlide, WsStateUpdate, WsTranscript, WsError,
)

logger = logging.getLogger(__name__)


class MeetingSession:
    """
    Manages a single meeting session.

    Lifecycle:
      1. prepare(topic, content) → generates slides via LLM
      2. present() → iterates slides, generates TTS, streams to client
      3. handle_question(text) → pauses, answers, optionally updates slides
      4. end() → summary generation
    """

    def __init__(self, session_id: str, user_id: str, websocket):
        self.session_id = session_id
        self.user_id = user_id
        self.ws = websocket
        self.state = MeetingState(phase=MeetingPhase.PREPARING)
        self.slides: list[SlideContent] = []
        self.transcript: list[dict] = []
        self.is_speaking = False
        self._cancel_presentation = False
        self._presentation_task: Optional[asyncio.Task] = None
        self._audio_played_event = asyncio.Event()

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------

    async def _send_json(self, data: dict):
        try:
            await self.ws.send_json(data)
        except Exception as e:
            logger.warning("WS send failed: %s", e)

    async def _send_state(self):
        await self._send_json(WsStateUpdate(state=self.state).model_dump())

    async def _send_transcript(self, speaker: str, text: str):
        self.transcript.append({"speaker": speaker, "text": text})
        await self._send_json(WsTranscript(speaker=speaker, text=text).model_dump())

    # ------------------------------------------------------------------
    # Slide generation
    # ------------------------------------------------------------------

    async def prepare(self, topic: str, content: str):
        """Generate slides from proposal content using LLM."""
        self.state.topic = topic
        self.state.phase = MeetingPhase.PREPARING
        await self._send_state()

        try:
            slides_json = await self._generate_slides(topic, content)
            self.slides = slides_json
            self.state.total_slides = len(self.slides)
            self.state.current_slide = 0
            logger.info("Generated %d slides for meeting %s", len(self.slides), self.session_id)
        except Exception as e:
            logger.error("Slide generation failed: %s", e)
            await self._send_json(WsError(message=f"スライド生成に失敗しました: {e}").model_dump())
            return

        # Auto-start presentation
        self._presentation_task = asyncio.create_task(self._present_all())

    async def _generate_slides(self, topic: str, content: str) -> list[SlideContent]:
        """Generate slides using Gemini."""
        import google.generativeai as genai

        genai.configure(api_key=settings.GOOGLE_GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-2.0-flash")

        prompt = f"""あなたはプレゼンテーション構成の専門家です。
以下の提案内容をMTG用のスライドに変換してください。

# ルール
- 5〜10枚のスライドに分割
- 各スライドにはtitle、bullets（3〜5個）、note（そのスライドで話す内容を自然な口語体で2〜3文）を含む
- 最初のスライドは概要/アジェンダ
- 最後のスライドはまとめ/次のステップ
- noteは「です・ます調」で、実際にプレゼンで話すセリフとして書く

# 提案タイトル
{topic}

# 提案内容
{content}

# 出力形式
JSONの配列を返してください。各要素:
{{"title": "...", "bullets": ["...", "..."], "note": "...", "highlight": "..."}}

JSONのみ出力。説明文やmarkdownフェンスは不要。"""

        response = await model.generate_content_async(prompt)
        raw = response.text.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        slides_data = json.loads(raw)
        slides = []
        for i, s in enumerate(slides_data):
            slides.append(SlideContent(
                index=i,
                total=len(slides_data),
                title=s.get("title", ""),
                bullets=s.get("bullets", []),
                note=s.get("note", ""),
                highlight=s.get("highlight"),
            ))
        return slides

    # ------------------------------------------------------------------
    # Presentation flow
    # ------------------------------------------------------------------

    async def _wait_audio_played(self, timeout: float = 120):
        """Wait until client signals audio playback finished."""
        self._audio_played_event.clear()
        try:
            await asyncio.wait_for(self._audio_played_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("audio_played timeout after %.0fs", timeout)

    def notify_audio_played(self):
        """Called when client sends audio_played message."""
        self._audio_played_event.set()

    async def _present_all(self):
        """Present all slides sequentially, waiting for audio playback between slides."""
        self.state.phase = MeetingPhase.PRESENTING
        await self._send_state()

        for i, slide in enumerate(self.slides):
            if self._cancel_presentation:
                break

            self.state.current_slide = i
            await self._send_state()

            # Send slide content
            narration = slide.note or f"{slide.title}について説明します。"
            await self._send_json(WsSlide(slide=slide, narration=narration).model_dump())
            await self._send_transcript("dan", narration)

            # Generate and stream TTS audio
            self.is_speaking = True
            await self._speak(narration)
            self.is_speaking = False

            if self._cancel_presentation:
                break

            # Wait for the client to finish playing the audio before moving on
            await self._wait_audio_played()

            if self._cancel_presentation:
                break

        if not self._cancel_presentation:
            # Presentation complete, enter Q&A mode
            self.state.phase = MeetingPhase.QA
            await self._send_state()
            qa_msg = "以上がプレゼンテーションの内容です。ご質問があればどうぞ。"
            await self._send_transcript("dan", qa_msg)
            await self._speak(qa_msg)

    async def _speak(self, text: str):
        """Generate TTS audio and stream as binary frames."""
        elevenlabs_key = getattr(settings, 'ELEVENLABS_API_KEY', None)
        elevenlabs_voice = getattr(settings, 'ELEVENLABS_VOICE_ID', None) or "pNInz6obpgDQGcFmaJgB"
        elevenlabs_model = getattr(settings, 'ELEVENLABS_MODEL_ID', 'eleven_v3')

        if not elevenlabs_key:
            # Fallback: send text-only, no audio
            logger.warning("ElevenLabs not configured, skipping TTS")
            await asyncio.sleep(len(text) * 0.05)  # Simulate speaking time
            return

        try:
            # Use ElevenLabs streaming TTS for low latency
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{elevenlabs_voice}/stream"
            headers = {
                "xi-api-key": elevenlabs_key,
                "Content-Type": "application/json",
            }
            payload = {
                "text": text,
                "model_id": elevenlabs_model,
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75,
                },
                "output_format": "mp3_44100_128",
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error("TTS stream error: %s - %s", resp.status, error_text)
                        return

                    # Stream audio chunks to client as binary WebSocket frames
                    async for chunk in resp.content.iter_chunked(4096):
                        if self._cancel_presentation:
                            break
                        try:
                            await self.ws.send_bytes(chunk)
                        except Exception:
                            break

            # Signal end of audio for this segment
            await self._send_json({"type": "audio_end"})

        except Exception as e:
            logger.error("TTS failed: %s", e)

    # ------------------------------------------------------------------
    # User interaction
    # ------------------------------------------------------------------

    async def handle_question(self, text: str):
        """Handle user question during presentation."""
        # Pause presentation if currently running
        was_presenting = self.state.phase == MeetingPhase.PRESENTING
        if was_presenting:
            self._cancel_presentation = True
            if self._presentation_task and not self._presentation_task.done():
                self._presentation_task.cancel()
                try:
                    await self._presentation_task
                except (asyncio.CancelledError, Exception):
                    pass

        self.state.phase = MeetingPhase.QA
        await self._send_state()
        await self._send_transcript("user", text)

        # Generate answer
        answer = await self._generate_answer(text)
        await self._send_transcript("dan", answer)
        self.is_speaking = True
        await self._speak(answer)
        self.is_speaking = False

    async def _generate_answer(self, question: str) -> str:
        """Generate an answer to the user's question using Gemini."""
        import google.generativeai as genai

        genai.configure(api_key=settings.GOOGLE_GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-2.0-flash")

        slides_context = "\n".join(
            f"スライド{s.index + 1}: {s.title}\n" + "\n".join(f"  - {b}" for b in s.bullets)
            for s in self.slides
        )
        transcript_context = "\n".join(
            f"{'ダン' if t['speaker'] == 'dan' else 'ユーザー'}: {t['text']}"
            for t in self.transcript[-10:]
        )

        prompt = f"""あなたはAIアシスタントのダンです。MTGでプレゼンテーション中に質問を受けました。

# プレゼン内容
{slides_context}

# これまでの会話
{transcript_context}

# ユーザーの質問
{question}

# ルール
- 口語体で簡潔に回答（2〜4文程度）
- 分からない場合は正直に「調べてみます」と言う
- スライドの内容を踏まえて回答する
- 「です・ます」調で話す"""

        response = await model.generate_content_async(prompt)
        return response.text.strip()

    # ------------------------------------------------------------------
    # Navigation controls
    # ------------------------------------------------------------------

    async def go_to_slide(self, direction: str):
        """Navigate to next/prev slide."""
        if direction == "next" and self.state.current_slide < self.state.total_slides - 1:
            self.state.current_slide += 1
        elif direction == "prev" and self.state.current_slide > 0:
            self.state.current_slide -= 1
        else:
            return

        slide = self.slides[self.state.current_slide]
        await self._send_state()
        narration = slide.note or slide.title
        await self._send_json(WsSlide(slide=slide, narration=narration).model_dump())
        await self._send_transcript("dan", narration)
        await self._speak(narration)

    async def resume_presentation(self):
        """Resume presentation from current slide."""
        self._cancel_presentation = False
        remaining = self.slides[self.state.current_slide:]
        self.slides_remaining = remaining
        self._presentation_task = asyncio.create_task(self._present_remaining(remaining))

    async def _present_remaining(self, slides: list[SlideContent]):
        """Present remaining slides."""
        self.state.phase = MeetingPhase.PRESENTING
        await self._send_state()

        for slide in slides:
            if self._cancel_presentation:
                break

            self.state.current_slide = slide.index
            await self._send_state()

            narration = slide.note or slide.title
            await self._send_json(WsSlide(slide=slide, narration=narration).model_dump())
            await self._send_transcript("dan", narration)

            self.is_speaking = True
            await self._speak(narration)
            self.is_speaking = False

            if self._cancel_presentation:
                break
            await asyncio.sleep(0.5)

        if not self._cancel_presentation:
            self.state.phase = MeetingPhase.QA
            await self._send_state()

    async def end(self):
        """End the meeting."""
        self._cancel_presentation = True
        if self._presentation_task and not self._presentation_task.done():
            self._presentation_task.cancel()
            try:
                await self._presentation_task
            except (asyncio.CancelledError, Exception):
                pass

        self.state.phase = MeetingPhase.ENDED
        await self._send_state()

        # Generate summary
        if self.transcript:
            summary = await self._generate_summary()
            await self._send_json({
                "type": "summary",
                "text": summary,
                "transcript": self.transcript,
            })

    async def _generate_summary(self) -> str:
        """Generate meeting summary using Gemini."""
        import google.generativeai as genai

        genai.configure(api_key=settings.GOOGLE_GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-2.0-flash")

        transcript_text = "\n".join(
            f"{'ダン' if t['speaker'] == 'dan' else 'ユーザー'}: {t['text']}"
            for t in self.transcript
        )

        response = await model.generate_content_async(
            f"以下のMTGの内容を箇条書きで要約してください。決定事項・未解決の質問・次のアクションを含めてください。\n\n{transcript_text}"
        )
        return response.text.strip()


# Active meetings registry
_active_meetings: dict[str, MeetingSession] = {}


def get_meeting(session_id: str) -> Optional[MeetingSession]:
    return _active_meetings.get(session_id)


def register_meeting(session: MeetingSession):
    _active_meetings[session.session_id] = session


def unregister_meeting(session_id: str):
    _active_meetings.pop(session_id, None)
