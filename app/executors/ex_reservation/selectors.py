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

# ===== ログインページ（実確認済み）=====
LOGIN = {
    # 会員ID入力 - placeholder="数字10桁（半角）"
    "member_id": 'input[placeholder="数字10桁（半角）"]',
    
    # パスワード入力 - placeholder="英数記号4-8桁（半角）"
    "password": 'input[placeholder="英数記号4-8桁（半角）"]',
    
    # ログインボタン
    "login_button": 'button:has-text("ログイン")',
}

# ===== OTPページ（実確認済み・電話認証）=====
OTP = {
    # 自動音声案内発信ボタン
    "send_voice_button": 'button:has-text("自動音声案内発信")',
    
    # OTP入力フィールド - placeholder="数字6桁（半角）"
    "otp_input": 'input[placeholder="数字6桁（半角）"]',
    
    # 次へボタン
    "next_button": 'button:has-text("次へ")',
    
    # 閉じるボタン（ダイアログ）
    "close_dialog": 'generic:has-text("閉じる")',
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
    
    # 予約を続けるボタン
    "continue_button": 'button:has-text("予約を続ける")',
    
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
    
    # 予約を続けるボタン
    "continue_button": 'button:has-text("予約を続ける")',
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
