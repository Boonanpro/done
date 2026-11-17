"""The call as ChatGPT's voice runs it (owner, 2026-11-03): the speech model keeps the conversation to itself.

Why: from 10/31 every fix added something the server said into the call: an instruction appended at each interruption
(voice_interruption), a forced reply after 1.5 s of quiet (voice_turn_intake), a result followed by 「話して」
(voice_actions), a stop notice (voice_stop_control), and a cue after each result telling the speech model how to word it
(voice_sideband.job_feed). On 11/2 the owner's call was 「全くダメ」 next to ChatGPT's voice, which uses the same kind of
model and none of that. The speech model now has OpenAI's recommended prompt (live-prompting, "Recommended prompt
structure": persona, Backchannel / Interruption / Delegation policy) and nothing else is pushed into the call but facts:
a finished result, a problem, a question from the work, given as commentary, which GPT-Live is trained to paraphrase
and say aloud by itself when it fits the conversation (live-delegation).
The backend model keeps its tools and its voice rules but no longer reads chat Dan's whole brief (dan_core.shared,
about 18,000 characters) on every turn: long work goes to chat Dan (start_work), which has it.

After the owner's first call on it (2026-11-03 13:35: lighter, but four faults), each fault has one owner, in the official
patterns: who Dan is (persona: whose assistant, the same Dan as the chat, does the work); talking while the backend works
(the chatty "natural progress" pattern of live-prompting, with the verified facts given by the backend's share_progress);
a candidate checked against the owner's conditions by the tool that shows it (voice_page_check); a fast backend
(voice_settings.PLAIN_DEFAULTS, think_carefully for hard choices); the owner's 「切って」 heard by the server (voice_hangup).

After the second call (19:15: a delegation open for 44 s, the owner's correction unanswered for 25 s), lookups run beside
the conversation (voice_lookup): the delegation hands them over and ends at once; a page is shown first and checked
behind it (voice_stage.show_page); a slow search leaves its times in .tmp/web-search-slow.jsonl (web_search).

Switch: DAN_VOICE_PLAIN=0 returns to the earlier call; DAN_VOICE_BACKGROUND=0 keeps the lookups in the delegation.
"""
import os
import re
from pathlib import Path

from app.services import prompt_store

COMMENTARY_CHARS = 300   # one append is limited to 500 tokens; Japanese runs at about a token a character


def enabled():
    return os.environ.get('DAN_VOICE_PLAIN', '1') != '0'


USER = Path.home() / '.dan' / 'workspace' / 'USER.md'


def owner_names():
    """(full name, what Dan calls them) from the owner's USER.md; ('', '') when it is not there."""
    try: text = USER.read_text(encoding='utf-8')
    except OSError: return '', ''
    def field(label):
        found = re.search(r'^\s*-\s*' + label + r'\s*[:：]\s*(.+?)\s*$', text, re.M)
        return found.group(1) if found else ''
    return field('名前').replace(' ', '').replace('\u3000', ''), field('呼び方')


def persona():
    """Who Dan is, in the official form 「You are [name], a ... voice assistant for [service]」. With one line
    (「本人の仕事と暮らしを手伝うアシスタント」) asked 「自己紹介して」 Dan said 「落ち着いて、必要なことを手早く手伝う
    アシスタント」: it did not know whose it is, that it is the Dan of the chat, or that it does the work (2026-11-03 13:35)."""
    full, call = owner_names()
    owner = f'{full}さん（呼び名は{call}）' if full and call else (f'{call}' if call else '持ち主')
    whose = call or '持ち主'
    return prompt_store.fill('call/persona', owner=owner, whose=whose)


def policies():
    """How the speech model talks, takes turns and hands work to the backend (prompts/call/policies.md)."""
    return prompt_store.text('call/policies')


def __getattr__(name):
    if name == 'POLICIES': return policies()
    raise AttributeError(name)


def instructions():
    return persona() + chr(10) + policies()


def plain_text(text):
    """A chat report read as a fact: no headings, bullets, tables or emphasis marks."""
    lines = []
    for line in (text or '').splitlines():
        line = re.sub(r'^\s*(?:#+|[-*・]|\d+[.)]|>)\s*', '', line)
        line = line.replace('**', '').replace('`', '').strip(' |')
        if line and not re.fullmatch(r'[-|:\s]+', line):
            lines.append(line.replace('|', '、'))
    return chr(10).join(lines)


def job_said(kind, title, text):
    """What the call is given when a job of the room says something: (voice_say kind, the fact in a sentence or two).
    The full report is not given (a long one was given as silent material and came out as it was); the speech model
    reads it when it wants it (voice_router 'status'). The job is named by its own title; one not named yet is not named
    (「作業「はい、押したよ」」 was the owner's reply used as a name, 11/7)."""
    body = plain_text(text)
    named = f'「{title}」' if title else '頼まれた作業'
    head = {'result': f'{named}が終わった。', 'error': f'{named}で問題が起きた。',
            'confirmation': f'{named}から確認したいことがある。'}[kind]
    first = ''.join(re.split(r'(?<=[。！？!?])', body.replace(chr(10), ' '), maxsplit=2)[:2])
    return {'result': 'result', 'error': 'problem', 'confirmation': 'question'}[kind], head + first[:COMMENTARY_CHARS - len(head)]
