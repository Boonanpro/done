"""
EX予約（SmartEX）の完全検証済みセレクタ定義

実際のサイトで全ページを確認・検証済み
最終確認日: 2026/01/11 02:22
検証方法: scripts/ex_manual_investigate.py で実際にログイン→予約確認画面まで到達
"""

# ===== URL定義 =====
URLS = {
    "top": "https://smart-ex.jp/",
    "login": "https://shinkansen2.jr-central.co.jp/RSV_P/smart_index.htm",
    "mypage": "https://shinkansen2.jr-central.co.jp/RSV_P/ClientService",
}

# ===== ログインページ（検証済み）=====
LOGIN = {
    # 会員ID入力 - role="textbox" name="会員ID"
    "member_id": 'role=textbox[name="会員ID"]',

    # パスワード入力 - role="textbox" name="パスワード"
    "password": 'role=textbox[name="パスワード"]',

    # ログインボタン - role="button" name="ログイン"
    "login_button": 'role=button[name="ログイン"]',
}

# ===== OTPページ（電話認証）（検証済み）=====
OTP = {
    # 自動音声案内発信ボタン
    "send_voice_button": 'input[value="自動音声案内発信"]',

    # 閉じるボタン（ダイアログ）- ダイアログが表示されない場合もある
    "close_button": 'button:has-text("閉じる"), input[value="閉じる"]',

    # OTP入力フィールド - input[type="tel"]
    "otp_input": 'input[type="tel"]',

    # 次へボタン
    "next_button": 'input[value="次へ"]',
}

# ===== マイページ（検証済み）=====
MYPAGE = {
    # 列車を検索ボタン（大きなカード）
    "search_train": 'text="列車を検索"',

    # 自由席を予約ボタン
    "free_seat": 'text="自由席を予約"',

    # 予約確認/変更/払戻
    "reservations": 'text="予約確認/変更/払戻"',

    # ログアウトリンク
    "logout": 'text="ログアウト"',

    # メニュー
    "menu": 'text="メニュー"',
}

# ===== 検索フォーム（検証済み）=====
SEARCH_FORM = {
    # セレクトボックス（ID指定で確実）
    "registered_route": '#s-1',  # 登録した区間から選ぶ
    "date_area": '.new_date_area',  # 日付選択エリア（クリックでカレンダー表示）
    "hour": '#s-3',              # 時刻（時）6時〜23時
    "minute": '#s-4',            # 時刻（分）00分〜55分（5分刻み）
    "departure_arrival": '#s-5', # 出発/到着
    "departure_station": '#s6',  # 乗車駅
    "arrival_station": '#s7',    # 降車駅
    "one_way_round": '#c1-8',    # 片道/往復
    "adult_count": '#s10',       # おとな人数
    "child_count": '#s11',       # こども人数
    "seat_type": '#c1-6',        # 座席の種類

    # 日付カレンダー
    "calendar_popup": '.popup_wrap',
    "date_cell_prefix": '.selectable.',  # 日付セル（例: .selectable.20260130）

    # ボタン
    "continue_button": 'input[type="submit"][value*="予約"]',
    "back_button": 'button:has-text("戻る")',

    # 駅のvalue値（select_option(value="...")で使用）
    "stations": {
        "東京": "010",
        "品川": "020",
        "新横浜": "030",
        "小田原": "040",
        "熱海": "050",
        "三島": "060",
        "新富士": "070",
        "静岡": "080",
        "掛川": "090",
        "浜松": "100",
        "豊橋": "110",
        "三河安城": "120",
        "名古屋": "130",
        "岐阜羽島": "140",
        "米原": "150",
        "京都": "160",
        "新大阪": "170",
        "新神戸": "180",
        "西明石": "190",
        "姫路": "200",
        "相生": "210",
        "岡山": "220",
        "新倉敷": "230",
        "福山": "240",
        "新尾道": "250",
        "三原": "260",
        "東広島": "270",
        "広島": "280",
        "新岩国": "290",
        "徳山": "300",
        "新山口": "310",
        "厚狭": "320",
        "新下関": "330",
        "小倉": "340",
        "博多": "350",
    },

    # 時刻のvalue値（select_option(value="...")で使用）
    "hours": {
        "6時": "06",
        "7時": "07",
        "8時": "08",
        "9時": "09",
        "10時": "10",
        "11時": "11",
        "12時": "12",
        "13時": "13",
        "14時": "14",
        "15時": "15",
        "16時": "16",
        "17時": "17",
        "18時": "18",
        "19時": "19",
        "20時": "20",
        "21時": "21",
        "22時": "22",
        "23時": "23",
    },
    "minutes": {
        "00分": "00",
        "05分": "05",
        "10分": "10",
        "15分": "15",
        "20分": "20",
        "25分": "25",
        "30分": "30",
        "35分": "35",
        "40分": "40",
        "45分": "45",
        "50分": "50",
        "55分": "55",
    },
}

