'use client';

import {
  BodyCopy,
  BrushStroke,
  EditorialButton,
  EditorialFrame,
  HandRule,
  HeroCopy,
  InkCircle,
  InfoStrip,
  LeadCopy,
  MetaLabel,
  PhotoCaption,
  RoundelBadge,
  RuleDivider,
  SealMark,
  SectionKicker,
  SectionTitle,
  VerticalHeroCopy,
} from '@/components/templates';

type Status = 'usable' | 'review' | 'risky';

const statusText: Record<Status, string> = {
  usable: '採用可',
  review: '要確認',
  risky: '危険',
};

function DemoBlock({
  id,
  title,
  status,
  notes,
  children,
}: {
  id: string;
  title: string;
  status: Status;
  notes: string;
  children: React.ReactNode;
}) {
  const statusClass = {
    usable: 'border-emerald-700/30 bg-emerald-900/10 text-emerald-900',
    review: 'border-amber-700/30 bg-amber-900/10 text-amber-900',
    risky: 'border-red-700/30 bg-red-900/10 text-red-900',
  }[status];

  return (
    <section id={id} className="border-t border-[#d7c9b5] px-6 py-24 sm:px-10">
      <div className="mx-auto max-w-6xl">
        <div className="mb-10 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="mb-3 font-mono text-xs uppercase tracking-[0.18em] text-[#9a6b28]">
              components/templates
            </div>
            <h2 className="text-3xl font-medium tracking-normal text-[#1d1510] sm:text-5xl">
              {title}
            </h2>
          </div>
          <div className={`w-fit border px-3 py-1.5 text-xs tracking-[0.14em] ${statusClass}`}>
            {statusText[status]}
          </div>
        </div>
        <p className="mb-10 max-w-2xl text-sm leading-7 text-[#6b5a45]">{notes}</p>
        {children}
      </div>
    </section>
  );
}

function Comparison() {
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <div className="border border-[#d7c9b5] bg-white/45 p-7">
        <div className="mb-6 font-mono text-xs uppercase tracking-[0.14em] text-[#9a6b28]">
          raw classes
        </div>
        <h3 className="text-5xl font-bold tracking-wide text-[#1d1510]">
          おばんざいと、ご縁の集まる夜。
        </h3>
        <p className="mt-5 text-base leading-relaxed text-[#6b5a45]">
          文字は大きくなっていますが、日本語の字間と太さが強く、店の空気よりもテンプレ感が前に出ます。
        </p>
      </div>
      <div className="border border-[#d7c9b5] bg-white/45 p-7">
        <div className="mb-6 font-mono text-xs uppercase tracking-[0.14em] text-[#9a6b28]">
          typography components
        </div>
        <HeroCopy className="text-[#1d1510] sm:text-[clamp(3rem,5vw,5.2rem)]">
          おばんざいと、ご縁の集まる夜。
        </HeroCopy>
        <LeadCopy className="mt-6 text-[#5d4e3d]">
          文字の強さを少し抑え、行間と字間で余白を作ります。フォントそのものより、組み方の差を見るための比較です。
        </LeadCopy>
      </div>
    </div>
  );
}

