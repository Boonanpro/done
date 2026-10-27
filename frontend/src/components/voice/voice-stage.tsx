'use client';

/**
 * The stage of a call: the caption 「今の話: …」 and the scene the server draws while Dan talks (app/services/voice_stage.py).
 *
 * A scene is one of four things: an answer-shapes program (the same ```openui-lang parts as the chat: Flow, Stat, Compare,
 * Chart…, drawn with ShapeBlock), a free drawing (SVG/HTML the server cleaned, drawn in a sandboxed frame with no scripts
 * and its own origin), an image (one of Dan's files or an https URL; a photograph of a real page has its URL too) or a
 * message draft (the chat's outbound card as the stage sees it: recipient, subject, body, status; revised by voice, the
 * changed lines light up in place; sent by voice, the badge turns green. 2026-10-27). Since 2026-10-27 also a document of
 * one of the owner's sites (an article of the X room, a script: title, body, status; revised and published the same way)
 * and a picture made for the call (its waiting shown first, the picture when it arrives, redone on the owner's words).
 * A screen of this site (one of the owner's artifacts: the X room, the script room) is shown as the page itself in a
 * frame, signed in as the owner and usable by touch; a document of such a site is shown on that site's own screen, where
 * its editing assistant lays its suggestions (the owner on 2026-10-27: every screen on the stage must be the real one).
 * The server can ask that page to press one of its own buttons (approve all suggestions, reload): the command arrives
 * with the state and is passed to the page by postMessage once the page says it listens (StageFrame).
 * It arrives by long poll (GET /api/v1/voicelog/stage/<room>?after=<version>): the server answers the moment a newer
 * version exists, when the call ends, or after ~25 s. A program that fails the parts' validation is not shown; the
 * previous scene stays (checkCompleteShape).
 *
 * Only a new scene slides in. A version that changes the caption alone updates the caption in place and leaves the scene
 * untouched (2026-10-26: every caption change remounted the scene and replayed its entrance, 9 times in one call).
 *
 * Used by the PC voice panel (voice-session.tsx) and, as its own page, by the phone app's WebView (app/voice-stage/page.tsx).
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';

import { ShapeBlock, checkCompleteShape } from '@/components/chat/chat-shapes';

export type StageCard = {
  proposal_id: string; status: string; channel: string; to: string; to_name?: string; subject?: string; body: string;
  intent?: string; revision?: number; sent_at?: string; sendable?: boolean;
};

export type StageDoc = {
  id: string; kind: string; label?: string; title: string; body: string; status: string; revision?: number; account?: string; url?: string;
  error?: string; publishable?: boolean; publish_label?: string; page?: string; assistant?: boolean;
  assist?: { state: string; instruction?: string; message?: string; pending?: number } | null;
};

export type StageCommand = { seq: number; action: string; at: string };

export type StageMedia = {
  id: string; prompt: string; status: string; image?: string; previous?: string; revision?: number; history?: string[]; seconds?: number; error?: string;
};

export type StageState = {
  version: number; caption: string; program: string; html?: string; image?: string; page_url?: string; frame?: string; card?: StageCard | null;
  doc?: StageDoc | null; media?: StageMedia | null; command?: StageCommand | null;
  at: string | null; active: boolean; scenes?: number; session_id?: string;
};

export function stageHeaders(): Record<string, string> {
  const token = typeof localStorage !== 'undefined' ? localStorage.getItem('done-token') || '' : '';
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** The room's stage, kept current while `active`. null until the first answer. */
export function useVoiceStage(roomId: string, active: boolean, onState?: (s: StageState) => void): StageState | null {
  const [state, setState] = useState<StageState | null>(null);
  const onStateRef = useRef(onState);
  onStateRef.current = onState;
  useEffect(() => {
    if (!active || !roomId) return;
    let stopped = false;
    let after = 0;
    let session = '';
    const controller = { current: new AbortController() };
    const loop = async () => {
      let failures = 0;
      while (!stopped) {
        try {
          controller.current = new AbortController();
          const response = await fetch(`/api/v1/voicelog/stage/${encodeURIComponent(roomId)}?after=${after}&wait=25`, {
            headers: stageHeaders(), signal: controller.current.signal, cache: 'no-store',
          });
          if (stopped) return;
          if (!response.ok) throw new Error(String(response.status));
          const data = (await response.json()) as StageState;
          failures = 0;
          // a new call (session) is taken even if its version is not above the last one seen (the server counts on
          // across calls since 2026-10-25; this keeps older servers working too)
          if ((data.version || 0) > after || after === 0 || (data.session_id || '') !== session) {
            after = data.version || 0;
            session = data.session_id || '';
            setState(data);
            onStateRef.current?.(data);
          }
          if (!data.active) await new Promise((r) => setTimeout(r, 1500));   // no call yet (or it ended): look again, slowly
        } catch {
          if (stopped) return;
          failures += 1;
          await new Promise((r) => setTimeout(r, Math.min(5000, 500 * failures)));
        }
      }
    };
    void loop();
    return () => { stopped = true; controller.current.abort(); };
  }, [roomId, active]);
  return state;
}

