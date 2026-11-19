from app.services.send_authorization import check

T0 = "2026-11-11T07:30:00+00:00"   # 下書きを置いた
T1 = "2026-11-11T07:44:46+00:00"   # 本人の発言
T2 = "2026-11-11T07:50:00+00:00"   # 発言の後


def prop(created=T0, updated=T0, channel="line"):
    return {"created_at": created, "updated_at": updated, "action_data": {"channel": channel}}


def msg(text, at=T1):
    return {"content": text, "created_at": at}


def test_11_11_progress_word_is_not_send_permission():
    # 実際の事故: 台本の作業と文の直しをまとめて頼んだ「進めて」で送った
    m = msg("進めて。\n送る文章は編集したから直した上で進めよう。ちなみに今ある色変えとか…全部新しく提案モードで入れて。")
    assert not check(approval="進めて", latest_owner_message=m, watch_notes=[], proposal=prop())["ok"]
    assert not check(approval="送る文章は編集したから直した上で進めよう", latest_owner_message=m,
                     watch_notes=[], proposal=prop())["ok"]


def test_explicit_send_passes():
    m = msg("この文面でOK、送って")
    r = check(approval="送って", latest_owner_message=m, watch_notes=[], proposal=prop())
    assert r["ok"] and r["basis"] == "owner_message"


def test_quote_must_be_in_latest_owner_message():
    m = msg("台本どうなった？")
    assert not check(approval="送って", latest_owner_message=m, watch_notes=[], proposal=prop())["ok"]
    assert not check(approval="送って", latest_owner_message=None, watch_notes=[], proposal=prop())["ok"]


def test_changed_after_approval_is_refused():
    m = msg("送って")
    assert not check(approval="送って", latest_owner_message=m, watch_notes=[],
                     proposal=prop(created=T0, updated=T2))["ok"]


def test_draft_written_after_delegation_passes():
    # 「文面は任せるから送っておいて」の後にダンが作った下書き
    m = msg("文面は任せるから送っておいて")
    assert check(approval="送っておいて", latest_owner_message=m, watch_notes=[],
                 proposal=prop(created=T2, updated=T2))["ok"]


def test_negation_in_message_blocks_partial_quote():
    for text in ("まだ送らないで、台本を見てから送って", "送ってほしくない", "送るのは待って", "まだ送ってないよね？送って大丈夫？"):
        assert not check(approval="送って", latest_owner_message=msg(text), watch_notes=[], proposal=prop())["ok"], text


def test_bare_ok_or_iiyo_is_not_enough():
    for text in ("いいよ", "OK", "やって", "それで"):
        assert not check(approval=text, latest_owner_message=msg(text), watch_notes=[], proposal=prop())["ok"], text


def test_standing_watch_note():
    note = "毎月1日に請求書メールを送る。承認不要・実行して報告のみ"
    assert check(approval="承認不要・実行して報告のみ", latest_owner_message=msg("ありがとう"),
                 watch_notes=[note], proposal=prop())["ok"]
    # 前もって任されていない見張りは使えない
    assert not check(approval="請求書メールを送る", latest_owner_message=msg("ありがとう"),
                     watch_notes=["毎月1日に請求書メールを送る準備をする"], proposal=prop())["ok"]


def test_collab_auto_policy():
    assert check(approval="", latest_owner_message=None, watch_notes=[],
                 proposal=prop(channel="collab"), collab_autonomy="auto")["ok"]
    assert not check(approval="", latest_owner_message=None, watch_notes=[],
                     proposal=prop(channel="collab"), collab_autonomy="approval")["ok"]


def test_empty_approval_refused():
    assert not check(approval="", latest_owner_message=msg("送って"), watch_notes=[], proposal=prop())["ok"]


def test_scheduled_send_with_owner_words_in_watch_note():
    note = "明日の朝9時に吉田さんへ請求書メールを送る。本人の言葉「明日の朝9時に吉田さんへ送っておいて」"
    assert check(approval="明日の朝9時に吉田さんへ送っておいて", latest_owner_message=msg("おはよう"),
                 watch_notes=[note], proposal=prop())["ok"]


def test_reply_request_with_object_particle_and_another_task():
    for instruction in ("相手の要求に答える返信をして。", "取引先にお返事をしてください。"):
        message = msg(instruction + "\nあと部品の調達状況も知りたい。")
        for updated, expected in ((T0, True), (T2, False)):
            assert check(approval=instruction, latest_owner_message=message,
                         watch_notes=[], proposal=prop(updated=updated))["ok"] == expected


def test_partial_reply_quote_is_not_an_instruction():
    for text in ("返信をしていいか聞いて", "返信をしてほしくない", "「返信をして」と書いた例文です"):
        assert not check(approval="返信をして", latest_owner_message=msg(text),
                         watch_notes=[], proposal=prop())["ok"]


def test_prior_consent_binds_one_visible_draft_and_reviewed_conditions():
    from app.services.send_authorization import review_prior
    draft = dict(prop(), id="draft-a", source_room_id="draft-room", status="pending")
    owner = dict(msg("相手の要求に答える返信をして。"), id="owner-a")
    later = [msg("部品は届いた？", T2)]
    def run(context="[送信案: draft-a]", rows=later, card=draft, receipt=""):
        return review_prior(owner["content"], card, owner, context, rows, receipt)
    first = run()
    assert not first["ok"]
    receipt = first["review_token"]
    assert run(receipt=receipt)["ok"]
    assert not run(context="[送信案: draft-b]", receipt=receipt)["ok"]
    assert not run(card=dict(draft, updated_at=T2), receipt=receipt)["ok"]
    assert not run(rows=[msg("一旦保留で", T2)], receipt=receipt)["ok"]
    assert not run(rows=[msg("送らないで", T2)], receipt=receipt)["ok"]
    assert not run(rows=[msg("価格が変わった", T2)], receipt=receipt)["ok"]


def test_another_recipient_uses_own_review():
    from app.services.send_authorization import review_prior
    owner = dict(msg("この文面で送って。"), id="owner-b")
    card = dict(prop(), id="draft-b", status="pending")
    args = (owner["content"], card, owner, "/message-preview?proposal=draft-b", [msg("今何時？", T2)])
    receipt = review_prior(*args, "")["review_token"]
    assert review_prior(*args, receipt)["ok"]
