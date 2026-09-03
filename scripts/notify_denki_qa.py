# -*- coding: utf-8 -*-
"""
電管ナレッジ 質問掲示板の回答通知

未通知（notified=false）の回答を探し、その質問にメールが登録されていれば
質問者へ「回答が付きました」とお知らせメールを送る。送信後は notified=true にする。
メール未登録の質問への回答も notified=true にして再処理を防ぐ。

15分おきにWindowsタスクスケジューラから実行する想定。
"""
import os
import sys
import io
import smtplib
import ssl
from email.mime.text import MIMEText
from email.utils import formataddr

import requests
from dotenv import load_dotenv

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "")
SITE_URL = "https://denki-knowledge-done.vercel.app/"

H = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
HW = {**H, "Content-Type": "application/json"}


def sb_get(path):
    r = requests.get(f"{SUPABASE_URL}/rest/v1/{path}", headers=H, timeout=30)
    r.raise_for_status()
    return r.json()


def mark_notified(answer_id):
    requests.patch(
        f"{SUPABASE_URL}/rest/v1/denki_qa_answer?id=eq.{answer_id}",
        headers=HW,
        json={"notified": True},
        timeout=30,
    )


def send_mail(to_addr, subject, body):
    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = formataddr(("電管ナレッジ検索", GMAIL_ADDRESS))
    msg["To"] = to_addr
    msg["Subject"] = subject
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as s:
        s.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        s.send_message(msg)


def main():
    answers = sb_get(
        "denki_qa_answer?select=id,question_id,author_name,body,email,created_at"
        "&notified=eq.false&is_hidden=eq.false&order=created_at.asc"
    )
    if not answers:
        print("未通知の回答なし")
        return

    sent = 0
    skipped = 0
    for a in answers:
        qrows = sb_get(
            f"denki_qa_question?select=title,email,is_hidden&id=eq.{a['question_id']}"
        )
        q = qrows[0] if qrows else None
        if not q or q.get("is_hidden"):
            mark_notified(a["id"])
            continue

        # スレッド参加者（質問者＋全回答者）を集め、今回の回答者本人は除外
        arows = sb_get(
            f"denki_qa_answer?select=email&question_id=eq.{a['question_id']}"
        )
        exclude = (a.get("email") or "").strip().lower()
        recipients = set()
        if q.get("email"):
            recipients.add(q["email"].strip())
        for r in arows:
            if r.get("email"):
                recipients.add(r["email"].strip())
        targets = [e for e in recipients if e and e.lower() != exclude]

        if not targets:
            skipped += 1
            mark_notified(a["id"])
            continue

        snippet = a["body"][:200] + ("…" if len(a["body"]) > 200 else "")
        body = (
            f"質問「{q['title']}」に新しい回答が付きました。\n\n"
            f"── 回答（{a['author_name']} さん）──\n"
            f"{snippet}\n\n"
            f"続きや他の回答、返信はこちらの「質問・相談」タブからどうぞ。\n"
            f"{SITE_URL}\n\n"
            f"※このメールは、質問・回答時にメールアドレスをご記入いただいた方にお送りしています。\n"
            f"電管ナレッジ検索"
        )
        try:
            for to in targets:
                send_mail(to, "【電管ナレッジ】質問に新しい回答が付きました", body)
                sent += 1
                print(f"通知送信: {to} <- 質問「{q['title']}」")
        except Exception as e:
            print(f"送信失敗（再試行のため未通知のまま）: {e}")
            continue  # notified を立てずに次回再試行
        mark_notified(a["id"])

    print(f"完了: 送信 {sent} 件 / 宛先なしでスキップ {skipped} 件")


if __name__ == "__main__":
    main()
