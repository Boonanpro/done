"use client";

import * as React from "react";
import { motion } from "framer-motion";
import {
  Search,
  ExternalLink,
  BookOpen,
  X,
  ArrowUpRight,
  Calendar,
  Database,
  Factory,
  Wrench,
  Info,
  Youtube,
  Library,
  Calculator,
  MessagesSquare,
  MessageSquarePlus,
  Send,
  CornerDownRight,
  Clock,
  Loader2,
  ChevronDown,
  Mail,
} from "lucide-react";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

type Source = {
  id: string;
  name: string;
  url: string;
  type: string;
  count: number;
};

type Article = {
  id: number;
  source: string;
  sourceName: string;
  title: string;
  date: string;
  url: string;
  excerpt: string;
  text: string;
};

type IndexDoc = {
  generated_at: string;
  sources: Source[];
  count: number;
  articles: Article[];
};

type Indexed = Article & { _blob: string; _titleNorm: string };

const SOURCE_COLORS: Record<string, string> = {
  "toaru-d": "bg-sky-100 text-sky-700 border-sky-200",
  takaharaelec: "bg-emerald-100 text-emerald-700 border-emerald-200",
  denkikanri3y: "bg-amber-100 text-amber-700 border-amber-200",
  ohono1200: "bg-violet-100 text-violet-700 border-violet-200",
  tenkenbiyori: "bg-rose-100 text-rose-700 border-rose-200",
  hoandenkikanri: "bg-teal-100 text-teal-700 border-teal-200",
  ogawadenkikanri: "bg-cyan-100 text-cyan-700 border-cyan-200",
  denmasu2: "bg-lime-100 text-lime-700 border-lime-200",
  bibouroku: "bg-orange-100 text-orange-700 border-orange-200",
  denken333: "bg-indigo-100 text-indigo-700 border-indigo-200",
  dengamisama: "bg-fuchsia-100 text-fuchsia-700 border-fuchsia-200",
  ain1234: "bg-pink-100 text-pink-700 border-pink-200",
  wellstone7: "bg-purple-100 text-purple-700 border-purple-200",
  memolabo: "bg-green-100 text-green-700 border-green-200",
  sakon: "bg-blue-100 text-blue-700 border-blue-200",
  moridenkikanri: "bg-stone-100 text-stone-700 border-stone-200",
  yt_yuji: "bg-red-100 text-red-700 border-red-200",
  yt_ch2: "bg-red-100 text-red-700 border-red-200",
  yt_ch3: "bg-red-100 text-red-700 border-red-200",
};

const SUGGESTIONS = [
  "VCB",
  "絶縁抵抗",
  "Ior",
  "接地",
  "PAS",
  "継電器試験",
  "トラッキング",
  "キュービクル",
];

const norm = (s: string) => (s || "").normalize("NFKC").toLowerCase();

function highlight(display: string, terms: string[]): React.ReactNode {
  if (!terms.length || !display) return display;
  const low = display.normalize("NFKC").toLowerCase();
  // 正規化で文字数が変わると位置がずれるため、その場合は強調をやめて素のまま返す
  if (low.length !== display.length) return display;
  const ranges: [number, number][] = [];
  for (const t of terms) {
    if (!t) continue;
    let from = 0;
    let i: number;
    while ((i = low.indexOf(t, from)) >= 0) {
      ranges.push([i, i + t.length]);
      from = i + t.length;
    }
  }
  if (!ranges.length) return display;
  ranges.sort((a, b) => a[0] - b[0]);
  const merged: [number, number][] = [];
  for (const r of ranges) {
    const last = merged[merged.length - 1];
    if (last && r[0] <= last[1]) last[1] = Math.max(last[1], r[1]);
    else merged.push([r[0], r[1]]);
  }
  const out: React.ReactNode[] = [];
  let pos = 0;
  merged.forEach((r, k) => {
    if (r[0] > pos) out.push(display.slice(pos, r[0]));
    out.push(
      <mark
        key={k}
        className="rounded bg-yellow-200/80 px-0.5 text-foreground"
      >
        {display.slice(r[0], r[1])}
      </mark>,
    );
    pos = r[1];
  });
  if (pos < display.length) out.push(display.slice(pos));
  return out;
}

function makeSnippet(excerpt: string, terms: string[]): string {
  if (!excerpt) return "";
  if (!terms.length) return excerpt.slice(0, 150);
  const low = norm(excerpt);
  let idx = -1;
  for (const t of terms) {
    const i = low.indexOf(t);
    if (i >= 0 && (idx < 0 || i < idx)) idx = i;
  }
  if (idx < 0) return excerpt.slice(0, 150);
  const start = Math.max(0, idx - 40);
  return (start > 0 ? "…" : "") + excerpt.slice(start, start + 150);
}

function formatDate(d: string): string {
  if (!d) return "";
  const m = d.match(/^(\d{4})-(\d{2})-(\d{2})/);
  return m ? `${m[1]}.${m[2]}.${m[3]}` : d;
}

/* ───────────────────────── メーカー機器情報 ───────────────────────── */

type MakerCategory = { id: string; label: string };
type Maker = {
  id: string;
  name: string;
  kana: string;
  url: string;
  categories: string[];
  products: string[];
  note: string;
};

const MAKER_CATEGORIES: MakerCategory[] = [
  { id: "juhenden", label: "受変電・変圧器・遮断器" },
  { id: "kaiheiki", label: "開閉器・PAS・断路器" },
  { id: "hogo", label: "保護・地絡継電器" },
  { id: "hiraiki", label: "避雷器・雷対策" },
  { id: "cubicle", label: "キュービクル・盤" },
  { id: "fuse", label: "ヒューズ・カットアウト" },
  { id: "sokutei", label: "点検測定器・試験器" },
  { id: "kenden", label: "検電器・接地・安全用具" },
];

