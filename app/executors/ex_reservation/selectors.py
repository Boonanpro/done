"""
EX予約（SmartEX）のセレクタ定義

最終確認日: 2026/01/09
実際のサイトで確認済み
"""

# ===== URL定義 =====
URLS = {
    "top": "https://smart-ex.jp/",
    "login": "https://shinkansen2.jr-central.co.jp/RSV_P/smart_index.htm",
    "expy_login": "https://shinkansen1.jr-central.co.jp/RSV_P/index.htm",
}

# ===== ログインページ（実確認済み 2026/01/09）=====
LOGIN = {
    # 会員ID入力 - role="textbox" name="会員ID"
    "member_id": 'role=textbox[name="会員ID"]',
    
    # パスワード入力 - role="textbox" name="パスワード"  
    "password": 'role=textbox[name="パスワード"]',
    
    # ログインボタン - role="button" name="ログイン"
    "login_button": 'role=button[name="ログイン"]',
}

# ===== OTPページ（実確認済み 2026/01/10・電話認証・SMS認証対応）=====
OTP = {
    # 自動音声案内発信ボタン - input[value]で正確に指定
    "send_voice_button": 'input[value="自動音声案内発信"]',

    # SMS送信ボタン - SMS認証の場合に表示される
    "send_sms_button": 'button:has-text("SMS送信"), input[value="SMS送信"]',

    # 閉じるボタン - 音声案内発信後のダイアログを閉じる（存在しない場合あり）
    "close_button": 'button:has-text("閉じる"), input[value="閉じる"]',

    # OTP入力フィールド - input[type="tel"]
    "otp_input": 'input[type="tel"]',

    # 次へボタン - 実際は"OK"ではなく"次へ"
    "next_button": 'input[value="次へ"]',
}

# ===== マイページ（実確認済み）=====
MYPAGE = {
    # 列車を検索ボタン
    "search_train": 'article:has-text("列車を検索")',
    
    # 自由席を予約ボタン
    "free_seat": 'generic:has-text("自由席を予約")',
    
    # 予約確認/変更/払戻リンク
    "reservations": 'link:has-text("予約確認/変更/払戻")',
    
    # ログアウトリンク
    "logout": 'link:has-text("ログアウト")',
    
    # メニューリンク
    "menu": 'link:has-text("メニュー")',
}

# ===== 検索フォーム（実確認済み）=====
SEARCH_FORM = {
    # 登録区間セレクト（最初のcombobox）
    "registered_route": 'combobox >> nth=0',
    
    # 時刻（時）- 6時〜23時
    "hour": 'combobox >> nth=1',
    
    # 時刻（分）- 00分〜55分（5分刻み）
    "minute": 'combobox >> nth=2',
    
    # 出発/到着
    "departure_arrival": 'combobox >> nth=3',
    
    # 乗車駅
    "departure_station": 'combobox >> nth=4',
    
    # 降車駅
    "arrival_station": 'combobox >> nth=5',
    
    # 片道/往復
    "one_way_round": 'combobox >> nth=6',
    
    # 大人人数
    "adult_count": 'combobox >> nth=7',
    
    # 子供人数
    "child_count": 'combobox >> nth=8',
    
    # 座席の種類
    "seat_type": 'combobox >> nth=9',
    
    # 予約を続けるボタン（実際はinput type="submit"）
    "continue_button": 'input[type="submit"][value*="予約"], button:has-text("予約を続ける")',
    
    # 戻るボタン
    "back_button": 'button:has-text("戻る")',
}

# ===== 検索結果（実確認済み）=====
SEARCH_RESULT = {
    # 候補表示（例: "候補 1 / 6"）
    "candidate_label": 'generic:has-text("候補")',
    
    # 列車名（h3）
    "train_name": 'heading[level=3]',
    
    # この候補を選択ボタン
    "select_candidate": 'paragraph:has-text("この候補を選択")',
    
    # 前の時間帯へ
    "prev_time": 'generic:has-text("前の時間帯へ")',
    
    # 後の時間帯へ
    "next_time": 'generic:has-text("後の時間帯へ")',
    
    # 再検索ボタン
    "research_button": 'button:has-text("再検索")',
    
    # 発時刻
    "departure_time": 'term:has-text("発")',
    
    # 着時刻
    "arrival_time": 'term:has-text("着")',
}

# ===== 商品選択（実確認済み）=====
PRODUCT_SELECT = {
    # 普通車指定席（スマートEX）- 価格表示をクリック
    "regular_reserved": 'term:has-text("スマートEX") >> .. >> generic:has-text("￥")',
    
    # グリーン車
    "green_car": 'generic:has-text("グリーン車") >> .. >> generic:has-text("￥")',
    
    # 自由席
    "free_seat": 'term:has-text("自由席") >> .. >> generic:has-text("￥")',
    
    # 座席位置選択
    "seat_position": 'combobox:has-text("座席位置")',
    
    # 座席表から指定するボタン
    "seat_map_button": 'button:has-text("座席表から指定する")',
    
    # 予約を続けるボタン（実際はinput type="submit"）
    "continue_button": 'input[type="submit"][value*="予約"], button:has-text("予約を続ける")',
}

# ===== 最終確認画面（実確認済み）=====
CONFIRMATION = {
    # 見出し「まだ予約は完了していません。」
    "not_complete_heading": 'heading:has-text("まだ予約は完了していません")',
    
    # 列車名
    "train_name": 'heading[level=3]',
    
    # 座席情報（例: "4号車 4番D席"）
    "seat_info": 'cell:has-text("号車")',
    
    # 金額
    "price": 'cell:has-text("￥")',
    
    # 戻るリンク
    "back_link": 'link:has-text("戻る")',
    
    # 予約する（購入）ボタン - ※これは押さない
    "purchase_button": 'button:has-text("予約する（購入）")',
}

# ===== 共通 =====
COMMON = {
    # ログイン状態確認
    "logged_in": 'link:has-text("ログアウト")',
    
    # エラーメッセージ
    "error": '[class*="error"], [role="alert"]',
    
    # ローディング
    "loading": '[class*="loading"], [class*="spinner"]',
}