export default function TypographyComponentsScratchPage() {
  return (
    <main className="h-screen overflow-y-auto bg-[#f2eadc] text-[#1d1510]">
      <section className="px-6 py-20 sm:px-10">
        <div className="mx-auto max-w-6xl">
          <div className="max-w-3xl">
            <div className="mb-8 flex flex-wrap gap-3 text-sm text-[#6b5a45]">
              <a href="/scratch/motion-components" className="border border-[#d7c9b5] px-4 py-2 hover:border-[#9a6b28]">
                モーション
              </a>
              <a href="/scratch/typography-components" className="border border-[#9a6b28] px-4 py-2 text-[#1d1510]">
                文字組み
              </a>
            </div>
            <div className="mb-5 font-mono text-xs uppercase tracking-[0.22em] text-[#9a6b28]">
              Scratch / Typography Components
            </div>
            <h1 className="max-w-4xl text-5xl font-medium leading-[1.04] tracking-normal sm:text-7xl">
              <span className="block">文字組み・編集部品</span>
              <span className="block">カタログ</span>
            </h1>
            <p className="mt-7 max-w-2xl text-base leading-8 text-[#6b5a45]">
              typography と editorial accents を実画面で確認するためのページです。
              どの部品が自然に品質を上げるか、どれが危険かを見えるようにします。
            </p>
          </div>
          <div className="mt-10 grid gap-2 text-sm text-[#6b5a45] sm:grid-cols-4">
            {[
              ['比較', 'comparison'],
              ['HeroCopy', 'hero-copy'],
              ['VerticalHeroCopy', 'vertical-hero-copy'],
              ['Section Parts', 'section-parts'],
              ['EditorialButton', 'editorial-button'],
              ['RoundelBadge', 'roundel-badge'],
              ['InfoStrip', 'info-strip'],
              ['Risky Accents', 'risky-accents'],
            ].map(([label, id]) => (
              <a key={id} href={`#${id}`} className="border border-[#d7c9b5] px-4 py-3 hover:border-[#9a6b28]">
                {label}
              </a>
            ))}
          </div>
        </div>
      </section>

      <DemoBlock
        id="comparison"
        title="素の指定との比較"
        status="usable"
        notes="このページの typography 部品はフォントそのものを変える部品ではありません。文字サイズ、行間、字間、太さの基準を揃えるための部品です。"
      >
        <Comparison />
      </DemoBlock>

      <DemoBlock
        id="hero-copy"
        title="HeroCopy"
        status="usable"
        notes="横組みのヒーロー見出しです。大きく見せつつ、太字と過剰な字間に頼らないための基準です。"
      >
        <div className="border border-[#d7c9b5] bg-white/45 p-8">
          <SectionKicker className="text-[#9a6b28]">hero copy</SectionKicker>
          <HeroCopy className="mt-5 max-w-4xl text-[#1d1510]">
            旬の料理と、静かな時間。
          </HeroCopy>
          <LeadCopy className="mt-7 text-[#5d4e3d]">
            強いコピーでも、太さを上げすぎず余白で見せます。飲食店、宿、ブランドサイト向け。
          </LeadCopy>
        </div>
      </DemoBlock>

      <DemoBlock
        id="vertical-hero-copy"
        title="VerticalHeroCopy"
        status="review"
        notes="縦書きのヒーロー見出しです。和食、宿、工芸には合いますが、使いすぎると和風テンプレ化します。"
      >
        <div className="flex min-h-[520px] items-center justify-center border border-[#d7c9b5] bg-[#18120d] p-8 text-white">
          <VerticalHeroCopy className="h-[390px] text-white">
            今日もほっと一息。
          </VerticalHeroCopy>
        </div>
      </DemoBlock>

      <DemoBlock
        id="section-parts"
        title="SectionKicker / SectionTitle / LeadCopy / BodyCopy / MetaLabel"
        status="usable"
        notes="セクション見出しと本文の基本セットです。Dan が raw な text-5xl/font-bold/tracking-wide に逃げるのを減らすための部品です。"
      >
        <div className="grid gap-8 lg:grid-cols-[0.7fr_1.3fr]">
          <div className="border border-[#d7c9b5] bg-white/45 p-7">
            <SectionKicker className="text-[#9a6b28]">about</SectionKicker>
            <SectionTitle className="mt-4 text-[#1d1510]">五条について</SectionTitle>
            <LeadCopy className="mt-6 text-[#4f4335]">
              旬の食材を、やさしいおばんざいに。お酒と会話がすすむ、あたたかな場所。
            </LeadCopy>
          </div>
          <div className="border border-[#d7c9b5] bg-white/45 p-7">
            <MetaLabel className="text-[#9a6b28]">body copy</MetaLabel>
            <BodyCopy className="mt-5 text-[#5d4e3d]">
              本文は見出しよりも静かに、読みやすさを優先します。日本語の本文で過剰な字間を使うと素人感が出やすいため、行間と余白で整えます。
            </BodyCopy>
            <BodyCopy className="mt-4 text-[#5d4e3d]">
              長い説明は詰め込まず、段落の間隔を持たせます。サイト全体の上品さは、派手な装飾よりもこの密度調整で決まることが多いです。
            </BodyCopy>
          </div>
        </div>
      </DemoBlock>

      <DemoBlock
        id="editorial-button"
        title="EditorialButton"
        status="usable"
        notes="角丸の大きなCTAに頼らず、余白と罫線で上品に見せるボタンです。強いCV導線には別の設計が必要です。"
      >
        <div className="flex flex-wrap gap-4 border border-[#d7c9b5] bg-white/45 p-7">
          <EditorialButton href="#" className="border-[#9a6b28] text-[#1d1510]">
            詳しく見る
          </EditorialButton>
          <EditorialButton href="#" variant="solid" className="border-[#9a6b28] bg-[#9a6b28] text-white">
            予約する
          </EditorialButton>
          <EditorialButton href="#" variant="ghost" className="text-[#1d1510]">
            Instagramを見る
          </EditorialButton>
        </div>
      </DemoBlock>

      <DemoBlock
        id="roundel-badge"
        title="RoundelBadge / SealMark / RuleDivider"
        status="usable"
        notes="丸型バッジ、印、罫線です。距離、限定性、小さな補足情報に使うと自然です。主役にしすぎると装飾過多になります。"
      >
        <div className="grid gap-8 lg:grid-cols-3">
          <div className="flex items-center justify-center border border-[#d7c9b5] bg-white/45 p-8">
            <RoundelBadge eyebrow="米子駅から" value="徒歩5分" caption="小さな隠れ家空間" className="text-[#1d1510]" />
          </div>
          <div className="border border-[#d7c9b5] bg-white/45 p-8">
            <div className="flex items-center gap-4">
              <SealMark className="text-[#9a6b28]">季</SealMark>
              <div className="text-2xl">季節の一品</div>
            </div>
            <PhotoCaption className="text-[#6b5a45]">
              SealMark は見出しの先頭に小さく使う程度が自然です。
            </PhotoCaption>
          </div>
          <div className="flex items-center border border-[#d7c9b5] bg-white/45 p-8">
            <RuleDivider label="menu" className="w-full text-[#9a6b28]" />
          </div>
        </div>
      </DemoBlock>

      <DemoBlock
        id="info-strip"
        title="InfoStrip / EditorialFrame / PhotoCaption"
        status="usable"
        notes="営業時間、所在地、料金、実績などを整理するための編集部品です。情報の見せ方を揃える目的で使います。"
      >
        <div className="grid gap-8 lg:grid-cols-[1.2fr_0.8fr]">
          <InfoStrip
            className="border-[#d7c9b5] bg-white/45"
            items={[
              { label: '営業時間', value: '18:00 - 24:00' },
              { label: '定休日', value: '日曜' },
              { label: '席数', value: 'カウンター6席' },
            ]}
          />
          <EditorialFrame className="border-[#d7c9b5] bg-white/45 text-[#1d1510]">
            <img src="/yonago-gojo/g2.jpg" alt="" className="aspect-[4/3] w-full object-cover" />
            <PhotoCaption className="text-[#6b5a45]">
              写真キャプションは小さく、説明しすぎない。
            </PhotoCaption>
          </EditorialFrame>
        </div>
      </DemoBlock>

      <DemoBlock
        id="risky-accents"
        title="BrushStroke / InkCircle / HandRule"
        status="risky"
        notes="背景透過事故は避けられますが、造形品質が低いとただの波線や雑な丸に見えます。現状は非推奨。使うなら案件専用に品質確認したSVGへ差し替えるべきです。"
      >
        <div className="grid gap-8 lg:grid-cols-3">
          <div className="border border-[#d7c9b5] bg-white/45 p-8 text-center">
            <BrushStroke className="mx-auto text-[#1d1510]" />
            <div className="mt-6 text-sm text-[#6b5a45]">BrushStroke: 現状は波線に見える</div>
          </div>
          <div className="flex flex-col items-center border border-[#d7c9b5] bg-white/45 p-8">
            <InkCircle className="text-[#9a6b28]" />
            <div className="mt-6 text-sm text-[#6b5a45]">InkCircle: 用途限定。乱用禁止</div>
          </div>
          <div className="border border-[#d7c9b5] bg-white/45 p-8">
            <HandRule className="mt-8 text-[#1d1510]" />
            <div className="mt-6 text-sm text-[#6b5a45]">HandRule: 品質確認なしでは使わない</div>
          </div>
        </div>
      </DemoBlock>
    </main>
  );
}
