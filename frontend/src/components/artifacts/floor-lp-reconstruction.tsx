'use client';

import { Footprints, VolumeX, Wind } from 'lucide-react';
import { EditableElement as E, EditableText as T } from '@/components/dan/editable';
import './floor-lp-reconstruction.css';

export const FLOOR_ASSETS = '/floor-lp-comparison';
const COMPARISON_ROWS = [
  ['cold', '足が冷たい', '足元から暖まる', Footprints],
  ['dry', '喉と肌が乾く', '風が出ないので乾かない', Wind],
  ['noise', '運転音と風で疲れる', '無音で、無風', VolumeX],
] as const;

/** Same copy, order and visual composition as n1.webp + t2.webp. */
export function FloorLpReconstruction() {
  return (
    <div className="floor-lp">
      <E as="section" editId="floor-hero-section" className="floor-hero">
        <E editId="floor-hero-heading-block" className="floor-hero-heading">
          <T as="p" editId="floor-hero-eyebrow">賃貸でも、工事なしで。</T>
          <T as="h1" editId="floor-hero-title">コンセントで<br />使える床暖房。</T>
        </E>
        <E as="img" editId="floor-hero-photo" className="floor-hero-photo" src={`${FLOOR_ASSETS}/original-hero.webp`} alt="床暖房を敷いた部屋で、素足で在宅ワークをする男性" />
        <E editId="floor-hero-action-block" className="floor-hero-action">
          <T as="p" editId="floor-hero-benefit" className="floor-benefit">足元はあたたかく、頭は涼しい。だから、集中できる。</T>
          <T as="button" type="button" editId="floor-hero-cta" className="floor-cta">無料で先行登録する</T>
          <T as="p" editId="floor-hero-note" className="floor-note">発売のお知らせをメールでお届けします。</T>
        </E>
      </E>
      <E as="section" editId="floor-problem-section" className="floor-problem">
        <E editId="floor-problem-heading-block" className="floor-problem-heading">
          <T as="h2" editId="floor-problem-title">エアコンの暖房、<br />つらくないですか？</T>
        </E>
        <E as="img" editId="floor-problem-photo" className="floor-problem-photo" src={`${FLOOR_ASSETS}/original-problem.webp`} alt="エアコンで頭の周囲だけが暖まり、足元が冷えている女性" />
        <E editId="floor-comparison-block" className="floor-comparison-block">
          <table>
            <thead><tr>
              <th><T editId="floor-table-left-title">エアコン</T></th>
              <th><T editId="floor-table-right-title">コンセントで使える<br />床暖房</T></th>
            </tr></thead>
            <tbody>
              {COMPARISON_ROWS.map(([key, left, right, Icon]) => {
                return <tr key={key}>
                  <td><T editId={`floor-table-${key}-left`}>{left}</T></td>
                  <td><div className="floor-table-answer"><Icon aria-hidden="true" /><T editId={`floor-table-${key}-right`}>{right}</T></div></td>
                </tr>;
              })}
            </tbody>
          </table>
          <T as="p" editId="floor-problem-explanation" className="floor-explanation">つらさの理由は、<br />暖かい空気が上にしかないからです。</T>
        </E>
      </E>
    </div>
  );
}
