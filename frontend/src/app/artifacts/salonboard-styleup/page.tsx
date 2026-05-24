'use client';

/**
 * StyleSnap — サロンボード スタイルアップ補助ツール（デモ）
 *
 * ヘアスタイル写真を選ぶと、AIがサロンボードのスタイル投稿項目を自動推定。
 * サロンボードそっくりの投稿画面に項目が自動入力され、手直しして投稿できる。
 * 写真解析は本物（/api/v1/salonboard-styleup/analyze）。
 * 「サロンボードへ投稿」はデモ用の演出。
 */

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type ReactNode,
} from 'react';
import {
  AlertTriangle,
  Camera,
  Check,
  CheckCircle2,
  ChevronRight,
  Clock,
  GripHorizontal,
  Loader2,
  RotateCcw,
  Sparkles,
  Wand2,
} from 'lucide-react';
import { Reorder } from 'framer-motion';
import { isDanPreview } from '@/lib/dan-preview';

/* ============ 型 ============ */
type SField = { value: string; confidence: number; reason: string };
type MField = { value: string[]; confidence: number; reason: string };
type Fields = {
  category: SField;
  length: SField;
  menu: MField;
  hair_amount: SField;
  hair_quality: SField;
  hair_thickness: SField;
  hair_curl: SField;
  age: SField;
  face: SField;
  style_name: SField;
  comment: SField;
  hashtags: MField;
};
type Photo = { url: string; file: File };
type Step = 'init' | 'intro' | 'analyzing' | 'form' | 'posting' | 'done';

/* ============ 定数 ============ */
const OPT = {
  category: ['レディース', 'メンズ'],
  length: ['ベリーショート', 'ショート', 'ボブ', 'ミディアム', 'セミロング', 'ロング'],
  menu: ['パーマ', 'ストレートパーマ・縮毛矯正', 'エクステ', 'ブリーチ'],
  hair_amount: ['少ない', '普通', '多い'],
  hair_quality: ['柔らかい', '普通', '硬い'],
  hair_thickness: ['細い', '普通', '太い'],
  hair_curl: ['なし', '少し', '強い'],
  age: ['キッズ', '10代', '20代', '30代', '40代', '50代', '60代以上'],
  face: ['丸型', '卵型', '四角', '逆三角', 'ベース', '面長'],
};

const SAMPLES = [
  {
    key: 'bob_beige',
    label: 'ベージュのボブ',
    url: 'https://omcnusihkpfyvzglttop.supabase.co/storage/v1/object/public/generated-images/generate/81a2f0f6-e504-4bfc-96bf-3f456527ee15.png',
  },
  {
    key: 'long_dark',
    label: '暗髪のロング',
    url: 'https://omcnusihkpfyvzglttop.supabase.co/storage/v1/object/public/generated-images/generate/3e86dd7c-af0e-47ad-8f87-8b9139223833.png',
  },
  {
    key: 'mens_short',
    label: 'メンズショート',
    url: 'https://omcnusihkpfyvzglttop.supabase.co/storage/v1/object/public/generated-images/generate/40b48d40-8132-4da4-9ae9-58748717058e.png',
  },
  {
    key: 'hightone_short',
    label: 'ハイトーンボブ',
    url: 'https://omcnusihkpfyvzglttop.supabase.co/storage/v1/object/public/generated-images/generate/f720f85b-f03a-4695-9eeb-bcc73df8a459.png',
  },
];

const ANALYZE_MSGS = [
  '写真を読み込んでいます',
  '髪の長さと毛量を見ています',
  'カラーとパーマを判定しています',
  '年代・顔型を推定しています',
  'スタイル名とコメントを考えています',
];

const FIELD_SEQ: (keyof Fields)[] = [
  'category',
  'length',
  'menu',
  'style_name',
  'comment',
  'hashtags',
  'hair_amount',
  'hair_quality',
  'hair_thickness',
  'hair_curl',
  'age',
  'face',
];

const LOW = 0.6;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const FIELD_DEFAULTS: Partial<Record<keyof Fields, string>> = {
  hair_amount: '普通',
  hair_quality: '普通',
  hair_thickness: '普通',
  hair_curl: 'なし',
  age: '20代',
  face: '卵型',
};
const SINGLE_DEFAULT_KEYS = [
  'hair_amount',
  'hair_quality',
  'hair_thickness',
  'hair_curl',
  'age',
  'face',
] as const;

function normalizeFields(input: Fields): Fields {
  const next = { ...input };
  for (const key of SINGLE_DEFAULT_KEYS) {
    const options = OPT[key as keyof typeof OPT] as string[] | undefined;
    const fallback = FIELD_DEFAULTS[key];
    const current = next[key];
    if (options && fallback && !options.includes(current.value)) {
      next[key] = {
        ...current,
        value: fallback,
        confidence: Math.min(current.confidence || 0.4, 0.4),
        reason: current.reason || '未判定のため初期値',
      };
    }
  }
  return next;
}

function imageSize(file: File): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve({ width: img.naturalWidth, height: img.naturalHeight });
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error('画像サイズを確認できませんでした'));
    };
    img.src = url;
  });
}

/* ============ プレビュー専用（ライブプレビューでの全画面閲覧/編集） ============ */
const PREVIEW_STEPS: { key: Step; label: string }[] = [
  { key: 'init', label: '初期設定' },
  { key: 'intro', label: 'イントロ' },
  { key: 'analyzing', label: '解析中' },
  { key: 'form', label: '投稿フォーム' },
  { key: 'posting', label: '投稿中' },
  { key: 'done', label: '完了' },
];

