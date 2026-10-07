"""
MCP Server - DAN の全ツールを MCP プロトコルで公開

Agent SDK から stdio 接続で使用される。
コンテキスト（user_id, session_id, credentials）は環境変数で受け取る。

起動方法（Agent SDK が自動で起動）:
    python app/mcp_server.py
"""

import os
import sys
import json
import asyncio
import logging

# プロジェクトルートをパスに追加（import 用）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# .env から環境変数を補完（MCP サブプロセスには os.environ 経由でしか渡らないため、
# 空や未設定の場合は .env を直接読んで補完する）
def _ensure_env_from_dotenv():
    """ENCRYPTION_KEY 等、.env にしかない変数を os.environ に補完"""
    env_path = os.path.join(PROJECT_ROOT, ".env")
    if not os.path.exists(env_path):
        return
    needed = {"ENCRYPTION_KEY", "SUPABASE_URL", "SUPABASE_KEY", "SUPABASE_SERVICE_ROLE_KEY"}
    missing = {k for k in needed if not os.environ.get(k)}
    if not missing:
        return
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key in missing and value:
                    os.environ[key] = value
    except Exception:
        pass

_ensure_env_from_dotenv()

from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types

logger = logging.getLogger(__name__)

# コンテキスト: 環境変数から取得
USER_ID = os.environ.get("DAN_USER_ID", "")
SESSION_ID = os.environ.get("DAN_SESSION_ID", "")
CREDENTIALS = json.loads(os.environ.get("DAN_CREDENTIALS", "{}"))

app = Server("dan-tools")


# CLI組込ツールと重複するため MCP では公開しないツール
# CLI の Read/Write/Edit/Bash の方が高品質なのでそちらを使わせる
_CLI_BUILTIN_TOOLS = {"read_file", "write_file", "edit_file", "bash"}


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    """既存のツール定義を MCP 形式に変換して返す（CLI重複分は除外）"""
    from app.agent.v2.tools import get_all_skill_tools

    anthropic_tools = get_all_skill_tools()
    if os.environ.get('DAN_COMMAND_JOB_ID'):
        from app.services.command_job_tools import TOOLS
        from app.services.browser_script import TOOL as SCRIPT_TOOL
        # a parallel job asks the owner in words (its answer reaches the room); the voice-job confirmation card is not its
        anthropic_tools = [*anthropic_tools, *([] if os.environ.get('DAN_PARALLEL_JOB') else TOOLS), SCRIPT_TOOL]
    claude_harness = os.environ.get('DAN_JOB_HARNESS') == 'claude'

    mcp_tools = []
    for tool in anthropic_tools:
        # outside the CLI (a job, the voice call's tool host) there are no CLI built-ins: Dan's own versions are the tools
        if tool["name"] in _CLI_BUILTIN_TOOLS and (claude_harness or not (os.environ.get('DAN_COMMAND_JOB_ID') or os.environ.get('DAN_TOOL_HOST'))):
            continue
        description = tool.get("description", "")
        if os.environ.get('DAN_COMMAND_JOB_ID') and tool['name'] == 'bash':
            description += '\n任意コードの実行には具体的な内容の確認が必要。通常のファイル作成・編集・読み取りは write_file/edit_file/read_file を使う。'
        mcp_tools.append(
            types.Tool(
                name=tool["name"],
                description=description,
                inputSchema=tool.get("input_schema", {"type": "object", "properties": {}}),
            )
        )
    return mcp_tools


# Every tool call gets an upper limit, so the model gets its turn back when a tool never returns. On 2026-09-30 one
# browser call (an image puzzle at a login) did not return for 22 minutes; the model could not decide anything until
# the owner asked. Long by nature: commands (their own timeout), making media, research; an explicit wait has none.
TOOL_TIME_LIMITS = {'bash': 660, 'wait_until': None, 'deep_research': 1800}
LONG_TOOL_WORDS = ('media', 'higgsfield', 'generate', 'video', 'image')