type Scene = { kind: 'program'; program: string } | { kind: 'html'; html: string } | { kind: 'image'; image: string; pageUrl: string } | { kind: 'card'; card: StageCard }
  | { kind: 'doc'; doc: StageDoc } | { kind: 'media'; media: StageMedia } | { kind: 'frame'; path: string };

/** A page of this site the stage may open live: a path under /preview/ (the owner's artifacts), nothing else. */
export function stageFramePath(v: unknown): string | null {
  if (typeof v !== 'string') return null;
  const s = v.trim();
  return /^\/preview\/[A-Za-z0-9_-][^\s"'<>\\]{0,1800}$/.test(s) && !s.includes('..') && !s.includes('//') ? s : null;
}

/** An image the stage may show: one of Dan's files or an https URL (nothing else is a URL the screen should load). */
export function stageImageUrl(v: unknown): string | null {
  if (typeof v !== 'string') return null;
  const s = v.trim();
  if (/^\/api\/v1\/files\/[A-Za-z0-9._-]{1,200}$/.test(s)) return s;
  if (/^https:\/\/[A-Za-z0-9.-]+(:\d+)?\/[^\s"'<>\\]{0,1800}$/.test(s)) return s;
  return null;
}

/** The scene a state describes, or null when it has none the screen can draw. */
export function sceneOf(s: StageState | null): Scene | null {
  if (!s) return null;
  const program = s.program?.trim() || '';
  if (program) return checkCompleteShape(program).ok ? { kind: 'program', program } : null;
  const html = s.html?.trim() || '';
  if (html) return { kind: 'html', html };
  if (s.card && typeof s.card === 'object' && s.card.proposal_id) return { kind: 'card', card: s.card };
  if (s.doc && typeof s.doc === 'object' && s.doc.id) return { kind: 'doc', doc: s.doc };
  if (s.media && typeof s.media === 'object' && s.media.id) return { kind: 'media', media: s.media };
  const frame = stageFramePath(s.frame);
  if (frame) return { kind: 'frame', path: frame };
  const image = stageImageUrl(s.image);
  if (image) return { kind: 'image', image, pageUrl: s.page_url || '' };
  return null;
}

function sameScene(a: Scene | null, b: Scene | null): boolean {
  if (!a || !b || a.kind !== b.kind) return false;
  if (a.kind === 'program' && b.kind === 'program') return a.program === b.program;
  if (a.kind === 'html' && b.kind === 'html') return a.html === b.html;
  if (a.kind === 'image' && b.kind === 'image') return a.image === b.image;
  if (a.kind === 'card' && b.kind === 'card') return JSON.stringify(a.card) === JSON.stringify(b.card);
  if (a.kind === 'doc' && b.kind === 'doc') return JSON.stringify(a.doc) === JSON.stringify(b.doc);
  if (a.kind === 'media' && b.kind === 'media') return JSON.stringify(a.media) === JSON.stringify(b.media);
  if (a.kind === 'frame' && b.kind === 'frame') return a.path === b.path;
  return false;
}

const LAYOUT_PARTS = new Set(['Column', 'Row', 'Card', 'Heading', 'Text', 'Divider', 'Badge']);

/** The kind of scene, for telling growth (a flow with two more boxes) from a change (a flow -> big numbers): the parts used. */
export function sceneFamily(s: Scene): string {
  if (s.kind === 'doc' && stageFramePath(s.doc.page)) return 'page:' + s.doc.page;   // the same page: no entrance again
  if (s.kind === 'frame') return 'page:' + s.path;
  if (s.kind !== 'program') return s.kind;
  const names = new Set<string>();
  for (const m of s.program.matchAll(/\b([A-Z][A-Za-z]+)\(/g)) if (!LAYOUT_PARTS.has(m[1])) names.add(m[1]);
  return 'program:' + [...names].sort().join(',');
}

/** The document a free drawing is shown in: dark, no margins, the SVG filling the frame. */
export function drawingDocument(html: string): string {
  return `<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;height:100%;background:#0a0a0a;color:#f5f5f5;font-family:system-ui,-apple-system,sans-serif;overflow:hidden}svg{display:block;width:100%;height:100%}img{max-width:100%}</style></head><body>${html}</body></html>`;
}

/** The caption and the scene. Draws nothing until a scene exists (the orb alone is the call's face until then). */
export function VoiceStage({ roomId, active, className = '', onShown, fill = false }: { roomId: string; active: boolean; className?: string; onShown?: (shown: boolean) => void; fill?: boolean }) {
  // The scene on the stage and a number that changes only when the scene itself changes: the entrance animation keys
  // on it, so a caption-only version (or the same scene sent again) does not replay it. A program the checker refuses
  // (an unknown icon, a bad argument) keeps the previous scene instead of blanking the call's screen (2026-10-25).
  // A new call (session) starts empty.
  const [shownScene, setShownScene] = useState<{ scene: Scene | null; key: number; session: string }>({ scene: null, key: 0, session: '' });
  const state = useVoiceStage(roomId, active, (s) => {
    const session = s.session_id || '';
    const next = sceneOf(s);
    if (!next && s.program?.trim()) console.warn('[voice-stage] scene not drawable, keeping the last one');
    setShownScene((current) => {
      if (session !== current.session) return { scene: next, key: current.key + 1, session };
      if (!next || sameScene(next, current.scene)) return current;
      // the same kind of scene with more (or other) content updates in place: no entrance again (a flow growing from
      // 4 to 6 boxes as Dan lists them, 2026-10-27); a different kind of scene slides in
      const grows = !!current.scene && sceneFamily(next) === sceneFamily(current.scene);
      return { scene: next, key: grows ? current.key : current.key + 1, session };
    });
  });
  const { scene, key } = shownScene;
  const drawable = !!scene;
  const shown = !!state?.active && (drawable || !!state?.caption);
  const onShownRef = useRef(onShown);
  useEffect(() => { onShownRef.current = onShown; }, [onShown]);
  useEffect(() => { onShownRef.current?.(shown && drawable); }, [shown, drawable]);
  const drawing = useMemo(() => (scene?.kind === 'html' ? drawingDocument(scene.html) : ''), [scene]);
  if (!shown) return null;
  return (
    <div className={`flex flex-col gap-2 ${className}`} data-voice-stage={state?.version} data-stage-scene-key={key}>
      {state?.caption ? (
        <div className="flex items-center gap-2 text-xs text-muted-foreground" data-stage-caption>
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-primary" aria-hidden />
          <span className="truncate">今の話: {state.caption}</span>
        </div>
      ) : null}
      {scene ? (
        <div key={key} className="animate-in fade-in slide-in-from-bottom-2 duration-300 fill-mode-both" data-stage-scene data-stage-kind={scene.kind}>
          {scene.kind === 'program' ? (
            <ShapeBlock code={scene.program} complete live messageId={null} part="stage" renderFallback={() => null} />
          ) : scene.kind === 'card' ? (
            <StageMessageCard card={scene.card} />
          ) : scene.kind === 'doc' && stageFramePath(scene.doc.page) ? (
            <StageFrame path={stageFramePath(scene.doc.page)!} command={state?.command} fill={fill} title={scene.doc.label || '成果物の画面'}>
              <StageDocStatus doc={scene.doc} />
            </StageFrame>
          ) : scene.kind === 'doc' ? (
            <StageDocument doc={scene.doc} />
          ) : scene.kind === 'frame' ? (
            <StageFrame path={scene.path} command={state?.command} fill={fill} title={state?.caption || '成果物の画面'} />
          ) : scene.kind === 'media' ? (
            <StageMedia media={scene.media} />
          ) : scene.kind === 'html' ? (
            <iframe
              title="通話の画面の絵"
              sandbox=""
              srcDoc={drawing}
              className="aspect-video w-full rounded-xl border border-border bg-neutral-950"
              referrerPolicy="no-referrer"
            />
          ) : (
            <figure className="m-0 w-full">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={scene.image} alt={state?.caption || 'ページの画面'} className="w-full rounded-xl border border-border bg-neutral-950" />
              {scene.pageUrl ? <figcaption className="mt-1 truncate text-[11px] text-muted-foreground">{scene.pageUrl}</figcaption> : null}
            </figure>
          )}
        </div>
      ) : null}
    </div>
  );
}

const CHANNEL_LABEL: Record<string, string> = {
  email: 'メール', instagram_dm: 'Instagram DM', instagram_comment: 'Instagram コメント', line: 'LINE', sms: 'SMS', web_form: 'Webフォーム',
  chatwork: 'Chatwork', slack: 'Slack', x_dm: 'X DM', collab: '窓口のチャット', other: 'メッセージ',
};

/** The message draft as the call's screen shows it: who it goes to, the subject, the body line by line. A revision
 * (by voice) changes the lines in place and lights the changed ones for a moment; the whole card is not redrawn. */
export function StageMessageCard({ card }: { card: StageCard }) {
  const lines = useMemo(() => (card.body || '').split('\n'), [card.body]);
  // the lines that differ from the version shown before (a revision by voice): they replay a short highlight, keyed on
  // the revision so the same line lights again when it changes again
  const [seen, setSeen] = useState<{ lines: string[]; changed: Set<number> }>({ lines, changed: new Set() });
  if (seen.lines !== lines) {   // the previous version's lines, kept as state (derived from the prop, React's own pattern)
    const out = new Set<number>();
    lines.forEach((line, i) => { if (seen.lines[i] !== line) out.add(i); });
    setSeen({ lines, changed: out });
  }
  const changed = seen.lines === lines ? seen.changed : new Set<number>();
  const status = card.status === 'sent' ? { text: '送りました', cls: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' }
    : card.status === 'rejected' ? { text: '取り下げ', cls: 'bg-neutral-500/15 text-neutral-300 border-neutral-500/30' }
    : { text: '下書き', cls: 'bg-amber-500/15 text-amber-300 border-amber-500/30' };
  return (
    <div className="w-full rounded-xl border border-border bg-neutral-950/80 p-3 text-sm" data-stage-card={card.proposal_id} data-stage-card-status={card.status} data-stage-card-revision={card.revision || 1}>
      <div className="mb-2 flex items-center gap-2">
        <span className="rounded-md border border-border px-1.5 py-0.5 text-[11px] text-muted-foreground">{CHANNEL_LABEL[card.channel] || card.channel}</span>
        <span className="truncate font-medium">{card.to_name || card.to}</span>
        {card.to_name && card.to ? <span className="truncate text-[11px] text-muted-foreground">{card.to}</span> : null}
        <span className={`ml-auto rounded-md border px-1.5 py-0.5 text-[11px] ${status.cls}`}>{status.text}</span>
      </div>
      {card.subject ? <div className="mb-1.5 truncate text-[13px] text-foreground/90">{card.subject}</div> : null}
      <div className="whitespace-pre-wrap break-words leading-6" data-stage-card-body>
        {lines.map((line, i) => (
          <div key={changed.has(i) ? `${i}-${card.revision || 1}` : i} className="-mx-1 rounded px-1"
               style={changed.has(i) ? { animation: 'stage-line-flash 1.8s ease-out' } : undefined} data-stage-line={changed.has(i) ? 'changed' : undefined}>
            {line || '\u00a0'}
          </div>
        ))}
      </div>
    </div>
  );
}

/** The lines of a text and which of them differ from the version shown before (a revision by voice): the changed ones
 * replay a short highlight, keyed on the revision so the same line lights again when it changes again. */
function useChangedLines(text: string, revision: number) {
  const lines = useMemo(() => (text || '').split('\n'), [text]);
  const [seen, setSeen] = useState<{ lines: string[]; changed: Set<number> }>({ lines, changed: new Set() });
  if (seen.lines !== lines) {   // the previous version's lines, kept as state (derived from the prop, React's own pattern)
    const out = new Set<number>();
    lines.forEach((line, i) => { if (seen.lines[i] !== line) out.add(i); });
    setSeen({ lines, changed: out });
  }
  const changed = seen.lines === lines ? seen.changed : new Set<number>();
  return { lines, changed, revision };
}

function FlashLines({ lines, changed, revision }: { lines: string[]; changed: Set<number>; revision: number }) {
  return (
    <>
      {lines.map((line, i) => (
        <div key={changed.has(i) ? `${i}-${revision}` : i} className="-mx-1 rounded px-1"
             style={changed.has(i) ? { animation: 'stage-line-flash 1.8s ease-out' } : undefined} data-stage-line={changed.has(i) ? 'changed' : undefined}>
          {line || '\u00a0'}
        </div>
      ))}
    </>
  );
}

/** A document of one of the owner's sites on the call's screen (an article of the X room, a script): what it is and for
 * which account, the title, the body line by line (a revision by voice lights the changed lines), and its state. The
 * body scrolls inside the card so a long article does not push the call's controls off the screen. */
export function StageDocument({ doc }: { doc: StageDoc }) {
  const { lines, changed, revision } = useChangedLines(doc.body, doc.revision || 1);
  const status = doc.status === 'published' ? { text: '投稿しました', cls: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' }
    : doc.status === 'publishing' ? { text: '投稿しています', cls: 'bg-sky-500/15 text-sky-300 border-sky-500/30' }
    : doc.status === 'failed' ? { text: '投稿できませんでした', cls: 'bg-red-500/15 text-red-300 border-red-500/30' }
    : { text: '下書き', cls: 'bg-amber-500/15 text-amber-300 border-amber-500/30' };
  return (
    <div className="w-full rounded-xl border border-border bg-neutral-950/80 p-3 text-left text-sm" data-stage-doc={doc.id} data-stage-doc-status={doc.status} data-stage-doc-revision={doc.revision || 1}>
      <div className="mb-2 flex items-center gap-2">
        <span className="rounded-md border border-border px-1.5 py-0.5 text-[11px] text-muted-foreground">{doc.label || doc.kind}</span>
        {doc.account ? <span className="truncate text-[11px] text-muted-foreground">@{doc.account}</span> : null}
        <span className={`ml-auto rounded-md border px-1.5 py-0.5 text-[11px] ${status.cls}`}>{status.text}</span>
      </div>
      {doc.title ? <div className="mb-1.5 text-[15px] font-medium leading-snug text-foreground" data-stage-doc-title>{doc.title}</div> : null}
      <div className="max-h-[52vh] overflow-y-auto whitespace-pre-wrap break-words leading-6" data-stage-doc-body>
        <FlashLines lines={lines} changed={changed} revision={revision} />
      </div>
      {doc.status === 'failed' && doc.error ? <div className="mt-2 text-[11px] text-red-300">{doc.error}</div> : null}
      {doc.status === 'published' && doc.url ? <div className="mt-2 truncate text-[11px] text-muted-foreground">{doc.url}</div> : null}
    </div>
  );
}

/** A picture made for the call: while it is being made, its place (or the previous picture, dimmed) with 「作っています」;
 * then the picture, and the words it was made from under it. A revision shows the previous picture dimmed until the new
 * one arrives, so the owner watches it change rather than disappear. */
export function StageMedia({ media }: { media: StageMedia }) {
  const making = media.status === 'generating';
  const shown = stageImageUrl(making ? media.previous || media.image : media.image);
  const last = media.history && media.history.length ? media.history[media.history.length - 1] : '';
  return (
    <figure className="m-0 w-full" data-stage-media={media.id} data-stage-media-status={media.status} data-stage-media-revision={media.revision || 1}>
      <div className="relative w-full overflow-hidden rounded-xl border border-border bg-neutral-950">
        {shown ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={shown} alt={media.prompt} className={`w-full ${making ? 'opacity-40 blur-[1px]' : ''}`} style={{ transition: 'opacity .4s ease' }} />
        ) : (
          <div className="aspect-square w-full" />
        )}
        {making ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-sm text-foreground/90" data-stage-media-waiting>
            <span className="h-6 w-6 animate-spin rounded-full border-2 border-foreground/30 border-t-foreground" aria-hidden />
            <span>{media.revision && media.revision > 1 ? '直しています…' : '作っています…'}</span>
          </div>
        ) : null}
        {media.status === 'failed' ? (
          <div className="absolute inset-x-0 bottom-0 bg-red-950/80 px-2 py-1 text-[11px] text-red-200">作れませんでした{media.error ? `: ${media.error}` : ''}</div>
        ) : null}
      </div>
      <figcaption className="mt-1 truncate text-[11px] text-muted-foreground">{last ? `${media.prompt} → ${last}` : media.prompt}</figcaption>
    </figure>
  );
}

/** A page of this site on the call's screen, live: the owner's artifact itself, signed in (the same origin shares the
 * owner's token), usable by touch. The server's commands (approve all, reload…) are passed to the page by postMessage,
 * each once, after the page has said it listens ({type: 'dan-call-ready'}); a command older than 30 s is not replayed. */
export function StageFrame({ path, command, fill, title, children }: { path: string; command?: StageCommand | null; fill: boolean; title: string; children?: ReactNode }) {
  const frame = useRef<HTMLIFrameElement | null>(null);
  const ready = useRef(false);
  const sent = useRef(0);
  const waiting = useRef<StageCommand | null>(null);
  const [loading, setLoading] = useState(true);
  const post = (c: StageCommand) => {
    if (c.seq <= sent.current) return;
    sent.current = c.seq;
    frame.current?.contentWindow?.postMessage({ type: 'dan-call', action: c.action, seq: c.seq }, window.location.origin);
  };
  useEffect(() => {
    const listen = (event: MessageEvent) => {
      if (event.source !== frame.current?.contentWindow || event.origin !== window.location.origin) return;
      if (event.data?.type === 'dan-call-ready') {
        ready.current = true;
        if (waiting.current) { post(waiting.current); waiting.current = null; }
      }
    };
    window.addEventListener('message', listen);
    return () => window.removeEventListener('message', listen);
  }, []);
  useEffect(() => { ready.current = false; setLoading(true); }, [path]);
  useEffect(() => {
    if (!command || command.seq <= sent.current) return;
    if (Date.now() - Date.parse(command.at) > 30000) { sent.current = Math.max(sent.current, command.seq); return; }
    if (command.action === 'reload') {   // the page itself is loaded again (a published post, a state the page does not poll)
      sent.current = command.seq; ready.current = false; setLoading(true);
      if (frame.current) frame.current.src = path;
      return;
    }
    if (ready.current) post(command); else waiting.current = command;
  }, [command, path]);
  return (
    <div className="flex w-full flex-col gap-1.5" data-stage-frame={path}>
      {children}
      <div className="relative w-full overflow-hidden rounded-xl border border-border bg-white" style={{ height: fill ? 'calc(100dvh - 5.5rem)' : 'min(72vh, 860px)' }}>
        <iframe ref={frame} title={title} src={path} className="h-full w-full border-0 bg-white" onLoad={() => setLoading(false)} referrerPolicy="same-origin" />
        {loading ? (
          <div className="absolute inset-0 flex items-center justify-center bg-white" aria-hidden>
            <span className="h-6 w-6 animate-spin rounded-full border-2 border-neutral-300 border-t-neutral-700" />
          </div>
        ) : null}
      </div>
    </div>
  );
}

/** One line above a document's own screen: what it is, and where it stands (the assistant writing, suggestions waiting,
 * published). The document itself is the page under it. */
export function StageDocStatus({ doc }: { doc: StageDoc }) {
  const a = doc.assist;
  const status = doc.status === 'published' ? { text: '投稿しました', cls: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' }
    : doc.status === 'publishing' ? { text: '投稿しています', cls: 'bg-sky-500/15 text-sky-300 border-sky-500/30' }
    : doc.status === 'failed' ? { text: '投稿できませんでした', cls: 'bg-red-500/15 text-red-300 border-red-500/30' }
    : a && (a.state === 'running' || a.state === 'queued') ? { text: 'アシスタントが直しています', cls: 'bg-sky-500/15 text-sky-300 border-sky-500/30' }
    : a && a.pending ? { text: `直しの案 ${a.pending}件`, cls: 'bg-amber-500/15 text-amber-300 border-amber-500/30' }
    : { text: '下書き', cls: 'bg-neutral-500/15 text-neutral-300 border-neutral-500/30' };
  return (
    <div className="flex items-center gap-2 text-xs" data-stage-doc={doc.id} data-stage-doc-status={doc.status} data-stage-doc-assist={a?.state || ''}>
      <span className="rounded-md border border-border px-1.5 py-0.5 text-[11px] text-muted-foreground">{doc.label || doc.kind}</span>
      {doc.account ? <span className="truncate text-[11px] text-muted-foreground">@{doc.account}</span> : null}
      <span className={`ml-auto shrink-0 rounded-md border px-1.5 py-0.5 text-[11px] ${status.cls}`}>{status.text}</span>
    </div>
  );
}