const MAKER_CAT_LABEL: Record<string, string> = Object.fromEntries(
  MAKER_CATEGORIES.map((c) => [c.id, c.label]),
);

// 全URLは実際にアクセスして実在・取り扱い機器を確認済み（2026-05）
const MAKERS: Maker[] = [
  {
    id: "mitsubishi",
    name: "三菱電機",
    kana: "みつびしでんき mitsubishi denki",
    url: "https://www.mitsubishielectric.co.jp/fa/",
    categories: ["juhenden", "hogo", "fuse", "kaiheiki"],
    products: [
      "高圧遮断器(VCB)",
      "高圧電磁接触器",
      "保護継電器",
      "電力ヒューズ",
      "負荷開閉器・断路器",
      "低圧遮断器",
    ],
    note: "高圧・低圧の受配電制御機器を幅広く展開。サイト内に生産終了品の検索もあり。",
  },
  {
    id: "fuji",
    name: "富士電機",
    kana: "ふじでんき fuji denki",
    url: "https://www.fujielectric.co.jp/products/power_distribution_systems/",
    categories: ["juhenden", "hogo", "kaiheiki"],
    products: ["特高・高圧受配電設備", "受変電設備", "計測機器"],
    note: "特高・高圧の受配電設備に強い。",
  },
  {
    id: "hitachi",
    name: "日立産機システム",
    kana: "ひたちさんき hitachi sanki",
    url: "https://www.hitachi-ies.co.jp/products/power-distribution/",
    categories: ["juhenden"],
    products: ["受変電システム", "変圧器", "配電制御機器", "配電監視(H-NET)"],
    note: "受変電・変圧器から配電監視まで。",
  },
  {
    id: "meiden",
    name: "明電舎",
    kana: "めいでんしゃ meidensha meiden",
    url: "https://www.meidensha.co.jp/products/energy/",
    categories: ["juhenden"],
    products: ["受変電設備", "変圧器", "電力機器"],
    note: "電力・受変電設備の老舗メーカー。",
  },
  {
    id: "togami",
    name: "戸上電機製作所",
    kana: "とがみでんき togami",
    url: "https://www.togami-elec.co.jp/product/",
    categories: ["kaiheiki", "juhenden", "hogo"],
    products: [
      "PAS / SOG開閉器",
      "高圧開閉器・高圧遮断器",
      "SOG制御装置",
      "配電盤",
    ],
    note: "柱上PAS・SOG開閉器の定番メーカー。",
  },
  {
    id: "energys",
    name: "エナジーサポート",
    kana: "えなじーさぽーと energy support ngk",
    url: "https://www.energys.co.jp/denzai/",
    categories: ["fuse", "kaiheiki", "hiraiki"],
    products: [
      "高圧カットアウト(PC)",
      "限流ヒューズ(PF)",
      "限流ヒューズ付負荷開閉器(LBS)",
      "高圧配電用避雷器",
    ],
    note: "高圧カットアウト・ヒューズ・LBS。NGKグループ。",
  },
  {
    id: "nito",
    name: "日東工業",
    kana: "にっとうこうぎょう nito",
    url: "https://www.nito.co.jp/products/",
    categories: ["cubicle"],
    products: ["キュービクル", "分電盤", "制御盤", "各種ボックス"],
    note: "キュービクル・分電盤・盤の総合メーカー。",
  },
  {
    id: "otowa",
    name: "音羽電機工業",
    kana: "おとわでんき otowa",
    url: "https://www.otowadenki.co.jp/",
    categories: ["hiraiki"],
    products: ["高圧避雷器", "SPD(避雷器)", "耐雷トランス", "避雷器簡易試験器"],
    note: "避雷器・雷サージ対策の専門。生産終了/推奨代替機種の案内あり。",
  },
  {
    id: "hasegawa",
    name: "長谷川電機工業",
    kana: "はせがわでんき hasegawa",
    url: "https://www.hasegawa-elec.co.jp/product",
    categories: ["kenden", "hogo"],
    products: [
      "検電器",
      "検相器",
      "アースフック(接地)",
      "放電棒",
      "地絡継電器",
      "ZCT",
    ],
    note: "検電器・接地用具の定番メーカー。",
  },
  {
    id: "hioki",
    name: "日置電機 (HIOKI)",
    kana: "ひおきでんき hioki",
    url: "https://www.hioki.co.jp/",
    categories: ["sokutei"],
    products: ["絶縁抵抗計", "クランプメータ", "記録計", "各種測定器"],
    note: "電気測定器の総合メーカー。",
  },
  {
    id: "kyoritsu",
    name: "共立電気計器 (KYORITSU)",
    kana: "きょうりつでんきけいき kyoritsu kew",
    url: "https://www.kew-ltd.co.jp/products/",
    categories: ["sokutei", "kenden"],
    products: [
      "絶縁抵抗計",
      "接地抵抗計",
      "クランプメータ",
      "検電器",
      "電気備品定期点検試験器",
    ],
    note: "絶縁・接地抵抗計や点検試験器が充実。販売終了品の案内あり。",
  },
  {
    id: "musashi",
    name: "ムサシインテック",
    kana: "むさしいんてっく musashi intec",
    url: "https://www.musashi-in.co.jp/",
    categories: ["sokutei", "hogo"],
    products: [
      "保護継電器試験器",
      "SOG試験器",
      "位相特性試験器",
      "監視装置(監視王)",
    ],
    note: "継電器・SOG試験器に強い。",
  },
  {
    id: "soukou",
    name: "双興電機製作所",
    kana: "そうこうでんき soukou",
    url: "https://soukou.co.jp/",
    categories: ["sokutei", "kenden"],
    products: [
      "保護継電器試験装置",
      "交流耐圧試験器",
      "高圧絶縁抵抗計",
      "放電棒",
      "検電器",
    ],
    note: "試験器・耐圧試験装置の専門メーカー。",
  },
];

