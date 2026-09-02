'use client';

/**
 * 部屋ボード v2 ビジュアルモック 案C: フリーボード（ポストイット＋因果矢印）
 *
 * - 付箋の色＝手番（黄=あなた / 青=ダン / 灰=待ち）
 * - 矢印＝因果・依存（「これが決まるとこれが動く」）
 * - 完了・中止は貼られない（履歴タブへ）
 * - ページを開くと付箋が1枚ずつ貼られていく＝実物では会話に合わせて
 *   リアルタイムに貼られていく感覚のデモ
 *
 * データは「Epic Gamesログインと認証設定」部屋の実状況ベースの手書きモック。
 */

type NoteColor = 'you' | 'dan' | 'wait';

type Note = {
  id: string;
  x: number;
  y: number;
  w: number;
  rot: number;
  color: NoteColor;
  title: string;
  body?: string;
  live?: string;
  stale?: boolean;
  small?: boolean;
  delay: number; // 貼られる順番（秒）
};

const NOTES: Note[] = [
  // 左クラスタ: Stripe 2FA
  {
    id: 'decision1',
    x: 60, y: 48, w: 170, rot: -3, color: 'wait', small: true,
    title: '本番アカウント。方式は認証アプリで',
    delay: 0.2,
  },
  {
    id: 'stripe2fa',
    x: 80, y: 150, w: 210, rot: 2, color: 'you',
    title: 'Stripe本番の2段階認証追加',
    body: '進めてよければ「進めて」のひと言',
    delay: 0.6,
  },
  // 右クラスタ: hCaptcha転用
  {
    id: 'sitepick',
    x: 500, y: 52, w: 200, rot: -2, color: 'you',
    title: 'hCaptcha転用テストの対象サイト選び',
    body: '試したいログイン先を2つほど',
    delay: 1.0,
  },
  {
    id: 'test',
    x: 460, y: 300, w: 220, rot: 1, color: 'dan',
    title: 'hCaptcha座標方式の他サイト転用テスト',
    live: '2captchaに画像を送信中…（3/5サイト目）',
    delay: 1.4,
  },
  {
    id: 'balance',
    x: 220, y: 390, w: 180, rot: -1, color: 'wait',
    title: '2captcha残高の補充',
    body: '9/3(木)ごろ低下の見込み',
    delay: 1.8,
  },
  // 停滞
  {
    id: 'smsdoc',
    x: 60, y: 478, w: 190, rot: 3, color: 'wait', stale: true,
    title: 'SMS転送 新アプリ版の手順ドキュメント化',
    body: '10日動きなし',
    delay: 2.2,
  },
];

type Arrow = {
  id: string;
  d: string;        // SVG path
  label?: string;
  lx?: number;      // ラベル位置
  ly?: number;
  dashed?: boolean;
  delay: number;
};

const ARROWS: Arrow[] = [
  // 方式決定 → Stripe 2FA
  { id: 'a1', d: 'M 145 118 C 150 130, 160 138, 170 148', delay: 0.9 },
  // サイト選び → 転用テスト（決まったら広がる）
  { id: 'a2', d: 'M 595 172 C 605 220, 595 255, 580 292', label: '決まったら着手', lx: 650, ly: 240, delay: 1.7 },
  // 残高 → 転用テスト（依存）
  { id: 'a3', d: 'M 405 425 C 425 415, 435 400, 452 385', label: '残高が要る', lx: 420, ly: 445, dashed: true, delay: 2.1 },
];

const noteStyle: Record<NoteColor, { bg: string; edge: string }> = {
  you: { bg: '#fde047', edge: '#eab308' },
  dan: { bg: '#7dd3fc', edge: '#0ea5e9' },
  wait: { bg: '#d6d3d1', edge: '#a8a29e' },
};

