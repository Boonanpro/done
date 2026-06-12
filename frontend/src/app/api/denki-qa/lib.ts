import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { NextResponse } from "next/server";

let rootEnvCache: Record<string, string> | null = null;

function rootEnvValue(name: string): string | undefined {
  if (process.env[name]) return process.env[name];
  if (process.env.VERCEL) return undefined;
  if (!rootEnvCache) {
    rootEnvCache = {};
    try {
      const text = readFileSync(resolve(process.cwd(), "..", ".env"), "utf-8");
      for (const line of text.split(/\r?\n/)) {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith("#")) continue;
        const index = trimmed.indexOf("=");
        if (index <= 0) continue;
        const key = trimmed.slice(0, index).trim();
        let value = trimmed.slice(index + 1).trim();
        if (
          (value.startsWith('"') && value.endsWith('"')) ||
          (value.startsWith("'") && value.endsWith("'"))
        ) {
          value = value.slice(1, -1);
        }
        rootEnvCache[key] = value;
      }
    } catch {
      // Keep the existing config error path when local env is unavailable.
    }
  }
  return rootEnvCache[name];
}

// 質問・相談掲示板（電管ナレッジ）のサーバー側共通処理。
// Supabase へは service_role キーで直接アクセスする（RLSはバイパス／メールは公開しない）。

export function supabaseConfig() {
  const url = rootEnvValue("SUPABASE_URL") || rootEnvValue("NEXT_PUBLIC_SUPABASE_URL");
  const key =
    rootEnvValue("SUPABASE_SERVICE_ROLE_KEY") ||
    rootEnvValue("SUPABASE_SERVICE_KEY") ||
    rootEnvValue("SUPABASE_KEY") ||
    rootEnvValue("NEXT_PUBLIC_SUPABASE_ANON_KEY");
  return { url, key };
}

export function sbHeaders(key: string, write = false) {
  const h: Record<string, string> = {
    apikey: key,
    Authorization: `Bearer ${key}`,
  };
  if (write) {
    h["Content-Type"] = "application/json";
    h["Prefer"] = "return=representation";
  }
  return h;
}

export function clip(s: unknown, max: number): string {
  return String(s ?? "").trim().slice(0, max);
}

export function isValidEmail(s: string): boolean {
  if (!s) return false;
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(s);
}

// 軽いスパム判定: 本文中のリンク数が多すぎる投稿を弾く
export function looksLikeSpam(text: string): boolean {
  const links = (text.match(/https?:\/\//gi) || []).length;
  return links >= 4;
}

export function configError() {
  return NextResponse.json(
    { error: "保存先が設定されていません。" },
    { status: 500 },
  );
}