// 解析中/フォーム画面を描画するためのモック写真（実ファイルは不要、url だけ使われる）
function makePreviewPhotos(): Photo[] {
  return SAMPLES.slice(0, 3).map((s) => ({
    url: s.url,
    file:
      typeof File !== 'undefined'
        ? new File([], `${s.key}.png`, { type: 'image/png' })
        : ({ name: `${s.key}.png` } as unknown as File),
  }));
}

// 投稿フォーム画面を描画するためのモック AI 推定結果
function makePreviewForm(): Fields {
  const s = (value: string, confidence = 0.9, reason = 'プレビュー用のサンプルデータです'): SField => ({
    value,
    confidence,
    reason,
  });
  const m = (value: string[], confidence = 0.9, reason = 'プレビュー用のサンプルデータです'): MField => ({
    value,
    confidence,
    reason,
  });
  return {
    category: s('レディース'),
    length: s('ボブ'),
    menu: m(['パーマ']),
    hair_amount: s('普通'),
    hair_quality: s('普通'),
    hair_thickness: s('普通'),
    hair_curl: s('少し'),
    age: s('20代'),
    face: s('卵型'),
    style_name: s('くびれ感ナチュラルボブ'),
    // 「要確認」バッジの見た目も確認できるよう、あえて低信頼度にしている
    comment: s(
      '小顔に見えるくびれボブ。柔らかい質感とナチュラルなカラーで、大人かわいい仕上がりです。',
      0.5,
      '低信頼度表示の確認用にあえて confidence を下げています',
    ),
    hashtags: m(['ボブ', 'ナチュラル', '小顔', '透明感カラー']),
  };
}

