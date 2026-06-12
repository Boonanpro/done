import nodemailer from "nodemailer";
import { supabaseConfig, sbHeaders } from "./lib";

const SITE_URL = "https://denki-knowledge-done.vercel.app/";

function transporter() {
  const user = process.env.GMAIL_ADDRESS;
  const pass = (process.env.GMAIL_APP_PASSWORD || "").replace(/\s/g, "");
  if (!user || !pass) return null;
  return nodemailer.createTransport({
    host: "smtp.gmail.com",
    port: 465,
    secure: true,
    auth: { user, pass },
  });
}

async function sendMail(to: string, subject: string, text: string) {
  const t = transporter();
  if (!t) throw new Error("mail not configured");
  await t.sendMail({
    from: `電管ナレッジ検索 <${process.env.GMAIL_ADDRESS}>`,
    to,
    subject,
    text,
  });
}

/**
 * 質問スレッドの参加者（質問者＋回答者）全員に新着回答を通知する。
 * postedEmail（今書き込んだ本人）には送らない。
 * 成功すれば true（呼び出し側が notified=true を立てる）。失敗は投げる。
 */
export async function notifyThread(
  questionId: string,
  answerAuthor: string,
  answerBody: string,
  postedEmail: string,
): Promise<number> {
  const { url, key } = supabaseConfig();
  if (!url || !key) throw new Error("supabase not configured");

  // 質問（タイトル・通知先メール）
  const qRes = await fetch(
    `${url}/rest/v1/denki_qa_question?select=title,email,is_hidden&id=eq.${questionId}`,
    { headers: sbHeaders(key), cache: "no-store" },
  );
  const qRows = await qRes.json();
  const q = Array.isArray(qRows) ? qRows[0] : null;
  if (!q || q.is_hidden) return 0;

  // 同スレッドの回答者メール
  const aRes = await fetch(
    `${url}/rest/v1/denki_qa_answer?select=email&question_id=eq.${questionId}`,
    { headers: sbHeaders(key), cache: "no-store" },
  );
  const aRows = (await aRes.json()) as Array<{ email: string | null }>;

  const exclude = (postedEmail || "").trim().toLowerCase();
  const recipients = new Set<string>();
  if (q.email) recipients.add(String(q.email).trim());
  for (const r of aRows) if (r.email) recipients.add(String(r.email).trim());

  const targets = [...recipients].filter(
    (e) => e && e.toLowerCase() !== exclude,
  );
  if (targets.length === 0) return 0;

  const snippet =
    answerBody.length > 200 ? answerBody.slice(0, 200) + "…" : answerBody;
  const subject = "【電管ナレッジ】質問に新しい回答が付きました";
  const text =
    `質問「${q.title}」に新しい回答が付きました。\n\n` +
    `── 回答（${answerAuthor} さん）──\n${snippet}\n\n` +
    `続きや他の回答、返信はこちらの「質問・相談」タブからどうぞ。\n${SITE_URL}\n\n` +
    `※このメールは、質問・回答時にメールアドレスをご記入いただいた方にお送りしています。\n` +
    `電管ナレッジ検索`;

  let sent = 0;
  for (const to of targets) {
    await sendMail(to, subject, text);
    sent += 1;
  }
  return sent;
}
