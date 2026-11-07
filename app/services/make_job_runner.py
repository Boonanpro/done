"""Heavy making asked for by voice (pages, videos, documents, code): the work runs as a parallel job of the room on chat
Dan's harness — Claude Code (Opus, the default; or Fable) or Codex (GPT-6) — with the room's conversation, memory and
brief (parallel_job_runner / command_job_runner). The call follows it like any other job: the call screen's status line, 「どうなってる？」 (job_status), a change or a stop (steer_job), and the
result spoken in the call.

Why (2026-09-30): the worker that did work asked for by voice was DeepSeek Flash with a short brief, so a voice request to
make or fix something could not be done the way chat does it.
Why parallel (2026-10-08): it used to run as a turn of the room itself and waited (up to 5 minutes) for the room's chat to
be free, then held the room. Now it branches off the room's conversation and the chat stays free.
"""
from app.services import command_job_state as state

ORIGIN_NOTE = ('\n\n（通話で本人から頼まれた制作です。結果は通話でも読み上げられるので、最後の報告は要点から短く。'
               '取り返しのつかない確定（公開・送信・購入・削除）の前は、内容を示して本人の返事を待つ。）')


def words(task):
    """The owner's request as said, without the job's internal notes."""
    from app.services.voice_parts import VOICE_TASK
    return task.replace(VOICE_TASK, '').split('\n参考の直前会話（')[0].removeprefix('今回のユーザー発言（原文）:\n').strip()


async def note_request(row):
    """Give a job asked for on a call its voice note. Returns the job state. Nothing is written in the room's chat: the
    job is in the room's list of parallel work, and the call's own words are the call's. 「📞 通話からの依頼: …」 was
    written as the owner's message, and it was a backend's rewritten instruction with its notes (11/6 21:34) or a reply
    that was no request (「はい、押したよ」, 11/7 12:25). A person taking a request on the phone writes no such line."""
    job_id = row['id']
    s = state.read(job_id)
    asked = words(s['task'])
    from app.services.voice_router import TRANSCRIPT
    said = asked.split(TRANSCRIPT)[0].strip()
    return state.change(job_id, lambda x: x.update(voice_noted=True, origin_note=ORIGIN_NOTE, task=asked,
                                                   title=x.get('title') or said[:58]))