/* ============ メイン ============ */
export default function SalonboardStyleupPage() {
  const [step, setStep] = useState<Step>('init');
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [form, setForm] = useState<Fields | null>(null);
  const [error, setError] = useState('');
  const [elapsed, setElapsed] = useState(0);
  const [stylist, setStylist] = useState('');
  const [deviceId, setDeviceId] = useState('');
  const [postMsg, setPostMsg] = useState('');
  const [setupReady, setSetupReady] = useState(false);
  const [previewMode, setPreviewMode] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  // 起動時: device_id を確保し、サロンボード認証情報の設定状態を確認する
  useEffect(() => {
    if (typeof window === 'undefined') return;
    // ライブプレビュー（チャット右ペイン）では認証/初期設定ゲートをスキップし、
    // 管理者として全画面を閲覧・編集できるようにする。
    if (isDanPreview()) {
      setPreviewMode(true);
      setDeviceId('preview-device');
      setStylist((s) => s || 'プレビュー');
      setStep('intro');
      setSetupReady(true);
      return;
    }
    let id = window.localStorage.getItem('sb_device_id') ?? '';
    if (!id) {
      id =
        typeof crypto !== 'undefined' && 'randomUUID' in crypto
          ? crypto.randomUUID()
          : 'd-' + Math.random().toString(36).slice(2) + Date.now().toString(36);
      window.localStorage.setItem('sb_device_id', id);
    }
    setDeviceId(id);
    (async () => {
      try {
        const res = await fetch(
          `/api/v1/salonboard-credentials/status?device_id=${encodeURIComponent(id)}`,
        );
        if (res.ok) {
          const data = (await res.json()) as {
            has_credentials: boolean;
            stylist_name?: string | null;
          };
          if (data.has_credentials) {
            if (data.stylist_name) setStylist(data.stylist_name);
            setStep('intro');
          } else {
            setStep('init');
          }
        } else {
          setStep('init');
        }
      } catch {
        setStep('init');
      } finally {
        setSetupReady(true);
      }
    })();
  }, []);

  const runAnalyze = useCallback(async (items: Photo[]) => {
    setError('');
    setPhotos(items);
    setForm(null);
    setStep('analyzing');
    const t0 = Date.now();
    try {
      for (const [idx, item] of items.entries()) {
        const size = await imageSize(item.file);
        if (size.width > size.height) {
          throw new Error(
            `${idx + 1}枚目が横長です。サロンボードは横長画像をアップロードできないため、縦長の画像に差し替えてください。`,
          );
        }
      }
      const fd = new FormData();
      items.forEach((it) => fd.append('files', it.file));
      const res = await fetch('/api/v1/salonboard-styleup/analyze', {
        method: 'POST',
        body: fd,
      });
      if (!res.ok) {
        const j = (await res.json().catch(() => ({}))) as { detail?: string };
        throw new Error(j.detail || '写真の解析に失敗しました');
      }
      const data = (await res.json()) as {
        fields: Fields;
        images?: Array<{ angle: string; confidence: number; reason: string }>;
      };
      const wait = 3000 - (Date.now() - t0);
      if (wait > 0) await sleep(wait);
      setElapsed(Math.max(6, Math.round((Date.now() - t0) / 1000)));
      const imgs = data.images ?? [];
      if (imgs.length > 0) {
        const used = new Set<number>();
        const ordered: Photo[] = [];
        for (const angle of ['front', 'side', 'back'] as const) {
          const idx = imgs.findIndex(
            (im, i) => im.angle === angle && !used.has(i),
          );
          if (idx >= 0 && items[idx]) {
            ordered.push(items[idx]);
            used.add(idx);
          }
        }
        items.forEach((p, i) => {
          if (!used.has(i)) ordered.push(p);
        });
        if (ordered.length > 0) setPhotos(ordered);
      }
      setForm(normalizeFields(data.fields));
      setStep('form');
    } catch (e) {
      setError(e instanceof Error ? e.message : '写真の解析に失敗しました');
      setStep('intro');
    }
  }, []);

  const onPickFiles = (e: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []).slice(0, 3);
    e.target.value = '';
    if (!files.length) return;
    runAnalyze(files.map((f) => ({ url: URL.createObjectURL(f), file: f })));
  };

  const onPickSample = async (s: (typeof SAMPLES)[number]) => {
    setError('');
    setStep('analyzing');
    try {
      const res = await fetch(s.url);
      if (!res.ok) throw new Error();
      const blob = await res.blob();
      const file = new File([blob], `${s.key}.png`, {
        type: blob.type || 'image/png',
      });
      runAnalyze([{ url: s.url, file }]);
    } catch {
      setError('サンプル写真の読み込みに失敗しました');
      setStep('intro');
    }
  };

  const setVal = (k: keyof Fields, v: string) =>
    setForm((f) => (f ? { ...f, [k]: { ...f[k], value: v } } : f));

  const toggleMulti = (k: 'menu' | 'hashtags', opt: string) =>
    setForm((f) => {
      if (!f) return f;
      const cur = f[k].value as string[];
      const next = cur.includes(opt)
        ? cur.filter((x) => x !== opt)
        : [...cur, opt];
      return { ...f, [k]: { ...f[k], value: next } };
    });

  const post = async () => {
    if (!form) return;
    // チャット右ペインのプレビューは投稿の流れだけ再現する
    if (previewMode) {
      setStep('posting');
      await sleep(2100);
      setStep('done');
      return;
    }
    const files = photos.map((p) => p.file).filter((f): f is File => !!f);
    if (!files.length) {
      setError('写真が見つかりません。選び直してください');
      return;
    }
    setError('');
    setPostMsg('投稿ジョブを受け付けました');
    setStep('posting');
    try {
      const fd = new FormData();
      fd.append('device_id', deviceId);
      fd.append('fields', JSON.stringify(form));
      const angles = ['front', 'side', 'back'] as const;
      const imagesMeta = files.map((_, i) => ({ angle: angles[i] ?? 'front' }));
      fd.append('images', JSON.stringify(imagesMeta));
      fd.append('stylist_name', stylist || '');
      files.forEach((f) => fd.append('files', f));

      const res = await fetch('/api/v1/salonboard-styleup/post', {
        method: 'POST',
        body: fd,
      });
      if (!res.ok) {
        const j = (await res.json().catch(() => ({}))) as { detail?: string };
        throw new Error(j.detail || '投稿の受付に失敗しました');
      }
      const { job_id } = (await res.json()) as { job_id: string };

      const deadline = Date.now() + 10 * 60 * 1000; // 最大10分待つ
      while (Date.now() < deadline) {
        await sleep(3000);
        const sres = await fetch(
          `/api/v1/salonboard-styleup/post-status/${job_id}`,
        );
        if (!sres.ok) continue;
        const st = (await sres.json()) as { status: string; message: string };
        if (st.message) setPostMsg(st.message);
        if (st.status === 'done') {
          setStep('done');
          return;
        }
        if (st.status === 'error') {
          setError(st.message || '投稿に失敗しました');
          setStep('form');
          return;
        }
        // 'running' / 'needs_human' は待機継続
      }
      setError('投稿に時間がかかっています。少し待って一覧をご確認ください');
      setStep('form');
    } catch (e) {
      setError(e instanceof Error ? e.message : '投稿に失敗しました');
      setStep('form');
    }
  };

  const reset = () => {
    photos.forEach((p) => {
      if (p.url.startsWith('blob:')) URL.revokeObjectURL(p.url);
    });
    setPhotos([]);
    setForm(null);
    setStylist('');
    setError('');
    setStep('intro');
  };

  // プレビュー専用: 任意の画面へ直接ジャンプする（必要なモックデータを補う）
  const goPreviewStep = (target: Step) => {
    setError('');
    if (target === 'analyzing' || target === 'form') {
      setPhotos((p) => (p.length ? p : makePreviewPhotos()));
    }
    if (target === 'form') {
      setForm((f) => f ?? makePreviewForm());
    }
    if (target === 'done') {
      setElapsed((e) => e || 8);
    }
    setStep(target);
  };

  return (
    <div className="h-[100svh] overflow-y-auto bg-[#f4f5f7] text-gray-900">
      {previewMode && <PreviewStepBar current={step} onGo={goPreviewStep} />}
      <div className="mx-auto min-h-full max-w-md bg-white shadow-sm">
        {!setupReady && (
          <div className="flex min-h-screen items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
          </div>
        )}
        {setupReady && step === 'init' && (
          <InitScreen
            deviceId={deviceId}
            initialStylistName={stylist}
            onDone={(name) => {
              setStylist(name);
              setStep('intro');
            }}
          />
        )}
        {setupReady && step === 'intro' && (
          <Intro
            onPick={() => fileRef.current?.click()}
            onSample={onPickSample}
            error={error}
            onOpenSetup={() => setStep('init')}
          />
        )}
        {step === 'analyzing' && <Analyzing photos={photos} />}
        {step === 'form' && form && (
          <FormView
            photos={photos}
            onReorder={setPhotos}
            form={form}
            stylist={stylist}
            setStylist={setStylist}
            setVal={setVal}
            toggleMulti={toggleMulti}
            onPost={post}
          />
        )}
        {step === 'posting' && <Posting message={postMsg} />}
        {step === 'done' && <Done elapsed={elapsed} onReset={reset} />}
        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          multiple
          className="hidden"
          onChange={onPickFiles}
        />
      </div>
    </div>
  );
}