function makerLogoSrc(url: string): string {
  try {
    const host = new URL(url).hostname;
    return `https://www.google.com/s2/favicons?domain=${host}&sz=128`;
  } catch {
    return "";
  }
}

function MakerLogo({ url, name }: { url: string; name: string }) {
  const [ok, setOk] = React.useState(true);
  const src = makerLogoSrc(url);
  return (
    <span className="flex h-11 w-11 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-border bg-white">
      {ok && src ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={src}
          alt={`${name} ロゴ`}
          width={32}
          height={32}
          loading="lazy"
          className="h-8 w-8 object-contain"
          onError={() => setOk(false)}
        />
      ) : (
        <Factory className="h-5 w-5 text-primary" />
      )}
    </span>
  );
}

function MakerSection() {
  const [query, setQuery] = React.useState("");
  const [cat, setCat] = React.useState<string | null>(null);

  const q = norm(query);

  const results = React.useMemo(() => {
    return MAKERS.filter((m) => {
      if (cat && !m.categories.includes(cat)) return false;
      if (!q) return true;
      const blob = norm(
        `${m.name} ${m.kana} ${m.products.join(" ")} ${m.note} ${m.categories
          .map((c) => MAKER_CAT_LABEL[c] ?? "")
          .join(" ")}`,
      );
      return blob.includes(q);
    });
  }, [q, cat]);

  return (
    <>
      <header className="border-b border-border bg-gradient-to-b from-secondary/60 to-background">
        <div className="mx-auto max-w-5xl px-5 py-9 sm:py-12">
          <h1
            data-edit-id="denki-knowledge-maker-h1"
            className="max-w-3xl text-2xl font-bold leading-snug tracking-tight sm:text-3xl"
          >
            メーカーの機器情報を、公式サイトからすぐに。
          </h1>
          <p
            data-edit-id="denki-knowledge-maker-tagline"
            className="mt-3 max-w-2xl text-sm leading-relaxed text-muted-foreground sm:text-base"
          >
            遮断器・変圧器・避雷器から点検用の測定器まで。型番の仕様・取扱説明書・
            生産終了品の確認に、各メーカーの公式ページへワンクリックで飛べます。
          </p>

          <div className="mt-7">
            <div className="relative">
              <Search className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="メーカー名・機器名で検索（例: VCB / 避雷器 / 絶縁抵抗計）"
                className="h-14 rounded-xl border-border bg-card pl-12 pr-11 text-base shadow-sm focus-visible:ring-2 focus-visible:ring-primary/30"
              />
              {query && (
                <button
                  onClick={() => setQuery("")}
                  aria-label="クリア"
                  className="absolute right-3 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-muted-foreground hover:bg-secondary"
                >
                  <X className="h-4 w-4" />
                </button>
              )}
            </div>
          </div>
        </div>
      </header>

      {/* カテゴリ絞り込み */}
      <div className="sticky top-0 z-10 border-b border-border bg-background/90 backdrop-blur">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-1.5 px-5 py-3">
          <button
            onClick={() => setCat(null)}
            className={`rounded-full border px-3 py-1 text-xs font-medium transition ${
              cat === null
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border bg-card text-muted-foreground hover:text-foreground"
            }`}
          >
            すべて
          </button>
          {MAKER_CATEGORIES.map((c) => {
            const on = cat === c.id;
            return (
              <button
                key={c.id}
                onClick={() => setCat(on ? null : c.id)}
                className={`rounded-full border px-3 py-1 text-xs font-medium transition ${
                  on
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-border bg-card text-muted-foreground hover:text-foreground"
                }`}
              >
                {c.label}
              </button>
            );
          })}
        </div>
      </div>

      <main className="mx-auto max-w-5xl px-5 py-6">
        <div className="mb-4 text-sm text-muted-foreground">
          <span className="font-semibold text-foreground">
            {results.length}
          </span>{" "}
          社のメーカー
        </div>

        {results.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border bg-card/50 p-12 text-center">
            <Search className="mx-auto mb-3 h-8 w-8 text-muted-foreground/50" />
            <p className="text-muted-foreground">
              該当するメーカーが見つかりませんでした。
            </p>
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {results.map((m, i) => (
              <motion.a
                key={m.id}
                href={m.url}
                target="_blank"
                rel="noopener noreferrer"
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.18, delay: Math.min(i, 8) * 0.02 }}
                className="group flex flex-col rounded-xl border border-border bg-card p-5 shadow-sm transition hover:border-primary/40 hover:shadow-md"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex min-w-0 items-center gap-2.5">
                    <MakerLogo url={m.url} name={m.name} />
                    <h2 className="text-base font-bold leading-snug text-foreground">
                      <span className="group-hover:underline">{m.name}</span>
                    </h2>
                  </div>
                  <ArrowUpRight className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground opacity-0 transition group-hover:opacity-100" />
                </div>

                <div className="mt-2 flex flex-wrap gap-1.5">
                  {m.categories.map((c) => (
                    <Badge
                      key={c}
                      variant="outline"
                      className="border-primary/20 bg-primary/5 text-[11px] font-medium text-primary"
                    >
                      {MAKER_CAT_LABEL[c]}
                    </Badge>
                  ))}
                </div>

                <p className="mt-2.5 text-xs leading-relaxed text-muted-foreground">
                  {m.note}
                </p>

                <div className="mt-3 flex flex-wrap gap-1.5">
                  {m.products.map((p) => (
                    <span
                      key={p}
                      className="rounded-md bg-secondary px-2 py-0.5 text-[11px] text-foreground/70"
                    >
                      {p}
                    </span>
                  ))}
                </div>

                <div className="mt-3 flex items-center gap-1 text-xs text-muted-foreground">
                  <ExternalLink className="h-3 w-3" />
                  公式サイトを開く
                </div>
              </motion.a>
            ))}
          </div>
        )}

        <div className="mt-8 flex items-start gap-2 rounded-xl border border-border bg-secondary/40 p-4 text-xs leading-relaxed text-muted-foreground">
          <Info className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            各メーカーの公式サイトへリンクしています。型番ごとの詳しい仕様・取扱説明書・
            生産終了品の代替機種などは、各社サイト内の「製品情報」「ダウンロード」「カタログ」から探せます。
            掲載してほしいメーカーがあれば追加します。
          </span>
        </div>
      </main>
    </>
  );
}

