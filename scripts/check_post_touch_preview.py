"""Owner outcome: readable editable post + playable demo in one phone screen.

Only private test-user drafts are changed. No call or send is made. --before captures
the old card's missing video; the same assertion must pass after the change.
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
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://localhost:3002')
    ap.add_argument('--before', action='store_true')
    ap.add_argument('--video', required=True, help='An uploaded MP4 at /api/v1/files/<name>')
    args = ap.parse_args()
    load_dotenv('/Users/mikihonda/done/.env')
    from app.services.chat_service import ChatService
    from app.services.outbound_message_service import OutboundMessageService
    from app.services.voice_stage import card_of, stage_file
    out = ROOT / '.data/post-touch-preview'
    out.mkdir(parents=True, exist_ok=True)
    user = TEST_USER['id']
    room = asyncio.run(ChatService().create_room(user, '投稿プレビュー確認・送信なし', []))['id']
    svc = OutboundMessageService()
    auth = token()
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', args=['--mute-audio'])
        try:
            for width, channel in [(360, 'x_post'), (412, 'line')]:
                body = '部品を探せるツールを試作しました。\n\n' + '画面を見ながら確認できます。\n' * 10
                row = svc.create_draft(user_id=user, room_id=room, channel=channel,
                    to='never-send.invalid', body=body, show_card=False,
                    attachments=[args.video] if channel == 'x_post' and not args.before else None)
                if channel == 'x_post' and not args.before:
                    assert row['action_data']['attachments'][0]['url'] == args.video
                files = row['action_data'].get('attachments') or [{'name': 'デモ.mp4', 'url': args.video, 'type': 'video/mp4'}]
                # A genuine saved proposal; old rendering drops its media even when present.
                ad = {**row['action_data'], 'attachments': files}
                row = svc.sb.table('dan_proposals').update({'action_data': ad}).eq('id', row['id']).eq('user_id', user).execute().data[0]
                card = {**card_of(row), 'attachments': files}
                stage_file(room).write_text(json.dumps(dict(room_id=room, session_id='no-call', version=1,
                    active=True, caption='投稿の確認', program='', card=card, scenes=1, view_id=row['id'])))
                ctx = browser.new_context(viewport={'width': width, 'height': 780}, is_mobile=True, has_touch=True)
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
                page.screenshot(path=str(out / ('before.png' if args.before else f'after-{width}.png')), full_page=True)
                video = page.locator('video')
                expect(video).to_be_visible(timeout=4000)
                assert float(field.evaluate('(e)=>getComputedStyle(e).fontSize').removesuffix('px')) >= 16
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                video.evaluate('(v)=>{v.muted=true}')
                assert video.evaluate('(v)=>v.muted')
                video.evaluate('(v)=>v.play()')
                page.wait_for_function('document.querySelector("video").currentTime > 0.2')
                assert video.evaluate('(v)=>v.videoWidth > 0 && v.duration > 1')
                video.evaluate('(v)=>v.pause()')
                field.tap()
                expect(field).to_be_focused()
                edited = body + '\nタップして編集した本文'
                field.fill(edited)
                page.get_by_role('button', name='保存', exact=True).click()
                expect(page.get_by_role('status')).to_have_text('保存しました', timeout=20000)
                saved = svc.get(row['id'], user)
                assert saved['content'] == edited and saved['status'] == 'pending'
                assert saved['action_data']['attachments'] == files
                if channel == 'x_post':
                    attached = svc.revise_draft(row['id'], user, attachments=[args.video])
                    assert attached['content'] == edited and attached['action_data']['user_edited']
                # Same saved draft is accessible after the call ends, without a stage snapshot.
                page.goto(args.base + '/message-preview?proposal=' + row['id'])
                expect(field).to_be_editable(timeout=30000)
                expect(field).to_have_value(edited)
                expect(video).to_be_visible()
                page.reload()
                expect(field).to_have_value(edited)
                page.screenshot(path=str(out / f'reopened-{width}.png'), full_page=True)
                assert not sends
                results.append({'width': width, 'channel': channel, 'room': room, 'proposal': row['id'],
                    'tap_save_reopen': True, 'video_decoded': True, 'sends': 0})
                ctx.close()
        finally:
            browser.close()
    (out / 'result.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps(results, ensure_ascii=False))


if __name__ == '__main__':
    main()
