import { NextRequest, NextResponse } from "next/server";
import {
  supabaseConfig,
  sbHeaders,
  clip,
  isValidEmail,
  looksLikeSpam,
  configError,
} from "../lib";

export const runtime = "nodejs";

// 質問一覧（新着順・回答数つき・メールは含めない）
export async function GET() {
  const { url, key } = supabaseConfig();
  if (!url || !key) return configError();

  const endpoint = new URL("/rest/v1/denki_qa_question", url);
  endpoint.searchParams.set(
    "select",
    "id,created_at,author_name,title,body,denki_qa_answer(count)",
  );
  endpoint.searchParams.set("is_hidden", "eq.false");
  endpoint.searchParams.set("order", "created_at.desc");
  endpoint.searchParams.set("limit", "200");

  const res = await fetch(endpoint, { headers: sbHeaders(key), cache: "no-store" });
  if (!res.ok) {
    return NextResponse.json({ error: "読み込みに失敗しました。" }, { status: 502 });
  }
  const rows = await res.json();
  // 回答数を平坦化
  const out = (rows as Array<Record<string, unknown>>).map((r) => {
    const ans = r.denki_qa_answer as Array<{ count: number }> | undefined;
    const answerCount = Array.isArray(ans) && ans[0] ? ans[0].count : 0;
    return {
      id: r.id,
      created_at: r.created_at,
      author_name: r.author_name,
      title: r.title,
      body: r.body,
      answer_count: answerCount,
    };
  });
  return NextResponse.json(out, { headers: { "Cache-Control": "no-store" } });
}

// 質問の投稿（登録不要・メールは任意で非公開）
export async function POST(req: NextRequest) {
  const { url, key } = supabaseConfig();
  if (!url || !key) return configError();

  let raw: Record<string, unknown>;
  try {
    raw = await req.json();
  } catch {
    return NextResponse.json({ error: "不正なリクエストです。" }, { status: 400 });
  }

  // ハニーポット（人間には見えない欄）が埋まっていたらスパムとみなし、成功を装って破棄
  if (clip(raw.website, 1)) {
    return NextResponse.json({ ok: true });
  }

  const author_name = clip(raw.author_name, 40) || "名無しの技術者";
  const title = clip(raw.title, 120);
  const body = clip(raw.body, 4000);
  const emailRaw = clip(raw.email, 200);

  if (!title || !body) {
    return NextResponse.json(
      { error: "タイトルと内容を入力してください。" },
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

  const endpoint = new URL("/rest/v1/denki_qa_question", url);
  const res = await fetch(endpoint, {
    method: "POST",
    headers: sbHeaders(key, true),
    body: JSON.stringify({
      author_name,
      title,
      body,
      email: emailRaw || null,
    }),
  });
  if (!res.ok) {
    return NextResponse.json({ error: "投稿に失敗しました。" }, { status: 502 });
  }
  const created = (await res.json())[0];
  return NextResponse.json({ ok: true, id: created?.id });
}
