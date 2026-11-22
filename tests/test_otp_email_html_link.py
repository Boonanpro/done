"""ボタンの裏にだけURLがあるメール（Claude のサインインのメール）から、ワンタイムURLを取り出せる。"""
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.services.otp_service import OTPService


HTML = """<html><head><style>@import url(https://fonts.googleapis.com/css?family=Roboto:300,400);
@font-face { src: url('https://assets.claude.ai/Fonts/AnthropicSans-Text-Regular-Static.otf'); }</style></head>
<body><a href="https://claude.ai"><img src="https://assets.claude.ai/logo.png"></a>
<p>Claudeにサインイン</p><p>以下のボタンをクリックしてサインインを完了してください。このリンクは10分で有効期限が切れます。</p>
<a href="https://claude.ai/magic-link#abc123&amp;x=1" style="color:#fff"><span>サインイン</span></a>
<p>お困りですか？ <a href="https://support.anthropic.com/">Anthropicサポート</a></p>
<a href="https://claude.ai/help">ヘルプ</a> · <a href="https://www.anthropic.com/legal/privacy">プライバシー</a>
</body></html>"""


def _svc():
    return OTPService.__new__(OTPService)


def _mail(html, plain=None):
    m = MIMEMultipart("alternative")
    m["Subject"] = "Claudeへの安全なリンクが届きました"
    if plain is not None:
        m.attach(MIMEText(plain, "plain", "utf-8"))
    m.attach(MIMEText(html, "html", "utf-8"))
    return m


def test_button_only_html_mail_gives_the_sign_in_link():
    assert _svc()._extract_link_from_email(_mail(HTML), "Claudeへの安全なリンクが届きました") == \
        "https://claude.ai/magic-link#abc123&x=1"


def test_font_and_footer_links_are_not_taken():
    html = HTML.replace('<a href="https://claude.ai/magic-link#abc123&amp;x=1" style="color:#fff"><span>サインイン</span></a>', "")
    assert _svc()._extract_link_from_email(_mail(html), "") is None


def test_plain_text_mail_still_works():
    plain = "Tap to reset your password: https://ig.me/r/xyz"
    assert _svc()._extract_link_from_email(_mail("<p>x</p>", plain), "") == "https://ig.me/r/xyz"
