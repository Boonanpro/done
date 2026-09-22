from app.services import voice_readings as R


def test_identifiers_are_read_digit_by_digit_and_keep_their_zeros():
    # The owner's phone test: 「-0807」 was spoken as 「八ゼロ七」.
    assert R.say('660-0807') == 'ろくろくゼロの、ゼロはちゼロなな'
    assert R.say('090-1234-5678') == 'ゼロきゅうゼロの、いちにさんよんの、ごろくななはち'
    assert R.say('371234567895006') == 'さんなないちに、さんよんごろく、ななはちきゅうご、ゼロゼロろく'
    assert R.say('会員番号は00123です') == '会員番号はゼロゼロいちにさんです'


def test_expiry_and_dates_are_spoken_in_japanese_order():
    assert R.say('10/29') == '2029年の10月'   # was read 「十月二十九年」
    assert R.say('1985-04-03') == '1985年4月3日'


def test_amounts_names_and_plain_text_are_left_to_the_speech_model():
    for value in ('3000円', '山田太郎', '株式会社サンプル', '25.5度'):
        assert R.say(value) is None


def test_address_gets_the_official_kana_for_prefecture_city_and_town(monkeypatch):
    monkeypatch.setattr(R, 'KANA', True)   # kept for the day the owner switches it back on
    monkeypatch.setattr(R, '_towns', {'兵庫県尼崎市長洲西通': 'ひょうごけん、あまがさきし、ながすにしどおり', '尼崎市長洲西通': 'あまがさきし、ながすにしどおり'})
    assert R.say('〒660-0807 兵庫県尼崎市長洲西通9-9-9 サンプル尼崎駅前101') == \
        '郵便番号、ろくろくゼロの、ゼロはちゼロなな。ひょうごけん、あまがさきし、ながすにしどおり、9-9-9 サンプル尼崎駅前101'
    assert R.say('尼崎市長洲西通9') == 'あまがさきし、ながすにしどおり、9'


def test_without_the_postcode_table_the_address_is_left_alone(monkeypatch):
    monkeypatch.setattr(R, 'KANA', True)
    monkeypatch.setattr(R, '_towns', {})
    assert R.say('兵庫県尼崎市長洲西通9-9-9') is None


def test_annotate_adds_say_only_where_needed():
    facts = R.annotate([{'label': '郵便番号', 'value': '660-0807'}, {'label': '氏名', 'value': '山田太郎'}])
    assert facts[0]['say'] and 'say' not in facts[1]


def test_building_name_uses_the_learned_reading_and_asks_only_for_unknown_names(monkeypatch):
    monkeypatch.setattr(R, 'KANA', True)
    monkeypatch.setattr(R, '_towns', {'尼崎市長洲西通': 'あまがさきし、ながすにしどおり'})
    monkeypatch.setattr(R, '_learned', {R._key('見本尼崎駅前'): 'みほんあまがさきえきまえ'})
    asked = []
    monkeypatch.setattr(R, 'learn', lambda names: asked.extend(names))
    facts = R.annotate([{'label': '住所', 'value': '尼崎市長洲西通9-9-9 見本尼崎駅前101'}, {'label': '住所2', 'value': '尼崎市長洲西通9 未知荘'}])
    assert facts[0]['say'] == 'あまがさきし、ながすにしどおり、9-9-9 みほんあまがさきえきまえ101'   # was read 「あまさきまえ」
    assert asked == ['未知荘'] and '未知荘' in facts[1]['say']   # spoken from the spelling this once, learned for next time


def test_names_keep_their_normal_spelling_and_only_numbers_get_a_spoken_form():
    # Owner's decision after listening: hiragana place names sounded worse; numbers stay digit by digit.
    assert R.say('〒660-0807 兵庫県尼崎市長洲西通9-9-9 見本尼崎駅前101') == '郵便番号、ろくろくゼロの、ゼロはちゼロなな。兵庫県尼崎市長洲西通9-9-9 見本尼崎駅前101'
    assert R.say('兵庫県尼崎市長洲西通9-9-9') is None
