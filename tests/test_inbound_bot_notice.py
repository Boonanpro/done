from app.services.inbound_wakeup import automated_notice, schedule_room_wakeup


def test_vercel_bot_comment_is_automated():
    m = {"sender_info": {"from": '"vercel[bot]" <notifications@github.com>'}, "user_id": "u", "id": "x"}
    assert automated_notice(m)
    assert schedule_room_wakeup(m, "room", reason="content:existing") is True   # taken, no wake (no loop needed)


def test_person_on_github_still_wakes():
    m = {"sender_info": {"from": '"Taro" <notifications@github.com>'}}
    assert not automated_notice(m)
    assert not automated_notice({"sender_info": {"from": "vercel[bot] <someone@example.com>"}})


def test_github_actions_run_mail_is_automated():
    m = {"sender_info": {"from": '"Boonanpro" <notifications@github.com>'},
         "subject": "[Boonanpro/done] PR run failed: scope-check - 開発室の構成図 (0d9acb9)"}
    assert automated_notice(m)
    assert automated_notice({**m, "subject": "[Boonanpro/done] Run failed: tests - main (abc1234)"})
    assert not automated_notice({**m, "subject": "Re: [Boonanpro/done] 開発室の構成図 (PR #1102)"})
    assert not automated_notice({"sender_info": {"from": "x@example.com"}, "subject": "[a/b] PR run failed: x"})
