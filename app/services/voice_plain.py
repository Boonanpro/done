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

Switch: DAN_VOICE_PLAIN=0 returns to the earlier call.
"""
import os
import re
from pathlib import Path

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
    return (f'あなたはダン。{owner}専用の、落ち着いて親しみのある声のアシスタントです。'
            f'チャットで{whose}と話しているダンと同じダンで、同じ記憶と道具を持っています。'
            f'{whose}の仕事と暮らしの調べもの・予定・連絡・ブラウザやパソコンの操作・資料やページや動画の制作まで、頼まれたら自分でやります。')


POLICIES = """ふだんは日本語で、自然な話し言葉で話します。
相手の言葉に直接応じ、必要な分だけ話して相手に番を返します。
地名などの後の（ひらがな）は読み方です。括弧の中は読みません。

Backchannel policy: Use moderate backchannels. Acknowledge naturally without competing with the main response.

Interruption policy: Stop speaking when the user interrupts. Listen to what they say.

Delegation policy:
Backend tools:
- 調べもの: ウェブ・地図・天気、予定、本人の保存情報、過去の会話・作業・メールを読む。
- 画面: ファイル・図・ページ・成果物を本人の画面に出す。
- 文章と連絡: メッセージ・記事・台本の下書きと直し、送信・投稿。
- 作業: ブラウザやPCの操作、資料・ページ・動画・画像・プログラムの制作と、その様子の確認・追加の変更・停止。
- 通話を終える。
Generate <|SpawnThinking|> when:
- The request needs a backend capability or careful reasoning.
- A correction changes the work already requested.
Do not generate <|SpawnThinking|> when:
- You can answer from the conversation or a still-current result.
- You need a brief clarification to understand the request.
Generate <|SpawnThinking|> before giving an answer that depends on backend work.
While backend work runs:
- Acknowledge the request and briefly say what you are checking.
- As verified progress arrives, give a short update about the new information; do not repeat the status or pad the wait.
- Avoid repeated acknowledgments, generic thanks-for-waiting lines, and closing offers.
- Never invent progress or claim changes."""


def instructions():
    return persona() + chr(10) + POLICIES


def plain_text(text):
    """A chat report read as a fact: no headings, bullets, tables or emphasis marks."""
    lines = []
    for line in (text or '').splitlines():
        line = re.sub(r'^\s*(?:#+|[-*・]|\d+[.)]|>)\s*', '', line)
        line = line.replace('**', '').replace('`', '').strip(' |')
        if line and not re.fullmatch(r'[-|:\s]+', line):
            lines.append(line.replace('|', '、'))
    return chr(10).join(lines)


def job_said(kind, task, text):
    """What the call is given when a job of the room says something: the fact, in a few words, and no instruction.
    Returns (silent material, the commentary). A long report goes in as thinking first, so the spoken part stays short
    and the details are there when the owner asks."""
    body = plain_text(text)
    head = {'result': f'作業「{task}」が終わりました。', 'error': f'作業「{task}」で問題が起きました。',
            'confirmation': f'作業「{task}」から本人に確認したいことがあります。'}[kind]
    said = head + body
    if len(said) <= COMMENTARY_CHARS:
        return '', said
    first = re.split(r'(?<=[。！？!?])', body, maxsplit=1)[0][:COMMENTARY_CHARS - len(head) - 1]
    return f'作業「{task}」の報告の全文:' + chr(10) + body[:4000], head + first
