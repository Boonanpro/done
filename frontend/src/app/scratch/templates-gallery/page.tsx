'use client';

import {
  CaseStudyGrid,
  ConversionCta,
  FaqSection,
  FeatureGrid,
  FullBleedVideoHero,
  HeroMedia,
  HeroSection,
  InquiryForm,
  KpiCard,
  LocationMap,
  LpShell,
  PageShell,
  ProcessTimeline,
  ProofBar,
  Section,
  ServiceShowcase,
} from '@/components/templates';
import { Rocket, ShieldCheck, TrendingUp, Users, Zap } from 'lucide-react';

// scratch: components/templates のセクション/構造系部品を実物レンダリングで一覧する。
// 品質確認用。motion / typography / scroll-video は別ギャラリーにある:
//   /scratch/motion-components, /scratch/typography-components, /scratch/scroll-video-test

function Block({
  id,
  name,
  note,
  children,
}: {
  id: string;
  name: string;
  note: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="border-t border-neutral-200 px-6 py-16 sm:px-10">
      <div className="mx-auto max-w-7xl">
        <div className="mb-8">
          <div className="mb-2 font-mono text-xs uppercase tracking-[0.18em] text-neutral-400">
            {`<${name}>`}
          </div>
          <p className="max-w-2xl text-sm text-neutral-500">{note}</p>
        </div>
        <div className="rounded-xl border border-neutral-200 bg-white">{children}</div>
      </div>
    </section>
  );
}

const LIGHT = {
  '--background': '#ffffff',
  '--foreground': '#171717',
  '--card': '#ffffff',
  '--card-foreground': '#171717',
  '--popover': '#ffffff',
  '--popover-foreground': '#171717',
  '--muted': '#f5f5f5',
  '--muted-foreground': '#737373',
  '--border': '#e5e5e5',
  '--input': '#e5e5e5',
  '--primary': '#1d4ed8',
  '--primary-foreground': '#ffffff',
  '--secondary': '#f5f5f5',
  '--secondary-foreground': '#171717',
  '--accent': '#f5f5f5',
  '--accent-foreground': '#171717',
  '--ring': '#1d4ed8',
} as React.CSSProperties;