/* ───────────────────────── 資料・計算ツール ───────────────────────── */

type ToolItem = {
  id: string;
  name: string;
  url: string;
  note: string;
};

// 堀口電気管理事務所（堀口和夫氏）が公開している計算Webアプリ。URLは実在を確認済み（2026-05）
const HORIGUCHI_SITE = "https://hdk-jms.com/";
const TOOLS: ToolItem[] = [
  {
    id: "v_test",
    name: "耐圧試験 充電電流計算",
    url: "https://www.airus.jp/web_app/v_test",
    note: "ケーブルや変圧器容量から、耐圧試験時にかかる充電電流を計算します。",
  },
  {
    id: "ocr_tap",
    name: "OCR 電流タップ",
    url: "https://www.airus.jp/web_app/ocr_tap",
    note: "変圧器容量からCT比を選び、用途に応じたOCRの電流タップを自動で選定します。",
  },
  {
    id: "it_curve",
    name: "保護協調 I-t曲線作成",
    url: "https://www.airus.jp/web_app/it_curve",
    note: "配変・励磁突入電流を考慮した保護協調のI-t曲線グラフを作成できます。",
  },
];

function ReferenceSection() {
  return (
    <>
      <header className="border-b border-border bg-gradient-to-b from-secondary/60 to-background">
        <div className="mx-auto max-w-5xl px-5 py-9 sm:py-12">
          <h1 className="max-w-3xl text-2xl font-bold leading-snug tracking-tight sm:text-3xl">
            現場で使える、計算ツール。
          </h1>
          <p className="mt-3 max-w-2xl text-sm leading-relaxed text-muted-foreground sm:text-base">
            耐圧試験の充電電流、OCRの電流タップ、保護協調のI-t曲線。
            点検・試験の現場でそのまま使える計算ツールへ、ワンクリックで飛べます。
          </p>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-5 py-6">
        <div className="grid gap-3 sm:grid-cols-3">
          {TOOLS.map((t, i) => (
            <motion.a
              key={t.id}
              href={t.url}
              target="_blank"
              rel="noopener noreferrer"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.18, delay: Math.min(i, 8) * 0.02 }}
              className="group flex flex-col rounded-xl border border-border bg-card p-5 shadow-sm transition hover:border-primary/40 hover:shadow-md"
            >
              <div className="flex items-start justify-between gap-2">
                <h2 className="flex items-center gap-1.5 text-base font-bold leading-snug text-foreground">
                  <Calculator className="h-4 w-4 shrink-0 text-primary" />
                  <span className="group-hover:underline">{t.name}</span>
                </h2>
                <ArrowUpRight className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground opacity-0 transition group-hover:opacity-100" />
              </div>
              <p className="mt-2.5 text-xs leading-relaxed text-muted-foreground">
                {t.note}
              </p>
              <div className="mt-3 flex items-center gap-1 text-xs text-muted-foreground">
                <ExternalLink className="h-3 w-3" />
                ツールを開く
              </div>
            </motion.a>
          ))}
        </div>

        <p className="mt-4 text-xs leading-relaxed text-muted-foreground">
          ツールが開かない場合は{" "}
          <a
            href={HORIGUCHI_SITE}
            target="_blank"
            rel="noopener noreferrer"
            className="font-medium text-primary underline underline-offset-2"
          >
            堀口電気管理事務所のサイト
          </a>{" "}
          からアクセスしてください。サイトの更新により、上記リンク先が変わってつながらなくなることがあります。
        </p>

        <div className="mt-8 flex items-start gap-2 rounded-xl border border-border bg-secondary/40 p-4 text-xs leading-relaxed text-muted-foreground">
          <Info className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            これらの計算ツールは{" "}
            <a
              href={HORIGUCHI_SITE}
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium text-primary underline underline-offset-2"
            >
              堀口電気管理事務所（堀口和夫 氏）
            </a>{" "}
            が制作・公開しているWebアプリです。本サイトはリンクのみを掲載しており、ツールの著作権・運営は同事務所に帰属します。
          </span>
        </div>
      </main>
    </>
  );
}

/* ───────────────────────── 質問・相談（Q&A掲示板） ───────────────────────── */

type QAQuestion = {
  id: string;
  created_at: string;
  author_name: string;
  title: string;
  body: string;
  answer_count: number;
};

type QAAnswer = {
  id: string;
  created_at: string;
  author_name: string;
  body: string;
};

function timeLabel(iso: string): string {
  const f = formatDate(iso);
  return f || iso;
}

