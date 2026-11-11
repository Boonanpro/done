"""Exercise the actual call screen and saved draft API, without sending or opening a call.

Uses only dan-test@example.com's private room/drafts. Saves screenshots and results in .data.
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
from place_shot import TEST_USER, token
from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://localhost:3002')
    args = parser.parse_args()
    load_dotenv('/Users/mikihonda/done/.env')
    from app.services.chat_service import ChatService
    from app.services.outbound_message_service import OutboundMessageService
    from app.services.voice_stage import card_of, stage_file
    out = ROOT / '.data/voice-draft-editor-check'
    out.mkdir(parents=True, exist_ok=True)
    user = TEST_USER['id']
    room = asyncio.run(ChatService().create_room(user, '通話送信案・編集保存の確認', []))['id']
    service = OutboundMessageService()
    auth = token()
    headers = {'Authorization': 'Bearer ' + auth}
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for width, channel, body in [
                (360, 'line', 'ご相談ありがとうございます。\n\n' + '動画の用途と掲載先を教えてください。\n' * 25),
                (1280, 'email', '資料の確認をお願いします。\n\n候補日は来週です。'),
            ]:
                draft = service.create_draft(user_id=user, room_id=room, channel=channel,
                    to='never-send@example.invalid', body=body, subject='送信しない確認用', show_card=False)
                state = dict(room_id=room, session_id='no-call-editor-check', version=1, active=True,
                    caption='送信案の編集', program='', card=card_of(draft), scenes=1, view_id=draft['id'])
                stage_file(room).write_text(json.dumps(state, ensure_ascii=False))
                ctx = browser.new_context(viewport={'width': width, 'height': 780}, locale='ja-JP')
                ctx.add_init_script('localStorage.setItem("done-token", ' + json.dumps(auth) + ')')
                page = ctx.new_page()
                sends = []
                def block_send(route):
                    sends.append(route.request.url)
                    route.abort()
                page.route('**/proposals/*/send', block_send)
                page.goto(args.base + '/voice-stage?room=' + room)
                field = page.get_by_role('textbox', name='送信案の本文')
                expect(field).to_be_editable(timeout=30000)
                expect(field).to_have_value(body)
                page.screenshot(path=str(out / f'{channel}-loaded.png'))
                edited = body.replace('。', '！', 1) + '\n追記：本人が画面で編集した文章です。'
                field.fill(edited)
                page.get_by_role('button', name='保存', exact=True).click()
                expect(page.get_by_role('status')).to_have_text('保存しました')
                url = args.base + '/api/v1/chat/proposals/' + draft['id']
                saved = ctx.request.get(url, headers=headers).json()
                assert saved['content'] == edited and saved['status'] == 'pending'
                assert saved['action_data']['to'] == 'never-send@example.invalid'
                # The call snapshot still contains the original body: reopening must read the stored edit.
                page.reload()
                expect(field).to_be_editable(timeout=30000)
                expect(field).to_have_value(edited)
                failed_body = edited + '\n通信失敗時にも残す文章'
                field.fill(failed_body)
                page.route('**/proposals/*/draft', lambda route: route.fulfill(status=503, body='unavailable'))
                page.get_by_role('button', name='保存', exact=True).click()
                expect(page.get_by_role('status')).to_contain_text('保存できませんでした')
                expect(field).to_have_value(failed_body)
                assert ctx.request.get(url, headers=headers).json()['content'] == edited
                page.unroute('**/proposals/*/draft')
                page.get_by_role('button', name='保存', exact=True).click()
                expect(page.get_by_role('status')).to_have_text('保存しました')
                assert ctx.request.get(url, headers=headers).json()['content'] == failed_body
                page.screenshot(path=str(out / f'{channel}-saved.png'))
                assert sends == []
                results.append({'channel': channel, 'width': width, 'proposal': draft['id'],
                    'original_preserved': True, 'edit_save_reload': True, 'failure_retry': True, 'sends': 0})
                ctx.close()
        finally:
            browser.close()
    (out / 'result.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps(results, ensure_ascii=False))


if __name__ == '__main__':
    main()