export default function TemplatesGalleryPage() {
  return (
    <div style={LIGHT} className="h-screen overflow-y-auto bg-white text-neutral-900">
      <header className="px-6 py-14 sm:px-10">
        <div className="mx-auto max-w-7xl">
          <div className="font-mono text-xs uppercase tracking-[0.2em] text-neutral-400">
            scratch / templates-gallery
          </div>
          <h1 className="mt-3 text-4xl font-semibold tracking-tight sm:text-5xl">
            共通テンプレート一覧
          </h1>
          <p className="mt-4 max-w-2xl text-neutral-500">
            <code>components/templates</code> のセクション/構造系部品を実物でレンダリングしたカタログ。
            品質チェック用。タイポ・装飾・モーション・スクロール動画はそれぞれ別ギャラリー
            （typography-components / motion-components / scroll-video-test）にあります。
          </p>
        </div>
      </header>

      <Block id="hero-media" name="HeroMedia" note="静止画/動画背景のヒーロー。darken と fade で文字の可読性を確保。">
        <HeroMedia kind="image" src="/yonago-gojo/hero-poster.jpg" alt="sample" darken={0.45} fade="bottom" minHeightClass="min-h-[420px]">
          <div className="flex h-full min-h-[420px] flex-col justify-end p-8 text-white sm:p-12">
            <p className="text-sm uppercase tracking-widest opacity-80">Hero Media</p>
            <h2 className="mt-2 max-w-xl text-3xl font-semibold sm:text-5xl">画像の上に文字を重ねるヒーロー</h2>
          </div>
        </HeroMedia>
      </Block>

      <Block id="full-bleed-video-hero" name="FullBleedVideoHero" note="全画面動画ファーストビュー。PC/モバイルで別ソース、自動再生・ミュート。">
        <FullBleedVideoHero
          src="/yonago-gojo/hero-pc.mp4"
          poster="/yonago-gojo/hero-poster.jpg"
          eyebrow="VIDEO HERO"
          title="動きで世界観を伝えるヒーロー"
          description="本文はDOMに置く。動画に焼き込まない。"
          minHeightClass="min-h-[460px]"
          darken={0.4}
        />
      </Block>

      <Block id="hero-section" name="HeroSection" note="汎用ヒーロー。split / centered / stacked のレイアウト切替。">
        <HeroSection
          eyebrow="GENERIC HERO"
          heading="見出し・小見出し・CTA・メディアを置ける汎用ヒーロー"
          subheading="メディアを持たない情報系ページや、画像を横に置くページに使う。"
          layout="split"
          media={<img src="/yonago-gojo/g1.jpg" alt="" className="aspect-[4/3] w-full rounded-lg object-cover" />}
          actions={
            <a href="#" className="inline-flex rounded-md bg-[var(--primary)] px-5 py-2.5 text-sm font-medium text-white">
              お問い合わせ
            </a>
          }
        />
      </Block>

      <Block id="proof-bar" name="ProofBar" note="実績・信頼材料を横断バンドで見せる。value/label/note。">
        <ProofBar
          items={[
            { value: '120+', label: '施工実績', note: '累計' },
            { value: '15年', label: '地域での営業年数' },
            { value: '98%', label: 'リピート率', note: '直近2年' },
            { value: '24h', label: '問い合わせ対応' },
          ]}
        />
      </Block>

      <Block id="service-showcase" name="ServiceShowcase" note="主要サービスを強弱付きで。featuredIndex で1つを大きく。画像/アイコン対応。">
        <div className="p-6">
          <ServiceShowcase
            featuredIndex={0}
            items={[
              { title: '外構・エクステリア工事', description: '設計から施工まで一貫対応。', image: '/yonago-gojo/g2.jpg', icon: <Zap /> },
              { title: '造園・庭づくり', description: '住宅の緑地計画。', icon: <Rocket /> },
              { title: 'メンテナンス', description: '施工後の定期点検と保守。', icon: <ShieldCheck /> },
            ]}
          />
        </div>
      </Block>

      <Block id="case-study-grid" name="CaseStudyGrid" note="実績/事例。category・result・画像付きカード。">
        <div className="p-6">
          <CaseStudyGrid
            items={[
              { title: '戸建て外構フルリノベ', description: '築20年の外構を一新。', category: '外構', result: '工期3週間', image: '/yonago-gojo/g3.jpg' },
              { title: '商業施設の植栽計画', description: 'エントランスの緑地設計。', category: '造園', result: '来訪者+18%', image: '/yonago-gojo/g4.jpg' },
              { title: '駐車場舗装', description: '勾配と排水を考慮した設計。', category: '土木', result: '見積当日対応', image: '/yonago-gojo/g5.jpg' },
            ]}
          />
        </div>
      </Block>

      <Block id="feature-grid" name="FeatureGrid" note="均等な機能/特徴グリッド。columns と card/bare 切替。※ hp.md では『均等カードの連続』を避ける指針あり。">
        <div className="p-6">
          <FeatureGrid
            columns={3}
            items={[
              { icon: <Zap />, title: '速い', description: '最短即日で見積。' },
              { icon: <ShieldCheck />, title: '安心', description: '施工保証付き。' },
              { icon: <Users />, title: '地域密着', description: '地元で15年。' },
            ]}
          />
        </div>
      </Block>

      <Block id="process-timeline" name="ProcessTimeline" note="導入/問い合わせ後の流れ。steps の縦タイムライン。">
        <div className="p-6">
          <ProcessTimeline
            steps={[
              { title: 'お問い合わせ', description: 'フォームまたは電話でご連絡。', meta: 'Day 0' },
              { title: '現地調査・お見積り', description: '現地を確認し無料見積。', meta: 'Day 1-3' },
              { title: 'ご契約・着工', description: '内容にご納得いただいてから着工。', meta: 'Day 7-' },
              { title: '完了・アフター', description: '引き渡し後も定期点検。', meta: 'After' },
            ]}
          />
        </div>
      </Block>

      <Block id="kpi-card" name="KpiCard" note="ダッシュボード用の単一KPI。trend で増減方向と値。">
        <div className="grid grid-cols-1 gap-4 p-6 sm:grid-cols-3">
          <KpiCard label="今月の売上" value="¥4,820,000" icon={<TrendingUp className="h-4 w-4" />} trend={{ value: '+12.4%', direction: 'up', label: '前月比' }} />
          <KpiCard label="新規問い合わせ" value="38件" trend={{ value: '-3', direction: 'down', label: '前週比' }} hint="うち5件が見積依頼" />
          <KpiCard label="稼働率" value="92%" trend={{ value: '横ばい', direction: 'flat' }} />
        </div>
      </Block>

      <Block id="conversion-cta" name="ConversionCta" note="最終CTA帯。主/副ボタン、背景画像対応。">
        <ConversionCta
          eyebrow="まずはご相談ください"
          title="無料見積もりは最短即日"
          description="現地調査・お見積もりは無料です。お気軽にどうぞ。"
          primaryLabel="無料で見積もりを依頼"
          primaryHref="#"
          secondaryLabel="電話で相談"
          secondaryHref="#"
          image="/yonago-gojo/dish-poster.jpg"
        />
      </Block>

      <Block id="faq-section" name="FaqSection" note="FAQ。details/summary のアコーディオン。">
        <div className="p-6">
          <FaqSection
            items={[
              { question: '見積もりは無料ですか？', answer: 'はい、現地調査とお見積もりは無料です。' },
              { question: '対応エリアは？', answer: '米子市を中心に近隣市町村に対応しています。' },
              { question: '支払い方法は？', answer: '現金・銀行振込・各種カードに対応しています。' },
            ]}
          />
        </div>
      </Block>

      <Block id="inquiry-form" name="InquiryForm" note="問い合わせフォーム。loading/error/success 状態あり。scope で送信先を分岐。">
        <div className="p-6">
          <InquiryForm scope="templates-gallery-demo" submitLabel="送信する（デモ）" />
        </div>
      </Block>

      <Block id="location-map" name="LocationMap" note="Google Maps iframe。住所・キャプション・アスペクト比。">
        <div className="p-6">
          <LocationMap
            src="https://maps.google.com/maps?q=%E7%B1%B3%E5%AD%90%E5%B8%82&output=embed"
            address="鳥取県米子市富士見町2丁目8番"
            caption="駐車場あり / 米子駅から車で5分"
            aspectRatio="16/9"
          />
        </div>
      </Block>

      <Block id="section" name="Section" note="セクションの縦リズムと最大幅。width / padding / eyebrow / heading。">
        <Section width="lg" padding="md" eyebrow="SECTION" heading="セクション見出し" description="本文セクションの標準的な縦余白と最大幅を与えるラッパー。">
          <p className="text-neutral-600">ここに本文コンテンツが入る。</p>
        </Section>
      </Block>

      <Block id="page-shell" name="PageShell" note="管理画面/ツールの外枠。タイトル・説明・アクション付きヘッダー。">
        <PageShell width="lg" title="管理ダッシュボード" description="ツール/管理画面の標準的な外枠。" actions={<button className="rounded-md border border-neutral-300 px-3 py-1.5 text-sm">新規作成</button>}>
          <div className="rounded-lg border border-dashed border-neutral-300 p-8 text-center text-neutral-400">コンテンツ領域</div>
        </PageShell>
      </Block>

      <Block id="lp-shell" name="LpShell" note="LP/HP全体の外枠。nav / footer / stickyNav。">
        <LpShell
          nav={<div className="flex items-center justify-between px-6 py-4"><span className="font-semibold">ロゴ</span><span className="text-sm text-neutral-500">ナビ</span></div>}
          footer={<div className="px-6 py-8 text-center text-sm text-neutral-400">© sample footer</div>}
        >
          <div className="px-6 py-16 text-center text-neutral-500">LP本文領域（nav と footer に挟まれる）</div>
        </LpShell>
      </Block>

      <div className="px-6 py-16 sm:px-10">
        <div className="mx-auto max-w-7xl text-sm text-neutral-400">
          ImageSlicePage / ScrollVideo は専用ギャラリー（scroll-video-test）と用途が重なるため省略。
        </div>
      </div>
    </div>
  );
}