function QASection() {
  const [questions, setQuestions] = React.useState<QAQuestion[] | null>(null);
  const [error, setError] = React.useState(false);
  const [showForm, setShowForm] = React.useState(false);
  const [openId, setOpenId] = React.useState<string | null>(null);

  const load = React.useCallback(() => {
    setError(false);
    fetch("/api/denki-qa/questions", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d: QAQuestion[]) => setQuestions(d))
      .catch(() => setError(true));
  }, []);

  React.useEffect(() => {
    load();
  }, [load]);

  return (
    <>
      <header className="border-b border-border bg-gradient-to-b from-secondary/60 to-background">
        <div className="mx-auto max-w-5xl px-5 py-9 sm:py-12">
          <h1 className="max-w-3xl text-2xl font-bold leading-snug tracking-tight sm:text-3xl">
            現場の困りごとを、同業者に相談。
          </h1>
          <p className="mt-3 max-w-2xl text-sm leading-relaxed text-muted-foreground sm:text-base">
            点検中のトラブル、判断に迷ったこと、機器の不明点。
            登録なしで質問でき、同じ電気管理技術者が答えてくれます。
          </p>
          <div className="mt-6">
            <Button
              onClick={() => setShowForm((v) => !v)}
              className="gap-2"
              size="lg"
            >
              <MessageSquarePlus className="h-5 w-5" />
              質問する
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-5 py-6">
        {showForm && (
          <QuestionForm
            onPosted={() => {
              setShowForm(false);
              load();
            }}
            onCancel={() => setShowForm(false)}
          />
        )}

        {error && (
          <div className="rounded-xl border border-border bg-card p-8 text-center text-muted-foreground">
            読み込めませんでした。時間をおいて再度お試しください。
          </div>
        )}

        {!questions && !error && (
          <div className="flex items-center justify-center py-12 text-muted-foreground">
            <Loader2 className="mr-2 h-5 w-5 animate-spin" />
            読み込み中…
          </div>
        )}

        {questions && questions.length === 0 && !showForm && (
          <div className="rounded-xl border border-dashed border-border bg-card/50 p-12 text-center">
            <MessagesSquare className="mx-auto mb-3 h-8 w-8 text-muted-foreground/50" />
            <p className="text-muted-foreground">まだ質問がありません。</p>
            <p className="mt-1 text-sm text-muted-foreground/70">
              最初の質問を投稿してみましょう。
            </p>
          </div>
        )}

        {questions && questions.length > 0 && (
          <div className="space-y-3">
            {questions.map((q) => (
              <QuestionCard
                key={q.id}
                q={q}
                open={openId === q.id}
                onToggle={() => setOpenId((id) => (id === q.id ? null : q.id))}
              />
            ))}
          </div>
        )}

        <div className="mt-8 flex items-start gap-2 rounded-xl border border-border bg-secondary/40 p-4 text-xs leading-relaxed text-muted-foreground">
          <Info className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            登録は不要です。お名前と内容だけで質問・回答できます。メールアドレスは任意で、
            入れていただくと回答がついたときにお知らせメールが届きます（公開されません）。
            投稿は管理者が確認し、不適切なものは削除する場合があります。
          </span>
        </div>
      </main>
    </>
  );
}

function fieldCls() {
  return "w-full rounded-lg border border-border bg-card px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30";
}

function QuestionForm({
  onPosted,
  onCancel,
}: {
  onPosted: () => void;
  onCancel: () => void;
}) {
  const [name, setName] = React.useState("");
  const [email, setEmail] = React.useState("");
  const [title, setTitle] = React.useState("");
  const [body, setBody] = React.useState("");
  const [website, setWebsite] = React.useState(""); // ハニーポット
  const [posting, setPosting] = React.useState(false);
  const [msg, setMsg] = React.useState("");

  const submit = async () => {
    if (!title.trim() || !body.trim()) {
      setMsg("タイトルと内容を入力してください。");
      return;
    }
    setPosting(true);
    setMsg("");
    try {
      const r = await fetch("/api/denki-qa/questions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          author_name: name,
          email,
          title,
          body,
          website,
        }),
      });
      const d = await r.json();
      if (!r.ok) {
        setMsg(d.error || "投稿に失敗しました。");
        setPosting(false);
        return;
      }
      onPosted();
    } catch {
      setMsg("投稿に失敗しました。通信環境をご確認ください。");
      setPosting(false);
    }
  };

  return (
    <div className="mb-5 rounded-xl border border-primary/30 bg-card p-5 shadow-sm">
      <h2 className="mb-3 text-base font-bold">質問を投稿する</h2>
      <div className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">
              お名前（任意）
            </label>
            <input
              className={fieldCls()}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="名無しの技術者"
              maxLength={40}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">
              <Mail className="mr-1 inline h-3 w-3" />
              メール（任意・非公開／回答時に通知）
            </label>
            <input
              className={fieldCls()}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="例: you@example.com"
              type="email"
              maxLength={200}
            />
          </div>
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-muted-foreground">
            タイトル
          </label>
          <input
            className={fieldCls()}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="例: PAS交換後にSOGが動作しない"
            maxLength={120}
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-muted-foreground">
            内容
          </label>
          <textarea
            className={`${fieldCls()} min-h-[120px] resize-y`}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="状況・機器・困っていることを具体的に書くと回答が付きやすいです。"
            maxLength={4000}
          />
        </div>
        {/* ハニーポット: 人間には見えない。botが埋めるとスパム判定 */}
        <input
          tabIndex={-1}
          autoComplete="off"
          value={website}
          onChange={(e) => setWebsite(e.target.value)}
          className="hidden"
          aria-hidden="true"
        />
        {msg && <p className="text-sm text-red-600">{msg}</p>}
        <div className="flex items-center gap-2">
          <Button onClick={submit} disabled={posting} className="gap-2">
            {posting ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
            投稿する
          </Button>
          <Button variant="ghost" onClick={onCancel} disabled={posting}>
            キャンセル
          </Button>
        </div>
      </div>
    </div>
  );
}

