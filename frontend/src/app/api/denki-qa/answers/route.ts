import { NextRequest, NextResponse } from "next/server";
import {
  supabaseConfig,
  sbHeaders,
  clip,
  isValidEmail,
  looksLikeSpam,
  configError,
} from "../lib";
import { notifyThread } from "../mail";

export const runtime = "nodejs";

// 指定した質問への回答一覧（古い順）
export async function GET(req: NextRequest) {
  const { url, key } = supabaseConfig();
  if (!url || !key) return configError();

  const qid = req.nextUrl.searchParams.get("question_id")?.trim();
  if (!qid) {
    return NextResponse.json({ error: "question_id が必要です。" }, { status: 400 });
  }

  const endpoint = new URL("/rest/v1/denki_qa_answer", url);
  endpoint.searchParams.set("select", "id,created_at,author_name,body");
  endpoint.searchParams.set("question_id", `eq.${qid}`);
  endpoint.searchParams.set("is_hidden", "eq.false");
  endpoint.searchParams.set("order", "created_at.asc");

  const res = await fetch(endpoint, { headers: sbHeaders(key), cache: "no-store" });
  if (!res.ok) {
    return NextResponse.json({ error: "読み込みに失敗しました。" }, { status: 502 });
  }
  return NextResponse.json(await res.json(), {
    headers: { "Cache-Control": "no-store" },
  });
}

// 回答の投稿
export async function POST(req: NextRequest) {
  const { url, key } = supabaseConfig();
  if (!url || !key) return configError();

  let raw: Record<string, unknown>;
  try {
    raw = await req.json();
  } catch {
    return NextResponse.json({ error: "不正なリクエストです。" }, { status: 400 });
  }

  if (clip(raw.website, 1)) {
    return NextResponse.json({ ok: true });
  }

  const question_id = clip(raw.question_id, 60);
  const author_name = clip(raw.author_name, 40) || "名無しの技術者";
  const body = clip(raw.body, 4000);
  const emailRaw = clip(raw.email, 200);

  if (!question_id || !body) {
    return NextResponse.json(
      { error: "回答内容を入力してください。" },
      { status: 400 },
    );
  }
  if (emailRaw && !isValidEmail(emailRaw)) {
    return NextResponse.json(
      { error: "メールアドレスの形式が正しくありません。" },
      { status: 400 },
    );
  }
  if (looksLikeSpam(body)) {
    return NextResponse.json(
      { error: "リンクが多すぎます。本文を見直してください。" },
      { status: 400 },
    );
  }

  const endpoint = new URL("/rest/v1/denki_qa_answer", url);
  const res = await fetch(endpoint, {
    method: "POST",
    headers: sbHeaders(key, true),
    body: JSON.stringify({
      question_id,
      author_name,
      body,
      email: emailRaw || null,
    }),
  });
  if (!res.ok) {
    return NextResponse.json({ error: "投稿に失敗しました。" }, { status: 502 });
  }
  const created = (await res.json())[0];

  // 投稿の瞬間に、スレッド参加者（自分以外）へ即時メール通知。
  // 成功したら notified=true を立てる。失敗時は false のまま残し、予備の定期処理が拾う。
  try {
    await notifyThread(question_id, author_name, body, emailRaw);
    if (created?.id) {
      await fetch(`${url}/rest/v1/denki_qa_answer?id=eq.${created.id}`, {
        method: "PATCH",
        headers: sbHeaders(key, true),
        body: JSON.stringify({ notified: true }),
      });
    }
  } catch (e) {
    console.error("denki-qa notify failed (will retry via fallback):", e);
  }

  return NextResponse.json({ ok: true, id: created?.id });
}
