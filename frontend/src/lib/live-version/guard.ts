// 成果物タブの画面が「自分が動かしている部品の版」と「サーバーの今のファイルの版」を
// 比べ、違えば部品を取り直して読み直す。サーバー側の版は ./server.ts。
//
// 違いが出る原因は3つあった（2026-10-18 実測）。
// - ブラウザが古い部品を持たされている（Cloudflare の4時間キャッシュ。F5 でも直らない）
// - HMR のつながりが切れていて、ファイルの直しが届いていない
// - 古い部品の上に、HMR で一部だけ新しい部品が届いて混ざっている
// どれも「部品に焼き込まれた版 ≠ サーバーの版」になるので、この1つの比較で拾う。
//
// この関数は layout.tsx がページの HTML に直接埋め込む（HTML は毎回取り直されるので、
// 部品が古くてもこの処理は新しい）。部品側の LiveVersionMark が読み込んだ版を
// window.__danLiveLoaded に書く。古い部品にはこの印が無いので、それも「違う」と数える。
// toString() で埋め込むので、外の変数・import を使わないこと。
//
// 成果物に裏側（_server）がある時は、裏側が今のファイルで動いているかも見る。裏側が古いまま
// 20秒続いたら「裏側の更新待ち」を出し（押しても古い動きになることがあるため）、裏側が
// 新しくなったら画面も読み直す（古い裏側から取った中身を残さない）。

export type LiveGuardOptions = { serverVersion: string };

type GuardState = {
  server: string;
  state: string;
  reason?: string;
  mismatchSince: number;
  backend?: string;
  check?: () => void;
};
type LiveWindow = Window & {
  __danLiveGuard?: GuardState;
  __danLiveLoaded?: string;
  __danUnsaved?: boolean;
};

