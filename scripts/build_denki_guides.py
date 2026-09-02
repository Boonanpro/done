"""電管ナレッジ「テーマ別まとめページ」用の記事データを生成する。

frontend/public/denki-knowledge-index.json（全記事の索引）から、
まとめページのセクションごとに関連記事を抽出し、ページが import できる
スリムな JSON を書き出す。

なぜ index.json を直接読まずに切り出すのか:
  - 索引は 7MB あり、まとめページに必要なのは数十件だけ
  - fs で読むとデプロイ時にファイルが同梱されない事故があるため、
    import できる形（src 配下の JSON）にしておく

使い方:
    python scripts/build_denki_guides.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "frontend" / "public" / "denki-knowledge-index.json"
OUT_DIR = (
    ROOT / "frontend" / "src" / "app" / "artifacts" / "denki-knowledge" / "guides" / "_data"
)

# 1ページ = 1テーマ。セクションごとに拾うキーワードを定義する。
GUIDES: list[dict] = [
    {
        "slug": "nenji-tenken",
        "sections": [
            {
                "key": "dandori",
                "keywords": ["停電", "年次点検", "段取り", "作業手順", "点検計画", "保安規程"],
                "limit": 6,
            },
            {
                "key": "zetsuen",
                "keywords": ["絶縁抵抗", "メガー", "メガ測定", "絶縁測定", "絶縁不良"],
                "limit": 6,
            },
            {
                "key": "relay",
                "keywords": ["継電器", "リレー試験", "OCR", "DGR", "過電流", "地絡方向", "整定"],
                "limit": 6,
            },
            {
                "key": "trans",
                "keywords": ["変圧器", "トランス", "進相コンデンサ", "コンデンサ", "リアクトル"],
                "limit": 6,
            },
            {
                "key": "cable",
                "keywords": ["高圧ケーブル", "ケーブル", "PAS", "UGS", "端末", "気中開閉器"],
                "limit": 6,
            },
            {
                "key": "trouble",
                "keywords": ["焼損", "トラッキング", "波及事故", "不具合", "故障", "漏電", "劣化"],
                "limit": 6,
            },
        ],
    },
    # ここから下は「キーワード自動抽出」ではなく、記事本文を読んだうえで
    # 1本ずつ選び、推薦理由（why）を添えた手選びのテーマ。
    # 自動抽出だと「言葉が一致しただけの記事」が混ざり、"おすすめに値するか"を
    # 保証できないため、読み物として出すページはこちらの方式で作る。
    {
        "slug": "haikyu-jiko",
        "sections": [
            {
                "key": "what",
                "picks": [
                    (2039, "定義、報告義務、原因の内訳まで一枚で押さえられる。最初に読むならここから。"),
                    (2045, "事故のとき電力会社側で何が起きているか。自分の設備の外側を知る回。"),
                    (3447, "実際に起きた一日の記録。時刻順に判断が並んでいるので、流れがそのまま追える。"),
                ],
            },
            {
                "key": "boundary",
                "picks": [
                    (2147, "銘板の読み方から事故事例まで。PASを一つ理解するならこの記事。"),
                    (2030, "責任の境界が普通と違う地域がある。自分の担当がどちらか確認する材料。"),
                    (2179, "地中引込の現場はPASではなくUGS。違いを一度整理しておきたい。"),
                    (3516, "現役技術者からの質問に、根拠を示して答えている。判断の筋道が読める。"),
                ],
            },
            {
                "key": "yocho",
                "picks": [
                    (2869, "事故は突然ではない。まず予兆の名前を知っておく。"),
                    (2165, "予兆を記録できる装置。導入して意味があるかまで書かれている。"),
                    (2901, "点検と点検の間を埋める装置。仕組みと設置基準。"),
                    (1063, "朝7時の通報から原因特定まで。装置が実際に何を知らせてくるかが分かる。"),
                    (173, "付けただけでは意味がない。試験して初めて見つかった動作値不良の記録。"),
                ],
            },
            {
                "key": "rekka",
                "picks": [
                    (2872, "ケーブルの中で何年もかけて進む劣化。目視では分からない相手の正体。"),
                    (3171, "雷の一撃で何がどの順に壊れるか。現場の状況が順を追って書かれている。"),
                    (1275, "夜20時の停電メールから翌朝の調査まで。実際の出動記録。"),
                    (2168, "雷への備えは地域で違う。内蔵LAが推奨されない地域もある。"),
                ],
            },
            {
                "key": "jibun",
                "picks": [
                    (2177, "判断ミスがそのまま波及事故になった例。測定電圧の選択が結果を分けている。"),
                    (3161, "アースフックの外し忘れ。誰にでも起こりうる手順の抜け。"),
                    (2161, "測定器のリード1本の間違いで受電が落ちる。勘違いの怖さ。"),
                    (2170, "復旧作業そのものが次の事故の種になる。写真を撮る習慣の理由がここにある。"),
                    (3163, "「停電しているから安全」が成立しない場面。低圧側から高圧が現れる。"),
                    (2164, "自分のせいではない開放もある。切り分けのための材料。"),
                ],
            },
            {
                "key": "shiken",
                "picks": [
                    (2083, "整定が上位と協調していなければ、試験に合格していても波及は防げない。核心の記事。"),
                    (2096, "「どこまでやるか」を3パターンで比較している。自分の基準を決める材料。"),
                    (2169, "動作電流値・動作時間の判定基準。手元に置いておく用。"),
                    (3077, "整定値がどう決められたのか、その根拠になる試験。"),
                    (284, "受電後に可変抵抗で実際に試した記録。試験を自作している人の工夫。"),
                ],
            },
        ],
    },
    {
        "slug": "dokuritsu",
        "sections": [
            {
                "key": "joken",
                "picks": [
                    (1518, "何年やれば、どう証明するのか。独立の最初の関門はここ。"),
                    (1547, "試験に受からなくても道はある。ただし簡単ではない理由まで書いてある。"),
                    (1906, "必要な実務経験が5年から3年に短縮された。制度が変わった今の状況。"),
                    (1519, "技術面の不安に、経験者が結論から答えている。"),
                    (3130, "契約の形の話。知らないと届出でつまずく。"),
                ],
            },
            {
                "key": "okane",
                "picks": [
                    (1506, "工具674,886円、開業費935,162円。実額が書かれている数少ない記事。"),
                    (1522, "「1000万は余裕」の真偽を、点数の仕組みから説明している。"),
                    (1491, "見積りをいくらにするか。相場を知らないと安く受けてしまう。"),
                    (1542, "会社員時代と個人事業時代、両方を経験した人の実額比較。"),
                ],
            },
            {
                "key": "shozoku",
                "picks": [
                    (1510, "協会か保安法人か。ほぼ全員が最初に決める分岐点。"),
                    (3263, "法人にも種類がある。案件紹介と保険だけを請け負う会社もある。"),
                    (1901, "協会の中の人間関係。表に出にくい話が書かれている。"),
                    (3264, "内規の該当箇所まで示してある。兼業を考えるなら先に読む。"),
                ],
            },
            {
                "key": "kokyaku",
                "picks": [
                    (1488, "独立直後の食いつなぎ方。法人から仕事をもらいながら自己物件を増やす。"),
                    (1918, "物件が実際に動く場面。今は物件が不足気味という現状も分かる。"),
                    (3134, "新規参入者向けの入口。地元事業者を優先する条例がある自治体も。"),
                    (3253, "紹介で報酬が動く商習慣。知らないと戸惑う。"),
                    (3257, "中間に入る会社がある案件の構造。手取りがどうなるかの試算。"),
                ],
            },
            {
                "key": "genjitsu",
                "picks": [
                    (1958, "独立1年目に必ず来る。手が付かない感じまで正直に書かれている。"),
                    (1492, "やってみたら意外と、という話。2年目の実務の流れ。"),
                    (79, "マイナポータル連携の落とし穴。毎年更新されている記録。"),
                    (1147, "税理士に任せる場合でも、これだけの書類は自分で揃える。"),
                    (1535, "技術ではなく人間関係で行き詰まった話。独立前に読んでおきたい。"),
                ],
            },
            {
                "key": "kotoba",
                "picks": [
                    (1898, "相談で一番多い質問と、それに対する本音。このテーマの締めに。"),
                    (3254, "躊躇する理由を機材・賠償・収入の3つに分けて整理している。"),
                    (3255, "手順の全体像。何から始めるかを俯瞰する用。"),
                    (1520, "実務経歴証明書だけではない。提出書類の一覧。"),
                ],
            },
        ],
    },
]

MIN_EXCERPT = 30


def norm(s: str) -> str:
    return (s or "").normalize("NFKC").lower() if hasattr(s, "normalize") else (s or "").lower()


def jp_norm(s: str) -> str:
    import unicodedata

    return unicodedata.normalize("NFKC", s or "").lower()


def clean_excerpt(text: str, limit: int = 110) -> str:
    t = re.sub(r"\s+", " ", (text or "")).strip()
    if len(t) <= limit:
        return t
    return t[:limit].rstrip() + "…"


def score(article: dict, keywords: list[str]) -> int:
    title = jp_norm(article.get("title", ""))
    body = jp_norm(article.get("text", ""))
    s = 0
    for kw in keywords:
        k = jp_norm(kw)
        if not k:
            continue
        if k in title:
            s += 5
        if k in body:
            s += 1
    return s


def main() -> None:
    doc = json.loads(INDEX.read_text(encoding="utf-8"))
    articles = doc.get("articles", [])
    source_type = {s["id"]: s.get("type", "") for s in doc.get("sources", [])}

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    by_id = {a["id"]: a for a in articles}

    def to_entry(a: dict, why: str = "") -> dict:
        return {
            "id": a["id"],
            "title": a["title"],
            "url": a["url"],
            "date": a.get("date", ""),
            "source": a["source"],
            "sourceName": a["sourceName"],
            "isVideo": source_type.get(a["source"]) == "youtube",
            "excerpt": clean_excerpt(a.get("excerpt", "")),
            "why": why,
        }

    for guide in GUIDES:
        used: set[int] = set()
        out_sections: list[dict] = []

        for sec in guide["sections"]:
            # 手選びテーマ: 記事IDと推薦理由がそのまま指定されている
            if sec.get("picks"):
                picked = []
                for aid, why in sec["picks"]:
                    a = by_id.get(aid)
                    if a is None:
                        raise SystemExit(
                            f"[{guide['slug']}/{sec['key']}] 記事 id={aid} が索引に見つかりません"
                        )
                    used.add(aid)
                    picked.append(to_entry(a, why))
                out_sections.append({"key": sec["key"], "articles": picked})
                continue

            cands = []
            for a in articles:
                if a["id"] in used:
                    continue
                if len(a.get("excerpt", "")) < MIN_EXCERPT:
                    continue
                sc = score(a, sec["keywords"])
                if sc <= 0:
                    continue
                cands.append((sc, a.get("date", ""), a))

            cands.sort(key=lambda x: (x[0], x[1]), reverse=True)

            # 同じブログばかり並ぶと「横断まとめ」の意味が薄れるため、
            # 1セクション内で同一出典は2件までに抑える。
            # それで枠が埋まらない場合だけ制限を外して補充する。
            per_source_max = 2
            chosen: list[dict] = []
            counts: dict[str, int] = {}
            for _sc, _dt, a in cands:
                if len(chosen) >= sec["limit"]:
                    break
                src = a["source"]
                if counts.get(src, 0) >= per_source_max:
                    continue
                counts[src] = counts.get(src, 0) + 1
                chosen.append(a)
            if len(chosen) < sec["limit"]:
                have = {a["id"] for a in chosen}
                for _sc, _dt, a in cands:
                    if len(chosen) >= sec["limit"]:
                        break
                    if a["id"] not in have:
                        chosen.append(a)

            picked = []
            for a in chosen:
                used.add(a["id"])
                picked.append(to_entry(a))
            out_sections.append({"key": sec["key"], "articles": picked})

        payload = {
            "generatedAt": doc.get("generated_at", ""),
            "totalArticles": doc.get("count", len(articles)),
            "sections": out_sections,
        }
        out = OUT_DIR / f"{guide['slug']}.json"
        out.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        total = sum(len(s["articles"]) for s in out_sections)
        print(f"wrote {out} ({total} articles)")


if __name__ == "__main__":
    main()