# ===== 時間帯注意ページ（検証済み）=====
TIME_NOTICE = {
    # 見出し「予約のご案内」
    "heading": 'text="予約のご案内"',

    # 注意文「23:30〜翌5:30の予約操作は...」
    "notice_text": 'text="23:30〜翌5:30の予約操作は"',

    # 戻るボタン
    "back_button": 'button:has-text("戻る")',

    # 予約を続けるボタン
    "continue_button": 'button:has-text("予約を続ける")',
}

# ===== 検索結果（列車候補）（検証済み）=====
SEARCH_RESULT = {
    # 候補表示テキスト（例: "候補 1 / 6"）
    "candidate_label": 'text=/候補 \\d+ \\/ \\d+/',

    # この候補を選択ボタン（オレンジ色）
    "select_candidate": 'text="この候補を選択"',

    # 前の時間帯へボタン
    "prev_time": 'text="前の時間帯へ"',

    # 後の時間帯へボタン
    "next_time": 'text="後の時間帯へ"',

    # 再検索ボタン
    "research_button": 'button:has-text("再検索")',

    # 戻るボタン
    "back_button": 'button:has-text("戻る")',
}

# ===== 座席選択（商品選択）（検証済み）=====
SEAT_SELECTION = {
    # 普通車タブ
    "regular_tab": 'text="普通車"',

    # グリーン車タブ
    "green_tab": 'text="グリーン車"',

    # 商品ラベル（価格付き）
    # 例: "○ ￥15,820" のような表示
    "price_label": 'label.ticket_btn',

    # 価格表示（￥マーク付き）
    "price_display": 'text=/￥\\d+,?\\d+/',

    # スマートEXラベル
    "smartex_label": 'text="スマートEX"',

    # スマートEX自由席ラベル
    "smartex_free_label": 'text="スマートEX自由席"',

    # 座席位置セレクタ（窓側/通路側 A/B/C/D/E 選択）
    "seat_position_select": '#s-1',  # select[name="hd03"]

    # 座席位置のvalue値（select_option(value="...")で使用）
    "seat_positions": {
        "指定なし": "001",
        "窓側A": "004",      # 窓　側（普A／グA）
        "中央B": "005",      # 中　央（普B）
        "通路側C": "006",    # 通路側（普C／グB）
        "通路側D": "007",    # 通路側（普D／グC）
        "窓側E": "008",      # 窓　側（普E／グD）
    },

    # 座席表から指定するボタン
    "seat_map_button": 'button.seat_map_button',

    # 席が離れても良い チェックボックス（複数人予約時）
    "allow_separate_checkbox": '#mchk1',  # input[type="checkbox"][name="mchk1"]

    # 予約を続けるボタン（商品選択後に表示）
    "continue_button": 'input[name="b4"]',  # input[type="submit"][value="予約を続ける"]

    # 戻るボタン
    "back_button": 'button:has-text("戻る")',
}

