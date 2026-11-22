"""Build the job instructions shared by chat and voice editing requests."""
from app.services import prompt_store


def editor_task(title: str, task: str, original: str = '') -> str:
    if original and original.strip() != task:
        task = f'本人の発言（原文）:\n{original}\n\n引き継ぎの補足:\n{task}'
    return f'作品の部屋: {title}\n\n{task}\n\n{prompt_store.text("work/editor-handoff")}'