function QuestionCard({
  q,
  open,
  onToggle,
}: {
  q: QAQuestion;
  open: boolean;
  onToggle: () => void;
}) {
  const [answers, setAnswers] = React.useState<QAAnswer[] | null>(null);
  const [count, setCount] = React.useState(q.answer_count);

  const loadAnswers = React.useCallback(() => {
    fetch(`/api/denki-qa/answers?question_id=${q.id}`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d: QAAnswer[]) => {
        setAnswers(d);
        setCount(d.length);
      })
      .catch(() => setAnswers([]));
  }, [q.id]);

  React.useEffect(() => {
    if (open && answers === null) loadAnswers();
  }, [open, answers, loadAnswers]);

  return (
    <div className="rounded-xl border border-border bg-card shadow-sm">
      <button
        onClick={onToggle}
        className="flex w-full items-start gap-3 p-5 text-left"
      >
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-semibold leading-snug text-foreground">
            {q.title}
          </h2>
          <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">
            {q.body}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
            <span>{q.author_name}</span>
            <span className="flex items-center gap-1">
              <Clock className="h-3 w-3" />
              {timeLabel(q.created_at)}
            </span>
            <Badge
              variant="outline"
              className="border-primary/20 bg-primary/5 text-[11px] font-medium text-primary"
            >
              回答 {count}
            </Badge>
          </div>
        </div>
        <ChevronDown
          className={`mt-1 h-5 w-5 shrink-0 text-muted-foreground transition ${
            open ? "rotate-180" : ""
          }`}
        />
      </button>

      {open && (
        <div className="border-t border-border px-5 py-4">
          <div className="whitespace-pre-wrap text-sm leading-relaxed text-foreground/90">
            {q.body}
          </div>

          <div className="mt-5 space-y-3">
            {answers === null ? (
              <div className="flex items-center text-sm text-muted-foreground">
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                回答を読み込み中…
              </div>
            ) : answers.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                まだ回答がありません。最初の回答を書いてみませんか。
              </p>
            ) : (
              answers.map((a) => (
                <div
                  key={a.id}
                  className="flex gap-2 rounded-lg bg-secondary/50 p-3"
                >
                  <CornerDownRight className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                  <div className="min-w-0">
                    <div className="mb-1 flex items-center gap-2 text-xs text-muted-foreground">
                      <span className="font-medium text-foreground">
                        {a.author_name}
                      </span>
                      <span className="flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        {timeLabel(a.created_at)}
                      </span>
                    </div>
                    <div className="whitespace-pre-wrap text-sm leading-relaxed text-foreground/90">
                      {a.body}
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>

          <AnswerForm questionId={q.id} onPosted={loadAnswers} />
        </div>
      )}
    </div>
  );
}

function AnswerForm({
  questionId,
  onPosted,
}: {
  questionId: string;
  onPosted: () => void;
}) {
  const [name, setName] = React.useState("");
  const [email, setEmail] = React.useState("");
  const [body, setBody] = React.useState("");
  const [website, setWebsite] = React.useState("");
  const [posting, setPosting] = React.useState(false);
  const [msg, setMsg] = React.useState("");

  const submit = async () => {
    if (!body.trim()) {
      setMsg("回答内容を入力してください。");
      return;
    }
    setPosting(true);
    setMsg("");
    try {
      const r = await fetch("/api/denki-qa/answers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question_id: questionId,
          author_name: name,
          email,
          body,
          website,
        }),
      });
      const d = await r.json();
      if (!r.ok) {
        setMsg(d.error || "投稿に失敗しました。");
        setPosting(false);
        return;
      }
      setBody("");
      setName("");
      setEmail("");
      setPosting(false);
      onPosted();
    } catch {
      setMsg("投稿に失敗しました。");
      setPosting(false);
    }
  };

  return (
    <div className="mt-4 rounded-lg border border-border bg-background p-3">
      <p className="mb-2 text-xs font-medium text-muted-foreground">
        この質問に回答する
      </p>
      <div className="space-y-2">
        <div className="grid gap-2 sm:grid-cols-2">
          <input
            className={fieldCls()}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="お名前（任意）"
            maxLength={40}
          />
          <input
            className={fieldCls()}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="メール（任意・非公開／返信が来たら通知）"
            type="email"
            maxLength={200}
          />
        </div>
        <textarea
          className={`${fieldCls()} min-h-[80px] resize-y`}
          value={body}
          onChange={(e) => setBody(e.target.value)}
          placeholder="回答を書く"
          maxLength={4000}
        />
        <input
          tabIndex={-1}
          autoComplete="off"
          value={website}
          onChange={(e) => setWebsite(e.target.value)}
          className="hidden"
          aria-hidden="true"
        />
        {msg && <p className="text-sm text-red-600">{msg}</p>}
        <Button onClick={submit} disabled={posting} size="sm" className="gap-2">
          {posting ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Send className="h-4 w-4" />
          )}
          回答を投稿
        </Button>
      </div>
    </div>
  );
}

