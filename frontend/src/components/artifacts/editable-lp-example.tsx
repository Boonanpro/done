'use client';

import { EditableElement as E, EditableText as T } from '@/components/dan/editable';
import './editable-lp-example.css';

/** A native, responsive LP fixture. Product photographs remain replaceable media;
 * all copy and layout are native elements with release-aware stable identities. */
export function EditableLpExample() {
  return (
    <main className="editable-lp-example">
      <header className="lp-nav">
        <T editId="elp-top-brand" className="lp-brand">moonbox</T>
        <T as="a" editId="elp-top-nav" href="#details">仕組みを見る ↗</T>
      </header>
      <E as="section" editId="elp-top-hero" className="lp-hero">
        <div className="lp-hero-copy">
          <T as="p" editId="elp-top-eyebrow" className="lp-eyebrow">LESS SCOOPING. MORE LIVING.</T>
          <T as="h1" editId="elp-top-title">砂かきの時間を、<br />猫との時間に。</T>
          <T as="p" editId="elp-top-intro" className="lp-intro">くるっと回して、引き出すだけ。<br />毎日のトイレ掃除を、もっとシンプルに。</T>
          <T as="a" editId="elp-top-cta" className="lp-cta" href="#details">新しい掃除のかたちを見る ↗</T>
          <T as="p" editId="elp-top-caption" className="lp-caption">猫のいる暮らしを考えた、回転式トイレ。</T>
        </div>
        <E as="figure" editId="elp-top-visual" className="lp-hero-visual">
          <E as="img" editId="elp-top-photo" src="/editable-lp-example/studio.webp" alt="本体を手で回転させて猫砂をふるい分ける様子" />
          <T as="figcaption" editId="elp-top-photo-caption">A LITTLE TURN. A BETTER EVERYDAY.</T>
        </E>
      </E>
      <E as="section" editId="elp-details-section" id="details" className="lp-details">
        <div className="lp-section-heading">
          <T as="p" editId="elp-details-eyebrow" className="lp-eyebrow">THE SIMPLE ROUTINE</T>
          <T as="h2" editId="elp-details-title">手間を減らす。<br />仕組みは、増やさない。</T>
        </div>
        <div className="lp-steps">
          {[
            ['turn', '01', 'くるっと、回す。', '本体を回して、固まった砂をふるいに通します。'],
            ['separate', '02', '自然に、分かれる。', 'ふるい分けた砂の塊は、下の引き出しへ。'],
            ['empty', '03', 'すっと、捨てる。', '引き出しを取り出して処理。いつもの場所で、いつものお手入れ。'],
          ].map(([key, number, title, copy]) => (
            <E as="article" key={key} editId={`elp-details-${key}`} className="lp-step">
              <T as="p" editId={`elp-details-${key}-number`} className="lp-step-number">{number}</T>
              <T as="h3" editId={`elp-details-${key}-title`}>{title}</T>
              <T as="p" editId={`elp-details-${key}-copy`}>{copy}</T>
            </E>
          ))}
        </div>
      </E>
      <E as="section" editId="elp-design-section" className="lp-design">
        <E as="img" editId="elp-design-photo" src="/editable-lp-example/stainless.webp" alt="ふるいと引き出しの構造を見せた製品写真" loading="lazy" />
        <div>
          <T as="p" editId="elp-design-eyebrow" className="lp-eyebrow">DESIGNED AROUND YOUR EVERYDAY</T>
          <T as="h2" editId="elp-design-title">いつものことを、<br />気持ちよく。</T>
          <T as="p" editId="elp-design-copy" className="lp-intro">毎日使うものだから、仕組みが見えること。<br />掃除の流れが、すっとつながること。</T>
          <T as="a" editId="elp-design-cta" className="lp-cta" href="#details">お手入れの流れを確認する ↗</T>
        </div>
      </E>
      <footer className="lp-footer">
        <T editId="elp-footer-brand" className="lp-brand">moonbox</T>
        <T as="p" editId="elp-footer-note">編集可能なLPの制作検証サンプル・販売ページではありません。</T>
      </footer>
    </main>
  );
}
