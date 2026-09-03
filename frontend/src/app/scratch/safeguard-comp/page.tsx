/**
 * Safeguard LP（第5版）カンプ確認用ページ。
 * recipes/image-first-lp.md 手順1: カンプ画像を上から順に幅100%で縦に並べただけの
 * 簡易プレビュー。成果物には登録しない試作領域。
 */

const BASE = "/scratch/safeguard-comp";

const COMPS = [
  { file: "comp1.png", alt: "カンプ1/4: EDが治った（ヒーロー）〜昔のEDは中高年のものだった" },
  { file: "comp2.png", alt: "カンプ2/4: 今つらいのは健康な若者〜意志では勝てない" },
  { file: "comp3.png", alt: "カンプ3/4: 仕組みで止める5つの層〜止めないもの・プライバシー" },
  { file: "comp4.png", alt: "カンプ4/4: 実測の数字・料金・受け取り方〜ダウンロード・フッター" },
];

export default function SafeguardCompPreview() {
  return (
    <main style={{ background: "#0b0b0d", margin: 0, minHeight: "100vh" }}>
      {/* PCでは幅100%だとブラウザズームしても窓に再フィットして拡大にならないため、
          スマホ実寸相当の430px中央カラムに固定する。画像クリックで原寸PNGを
          新規タブに開き、ブラウザ標準のズーム/パンで細部を確認できる。 */}
      <div style={{ maxWidth: 430, margin: "0 auto" }}>
        {COMPS.map((c) => (
          <a key={c.file} href={`${BASE}/${c.file}`} target="_blank" rel="noreferrer">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={`${BASE}/${c.file}`}
              alt={c.alt}
              style={{ display: "block", width: "100%", height: "auto" }}
            />
          </a>
        ))}
      </div>
      <p style={{ color: "#888", textAlign: "center", font: "12px sans-serif", padding: 12 }}>
        画像をクリック/タップすると原寸を新規タブで開けます（細部確認用）
      </p>
    </main>
  );
}