export default function DenkiKnowledgePage() {
  const [view, setView] = React.useState<
    "search" | "makers" | "refs" | "qa"
  >("search");
  const [doc, setDoc] = React.useState<IndexDoc | null>(null);
  const [error, setError] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const [active, setActive] = React.useState<Set<string>>(new Set());
  const [sort, setSort] = React.useState<"relevance" | "newest">("relevance");
  const [limit, setLimit] = React.useState(40);

  React.useEffect(() => {
    fetch("/denki-knowledge-index.json")
      .then((r) => {
        if (!r.ok) throw new Error("not found");
        return r.json();
      })
      .then((d: IndexDoc) => {
        setDoc(d);
        setActive(new Set(d.sources.map((s) => s.id)));
      })
      .catch(() => setError(true));
  }, []);

  const indexed: Indexed[] = React.useMemo(() => {
    if (!doc) return [];
    return doc.articles.map((a) => ({
      ...a,
      _blob: norm(a.text),
      _titleNorm: norm(a.title),
    }));
  }, [doc]);

  const ytSources = React.useMemo(
    () =>
      new Set(
        (doc?.sources ?? [])
          .filter((s) => s.type === "youtube")
          .map((s) => s.id),
      ),
    [doc],
  );

  const terms = React.useMemo(
    () => norm(query).split(/\s+/).filter(Boolean),
    [query],
  );

  const results = React.useMemo(() => {
    let res = indexed.filter((a) => active.has(a.source));
    if (terms.length) {
      res = res.filter((a) => terms.every((t) => a._blob.includes(t)));
    }
    const titleScore = (a: Indexed) =>
      terms.reduce((n, t) => n + (a._titleNorm.includes(t) ? 1 : 0), 0);
    res = [...res].sort((a, b) => {
      if (sort === "relevance" && terms.length) {
        const d = titleScore(b) - titleScore(a);
        if (d !== 0) return d;
      }
      return (b.date || "").localeCompare(a.date || "");
    });
    return res;
  }, [indexed, active, terms, sort]);

  React.useEffect(() => {
    setLimit(40);
  }, [query, sort]);

  const toggleSource = (id: string) => {
    setActive((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const allActive = doc ? active.size === doc.sources.length : false;
  const totalCount = doc?.count ?? 0;

  return (
    <div className="denki-theme min-h-screen bg-background text-foreground">
      <style>{themeCss}</style>

      {/* トップバー: ブランド + タブ切り替え */}
      <div className="border-b border-border bg-background">
        <div className="mx-auto flex max-w-5xl flex-col gap-3 px-5 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <BookOpen className="h-5 w-5" />
            </div>
            <span
              data-edit-id="denki-knowledge-brand"
              className="text-lg font-bold tracking-tight"
            >
              電気主任技術者応援サイト
            </span>
          </div>

          <nav className="grid w-full grid-cols-2 gap-1 rounded-lg border border-border bg-secondary/50 p-1 text-sm sm:flex sm:w-auto sm:items-center">
            <button
              onClick={() => setView("search")}
              className={`flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md px-3 py-1.5 font-medium transition ${
                view === "search"
                  ? "bg-card text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <BookOpen className="h-4 w-4" />
              ブログ横断検索
            </button>
            <button
              onClick={() => setView("makers")}
              className={`flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md px-3 py-1.5 font-medium transition ${
                view === "makers"
                  ? "bg-card text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <Wrench className="h-4 w-4" />
              メーカー機器情報
            </button>
            <button
              onClick={() => setView("refs")}
              className={`flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md px-3 py-1.5 font-medium transition ${
                view === "refs"
                  ? "bg-card text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <Library className="h-4 w-4" />
              資料・ツール
            </button>
            <button
              onClick={() => setView("qa")}
              className={`flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md px-3 py-1.5 font-medium transition ${
                view === "qa"
                  ? "bg-card text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <MessagesSquare className="h-4 w-4" />
              質問・相談
            </button>
          </nav>
        </div>
      </div>

      {view === "makers" && <MakerSection />}
      {view === "refs" && <ReferenceSection />}
      {view === "qa" && <QASection />}

      {view === "search" && (
        <>
          {/* ヘッダー / ヒーロー */}
          <header className="border-b border-border bg-gradient-to-b from-secondary/60 to-background">
            <div className="mx-auto max-w-5xl px-5 py-10 sm:py-14">
              <h1
                data-edit-id="denki-knowledge-hero-h1"
            className="max-w-3xl text-2xl font-bold leading-snug tracking-tight sm:text-3xl"
          >
            全国の電気管理技術者のブログ・動画を、
            <br className="hidden sm:block" />
            ひとつの検索窓で。
          </h1>
          <p
            data-edit-id="denki-knowledge-hero-tagline"
            className="mt-3 max-w-2xl text-sm leading-relaxed text-muted-foreground sm:text-base"
          >
            点検・試験・トラブル事例など、教科書にない現場の知恵を横断検索。
            「どのブログで読んだか思い出せない」をなくします。
          </p>

          {/* 検索ボックス */}
          <div className="mt-7">
            <div className="relative">
              <Search className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-muted-foreground" />
              <Input
                autoFocus
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="キーワードで検索（例: VCB トラッキング）"
                className="h-14 rounded-xl border-border bg-card pl-12 pr-11 text-base shadow-sm focus-visible:ring-2 focus-visible:ring-primary/30"
              />
              {query && (
                <button
                  onClick={() => setQuery("")}
                  aria-label="クリア"
                  className="absolute right-3 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-muted-foreground hover:bg-secondary"
                >
                  <X className="h-4 w-4" />
                </button>
              )}
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-2">
              <span className="text-xs text-muted-foreground">よく検索:</span>
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => setQuery(s)}
                  className="rounded-full border border-border bg-card px-3 py-1 text-xs text-foreground/80 transition hover:border-primary/40 hover:text-foreground"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        </div>
      </header>

      {/* コントロール */}
      <div className="sticky top-0 z-10 border-b border-border bg-background/90 backdrop-blur">
        <div className="mx-auto flex max-w-5xl flex-col gap-3 px-5 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-wrap items-center gap-1.5">
            <button
              onClick={() =>
                setActive(
                  allActive
                    ? new Set()
                    : new Set(doc?.sources.map((s) => s.id) ?? []),
                )
              }
              className={`rounded-full border px-3 py-1 text-xs font-medium transition ${
                allActive
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-card text-muted-foreground hover:text-foreground"
              }`}
            >
              すべて
            </button>
            {doc?.sources.map((s) => {
              const on = active.has(s.id);
              return (
                <button
                  key={s.id}
                  onClick={() => toggleSource(s.id)}
                  className={`rounded-full border px-3 py-1 text-xs font-medium transition ${
                    on
                      ? SOURCE_COLORS[s.id] ??
                        "bg-secondary text-foreground border-border"
                      : "border-border bg-card text-muted-foreground/60 hover:text-foreground"
                  }`}
                  title={s.name}
                >
                  {s.name}
                  <span className="ml-1 opacity-60">{s.count}</span>
                </button>
              );
            })}
          </div>

          <div className="flex items-center gap-1 text-xs">
            <span className="text-muted-foreground">並び順</span>
            {(
              [
                ["relevance", "関連度"],
                ["newest", "新しい順"],
              ] as const
            ).map(([k, label]) => (
              <button
                key={k}
                onClick={() => setSort(k)}
                className={`rounded-md px-2.5 py-1 font-medium transition ${
                  sort === k
                    ? "bg-secondary text-foreground"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* 結果 */}
      <main className="mx-auto max-w-5xl px-5 py-6">
        {error && (
          <div className="rounded-xl border border-border bg-card p-8 text-center text-muted-foreground">
            データを読み込めませんでした。時間をおいて再度お試しください。
          </div>
        )}

        {!doc && !error && (
          <div className="space-y-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <div
                key={i}
                className="rounded-xl border border-border bg-card p-5"
              >
                <Skeleton className="h-5 w-2/3" />
                <Skeleton className="mt-3 h-4 w-full" />
                <Skeleton className="mt-2 h-4 w-5/6" />
              </div>
            ))}
          </div>
        )}

        {doc && (
          <>
            <div className="mb-4 flex items-center justify-between text-sm text-muted-foreground">
              <span>
                {terms.length ? (
                  <>
                    <span className="font-semibold text-foreground">
                      {results.length.toLocaleString()}
                    </span>{" "}
                    件ヒット
                  </>
                ) : (
                  <>
                    全{" "}
                    <span className="font-semibold text-foreground">
                      {totalCount.toLocaleString()}
                    </span>{" "}
                    件を横断検索中
                  </>
                )}
              </span>
            </div>

            {results.length === 0 ? (
              <div className="rounded-xl border border-dashed border-border bg-card/50 p-12 text-center">
                <Search className="mx-auto mb-3 h-8 w-8 text-muted-foreground/50" />
                <p className="text-muted-foreground">
                  該当する記事が見つかりませんでした。
                </p>
                <p className="mt-1 text-sm text-muted-foreground/70">
                  キーワードを短くするか、別の言葉で試してください。
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                {results.slice(0, limit).map((a, i) => (
                  <motion.a
                    key={a.id}
                    href={a.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.18, delay: Math.min(i, 8) * 0.015 }}
                    className="group block rounded-xl border border-border bg-card p-5 shadow-sm transition hover:border-primary/40 hover:shadow-md"
                  >
                    <div className="mb-2 flex flex-wrap items-center gap-2">
                      <Badge
                        variant="outline"
                        className={`border ${
                          SOURCE_COLORS[a.source] ?? ""
                        } font-medium`}
                      >
                        {ytSources.has(a.source) && (
                          <Youtube className="mr-1 inline h-3 w-3" />
                        )}
                        {a.sourceName}
                      </Badge>
                      {a.date && (
                        <span className="flex items-center gap-1 text-xs text-muted-foreground">
                          <Calendar className="h-3 w-3" />
                          {formatDate(a.date)}
                        </span>
                      )}
                    </div>
                    <h2 className="flex items-start gap-1.5 text-base font-semibold leading-snug text-foreground">
                      <span className="group-hover:underline">
                        {highlight(a.title, terms)}
                      </span>
                      <ArrowUpRight className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground opacity-0 transition group-hover:opacity-100" />
                    </h2>
                    <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
                      {highlight(makeSnippet(a.excerpt, terms), terms)}
                    </p>
                  </motion.a>
                ))}

                {results.length > limit && (
                  <div className="pt-2 text-center">
                    <Button
                      variant="outline"
                      onClick={() => setLimit((l) => l + 40)}
                    >
                      さらに表示（残り{" "}
                      {(results.length - limit).toLocaleString()} 件）
                    </Button>
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </main>

      {/* フッター: 情報源と注記 */}
      <footer className="mt-10 border-t border-border bg-secondary/40">
        <div className="mx-auto max-w-5xl px-5 py-8">
          <div className="flex items-center gap-2 text-sm font-semibold">
            <Database className="h-4 w-4 text-muted-foreground" />
            情報源（{doc?.sources.length ?? 0} サイト）
          </div>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {doc?.sources.map((s) => (
              <a
                key={s.id}
                href={s.url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center justify-between rounded-lg border border-border bg-card px-3 py-2 text-sm transition hover:border-primary/40"
              >
                <span className="flex items-center gap-2">
                  <span
                    className={`inline-block h-2 w-2 rounded-full ${
                      (SOURCE_COLORS[s.id] ?? "").split(" ")[0]
                    }`}
                  />
                  {s.name}
                </span>
                <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  {s.count} 記事
                  <ExternalLink className="h-3 w-3" />
                </span>
              </a>
            ))}
          </div>
          <p className="mt-5 text-xs leading-relaxed text-muted-foreground">
            本サイトは各ブログの記事タイトル・本文の一部、YouTube動画のタイトルを引用し、検索結果から元の記事・動画へリンクします。
            著作権は各執筆者・投稿者に帰属します。全文・本編は各サイトの元ページでご覧ください。
          </p>
          {doc?.generated_at && (
            <p className="mt-1 text-xs text-muted-foreground/70">
              索引の更新日時: {doc.generated_at.replace("T", " ")}
            </p>
          )}
        </div>
      </footer>
        </>
      )}
    </div>
  );
}

const themeCss = `
.denki-theme {
  --background: oklch(0.99 0.003 250);
  --foreground: oklch(0.25 0.02 255);
  --card: oklch(1 0 0);
  --card-foreground: oklch(0.25 0.02 255);
  --popover: oklch(1 0 0);
  --popover-foreground: oklch(0.25 0.02 255);
  --primary: oklch(0.52 0.16 255);
  --primary-foreground: oklch(0.99 0 0);
  --secondary: oklch(0.96 0.008 250);
  --secondary-foreground: oklch(0.3 0.02 255);
  --muted: oklch(0.96 0.008 250);
  --muted-foreground: oklch(0.5 0.02 255);
  --accent: oklch(0.94 0.012 250);
  --accent-foreground: oklch(0.3 0.02 255);
  --border: oklch(0.91 0.01 250);
  --input: oklch(0.91 0.01 250);
  --ring: oklch(0.52 0.16 255);
  --radius: 0.7rem;
  color: var(--foreground);
}
`;
