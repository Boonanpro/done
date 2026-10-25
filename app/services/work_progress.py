"""What Dan writes for the chat's work line while a turn runs (2026-10-25, ダン開発室).

本人「「考えています」「作業しています」…という書き方だと、何をしてるのかわからなさすぎる」「人間が見て、今何をしているのか、
どういうふうに考えて行動しているのかがもう少し具体的にわかるプロセスモニターに」. The words picked per tool kind
(app/agent/activity_line.py) cannot say what a step is for, so Dan writes them itself with this tool:

    サーバーの記録を見ました。スマホは 1.0.75 と 1.0.76 を落としていました。
    その後は新しい版があるか聞きに来ているだけでした。
    アプリが自分の版を知らせているか確かめています 8秒

``done`` becomes a finished line, ``doing`` the line at the bottom. The tool itself does nothing: its arguments travel
with the tool_use execution event (metadata.done / metadata.activity, cli_runner._save_execution_event_sync), the one
place every backend (Claude CLI, Codex) passes through, and the screens draw them
(frontend/src/lib/chat-shapes/live-line.ts). Nothing here reaches the reply.
"""
from __future__ import annotations

TOOL = {
    'name': 'progress',
    'description': (
        '作業中、本人のチャットには作業の様子が数行で出る。その文をここで書く（返事の本文には出ない）。'
        '段取りが1つ終わった時に done、次の段取りを始める時に doing を渡す（1回で両方渡してよい）。'
        'done は何をして何が分かったかを、です・ます調の普通の文で1〜2文（例:「サーバーの記録を見ました。スマホは 1.0.75 と 1.0.76 を落としていました。」'
        '「記録が無かったので、ダウンロードの方も見ました。」）。'
        'doing は今していることを「〜しています」の1文（例:「アプリが自分の版を知らせているか確かめています」）。'
        '本人の言葉で書き、コマンド・ファイル名・道具の名前・英語・記号（✓ → 番号 3/3）は書かない。'
        '見張り・記憶・保存など裏の作業は書かない。道具を1つ使うたびには呼ばず、段取りの区切りで呼ぶ。'
        '1〜2手で終わる返事や雑談では呼ばない。'
    ),
    'input_schema': {'type': 'object', 'properties': {
        'done': {'type': 'string', 'description': '終わった段取り: 何をして何が分かったか（「〜しました」「〜でした」）'},
        'doing': {'type': 'string', 'description': '今始める段取り（「〜しています」）'},
    }, 'additionalProperties': False},
}


async def tool(params):
    done = str((params or {}).get('done') or '').strip()
    doing = str((params or {}).get('doing') or '').strip()
    if not done and not doing:
        return {'success': False, 'error': 'done か doing のどちらかを書く'}
    return {'success': True, 'output': 'ok'}
