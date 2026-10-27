import {randomBytes} from 'node:crypto';
import {NextRequest, NextResponse} from 'next/server';

// アプリから成果物を「ブラウザで開く」時の入口（10-25 本人「俺にログインさせないで。自動でログインして」）。
// スマホのブラウザはアプリのログインを持っていないので、アプリがここで使い捨ての入館証をもらい、
// ブラウザはそれを持ってここを開く。ブラウザにはダンのログイン（30日もつ更新用の記録つき）が入り、
// 頼まれた画面へそのまま進む。入館証は60秒・1回きりで、URL の # の後ろにだけ載る（サーバーの記録に残らない）。
// X運用室の artifacts/x-operation/open と同じ作りを、どの成果物にも使えるようにしたもの。
// 10-27 からパソコンの画面（成果物タブの全画面・チャットのボタン）も、別のタブを開く時にここを通る（lib/signed-in-open.ts）。

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const origin = process.env.DAN_PUBLIC_ORIGIN || 'https://dan.paina.info';
const core = process.env.CORE_BACKEND_URL || 'http://127.0.0.1:9000';
const ACCESS_MAX_AGE = 24 * 60 * 60;        // app/config.py JWT_ACCESS_TOKEN_EXPIRE_MINUTES と同じ
const REFRESH_MAX_AGE = 30 * 24 * 60 * 60;  // app/config.py JWT_REFRESH_TOKEN_EXPIRE_DAYS と同じ
const TICKET_MS = 60_000;

type Ticket = {access: string; refresh: string | null; to: string; user: string; expires: number};
const tickets = new Map<string, Ticket>();
const privateHeaders = {'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'};
const fail = (status: number) => NextResponse.json({error: 'ダンのアプリからもう一度開いてください。'}, {status, headers: privateHeaders});

// 行き先は、ダンの入口の中の道か、https の住所だけ。
function destination(raw: unknown): string | null {
  if (typeof raw !== 'string' || raw.length > 2000) return null;
  if (raw.startsWith('/') && !raw.startsWith('//') && !raw.startsWith('/\\')) return raw;
  try {
    const url = new URL(raw);
    if (url.protocol !== 'https:' || url.username || url.password) return null;
    return url.toString();
  } catch { return null; }
}

async function json(path: string, init: RequestInit): Promise<Record<string, unknown> | null> {
  const response = await fetch(core + path, {...init, cache: 'no-store', signal: AbortSignal.timeout(15000)}).catch(() => null);
  if (!response?.ok) return null;
  return response.json().catch(() => null);
}

export async function POST(req: NextRequest) {
  // ブラウザからの引き換えは同じ入口からだけ。アプリ（ネイティブ）の要求には Origin が無い。
  const source = req.headers.get('origin');
  if (source && source !== origin && source !== req.nextUrl.origin) return fail(403);
  for (const [key, value] of tickets) if (value.expires <= Date.now()) tickets.delete(key);
  const input = await req.json().catch(() => null) as Record<string, unknown> | null;

  const authorization = req.headers.get('authorization');
  if (authorization?.startsWith('Bearer ')) {
    // アプリからの申し込み: ログインを確かめ、ブラウザ用に新しいログインの組を作って預かる。
    const to = destination(input?.to);
    if (!to) return fail(400);
    const me = await json('/api/v1/chat/me', {headers: {Authorization: authorization}});
    if (!me) return fail(401);
    let access = authorization.slice(7), refresh: string | null = null;
    if (typeof input?.refresh_token === 'string' && input.refresh_token) {
      const pair = await json('/api/v1/chat/refresh', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({refresh_token: input.refresh_token}),
      });
      if (typeof pair?.access_token === 'string' && typeof pair?.refresh_token === 'string') {
        access = pair.access_token; refresh = pair.refresh_token;
      }
    }
    if (tickets.size >= 1000) return fail(429);
    const ticket = randomBytes(32).toString('base64url');
    tickets.set(ticket, {access, refresh, to, user: typeof me.id === 'string' ? me.id : '', expires: Date.now() + TICKET_MS});
    return NextResponse.json({url: `${origin}/enter#${ticket}`}, {headers: privateHeaders});
  }

  // ブラウザからの引き換え: 入館証を1回だけ使い、ログインの記録を入れて行き先を返す。
  const ticket = input?.ticket;
  if (typeof ticket !== 'string' || !/^[\w-]{43}$/.test(ticket)) return fail(401);
  const entry = tickets.get(ticket);
  tickets.delete(ticket);   // 非同期の処理より先に消す。同時に使い回しても通らない
  if (!entry || entry.expires <= Date.now()) return fail(401);
  const secure = origin.startsWith('https:');
  // token と user は、このブラウザに残っている画面用のログイン（localStorage）を入れ替えるため。
  const response = NextResponse.json({to: entry.to, token: entry.access, user: entry.user}, {headers: privateHeaders});
  response.cookies.set('done_access_token', entry.access, {httpOnly: true, secure, sameSite: 'lax', path: '/', maxAge: ACCESS_MAX_AGE});
  // 更新用の記録が作れなかった時は、前にこのブラウザにいた人の更新用の記録で入り直さないよう消す。
  response.cookies.set('done_refresh_token', entry.refresh || '', {
    httpOnly: true, secure, sameSite: 'lax', path: '/api/v1/chat/refresh', maxAge: entry.refresh ? REFRESH_MAX_AGE : 0,
  });
  return response;
}

export function GET() {
  const nonce = randomBytes(18).toString('base64');
  return new NextResponse(`<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>ダン</title><body style="font-family:system-ui,sans-serif;color:#444;display:grid;place-items:center;min-height:90vh;margin:0"><p id="status">開いています…</p><script nonce="${nonce}">
  function connect() {
    const ticket = location.hash.slice(1);
    if (!ticket) return;
    history.replaceState(null, '', location.pathname);
    fetch(location.pathname, {method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({ticket})})
      .then(r=>{if(!r.ok)throw Error();return r.json();})
      .then(d=>{
        // 同じ人の画面の記録は残し、ログインだけ新しくする。別の人の記録なら消す（前にこのブラウザにいた人で動かない）。
        let same=false;
        try{same=!!d.user&&JSON.parse(localStorage.getItem('done-auth')||'{}').state.user.id===d.user;}catch(e){}
        if(!same)localStorage.removeItem('done-auth');
        if(d.token)localStorage.setItem('done-token',d.token);else localStorage.removeItem('done-token');
        location.replace(d.to);})
      .catch(()=>{document.getElementById('status').textContent='開く期限が切れました。ダンのアプリからもう一度開いてください。';});
  }
  window.addEventListener('hashchange', connect);
  connect();
  </script></body></html>`, {headers: {...privateHeaders, 'Content-Type': 'text/html; charset=utf-8', 'Content-Security-Policy': `default-src 'none'; script-src 'nonce-${nonce}'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'`}});
}
