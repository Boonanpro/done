"""Qwen was retired at the user's explicit request; no automatic fallback."""
MESSAGE = 'ユーザーの指定によりQwen3-TTSは使用停止しています。既存音声を使うか、別の音声生成手段を選んでください。'


def require_enabled():
    raise RuntimeError(MESSAGE)