# ===== 座席表（シートマップ）検証済み 2026/01/20 =====
SEAT_MAP = {
    # 座席表を開くボタン
    "open_button": 'button.seat_map_button',

    # 座席表テーブル
    "table": '#seatlist_table_pc',

    # 号車選択セレクト（value例: "2,03,1,00" = 普通3号車）
    "car_select": '#pc-sel1',

    # 席番選択セレクト（value: 0=指定なし, 1-20=番号）
    "row_select": '#pc-1',

    # 席列チェックボックス
    "seat_checkbox_a": '#pc-1a',  # A席（窓側）
    "seat_checkbox_b": '#pc-1b',  # B席（中央）
    "seat_checkbox_c": '#pc-1c',  # C席（通路側）
    "seat_checkbox_d": '#pc-1d',  # D席（通路側）
    "seat_checkbox_e": '#pc-1e',  # E席（窓側）

    # 座席セル（IDパターン: [A-E]-[1-20]）
    # 例: td#A-19, td#B-5
    "seat_cell_pattern": 'td#{}',  # formatで使用: "A-19"

    # 空席セル（disabledクラスがない、○表示）
    "available_seat": '#seatlist_table_pc td:not(.disabled)',

    # 予約済みセル（disabledクラスあり、×表示）
    "occupied_seat": '#seatlist_table_pc td.disabled',

    # hidden inputs for selected seats
    "hidden_seat_row": '#jmpsel1',      # 選択座席1の番号
    "hidden_seat_col_a": '#jmpsel1a',   # A席選択フラグ
    "hidden_seat_col_b": '#jmpsel1b',   # B席選択フラグ
    "hidden_seat_col_c": '#jmpsel1c',   # C席選択フラグ
    "hidden_seat_col_d": '#jmpsel1d',   # D席選択フラグ
    "hidden_seat_col_e": '#jmpsel1e',   # E席選択フラグ

    # ボタン
    "clear_button": '#clr01',
    "continue_button": 'input[name="b4"]',  # 予約を続ける
    "back_button": 'button[name="b0"]',     # 戻る
}

# ===== 同意事項ダイアログ（座席表表示時）（検証済み）=====
AGREEMENT_DIALOG = {
    # ダイアログラッパー
    "dialog": '.popup_wrap',

    # タイトル「同意事項」
    "heading": 'h1:has-text("同意事項")',

    # 同意するチェックボックス
    "agree_checkbox": '#chkbox_2',  # input[type="checkbox"][name="hd16"]

    # 戻るボタン
    "back_button": '#b-3',

    # 予約を続けるボタン（チェックボックスをチェック後に有効化）
    "continue_button": 'input[name="sb-5"]',
}

# ===== 最終確認画面（検証済み）=====
CONFIRMATION = {
    # 見出し「まだ予約は完了していません。」
    "not_complete_heading": 'text="まだ予約は完了していません。"',

    # 列車情報エリア
    "train_info": 'text=/\\d+時\\d+分 発/',

    # 料金表示
    "price": 'text=/￥\\d+,?\\d+/',

    # 合計表示
    "total": 'text="合計"',

    # 戻るボタン
    "back_button": 'a[name="b1"]',

    # 予約する（購入）ボタン - ID指定で確実
    "purchase_button": '#sb-1',  # input[value="予約する（購入）"] onclick="check_new('RSWP200AIDP016')"
}

# ===== 購入完了画面 =====
PURCHASE_COMPLETE = {
    # 完了見出し
    "complete_heading": 'text="予約が完了しました"',

    # 予約番号
    "reservation_number": 'text=/予約番号[：:]/',

    # トップへ戻るボタン
    "top_button": 'text="トップへ戻る"',

    # 予約確認ボタン
    "confirm_reservation": 'text="予約確認"',
}

# ===== 共通（検証済み）=====
COMMON = {
    # ログイン状態確認
    "logged_in": 'text="ログアウト"',

    # エラーメッセージ
    "error": '[class*="error"], [role="alert"]',

    # ローディング
    "loading": '[class*="loading"], [class*="spinner"]',

    # メニューボタン
    "menu": 'text="メニュー"',

    # パンくずリスト
    "breadcrumb": '[class*="breadcrumb"]',
}

# ===== 使用例 =====
"""
# 検索フォームで駅を選択
await page.locator(SEARCH_FORM["departure_station"]).select_option(
    value=SEARCH_FORM["stations"]["新大阪"]
)

# 時刻を選択
await page.locator(SEARCH_FORM["hour"]).select_option(
    value=SEARCH_FORM["hours"]["19時"]
)

# 時間帯注意ページが表示された場合
if await page.locator(TIME_NOTICE["heading"]).count() > 0:
    await page.locator(TIME_NOTICE["continue_button"]).click()

# 列車候補を選択（最初の候補）
select_buttons = await page.locator(SEARCH_RESULT["select_candidate"]).all()
await select_buttons[0].click()

# 座席（価格）を選択（最初の価格）
price_labels = await page.locator(SEAT_SELECTION["price_label"]).all()
await price_labels[0].click()
"""
