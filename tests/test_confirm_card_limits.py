"""確認カードは、これから起きることだけを短く載せる（2026-11-12 本人「文字が多すぎてほとんど読んでない」）。"""
import asyncio

from app.services import confirm_cards


def test_long_card_from_11_12_is_refused(monkeypatch):
    # 11/12 に実際に出して本人に読まれなかったカード
    monkeypatch.setenv('DAN_USER_ID', 'u')
    monkeypatch.setenv('DAN_SESSION_ID', 'r')
    params = {
        'title': 'DeepSeek に11ドルをチャージ（アメックスはダンの画面から通らない）',
        'items': [
            {'label': '支払う合計', 'value': '11.66ドル（11ドル＋消費税0.66ドル）'},
            {'label': '入金先', 'value': 'DeepSeek の株式会社パイナのアカウント'},
            {'label': 'カード払いの欄', 'value': 'VISA とマスターだけ。アメックスを入れると「対応していないカード」と出た'},
            {'label': 'PayPal 経由のカード払い', 'value': 'アメックスは使えるが、ダンのブラウザでは払うボタンが出ない'},
            {'label': 'Google Pay', 'value': '押すとすぐ「支払い取り消し」になった'},
            {'label': '今の状態', 'value': 'お金は1円も引かれていない'},
        ],
        'choices': ['法人デビット（マスター末尾3666）で払う。9月に2回通ったやり方で、ダンがすぐ払える',
                    'アメックスで、自分のパソコンから PayPal のカード払いで払う'],
        'confirm_label': '払う',
    }
    out = asyncio.run(confirm_cards.tool(params))
    assert out['success'] is False
    assert '長すぎる' in out['error']


def test_short_card_fits():
    params = {
        'title': 'DeepSeek に11ドルをチャージ',
        'items': [{'label': '支払い', 'value': '11.66ドル（税込）'}, {'label': '入金先', 'value': 'DeepSeek（パイナ）'}],
        'choices': ['法人デビット 末尾3666', 'アメックス（自分のPCで）'],
    }
    assert confirm_cards._too_long(params) == ''