export function installLiveGuard(opts: LiveGuardOptions): void {
  const w = window as LiveWindow;
  if (w.__danLiveGuard || !opts || !opts.serverVersion) return;
  const VERSION_URL = '/_live/live-version';
  const VIEW_URL = '/_live/live-view';
  const GRACE_MS = 15000; // HMR が届くまで待つ時間
  const POLL_MS = 15000;
  const HEARTBEAT_MS = 60000;
  const INPUT_QUIET_MS = 60000;
  const RELOAD_KEY = 'dan-live-reloads';
  const TAB_KEY = 'dan-live-tab';
  const guard: GuardState = { server: opts.serverVersion, state: 'starting', mismatchSince: 0 };
  w.__danLiveGuard = guard;

  let tab = '';
  try {
    tab = sessionStorage.getItem(TAB_KEY) || '';
    if (!tab) {
      tab = Math.random().toString(36).slice(2, 10);
      sessionStorage.setItem(TAB_KEY, tab);
    }
  } catch {
    tab = Math.random().toString(36).slice(2, 10);
  }
  let inFrame = false;
  try {
    inFrame = window.top !== window.self;
  } catch {
    inFrame = true;
  }
  const slugMatch = location.pathname.match(/\/(?:artifacts|preview)\/([^/?#]+)/);
  const slug = slugMatch ? slugMatch[1] : '';
  const startedAt = Date.now();

  // 入力中・保存中は勝手に読み直さない。保存は fetch の POST 等で出るので数えておく。
  let lastInput = 0;
  let pendingWrites = 0;
  const markInput = function () {
    lastInput = Date.now();
  };
  document.addEventListener('input', markInput, true);
  document.addEventListener('keydown', markInput, true);
  const origFetch = window.fetch;
  if (origFetch) {
    window.fetch = function (...args: Parameters<typeof fetch>) {
      const input = args[0];
      const init = args[1];
      const method = String((init && init.method) || (input instanceof Request ? input.method : 'GET')).toUpperCase();
      if (method === 'GET' || method === 'HEAD') return origFetch.apply(window, args);
      pendingWrites++;
      const done = function () {
        pendingWrites = Math.max(0, pendingWrites - 1);
      };
      try {
        const p = origFetch.apply(window, args);
        p.then(done, done);
        return p;
      } catch (err) {
        done();
        throw err;
      }
    } as typeof window.fetch;
  }
  const editingNow = function () {
    const el = document.activeElement as HTMLElement | null;
    if (!el) return false;
    const tag = el.tagName;
    return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable;
  };
  // 読み直すと失いそうな物があるか。成果物は data-dan-unsaved / window.__danUnsaved で
  // 「未保存あり」を知らせられる。
  const busyReason = function () {
    if (pendingWrites > 0) return 'saving';
    if (w.__danUnsaved || document.documentElement.hasAttribute('data-dan-unsaved')) return 'unsaved';
    if (editingNow()) return 'typing';
    if (lastInput && Date.now() - lastInput < INPUT_QUIET_MS) return 'typing';
    return '';
  };

  const recentReloads = function () {
    try {
      const list = JSON.parse(sessionStorage.getItem(RELOAD_KEY) || '[]') as number[];
      return list.filter(function (t) {
        return Date.now() - t < 180000;
      });
    } catch {
      return [] as number[];
    }
  };

  let lastSent = '';
  let lastSentAt = 0;
  const report = function (force?: boolean) {
    const loaded = typeof w.__danLiveLoaded === 'string' ? w.__danLiveLoaded : null;
    const payload = {
      tab: tab,
      slug: slug,
      path: location.pathname,
      frame: inFrame ? 'frame' : 'top',
      loaded: loaded,
      server: guard.server,
      state: guard.state,
      reason: guard.reason || '',
      visible: document.visibilityState === 'visible',
      reloads: recentReloads().length,
      backend: guard.backend || '',
      at: Date.now(),
    };
    const key = [payload.loaded, payload.server, payload.state, payload.reason, payload.visible, payload.backend].join('|');
    if (!force && key === lastSent && Date.now() - lastSentAt < HEARTBEAT_MS) return;
    lastSent = key;
    lastSentAt = Date.now();
    const body = JSON.stringify(payload);
    try {
      if (navigator.sendBeacon && navigator.sendBeacon(VIEW_URL, body)) return;
    } catch {
      // 下の fetch で送る
    }
    try {
      origFetch.call(window, VIEW_URL, { method: 'POST', body: body, keepalive: true, credentials: 'same-origin' });
    } catch {
      // 次の知らせに任せる
    }
  };

  let banner: HTMLButtonElement | null = null;
  const showBanner = function () {
    if (banner || !document.body) return;
    banner = document.createElement('button');
    banner.type = 'button';
    banner.textContent = '新しい版があります — 押すと読み直します';
    banner.setAttribute(
      'style',
      'position:fixed;left:50%;bottom:16px;transform:translateX(-50%);z-index:2147483647;' +
        'padding:8px 16px;border-radius:999px;border:1px solid #d4d4d8;background:#fff;color:#111;' +
        'font:14px/1.4 system-ui,sans-serif;box-shadow:0 4px 16px rgba(0,0,0,.18);cursor:pointer;',
    );
    banner.addEventListener('click', function () {
      refresh(true);
    });
    document.body.appendChild(banner);
  };
  const hideBanner = function () {
    if (banner && banner.parentNode) banner.parentNode.removeChild(banner);
    banner = null;
  };

  // 裏側が古い間の知らせ。押す物ではない（押しても直らない）ので、読み直しのボタンとは別に出す。
  let backendNote: HTMLDivElement | null = null;
  const showBackendNote = function (text: string) {
    if (!document.body) return;
    if (!backendNote) {
      backendNote = document.createElement('div');
      backendNote.setAttribute('role', 'status');
      backendNote.setAttribute(
        'style',
        'position:fixed;left:50%;top:12px;transform:translateX(-50%);z-index:2147483647;max-width:92vw;' +
          'padding:8px 14px;border-radius:10px;border:1px solid #f59e0b;background:#fffbeb;color:#78350f;' +
          'font:13px/1.5 system-ui,sans-serif;box-shadow:0 4px 16px rgba(0,0,0,.12);pointer-events:none;',
      );
      document.body.appendChild(backendNote);
    }
    backendNote.textContent = text;
  };
  const hideBackendNote = function () {
    if (backendNote && backendNote.parentNode) backendNote.parentNode.removeChild(backendNote);
    backendNote = null;
  };
  const BACKEND_GRACE_MS = 20000;
  let backendBehindSince = 0;
  let backendNoted = false;
  const seeBackend = function (b: { current?: boolean; state?: string } | null | undefined) {
    if (!b) {
      guard.backend = '';
      return;
    }
    if (b.current) {
      guard.backend = 'current';
      backendBehindSince = 0;
      if (backendNoted) {
        backendNoted = false;
        hideBackendNote();
        // 古い裏側から読んだ中身が画面に残っているので、入力中でなければ読み直す
        act();
      }
      return;
    }
    guard.backend = b.state || 'behind';
    if (!backendBehindSince) backendBehindSince = Date.now();
    if (Date.now() - backendBehindSince < BACKEND_GRACE_MS) return;
    backendNoted = true;
    showBackendNote(
      b.state === 'needs-restart'
        ? 'この画面の裏側（サーバー）は、ダン本体の再起動を待っています。それまでボタンが古い動きをすることがあります'
        : b.state === 'failed'
          ? 'この画面の裏側（サーバー）の新しい版が読み込めず、古い版で動いています。ダンが直すまで古い動きをすることがあります'
          : 'この画面の裏側（サーバー）を新しい版に切り替えています',
    );
  };

  let refreshing = false;
  // 部品をキャッシュを無視して取り直してから読み直す。ふつうの再読み込みだと、
  // ブラウザが持たされている古い部品をそのまま使うことがある。
  const refresh = function (byUser?: boolean) {
    if (refreshing) return;
    const reloads = recentReloads();
    if (!byUser && reloads.length >= 2) {
      guard.state = 'stale';
      guard.reason = 'reload-loop';
      showBanner();
      report();
      return;
    }
    refreshing = true;
    guard.state = 'reloading';
    report(true);
    try {
      reloads.push(Date.now());
      sessionStorage.setItem(RELOAD_KEY, JSON.stringify(reloads));
    } catch {
      // 数えられなくても読み直しは進める
    }
    const urls: Record<string, true> = {};
    try {
      performance.getEntriesByType('resource').forEach(function (entry) {
        if (entry.name.indexOf('/_next/static/') >= 0) urls[entry.name] = true;
      });
    } catch {
      // 取れなければ script タグだけで進める
    }
    Array.prototype.forEach.call(document.querySelectorAll('script[src],link[rel="stylesheet"][href]'), function (el: HTMLScriptElement | HTMLLinkElement) {
      const u = 'src' in el ? el.src : el.href;
      if (u && u.indexOf('/_next/static/') >= 0) urls[u] = true;
    });
    const jobs = Object.keys(urls).map(function (u) {
      return origFetch.call(window, u, { cache: 'reload', credentials: 'same-origin' }).then(
        function (r) {
          return r.arrayBuffer();
        },
        function () {
          return null;
        },
      );
    });
    const go = function () {
      location.reload();
    };
    Promise.all(jobs).then(go, go);
    setTimeout(go, 8000);
  };

  // 一度でも入力中で止めた画面は、前に出ている間は読み直さない（書きかけを消さない）。
  // ボタンを出して、本人が押すか、画面が裏に回った時に読み直す。
  let heldForInput = false;
  const act = function () {
    if (refreshing) return;
    let reason = busyReason();
    if (!reason && heldForInput && document.visibilityState === 'visible') reason = 'typed';
    if (!reason) {
      refresh(false);
      return;
    }
    if (reason === 'typing') heldForInput = true;
    guard.state = 'stale';
    guard.reason = reason;
    showBanner();
    report();
  };

  let compareTimer = 0;
  const compare = function () {
    if (compareTimer) {
      clearTimeout(compareTimer);
      compareTimer = 0;
    }
    const loaded = w.__danLiveLoaded;
    if (loaded === guard.server) {
      guard.mismatchSince = 0;
      guard.state = 'current';
      guard.reason = '';
      hideBanner();
      report();
      return;
    }
    const now = Date.now();
    if (!guard.mismatchSince) guard.mismatchSince = now;
    if (now - guard.mismatchSince < GRACE_MS || now - startedAt < GRACE_MS) {
      guard.state = 'checking';
      compareTimer = window.setTimeout(compare, 3000);
      return;
    }
    act();
  };

  let checking = false;
  const check = function () {
    if (checking || refreshing) return;
    checking = true;
    origFetch
      .call(window, slug ? VERSION_URL + '?slug=' + encodeURIComponent(slug) : VERSION_URL, {
        cache: 'no-store',
        credentials: 'same-origin',
      })
      .then(function (r) {
        return r.ok ? r.json() : null;
      })
      .then(
        function (data: { version?: string; backend?: { current?: boolean; state?: string } | null } | null) {
          checking = false;
          if (data) seeBackend(data.backend);
          // サーバーの版が変わっても待ち時間は数え直さない（ほかの作業がファイルを直し続けると、
          // HMR が切れた画面がいつまでも読み直さなくなる）。数え直すのは画面の版が届いた時だけ。
          if (data && typeof data.version === 'string' && data.version) guard.server = data.version;
          compare();
        },
        function () {
          checking = false;
          // 開発サーバーの再起動中などは次の確認に任せる
        },
      );
  };
  guard.check = check;

  window.addEventListener('dan-live-loaded', function () {
    guard.mismatchSince = 0;
    compare();
  });
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') {
      check();
      return;
    }
    // 裏に回った時は、保存中・未保存でなければ読み直してよい
    if ((guard.state === 'stale' || guard.state === 'checking') && guard.mismatchSince) {
      const reason = busyReason();
      if (reason !== 'saving' && reason !== 'unsaved') refresh(false);
    }
    report();
  });
  window.addEventListener('online', check);
  window.addEventListener('focus', check);
  let tick = 0;
  setInterval(function () {
    tick++;
    if (document.visibilityState === 'visible' || tick % 4 === 0) check();
    // 裏にある画面も、開いていることだけは4分おきに知らせる
    if (document.visibilityState === 'visible' || tick % 16 === 0) report();
  }, POLL_MS);
  // 閉じた（読み直す時も含む）ことを知らせる。読み直した後は同じ tab で新しい行に上書きされる。
  window.addEventListener('pagehide', function () {
    if (refreshing) return;
    guard.state = 'closed';
    report(true);
  });
  window.addEventListener('pageshow', function (event) {
    if ((event as PageTransitionEvent).persisted) check();
  });
  const begin = function () {
    setTimeout(check, 3000);
  };
  if (document.readyState === 'complete') begin();
  else window.addEventListener('load', begin);
}