function PostIt({ n }: { n: Note }) {
  const s = noteStyle[n.color];
  return (
    <div
      className={`note absolute rounded-sm px-3.5 pb-3 pt-4 text-[#1c1917] shadow-[4px_6px_14px_rgba(0,0,0,0.45)] ${n.stale ? 'opacity-40' : ''}`}
      style={{
        left: n.x,
        top: n.y,
        width: n.w,
        background: s.bg,
        transform: `rotate(${n.rot}deg)`,
        animationDelay: `${n.delay}s`,
        borderTop: `6px solid ${s.edge}`,
      }}
    >
      <div className={`font-bold leading-snug ${n.small ? 'text-[12px]' : 'text-[13.5px]'}`}>{n.title}</div>
      {n.body && <div className="mt-1 text-[11.5px] leading-snug text-[#44403c]">{n.body}</div>}
      {n.live && (
        <div className="mt-1.5 flex items-center gap-1.5 text-[11px] font-semibold text-[#075985]">
          <span className="live-dot h-1.5 w-1.5 shrink-0 rounded-full bg-[#0284c7]" />
          {n.live}
        </div>
      )}
    </div>
  );
}

function FreeBoard() {
  return (
    <div className="rounded-2xl border border-white/10 bg-[#101214] p-5">
      {/* ヘッダー */}
      <div className="mb-3 flex items-center justify-between">
        <div className="flex gap-1 rounded-full bg-white/5 p-1">
          <span className="rounded-full bg-white/15 px-4 py-1 text-xs font-semibold text-white">今</span>
          <span className="rounded-full px-4 py-1 text-xs text-white/40">履歴</span>
        </div>
        <div className="flex items-center gap-3 text-[11px] text-white/60">
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-[2px]" style={{ background: noteStyle.you.bg }} />
            あなた
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-[2px]" style={{ background: noteStyle.dan.bg }} />
            ダン
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-[2px]" style={{ background: noteStyle.wait.bg }} />
            待ち
          </span>
        </div>
      </div>

      {/* ボード面: ドットグリッド */}
      <div
        className="relative h-[600px] overflow-hidden rounded-xl"
        style={{
          background:
            'radial-gradient(circle, rgba(255,255,255,0.07) 1px, transparent 1px) 0 0 / 26px 26px, #16181b',
        }}
      >
        {/* 矢印レイヤー */}
        <svg className="pointer-events-none absolute inset-0 h-full w-full">
          <defs>
            <marker id="arrowhead" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
              <path d="M 0 0 L 8 4 L 0 8 Z" fill="rgba(255,255,255,0.55)" />
            </marker>
          </defs>
          {ARROWS.map((a) => (
            <g key={a.id} className="arrow" style={{ animationDelay: `${a.delay}s` }}>
              <path
                d={a.d}
                fill="none"
                stroke="rgba(255,255,255,0.55)"
                strokeWidth={1.8}
                strokeDasharray={a.dashed ? '5 4' : undefined}
                markerEnd="url(#arrowhead)"
              />
              {a.label && (
                <text x={a.lx} y={a.ly} textAnchor="middle" fill="rgba(255,255,255,0.5)" fontSize={11}>
                  {a.label}
                </text>
              )}
            </g>
          ))}
        </svg>

        {/* 付箋レイヤー */}
        {NOTES.map((n) => (
          <PostIt key={n.id} n={n} />
        ))}
      </div>

      <div className="mt-3 text-center text-[11px] text-white/30">
        実物では会話・ダンの作業に合わせて付箋がこの調子でリアルタイムに貼られていきます／付箋はドラッグで並べ替え可（あなたの配置をダンも尊重）
      </div>
    </div>
  );
}

export default function BoardMockPage() {
  return (
    <div className="fixed inset-0 overflow-y-auto bg-[#07080a] px-6 py-10 text-white">
      <style>{`
        .live-dot { animation: blink 1.2s ease-in-out infinite; }
        @keyframes blink { 0%,100% { opacity: 1 } 50% { opacity: 0.25 } }
        .note {
          animation: stick 0.35s cubic-bezier(0.34, 1.56, 0.64, 1) both;
        }
        @keyframes stick {
          from { opacity: 0; transform: scale(1.25) rotate(0deg); }
          to { opacity: 1; }
        }
        .arrow { animation: fadein 0.5s ease both; }
        @keyframes fadein { from { opacity: 0 } to { opacity: 1 } }
      `}</style>

      <div className="mx-auto max-w-3xl space-y-6">
        <div>
          <h1 className="text-lg font-bold">部屋ボード v2 — 案C: フリーボード（ポストイット＋因果矢印）</h1>
          <p className="mt-1 text-sm text-white/40">
            色＝手番、矢印＝因果・依存。完了・中止は貼られない。リロードすると貼られていく様子が見られます。
          </p>
        </div>
        <FreeBoard />
      </div>
    </div>
  );
}
