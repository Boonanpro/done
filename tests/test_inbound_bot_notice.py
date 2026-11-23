from app.services.inbound_wakeup import automated_notice, schedule_room_wakeup


def test_vercel_bot_comment_is_automated():
    m = {"sender_info": {"from": '"vercel[bot]" <notifications@github.com>'}, "user_id": "u", "id": "x"}
    assert automated_notice(m)
    assert schedule_room_wakeup(m, "room", reason="content:existing") is True   # taken, no wake (no loop needed)


def test_person_on_github_still_wakes():
    m = {"sender_info": {"from": '"Taro" <notifications@github.com>'}}
    assert not automated_notice(m)
    assert not automated_notice({"sender_info": {"from": "vercel[bot] <someone@example.com>"}})
