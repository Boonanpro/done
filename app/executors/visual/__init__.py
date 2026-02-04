"""
Visual Browser Executor

視覚ベースのブラウザ操作エージェント。
スキルが存在しない場合に、スクリーンショットを見てLLMが判断し操作を実行。
操作ログを記録し、将来のスキル自動生成に備える。
"""

from app.executors.visual.agent import VisualAgent
from app.executors.visual.recorder import BrowserRecorder
from app.executors.visual.history import BrowserSession, BrowserStep

__all__ = [
    "VisualAgent",
    "BrowserRecorder",
    "BrowserSession",
    "BrowserStep",
]
