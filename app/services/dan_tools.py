"""Dan's whole tool set for the models that are not the chat CLI (the voice backend, API jobs), disclosed in steps.

Chat Dan (Claude CLI) sees every Dan tool and every skill. The voice path used to get a hand-picked few (the voice backend
12 functions, a job 11 of the 27 Dan tools and no skills), and felt weaker than chat for that reason alone (2026-09-24).
Sending every tool's full definition on each model call is what made a job step slow (6-8 s, 2026-09-23), so the rest of
the tools are disclosed in steps, the way skills are: a one-line catalog in the instructions, `dan_tool_help` for a tool's
full description and parameters, and `dan_tool` to run it."""
import json
import re
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2] / '.claude' / 'skills'

HELP = {'name': 'dan_tool_help', 'description': 'ダンの道具の一覧にある道具の、詳しい説明と引数を見る。使う前に一度見る。',
        'parameters': {'type': 'object', 'properties': {'name': {'type': 'string', 'description': '道具の名前'}}, 'required': ['name'], 'additionalProperties': False}}
USE = {'name': 'dan_tool', 'description': 'ダンの道具の一覧にある道具を使う（引数は dan_tool_help で見た形）。',
       'parameters': {'type': 'object', 'properties': {'name': {'type': 'string', 'description': '道具の名前'},
                                                      'arguments': {'type': 'object', 'description': 'その道具の引数'}},
                      'required': ['name', 'arguments'], 'additionalProperties': False}}


def _fields(tool):
    """(name, description, parameters) of an MCP tool or of a tool definition dict (app.agent.v2.tools)."""
    if isinstance(tool, dict):
        return tool.get('name', ''), tool.get('description', ''), tool.get('input_schema') or tool.get('parameters') or {}
    return tool.name, tool.description, tool.inputSchema


def definitions():
    """Every Dan tool definition as the chat CLI gets them, plus Dan's own file/command tools (the CLI has built-ins for
    those; a model outside the CLI needs these). Read in this process without running anything."""
    from app.agent.v2.tools import get_all_skill_tools
    return get_all_skill_tools()


def first_line(text, limit=110):
    line = next((l.strip() for l in str(text or '').splitlines() if l.strip()), '')
    return line[:limit]


def skills():
    """(name, one-line description) of each skill: the procedures chat Dan follows (check_skill reads one in full)."""
    out = []
    for path in sorted(SKILLS.glob('*/SKILL.md')):
        try:
            head = path.read_text(encoding='utf-8')[:2000]
        except OSError:
            continue
        found = re.search(r'^description:\s*(.+)$', head, re.M)
        out.append((path.parent.name, first_line(found.group(1).strip().strip('"\'') if found else '', 90)))
    return out


def catalog(mcp_tools, native=()):
    """The instructions' paragraph: the tools not already given as functions, one line each, and the skills."""
    rows = [f'- {n}: {first_line(d)}' for n, d, _ in map(_fields, mcp_tools) if n not in set(native)]
    lines = ['ダンの道具（チャットのダンと同じもの）。使う時は dan_tool_help で詳しい説明と引数を見て、dan_tool で使う:', *rows]
    listed = skills()
    if listed:
        lines.append('スキル（作業の手順書。check_skill で全文を読む）: ' + ' / '.join(f'{n}（{d}）' if d else n for n, d in listed))
    return '\n'.join(lines)


def help_text(mcp_tools, name):
    found = next((f for f in map(_fields, mcp_tools) if f[0] == name), None)
    if found is None:
        return json.dumps({'error': f'{name} という道具はありません。一覧の名前を使う。'}, ensure_ascii=False)
    return json.dumps({'name': found[0], 'description': found[1], 'parameters': found[2]}, ensure_ascii=False)
