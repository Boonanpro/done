"""2026-11-21 本人「サムネは動画とセット」「修正のたびにサムネが増えている」の片付け（1回きり）。

本体の部屋 dc33f0c1 のサムネの作品を、ひと組の動画の作品につなぎ、増えてしまった控えは消さずに隠す。
  python scripts/pair_thumbnails_with_videos.py          何をどうするかの一覧だけ
  python scripts/pair_thumbnails_with_videos.py --apply  つなぐ・隠す（作品は1つも消さない。戻すのは thumb.py attach）
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOM = 'dc33f0c1-d8f1-4786-88a9-564efc407fed'
SUYA1 = '701dc607'          # スヤさん1本目 粗編集
YOUTUBE = '2306835d'        # 中村さん YouTube「今までありがとう。」（11/21撮影）
DOC_YOUTUBE = '1xxfzb0_99_KNNwWZHSjp9eu8LxIqDg3iw-AO367jNAc'
DOC_LAUNCH2 = '1YrEXisxuge_SOmcFNJ_7ecPjTxGQSVwOice25RYBfbA'

ATTACH = [  # (サムネ, 動画, 何枚目)
    ('086487df', SUYA1, 0),
    ('198d9530', YOUTUBE, 0), ('3f193573', YOUTUBE, 1), ('7b257217', YOUTUBE, 2),   # 台本の上の3案（A・B・C）
]
ARCHIVE = [  # 試しの案と、開き直した時に作り直された1枚絵（どれも台本の絵にはつながっていない）
    ('d52b71ac', YOUTUBE), ('48160d72', YOUTUBE), ('ccfbed90', YOUTUBE), ('b9860542', YOUTUBE),
    ('8d8fc759', YOUTUBE), ('f190efd3', YOUTUBE), ('ef881565', YOUTUBE), ('abab7eca', YOUTUBE),
    ('d592e04d', YOUTUBE), ('e71bcc2d', YOUTUBE),
    ('56000e89', None),     # 【試し・消してよい】サムネと会話の試験
]


def main() -> None:
    from app.api import production_asset_routes as par
    from app.services import thumbnail_doc as td
    from app.services.timeline_draft import ContentsLock
    apply = '--apply' in sys.argv
    rows = par._read_contents(ROOM)
    full = {c['id'][:8]: c for c in rows}
    title = lambda k: full[k]['title'] if k in full else '（無い）'
    # 台本の動画を決める（ローンチ2本目は撮影前なので、空の動画の作品を作る）
    if apply:
        with ContentsLock(ROOM):
            rows = par._read_contents(ROOM)
            for c in rows:
                if c['id'].startswith(YOUTUBE):
                    c['script_doc'] = DOC_YOUTUBE
            par._write_contents(ROOM, rows)
        launch2 = td.video_for_doc(ROOM, DOC_LAUNCH2, '中村さん ローンチ2本目（合格者向け）')
        ATTACH.append(('0ee7635e', launch2[:8], 0))
        full = {c['id'][:8]: c for c in par._read_contents(ROOM)}
    else:
        ATTACH.append(('0ee7635e', '（新しく作る「中村さん ローンチ2本目（合格者向け）」）', 0))
    for t, v, k in ATTACH:
        print(f"つなぐ: {title(t)}  →  {title(v) if v in full else v}  {k + 1}枚目")
        if apply:
            td.attach(ROOM, full[t]['id'], full[v]['id'], order=k)
    for t, v in ARCHIVE:
        print(f"隠す:   {title(t)}")
        if apply and t in full:
            td.archive(ROOM, full[t]['id'], full[v]['id'] if v else None)
    left = [c for c in par._read_contents(ROOM) if td.is_thumbnail(c) and not c.get('video_id') and not c.get('archived')]
    print('一覧に残るサムネ:', [c['title'] for c in left] or 'なし')


if __name__ == '__main__':
    main()