/* ============ プレビュー専用: 画面切替バー ============ */
// data-dan-preview-ui を付けることで、編集モード中でもインスペクタにクリックを
// 横取りされず、各画面へジャンプできる（iframe-inspector の isPreviewUi で除外）。
function PreviewStepBar({
  current,
  onGo,
}: {
  current: Step;
  onGo: (s: Step) => void;
}) {
  return (
    <div
      data-dan-preview-ui
      className="fixed left-1/2 top-2 z-[2147483647] flex max-w-[calc(100vw-16px)] -translate-x-1/2 flex-wrap items-center justify-center gap-1 rounded-full border border-gray-200 bg-white/95 px-2 py-1.5 shadow-lg backdrop-blur"
    >
      <span className="px-1.5 text-[10px] font-bold tracking-wide text-[#d4577a]">
        プレビュー
      </span>
      {PREVIEW_STEPS.map((s) => (
        <button
          key={s.key}
          type="button"
          onClick={() => onGo(s.key)}
          className={`rounded-full px-2.5 py-1 text-[11px] font-medium transition ${
            current === s.key
              ? 'bg-[#0a3d62] text-white'
              : 'text-gray-600 hover:bg-gray-100'
          }`}
        >
          {s.label}
        </button>
      ))}
    </div>
  );
}