def tool_time_limit(name: str):
    if name in TOOL_TIME_LIMITS:
        return TOOL_TIME_LIMITS[name]
    if any(word in name for word in LONG_TOOL_WORDS):
        return 900
    return 240


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent | types.ImageContent]:
    """ツールを実行し、結果を MCP コンテンツとして返す"""
    from app.agent.v2.tools import execute_tool, parse_tool_name, format_tool_result, SkillRegistry
    job_id = os.environ.get('DAN_COMMAND_JOB_ID')
    approval_notice = None
    if job_id and name=='browser_script':
        from app.services.browser_script import run
        try: result=await run(job_id,str(arguments.get('code','')))
        except Exception as exc: result={'success':False,'error':str(exc)}
        return [types.TextContent(type='text',text=json.dumps(result,ensure_ascii=False))]
    if job_id:
        from app.services.command_job_tools import guard, special
        try:
            if name in {'job_progress','job_confirmation'}:
                result = await special(job_id,name,arguments)
                return [types.TextContent(type='text',text=json.dumps(result,ensure_ascii=False))]
            approval_notice = await guard(job_id,name,arguments)
        except Exception as exc:
            return [types.TextContent(type='text',text='操作は実行していません: '+str(exc))]

    # Parallel work in one room: the same file, the PC screen or the phone is used by one piece of work at a time
    # (work_locks). Waiting here is shown in the room's work list; still taken after the limit → this call is not made.
    if not os.environ.get('DAN_TOOL_HOST'):
        from app.services import work_locks
        lock_key = work_locks.tool_key(name, arguments)
        lock_owner = work_locks.current_owner()
        if lock_key and lock_owner:
            waited = []

            def on_wait(record):
                waited.append(record)
                work_locks.note_waiting(lock_owner, record)
            other = await asyncio.to_thread(work_locks.acquire, lock_key, lock_owner, work_locks.current_title(),
                                            on_wait, work_locks.wait_limit(lock_owner))
            work_locks.clear_waiting(lock_owner)
            if other:
                return [types.TextContent(type='text', text=(
                    f'操作は実行していません: {work_locks.label(lock_key)} は{work_locks.waiting_text(other)}で、まだ使われています。'
                    'ほかの部分を先に進めてから、あとでもう一度試してください。'))]
            if waited:   # it changed while this call waited: look again first (it is this work's turn now)
                return [types.TextContent(type='text', text=work_locks.changed_while_waiting(lock_key, waited[0]))]

    # ツール名をパース
    parsed = parse_tool_name(name)
    if not parsed:
        return [types.TextContent(type="text", text=f"Unknown tool: {name}")]

    skill_name, action = parsed
    tool_call = {
        "tool_use_id": f"mcp_{name}",
        "skill": skill_name,
        "action": action,
        "params": dict(arguments),
    }

    # execute_tool を呼び出し
    if job_id:
        from app.services import command_job_state as job_state
        import time
        tool_started = time.perf_counter()
        job_state.change(job_id, lambda s:s.update(current_tool={'name':name,
            'action':arguments.get('action') if name=='browser' else None,'started_at':job_state.now()}))
    limit = tool_time_limit(name)
    try:
        try:
            result = await asyncio.wait_for(execute_tool(
                tool_call=tool_call,
                user_id=USER_ID,
                credentials=CREDENTIALS,
                session_id=SESSION_ID,
            ), timeout=limit)
        except asyncio.TimeoutError:
            if name.startswith('browser'):
                try:
                    from app.tools.browser import abort_executor_session
                    abort_executor_session()
                except Exception:
                    pass
            return [types.TextContent(type="text", text=(
                f"この道具（{name}）が{int(limit)}秒たっても返ってこなかったので、待つのをやめました。"
                "同じ手をそのまま繰り返さない。別の道を選ぶ: ログイン済みの状態で入れる入口を試す、別の画面から入る。"
                "それでも進めない時は、どこで止まったかと、本人に何をしてほしいかを具体的に伝えて止まる。"))]
    finally:
        if job_id:
            def observed(s):
                s['current_tool'] = None
                s['last_tool'] = {'name':name,'action':arguments.get('action') if name=='browser' else None,
                    'elapsed_ms':round((time.perf_counter()-tool_started)*1000),'at':job_state.now()}
                job_state.event(s,'tool',name + (':'+str(arguments.get('action','')) if name=='browser' else ''))
            job_state.change(job_id, observed)

    # format_tool_result で整形（Progressive Disclosure 対応）
    skill = SkillRegistry.get(skill_name)
    formatted = format_tool_result(result, skill_name, action, skill=skill)
    if job_id and name=='browser' and formatted.text:
        job_state.change(job_id, lambda s:s.update(last_observation={
            'text':formatted.text[:3500], 'at':job_state.now()}))

    contents: list[types.TextContent | types.ImageContent] = []

    # 画像（ブラウザスクリーンショット等）
    if formatted.has_images():
        for img in formatted.images:
            if isinstance(img, dict) and img.get("type") == "image":
                source = img.get("source", {})
                if source.get("type") == "base64":
                    contents.append(
                        types.ImageContent(
                            type="image",
                            data=source["data"],
                            mimeType=source.get("media_type", "image/png"),
                        )
                    )

    # テキスト
    if formatted.text:
        contents.append(types.TextContent(type="text", text=formatted.text))
    if approval_notice:
        contents.append(types.TextContent(type='text', text=approval_notice))

    # フォールバック: 何も返せない場合
    if not contents:
        contents.append(types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, default=str)))

    return contents


async def main():
    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
