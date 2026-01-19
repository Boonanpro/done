"""
EX予約（SmartEX）の検証済みセレクタ定義

実際のサイトで確認・検証済み
最終確認日: 2026/01/11
"""

# ===== URL定義 =====
URLS = {
    "top": "https://smart-ex.jp/",
    "login": "https://shinkansen2.jr-central.co.jp/RSV_P/smart_index.htm",
    "mypage": "https://shinkansen2.jr-central.co.jp/RSV_P/ClientService",
}

# ===== ログインページ =====
LOGIN = {
    # 会員ID入力 - role="textbox" name="会員ID"
    "member_id": 'role=textbox[name="会員ID"]',

    # パスワード入力 - role="textbox" name="パスワード"
    "password": 'role=textbox[name="パスワード"]',

    # ログインボタン - role="button" name="ログイン"
    "login_button": 'role=button[name="ログイン"]',
}

# ===== OTPページ（電話認証）=====
OTP = {
    # 自動音声案内発信ボタン
    "send_voice_button": 'input[value="自動音声案内発信"]',

    # 閉じるボタン（ダイアログ）
    "close_button": 'button:has-text("閉じる"), input[value="閉じる"]',

    # OTP入力フィールド - input[type="tel"]
    "otp_input": 'input[type="tel"]',

    # 次へボタン
    "next_button": 'input[value="次へ"]',
}

# ===== マイページ =====
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

# ===== 検索フォーム =====
# 注意: セレクトボックスはインデックスまたはname/id属性で指定
SEARCH_FORM = {
    # セレクトボックス（インデックス順）
    "registered_route": '#s-1',  # 登録した区間から選ぶ
    "hour": '#s-3',              # 時刻（時）6時〜23時
    "minute": '#s-4',            # 時刻（分）00分〜55分（5分刻み）
    "departure_arrival": '#s-5', # 出発/到着
    "departure_station": '#s6',  # 乗車駅
    "arrival_station": '#s7',    # 降車駅
    "one_way_round": '#c1-8',    # 片道/往復
    "adult_count": '#s10',       # おとな人数
    "child_count": '#s11',       # こども人数
    "seat_type": '#c1-6',        # 座席の種類

    # ボタン
    "continue_button": 'input[type="submit"][value*="予約"]',
    "back_button": 'button:has-text("戻る")',

    # 駅のvalue値（select_option(value="...")で使用）
    "stations": {
        "東京": "010",
        "品川": "020",
        "新横浜": "030",
        "名古屋": "100",
        "京都": "160",
        "新大阪": "170",
        "新神戸": "180",
        "岡山": "230",
        "広島": "270",
        "小倉": "330",
        "博多": "350",
    },

    # 時刻のvalue値（select_option(value="...")で使用）
    "hours": {
        f"{h}時": f"{h:02d}" for h in range(6, 24)
    },
}

# ===== 検索結果 =====
SEARCH_RESULT = {
    # 列車候補選択ボタン
    "select_candidate": 'text="この候補を選択"',

    # 前の時間帯へ
    "prev_time": 'text="前の時間帯へ"',

    # 後の時間帯へ
    "next_time": 'text="後の時間帯へ"',

    # 再検索ボタン
    "research_button": 'button:has-text("再検索")',

    # 戻るボタン
    "back_button": 'button:has-text("戻る")',

    # 予約を続けるボタン
    "continue_button": 'button:has-text("予約を続ける")',
}

# ===== 商品選択（座席タイプ選択）=====
PRODUCT_SELECT = {
    # 価格表示（￥マーク付き）
    "price_display": 'text=/￥\\d+,?\\d+/',

    # 座席位置選択
    "seat_position": 'select',  # 具体的なセレクタは要確認

    # 座席表から指定するボタン
    "seat_map_button": 'text="座席表から指定する"',

    # 予約を続けるボタン
    "continue_button": 'input[type="submit"][value*="予約"]',
}

# ===== 最終確認画面 =====
CONFIRMATION = {
    # 見出し「まだ予約は完了していません。」
    "not_complete_heading": 'text="まだ予約は完了していません"',

    # 戻るリンク
    "back_link": 'text="戻る"',

    # 予約する（購入）ボタン - ※これは押さない
    "purchase_button": 'text="予約する（購入）"',
}

# ===== 共通 =====
COMMON = {
    # ログイン状態確認
    "logged_in": 'text="ログアウト"',

    # エラーメッセージ
    "error": '[class*="error"], [role="alert"]',

    # ローディング
    "loading": '[class*="loading"], [class*="spinner"]',
}