/* ============ 画面: イントロ ============ */
function Intro({
  onPick,
  onSample,
  error,
  onOpenSetup,
}: {
  onPick: () => void;
  onSample: (s: (typeof SAMPLES)[number]) => void;
  error: string;
  onOpenSetup?: () => void;
}) {
  return (
    <div className="flex flex-col">
      <div className="bg-gradient-to-b from-[#e8607f] to-[#c8587a] px-6 pb-11 pt-14 text-white">
        <div className="flex items-center gap-1.5 text-sm font-semibold text-white/90">
          <Sparkles className="h-4 w-4" />
          StyleSnap
          {onOpenSetup && (
            <button
              onClick={onOpenSetup}
              className="ml-auto rounded-full bg-white/15 px-3 py-1 text-[11px] font-medium text-white hover:bg-white/25"
            >
              設定
            </button>
          )}
        </div>
        <h1 className="mt-4 text-[26px] font-bold leading-snug">
          写真を撮るだけで、
          <br />
          スタイル投稿が終わる。
        </h1>
        <p className="mt-3 text-sm leading-relaxed text-white/90">
          ヘアスタイルの写真を選ぶだけ。サロンボードの入力項目をAIが自動で
          埋めます。あとは確認して投稿するだけです。
        </p>
      </div>

      <div className="-mt-6 px-6">
        <button
          onClick={onPick}
          className="flex w-full items-center gap-4 rounded-2xl border border-gray-100 bg-white px-5 py-5 shadow-lg transition active:scale-[0.99]"
        >
          <span className="grid h-12 w-12 place-items-center rounded-xl bg-[#fde7ec] text-[#d4577a]">
            <Camera className="h-6 w-6" />
          </span>
          <span className="text-left">
            <span className="block font-bold text-gray-800">
              写真を撮る・選ぶ
            </span>
            <span className="mt-0.5 block text-xs text-gray-500">
              前・横・後ろ 最大3枚まで
            </span>
          </span>
          <ChevronRight className="ml-auto h-5 w-5 text-gray-300" />
        </button>
      </div>

      {error && (
        <div className="mx-6 mt-4 flex items-center gap-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      <div className="mt-8 px-6 pb-9">
        <div className="text-xs font-semibold tracking-wide text-gray-400">
          写真がなければ、サンプルで試せます
        </div>
        <div className="mt-3 grid grid-cols-2 gap-3">
          {SAMPLES.map((s) => (
            <button
              key={s.key}
              onClick={() => onSample(s)}
              className="group overflow-hidden rounded-xl border border-gray-100 bg-gray-50 text-left transition active:scale-[0.98]"
            >
              <div className="aspect-[3/4] overflow-hidden bg-gray-100">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={s.url}
                  alt={s.label}
                  className="h-full w-full object-cover transition group-active:opacity-90"
                />
              </div>
              <div className="px-2.5 py-2 text-xs font-medium text-gray-600">
                {s.label}
              </div>
            </button>
          ))}
        </div>
      </div>

      <div className="bg-[#faf7f8] px-6 py-7">
        <div className="mb-3 text-xs font-semibold text-gray-400">
          かんたん3ステップ
        </div>
        <Flow n="1" t="写真を選ぶ" d="撮った写真をその場でアップ" />
        <Flow n="2" t="AIが自動入力" d="長さ・カラー・コメントまで全部" />
        <Flow n="3" t="確認して投稿" d="気になる所だけ直してボタン1つ" />
      </div>
    </div>
  );
}

function Flow({ n, t, d }: { n: string; t: string; d: string }) {
  return (
    <div className="flex items-center gap-3 py-2">
      <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-[#e8607f] text-xs font-bold text-white">
        {n}
      </span>
      <div>
        <div className="text-sm font-semibold text-gray-700">{t}</div>
        <div className="text-xs text-gray-400">{d}</div>
      </div>
    </div>
  );
}

/* ============ 画面: 解析中 ============ */
function Analyzing({ photos }: { photos: Photo[] }) {
  const [msg, setMsg] = useState(0);
  useEffect(() => {
    const t = setInterval(
      () => setMsg((m) => Math.min(m + 1, ANALYZE_MSGS.length - 1)),
      720,
    );
    return () => clearInterval(t);
  }, []);
  return (
    <div className="flex flex-col items-center px-6 pb-16 pt-20">
      <div className="relative">
        <div className="h-44 w-36 overflow-hidden rounded-2xl bg-gray-100 shadow-md">
          {photos[0] && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={photos[0].url}
              alt=""
              className="h-full w-full object-cover"
            />
          )}
        </div>
        <div className="absolute inset-0 animate-pulse rounded-2xl ring-2 ring-[#e8607f]/50" />
      </div>
      <div className="mt-8 flex items-center gap-2 text-[#d4577a]">
        <Loader2 className="h-5 w-5 animate-spin" />
        <span className="font-bold">AIが解析中…</span>
      </div>
      <div className="mt-2 h-5 text-sm text-gray-500">{ANALYZE_MSGS[msg]}</div>
      <div className="mt-6 flex gap-1.5">
        {ANALYZE_MSGS.map((_, i) => (
          <span
            key={i}
            className={`h-1.5 rounded-full transition-all duration-300 ${
              i <= msg ? 'w-6 bg-[#e8607f]' : 'w-1.5 bg-gray-200'
            }`}
          />
        ))}
      </div>
    </div>
  );
}

/* ============ 部品: 写真の並べ替え（ドラッグで FRONT/SIDE/BACK を入替） ============ */
const SLOT_LABELS = ['FRONT', 'SIDE', 'BACK'] as const;

function PhotoReorder({
  photos,
  onReorder,
}: {
  photos: Photo[];
  onReorder: (next: Photo[]) => void;
}) {
  const canReorder = photos.length > 1;
  return (
    <>
      <Reorder.Group
        axis="x"
        values={photos}
        onReorder={onReorder}
        className="flex gap-2"
      >
        {photos.map((p, i) => (
          <Reorder.Item
            key={p.url}
            value={p}
            drag={canReorder}
            whileDrag={{ scale: 1.05, zIndex: 10 }}
            className={`flex-1 touch-none ${canReorder ? 'cursor-grab active:cursor-grabbing' : ''}`}
          >
            <div className="relative grid aspect-[3/4] place-items-center overflow-hidden rounded-lg border border-gray-200 bg-gray-50">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={p.url}
                alt={SLOT_LABELS[i] ?? ''}
                draggable={false}
                className="h-full w-full select-none object-cover"
              />
              {canReorder && (
                <span className="absolute right-1 top-1 grid h-5 w-5 place-items-center rounded-full bg-black/40 text-white">
                  <GripHorizontal className="h-3 w-3" />
                </span>
              )}
            </div>
            <div className="mt-1 text-center text-[10px] font-semibold text-gray-500">
              {SLOT_LABELS[i] ?? `${i + 1}枚目`}
            </div>
          </Reorder.Item>
        ))}
      </Reorder.Group>
      {canReorder && (
        <p className="mt-2 flex items-start gap-1 text-[11px] leading-relaxed text-gray-400">
          <GripHorizontal className="mt-0.5 h-3 w-3 shrink-0" />
          <span>
            写真をドラッグして並べ替えると、前(FRONT)・横(SIDE)・後ろ(BACK)の順番が変わります。この順番のままサロンボードに登録されます。
          </span>
        </p>
      )}
    </>
  );
}

/* ============ 画面: 投稿フォーム ============ */
function FormView({
  photos,
  onReorder,
  form,
  stylist,
  setStylist,
  setVal,
  toggleMulti,
  onPost,
}: {
  photos: Photo[];
  onReorder: (next: Photo[]) => void;
  form: Fields;
  stylist: string;
  setStylist: (v: string) => void;
  setVal: (k: keyof Fields, v: string) => void;
  toggleMulti: (k: 'menu' | 'hashtags', opt: string) => void;
  onPost: () => void;
}) {
  const [reveal, setReveal] = useState(0);
  useEffect(() => {
    if (reveal >= FIELD_SEQ.length) return;
    const t = setTimeout(() => setReveal((r) => r + 1), 240);
    return () => clearTimeout(t);
  }, [reveal]);

  const shown = (k: keyof Fields) => reveal > FIELD_SEQ.indexOf(k);
  const done = reveal >= FIELD_SEQ.length;

  return (
    <div>
      <div className="sticky top-0 z-10 flex items-center gap-2 bg-[#0a3d62] px-4 py-3 text-white">
        <span className="text-sm font-bold">スタイル登録</span>
        <span className="ml-auto rounded bg-white/15 px-2 py-0.5 text-[11px]">
          サロンボード
        </span>
      </div>

      <div
        className={`flex items-center gap-2 px-4 py-2.5 text-xs font-medium transition-colors ${
          done ? 'bg-[#eaf6ec] text-[#2e7d32]' : 'bg-[#fdeef2] text-[#d4577a]'
        }`}
      >
        {done ? (
          <>
            <CheckCircle2 className="h-4 w-4" />
            自動入力が完了しました。確認して投稿してください
          </>
        ) : (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            AIが写真を見て項目を入力しています…
          </>
        )}
      </div>

      <Section title="スタイル登録">
        <PhotoReorder photos={photos} onReorder={onReorder} />
      </Section>

      <Section title="スタイリストコメント">
        <Label text="スタイリスト名" />
        <input
          value={stylist}
          onChange={(e) => setStylist(e.target.value)}
          placeholder="お名前を入力"
          className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-900 placeholder:text-gray-400 outline-none focus:border-[#0a3d62]"
        />
        <div className="mt-4">
          <Label
            text="コメント"
            required
            ai={shown('comment')}
            low={shown('comment') && form.comment.confidence < LOW}
          />
          {shown('comment') ? (
            <>
              <textarea
                value={form.comment.value}
                onChange={(e) => setVal('comment', e.target.value.slice(0, 120))}
                rows={4}
                className="w-full resize-none rounded-lg border border-gray-200 px-3 py-2 text-sm leading-relaxed text-gray-900 placeholder:text-gray-400 outline-none focus:border-[#0a3d62]"
              />
              <Counter
                n={form.comment.value.length}
                max={120}
                reason={form.comment.reason}
              />
            </>
          ) : (
            <Skeleton />
          )}
        </div>
      </Section>

      <Section title="スタイル">
        <Label
          text="スタイル名"
          required
          ai={shown('style_name')}
          low={shown('style_name') && form.style_name.confidence < LOW}
        />
        {shown('style_name') ? (
          <>
            <input
              value={form.style_name.value}
              onChange={(e) => setVal('style_name', e.target.value.slice(0, 30))}
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-900 placeholder:text-gray-400 outline-none focus:border-[#0a3d62]"
            />
            <Counter
              n={form.style_name.value.length}
              max={30}
              reason={form.style_name.reason}
            />
          </>
        ) : (
          <Skeleton />
        )}

        <PillField
          label="カテゴリ"
          required
          field={form.category}
          options={OPT.category}
          show={shown('category')}
          onSelect={(v) => setVal('category', v)}
        />
        <PillField
          label="長さ"
          required
          field={form.length}
          options={OPT.length}
          show={shown('length')}
          onSelect={(v) => setVal('length', v)}
        />
        <MultiField
          label="メニュー内容"
          field={form.menu}
          options={OPT.menu}
          show={shown('menu')}
          onToggle={(v) => toggleMulti('menu', v)}
        />

        <div className="mt-4">
          <Label text="クーポン" />
          <button className="w-full rounded-lg border border-dashed border-gray-300 px-3 py-2 text-left text-sm text-gray-400">
            クーポンを選択（任意）
          </button>
        </div>

        <div className="mt-4">
          <Label text="ハッシュタグ" ai={shown('hashtags')} />
          {shown('hashtags') ? (
            <>
              <div className="flex flex-wrap gap-1.5">
                {form.hashtags.value.map((t) => (
                  <span
                    key={t}
                    className="inline-flex items-center gap-1 rounded-full bg-[#eef2f7] px-2.5 py-1 text-xs text-[#0a3d62]"
                  >
                    #{t}
                    <button
                      onClick={() => toggleMulti('hashtags', t)}
                      className="text-[#0a3d62]/50"
                      aria-label="削除"
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
              {form.hashtags.reason && <Reason text={form.hashtags.reason} />}
            </>
          ) : (
            <Skeleton />
          )}
        </div>
      </Section>

      <Section title="スタイルのモデル情報">
        <PillField
          label="髪量"
          field={form.hair_amount}
          options={OPT.hair_amount}
          show={shown('hair_amount')}
          onSelect={(v) => setVal('hair_amount', v)}
        />
        <PillField
          label="髪質"
          field={form.hair_quality}
          options={OPT.hair_quality}
          show={shown('hair_quality')}
          onSelect={(v) => setVal('hair_quality', v)}
        />
        <PillField
          label="太さ"
          field={form.hair_thickness}
          options={OPT.hair_thickness}
          show={shown('hair_thickness')}
          onSelect={(v) => setVal('hair_thickness', v)}
        />
        <PillField
          label="クセ"
          field={form.hair_curl}
          options={OPT.hair_curl}
          show={shown('hair_curl')}
          onSelect={(v) => setVal('hair_curl', v)}
        />
        <PillField
          label="年代"
          field={form.age}
          options={OPT.age}
          show={shown('age')}
          onSelect={(v) => setVal('age', v)}
        />
        <PillField
          label="顔型"
          field={form.face}
          options={OPT.face}
          show={shown('face')}
          onSelect={(v) => setVal('face', v)}
        />
      </Section>

      <div className="sticky bottom-0">
        <div className="mx-auto max-w-md border-t border-gray-100 bg-white px-4 py-3">
          <button
            onClick={onPost}
            disabled={!done}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-[#0a3d62] py-3.5 font-bold text-white transition active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-40"
          >
            {done ? (
              <>
                サロンボードに投稿する
                <ChevronRight className="h-4 w-4" />
              </>
            ) : (
              'AIが入力中…'
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ============ 画面: 投稿中 ============ */
function Posting({ message }: { message?: string }) {
  return (
    <div
      className="flex flex-col items-center justify-center px-6"
      style={{ minHeight: '72vh' }}
    >
      <CheckCircle2 className="h-12 w-12 text-[#2e7d32]" />
      <div className="mt-5 text-xl font-bold text-gray-800">
        投稿を開始しました
      </div>
      <div className="mt-5 flex items-center gap-2 text-sm font-medium text-[#0a3d62]">
        <Loader2 className="h-4 w-4 animate-spin" />
        登録から公開反映まで処理中です
      </div>
      <div className="mt-2 text-sm text-gray-500">
        {message || 'PC側のブラウザでサロンボード操作を進めています'}
      </div>
      <div className="mt-4 max-w-xs text-center text-[11px] leading-relaxed text-gray-400">
        この画面を閉じたり、スマホをスリープしても処理はPC側で続きます。結果を見る場合はこの画面を開いたままお待ちください。
      </div>
    </div>
  );
}

/* ============ 画面: 完了 ============ */
function Done({ elapsed, onReset }: { elapsed: number; onReset: () => void }) {
  const saved = Math.max(1, Math.round(((300 - elapsed) / 60) * 10) / 10);
  return (
    <div className="flex flex-col items-center px-6 pb-12 pt-20 text-center">
      <div className="grid h-20 w-20 place-items-center rounded-full bg-[#eaf6ec]">
        <CheckCircle2 className="h-11 w-11 text-[#2e7d32]" />
      </div>
      <h2 className="mt-6 text-xl font-bold text-gray-800">
        投稿が完了しました
      </h2>
      <p className="mt-2 text-sm text-gray-500">
        サロンボードへの登録と公開反映が完了しました。
      </p>

      <div className="mt-7 w-full rounded-2xl bg-[#f7f8fa] px-5 py-5">
        <div className="flex items-center justify-center gap-2 text-[#0a3d62]">
          <Clock className="h-5 w-5" />
          <span className="text-3xl font-bold">{elapsed}</span>
          <span className="mt-1.5 text-sm font-medium">秒で自動入力完了</span>
        </div>
        <div className="mt-3 flex items-center justify-center gap-3 text-xs">
          <span className="text-gray-400 line-through">手入力 約5分</span>
          <ChevronRight className="h-3 w-3 text-gray-300" />
          <span className="font-bold text-[#2e7d32]">約{saved}分の時短</span>
        </div>
      </div>

      <p className="mt-5 text-[11px] leading-relaxed text-gray-400">
        ※ サロンボードに登録されました。お客様向けページに公開するには、
        サロンボードの掲載管理で「反映申請」を押してください（反映まで30分ほど）。
      </p>

      <button
        onClick={onReset}
        className="mt-6 flex w-full items-center justify-center gap-2 rounded-xl border border-gray-200 py-3 font-semibold text-gray-600 transition active:scale-[0.99]"
      >
        <RotateCcw className="h-4 w-4" />
        次のスタイルを投稿する
      </button>
    </div>
  );
}

/* ============ 部品 ============ */
function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="border-b-8 border-gray-100">
      <div className="border-l-4 border-[#0a3d62] bg-[#eef0f2] px-4 py-2 text-sm font-bold text-gray-700">
        {title}
      </div>
      <div className="px-4 py-4">{children}</div>
    </div>
  );
}

function Label({
  text,
  required,
  ai,
  low,
}: {
  text: string;
  required?: boolean;
  ai?: boolean;
  low?: boolean;
}) {
  return (
    <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
      <span className="text-sm font-semibold text-gray-700">{text}</span>
      {required && (
        <span className="rounded bg-[#e53935] px-1 py-0.5 text-[10px] text-white">
          必須
        </span>
      )}
      {ai && (
        <span className="inline-flex items-center gap-0.5 rounded bg-[#f3edff] px-1.5 py-0.5 text-[10px] font-medium text-[#7c3aed]">
          <Wand2 className="h-2.5 w-2.5" />
          AI入力
        </span>
      )}
      {low && (
        <span className="inline-flex items-center gap-0.5 rounded bg-[#fff3df] px-1.5 py-0.5 text-[10px] font-medium text-[#b26a00]">
          <AlertTriangle className="h-2.5 w-2.5" />
          要確認
        </span>
      )}
    </div>
  );
}

function PillField({
  label,
  required,
  field,
  options,
  show,
  onSelect,
}: {
  label: string;
  required?: boolean;
  field: SField;
  options: string[];
  show: boolean;
  onSelect: (v: string) => void;
}) {
  return (
    <div className="mt-4 first:mt-0">
      <Label
        text={label}
        required={required}
        ai={show}
        low={show && field.confidence < LOW}
      />
      {show ? (
        <>
          <div className="flex flex-wrap gap-1.5">
            {options.map((o) => {
              const on = field.value === o;
              return (
                <button
                  key={o}
                  onClick={() => onSelect(o)}
                  className={`rounded-full border px-3 py-1.5 text-xs font-medium transition ${
                    on
                      ? 'border-[#0a3d62] bg-[#0a3d62] text-white'
                      : 'border-gray-200 bg-white text-gray-600'
                  }`}
                >
                  {o}
                </button>
              );
            })}
          </div>
          {field.reason && <Reason text={field.reason} />}
        </>
      ) : (
        <Skeleton />
      )}
    </div>
  );
}

function MultiField({
  label,
  field,
  options,
  show,
  onToggle,
}: {
  label: string;
  field: MField;
  options: string[];
  show: boolean;
  onToggle: (v: string) => void;
}) {
  return (
    <div className="mt-4">
      <Label text={label} ai={show} />
      {show ? (
        <>
          <div className="flex flex-wrap gap-1.5">
            {options.map((o) => {
              const on = field.value.includes(o);
              return (
                <button
                  key={o}
                  onClick={() => onToggle(o)}
                  className={`inline-flex items-center gap-1 rounded-full border px-3 py-1.5 text-xs font-medium transition ${
                    on
                      ? 'border-[#0a3d62] bg-[#0a3d62] text-white'
                      : 'border-gray-200 bg-white text-gray-600'
                  }`}
                >
                  {on && <Check className="h-3 w-3" />}
                  {o}
                </button>
              );
            })}
          </div>
          {field.value.length === 0 && (
            <div className="mt-1.5 text-[11px] text-gray-400">
              該当なし（パーマ・ブリーチ等の施術があれば選択）
            </div>
          )}
          {field.reason && <Reason text={field.reason} />}
        </>
      ) : (
        <Skeleton />
      )}
    </div>
  );
}

function Skeleton() {
  return (
    <div className="flex items-center gap-2 rounded-lg bg-gray-50 px-3 py-2.5 text-xs text-gray-400">
      <Loader2 className="h-3.5 w-3.5 animate-spin" />
      AIが入力中…
    </div>
  );
}

function Reason({ text }: { text: string }) {
  return (
    <div className="mt-1.5 flex items-start gap-1 text-[11px] text-gray-400">
      <Sparkles className="mt-0.5 h-3 w-3 shrink-0 text-[#b9a0d8]" />
      <span>AIの判断: {text}</span>
    </div>
  );
}

function Counter({
  n,
  max,
  reason,
}: {
  n: number;
  max: number;
  reason?: string;
}) {
  return (
    <>
      <div className="mt-1 text-right text-[11px] text-gray-400">
        {n}/{max}
      </div>
      {reason && <Reason text={reason} />}
    </>
  );
}

/* ============ 画面: 初期設定 ============ */
function InitScreen({
  deviceId,
  initialStylistName,
  onDone,
}: {
  deviceId: string;
  initialStylistName: string;
  onDone: (stylistName: string) => void;
}) {
  const [stylistName, setStylistName] = useState(initialStylistName);
  const [loginId, setLoginId] = useState('');
  const [password, setPassword] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [agree, setAgree] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const canSubmit =
    stylistName.trim().length > 0 &&
    loginId.trim().length > 0 &&
    password.length > 0 &&
    agree &&
    !submitting;

  const submit = async () => {
    if (!canSubmit) return;
    setError('');
    setSubmitting(true);
    try {
      const res = await fetch('/api/v1/salonboard-credentials', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          device_id: deviceId,
          stylist_name: stylistName.trim(),
          login_id: loginId.trim(),
          password,
          consent: true,
        }),
      });
      if (!res.ok) {
        const j = (await res.json().catch(() => ({}))) as { detail?: string };
        throw new Error(j.detail || '保存に失敗しました');
      }
      onDone(stylistName.trim());
    } catch (e) {
      setError(e instanceof Error ? e.message : '保存に失敗しました');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex flex-col">
      <div className="bg-gradient-to-b from-[#e8607f] to-[#c8587a] px-6 pb-9 pt-14 text-white">
        <div className="flex items-center gap-1.5 text-sm font-semibold text-white/90">
          <Sparkles className="h-4 w-4" />
          StyleSnap
        </div>
        <h1 className="mt-4 text-[24px] font-bold leading-snug">最初の設定</h1>
        <p className="mt-3 text-sm leading-relaxed text-white/90">
          初回だけ、お名前とサロンボードのログイン情報をお預かりします。暗号化して保管するので、開発者を含め誰も中身を見ることはできません。
        </p>
      </div>

      <div className="space-y-5 px-6 pb-6 pt-6">
        <div>
          <Label text="スタイリスト名" required />
          <input
            value={stylistName}
            onChange={(e) => setStylistName(e.target.value.slice(0, 50))}
            placeholder="お名前(例: 田中 美咲)"
            className="w-full rounded-lg border border-gray-200 px-3 py-2.5 text-sm text-gray-900 placeholder:text-gray-400 outline-none focus:border-[#0a3d62]"
          />
        </div>

        <div>
          <Label text="サロンボードのログインID" required />
          <input
            value={loginId}
            onChange={(e) => setLoginId(e.target.value)}
            placeholder="ログインID または メール"
            autoComplete="off"
            className="w-full rounded-lg border border-gray-200 px-3 py-2.5 text-sm text-gray-900 placeholder:text-gray-400 outline-none focus:border-[#0a3d62]"
          />
        </div>

        <div>
          <Label text="サロンボードのパスワード" required />
          <div className="relative">
            <input
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              type={showPw ? 'text' : 'password'}
              placeholder="パスワード"
              autoComplete="off"
              className="w-full rounded-lg border border-gray-200 px-3 py-2.5 pr-16 text-sm text-gray-900 placeholder:text-gray-400 outline-none focus:border-[#0a3d62]"
            />
            <button
              type="button"
              onClick={() => setShowPw((v) => !v)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-[11px] font-medium text-[#0a3d62]"
            >
              {showPw ? '隠す' : '表示'}
            </button>
          </div>
        </div>

        <div className="space-y-1.5 rounded-xl bg-[#f6f8fb] p-4 text-[12px] leading-relaxed text-gray-600">
          <div className="font-semibold text-gray-800">取扱いについて</div>
          <ul className="list-disc space-y-1 pl-4">
            <li>ログイン情報は暗号化して保管します</li>
            <li>サロンボードへの自動投稿の目的でのみ使用します</li>
            <li>開発者を含め、誰もパスワードの中身を見られません</li>
            <li>削除を希望されたらすぐに消去します</li>
          </ul>
        </div>

        <label className="flex items-start gap-3 text-sm text-gray-700">
          <input
            type="checkbox"
            checked={agree}
            onChange={(e) => setAgree(e.target.checked)}
            className="mt-0.5 h-4 w-4 shrink-0 accent-[#0a3d62]"
          />
          <span>上記の取扱いに同意します</span>
        </label>

        {error && (
          <div className="flex items-center gap-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            {error}
          </div>
        )}
      </div>

      <div className="sticky bottom-0">
        <div className="mx-auto max-w-md border-t border-gray-100 bg-white px-4 py-3">
          <button
            onClick={submit}
            disabled={!canSubmit}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-[#0a3d62] py-3.5 font-bold text-white transition active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-40"
          >
            {submitting ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                保存中…
              </>
            ) : (
              '保存して始める'
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
