import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";

type ContactPayload = {
  service?: string;
  serviceLabel?: string;
  name?: string;
  email: string;
  content: string;
  customFields?: Record<string, string>;
  fileNames?: string[];
  sourceUrl?: string;
};

function escapeText(s: string): string {
  return s.replace(/\r/g, "");
}

export async function POST(req: NextRequest) {
  let body: ContactPayload;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }

  if (!body.email?.trim() || !body.content?.trim()) {
    return NextResponse.json(
      { error: "メールアドレスとお問い合わせ内容は必須です。" },
      { status: 400 },
    );
  }

  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(body.email.trim())) {
    return NextResponse.json(
      { error: "メールアドレスの形式が正しくありません。" },
      { status: 400 },
    );
  }

  const apiKey = process.env.RESEND_API_KEY;
  if (!apiKey) {
    return NextResponse.json(
      { error: "サーバー設定エラー: メール送信が無効です。" },
      { status: 500 },
    );
  }

  const toEmail = process.env.KITTOKU_CONTACT_TO_EMAIL || "shub6923@gmail.com";

  const customLines = body.customFields
    ? Object.entries(body.customFields)
        .filter(([, v]) => v && v.trim())
        .map(([k, v]) => `【${k}】 ${escapeText(v)}`)
        .join("\n")
    : "";

  const fileLines =
    body.fileNames && body.fileNames.length > 0
      ? `\n【添付ファイル名】\n${body.fileNames.map((f) => `・${f}`).join("\n")}\n※ 実体ファイルは別途ご対応をお願いします。\n`
      : "";

  const receivedAt = new Date().toLocaleString("ja-JP", {
    timeZone: "Asia/Tokyo",
  });

  const text = `吉川特装ホームページから新規お問い合わせが届きました。

━━━━━━━━━━━━━━━━━━━━━━
【お問い合わせ種別】 ${body.serviceLabel || body.service || "未選択"}
【お名前】 ${body.name?.trim() || "未記入"}
【メールアドレス】 ${body.email.trim()}
━━━━━━━━━━━━━━━━━━━━━━
${customLines ? `\n${customLines}\n` : ""}
【お問い合わせ内容】
${escapeText(body.content)}
${fileLines}
━━━━━━━━━━━━━━━━━━━━━━
受付日時 : ${receivedAt}
送信元URL : ${body.sourceUrl || "不明"}
`;

  const resp = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from: "吉川特装HP <onboarding@resend.dev>",
      reply_to: body.email.trim(),
      to: [toEmail],
      subject: `[吉川特装HP] お問い合わせ - ${body.serviceLabel || body.service || "一般"}`,
      text,
    }),
  });

  if (!resp.ok) {
    const errBody = await resp.text();
    console.error("Resend error:", resp.status, errBody);
    return NextResponse.json(
      { error: "メール送信に失敗しました。時間をおいて再度お試しください。" },
      { status: 502 },
    );
  }

  return NextResponse.json({ success: true });
}
