"""Claude Code PreToolUse hook for Dan's parallel jobs (DAN_COMMAND_JOB_ID set): a job must not hand its work to a
background Agent or go to sleep with ScheduleWakeup.

Why (2026-10-29, ローレンタンの部屋「スキルクリエイター比べ」): the job's worker started two background Agents, called
ScheduleWakeup(1800) and ended its turn. The runner takes the end of a turn as the answer and closes the worker's input;
Claude Code then only waits for the background work, and 600 s after the turn ended all four background workers got
「Request interrupted by user」. The parent woke 30 minutes later, judged from file timestamps that they were still
working, slept again, and the owner's words could no longer reach it. A job's worker therefore runs Agents in the
foreground (one at a time, their answer comes back in the same turn) and never sleeps. Chat rooms (no job id) keep their
input open between turns and are not touched.
"""
import json
import os
import sys

BACKGROUND_AGENT = ('並行作業では裏の担当（run_in_background）は使えません。親の返事が終わった時点で作業は終わった扱いになり、'
                    '裏の担当は10分で切られます。同じ担当を run_in_background 無しで前面で起こし（1つずつ）、返ってきた結果で続けてください。')
WAKEUP = ('並行作業では ScheduleWakeup で眠れません。眠った時点で作業は終わった扱いになり、起きても本人の言葉は届きません。'
          '待つ物があるなら wait_until や Monitor でこのターンの中で待ち、終わらないなら今ある結果で報告を書いて終えてください。')


def decide(tool_name, tool_input, env):
    """The denial reason for this call, or '' when it may go ahead."""
    if not env.get('DAN_COMMAND_JOB_ID'):
        return ''
    if tool_name == 'ScheduleWakeup':
        return WAKEUP
    if tool_name == 'Agent' and (tool_input or {}).get('run_in_background'):
        return BACKGROUND_AGENT
    return ''


def main():
    try:
        data = json.loads(sys.stdin.buffer.read().decode('utf-8') or '{}')
    except ValueError:
        return
    reason = decide(data.get('tool_name') or '', data.get('tool_input') or {}, os.environ)
    if reason:
        print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                                 'permissionDecisionReason': reason}}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:  # a broken hook must never stop Dan's work
        print(f'job_tool_hook: {exc}', file=sys.stderr)
