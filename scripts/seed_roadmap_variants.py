"""
ポルノブロッカー事業ロードマップの「見比べ用」2案を artifact_documents に投入する。

  python scripts/seed_roadmap_variants.py            # 無ければ作る
  python scripts/seed_roadmap_variants.py --replace  # 本文を初期内容で上書き（ダン編集扱い・通知なし）

  案A（slug: pornblocker-roadmap-a）= 1枚戦略ページ型
      目的と数字 → 現状・問題・打ち手 → 柱4本（商品・集客・LINE・アプリ）→ 節目 → 未解決の問い
      （Lenny Rachitsky の戦略テンプレ ＋ Notion公式 Project brief の型）
  案B（slug: pornblocker-roadmap-b）= 段階ボード型
      一言の概要 → 今／次／いずれ（段階ごとに「終わりの条件」「やること」「決めること」）→ 決めたこと → 未解決の問い
      （Now/Next/Later ＋ Notion公式ローンチ手順書の型）

書き方（2026-09-05 みきさんの指摘）:
  - 文は短く平易に。言い回しで凝らない。理由は判断に要るものだけ1文
  - チェックは「やること」だけ。決まったことには付けない
  - 決める値は黄色い書き込み欄。未定の話は「未解決の問い」に集める
やることの block id は本線（seed_artifact_documents.py）と同じにしてあるので、採用が決まったら
チェック状態をそのまま本線へ写せる。
編集の鍵は本線と同じ値に揃える（同じ端末で3ページとも編集できる）。
"""
from __future__ import annotations

import sys

sys.path.insert(0, "D:\\done")
sys.path.insert(0, "D:\\done\\scripts")

from app.services.artifact_documents_service import ArtifactDocumentsService  # noqa: E402
from seed_artifact_documents import (  # noqa: E402
    OWNER_USER_ID,
    ROOM_ID,
    SLUG as MAIN_SLUG,
    block,
    bullet,
    field,
    h2,
    h3,
    note,
    numbered,
    p,
    todo,
    txt,
)

SLUG_A = "pornblocker-roadmap-a"
SLUG_B = "pornblocker-roadmap-b"
TITLE_A = "ポルノブロッカー事業ロードマップ 案A"
TITLE_B = "ポルノブロッカー事業ロードマップ 案B"


def h2c(text, bid, color):
    """色付きの章見出し（案Bの 今/次/いずれ）。"""
    return block("heading", text, {"level": 2, "textColor": color}, bid=bid)


def h3_success(bid, text="成功の目安"):
    return h3(text, bid, "green")


def h3_decide(bid):
    return h3("決めること", bid, "orange")


def h3_todo(bid):
    return h3("やること", bid, "blue")


def h3_plain(text, bid):
    return h3(text, bid, "default")


def bold_line(label, rest, bid):
    return block("paragraph", [txt(label, bold=True), txt(rest)], bid=bid)


# ---------------------------------------------------------------- やること（本線と同じ id）
def T(key, checked=False):
    text = TODOS[key]
    return todo(text, key, checked)


TODOS = {
    "product-todo-contract": "契約書・秘密保持・特定商取引法の表記を作る",
    "traffic-todo-thumb": "サムネイルを決める",
    "traffic-todo-video1": "1本目の動画を撮って出す",
    "traffic-todo-other": "YouTube以外の入口を1つ試す（X、note、検索で読まれる記事）",
    "magnet-todo-script": "1通目の動画「鍵を妹に預けた話」の台本を書く",
    "magnet-todo-record": "1通目の動画を撮る",
    "magnet-todo-quiz": "抜け道診断を作る（ダン）",
    "sa-todo-line": "この事業用のLINE公式アカウントを作る（ダン）",
    "sa-todo-survey": "登録直後のアンケート「iPhoneかAndroidか」を設定する",
    "sa-todo-messages": "モニター募集の6通を書く",
    "sa-todo-form": "申込フォームを作る（何年悩んだか／試したこと／なぜ今か）",
    "sa-todo-recruit": "モニター3名を集める",
    "sb-todo-scenario": "実績3件が揃ったら、7日間の配信を書く",
    "sb-todo-iphone-notice": "iPhone版ができたら、順番待ちの人に案内する",
    "app-todo-silence": "【最優先】24時間音沙汰のないスマホを運営に知らせる（機種変・電源オフ・削除に気づくため）",
    "app-todo-securefolder": "セキュアフォルダの検知を「守りが立っているか」の判定に入れる",
    "app-todo-proxy": "iPhone向け「うちのサイト経由でXを見る」方式を、捨てアカウントで試す",
    "app-todo-fp": "誤検知を減らす（今は普通の投稿の3.5％が巻き添え）",
    "app-todo-manual": "客のスマホを設定する手順書を作る",
    "app-todo-admin": "複数人を管理する画面を作る（5人を超えたら）",
}


# ================================================================ 案A: 1枚戦略ページ型
def build_a() -> list[dict]:
    b: list[dict] = []
    b += [p("ポルノ中毒から抜け出す伴走プログラムを売る事業の計画。上から順に読めば全体が分かる。", "a-lead")]

    # 目的と数字
    b += [
        h2("目的と数字", "a-goal-h2"),
        bold_line("目的　", "ポルノをやめたい人に、意志に頼らずにやめられる方法を届ける。", "a-goal-purpose"),
        bold_line("一番大事な数字　", "3ヶ月やめ続けた人の数。", "a-goal-metric"),
        note("売上より先にこれを見る。これが増えれば体験談が増え、売上は後からついてくる。", "a-goal-note"),
        h3_decide("a-goal-decide-h3"),
        field("3ヶ月やめ続けた人の目標（1年で何人）", bid="a-goal-field-people"),
        field("年商目標", bid="a-goal-field-revenue"),
        field("達成の期限", bid="a-goal-field-deadline"),
    ]

    # 現状・問題・打ち手
    b += [
        h2("現状・問題・打ち手", "a-sit-h2"),
        bold_line("現状　", "Android版のアプリは動いている。みきさん本人はこれでやめられた。客はまだいない。", "a-sit-now"),
        bold_line("問題　", "意志や知識では続かない。市販のブロックアプリは自分で消せるので効かない。", "a-sit-problem"),
        bold_line("打ち手　", "相手のスマホをこちらで設定し、解除の鍵を運営が持つ。3ヶ月伴走する。", "a-sit-solution"),
    ]

    # 柱1 商品
    b += [
        h2("柱1　商品", "a-p1-h2"),
        p("インターネットポルノ中毒から脱却する、3ヶ月の伴走プログラム。", "a-p1-lead"),
        h3_plain("サービス内容", "a-p1-service-h3"),
        bullet("期間は3ヶ月", "a-p1-s1"),
        bullet("相手のスマホにブロックを設定する。抜け道を1つずつ塞ぐ", "a-p1-s2"),
        bullet("解除の鍵は運営が持つ。本人は解除できない", "a-p1-s3"),
        bullet("週1回、本人から報告をもらい、返事をする", "a-p1-s4"),
        bullet("SNSやゲームなど、他の依存にも対応する（期間中2つまで）", "a-p1-s5"),
        h3_plain("価格", "a-p1-price-h3"),
        bullet("モニター3名は3万円（体験談と引き換え）", "a-p1-pr1"),
        bullet("次の5名は5万円", "a-p1-pr2"),
        bullet("それ以降は10万円", "a-p1-pr3"),
        h3_success("a-p1-success-h3"),
        bullet("3ヶ月完走して戻らなかった人が3人。返金ゼロ", "a-p1-suc1"),
        h3_todo("a-p1-todo-h3"),
        T("product-todo-contract"),
    ]

    # 柱2 集客
    b += [
        h2("柱2　集客（YouTube）", "a-p2-h2"),
        p("YouTubeで体験談を出して、LINEに登録してもらう。", "a-p2-lead"),
        h3_plain("動画で話す順番", "a-p2-order-h3"),
        numbered("意志ではやめられなかった", "a-p2-o1"),
        numbered("市販のアプリは自分で消せた", "a-p2-o2"),
        numbered("自作した", "a-p2-o3"),
        numbered("鍵を人に預けた", "a-p2-o4"),
        numbered("やめられた", "a-p2-o5"),
        note("アプリは「商品」ではなく「道具の1つ」として話す。同じジャンルは登録者2万人でも1本1,000〜2,000回。伸びにくい前提で組む。", "a-p2-note"),
        h3_success("a-p2-success-h3"),
        field("LINE登録の目標（月何人）", bid="a-p2-field-subs"),
        h3_decide("a-p2-decide-h3"),
        field("投稿の頻度（週何本）", bid="a-p2-field-freq"),
        h3_todo("a-p2-todo-h3"),
        T("traffic-todo-thumb"),
        T("traffic-todo-video1"),
        T("traffic-todo-other"),
    ]

    # 柱3 LINE
    b += [
        h2("柱3　LINE（プレゼントと流れ）", "a-p3-h2"),
        p("登録した人にプレゼントを順番に渡し、申込までつなぐ。", "a-p3-lead"),
        h3_plain("プレゼント", "a-p3-gift-h3"),
        bullet("1通目は解説動画「鍵を妹に預けた話」。YouTubeではアプリを作ったところまで話し、続きをLINEで渡す", "a-p3-g1"),
        bullet("2通目以降の候補：抜け道診断（10問）／自分で設定する完全マニュアル／実演動画「市販アプリを全部すり抜けてみた」／依存度チェック／再発しやすい場面の一覧／パートナー向け「責めずに助ける方法」", "a-p3-g2"),
        h3_plain("流れA　モニター3名を集める時", "a-p3-fa-h3"),
        bullet("登録直後にアンケート1問「iPhoneかAndroidか」。iPhoneの人は順番待ちに入れ、今は売らない", "a-p3-fa0"),
        note("iPhoneではXの中を止められず、破られても気づけないため。", "a-p3-fa-note"),
        numbered("プレゼント（鍵を人に預けた話の動画）", "a-p3-fa1"),
        numbered("抜け道診断", "a-p3-fa2"),
        numbered("みきさんの体験談（3年間・ED・何を試して駄目だったか）", "a-p3-fa3"),
        numbered("モニター募集（3名・審査あり・3万円・今月中）", "a-p3-fa4"),
        numbered("申込フォーム", "a-p3-fa5"),
        numbered("締切の連絡", "a-p3-fa6"),
        h3_plain("流れB　実績ができた後", "a-p3-fb-h3"),
        bullet("登録した日を1日目として、全員に同じ7日間を送る", "a-p3-fb0"),
        bullet("1日目 プレゼント／2日目 体験談／3日目 なぜ意志では無理か／4日目 モニターの声／5日目 案内（10万円）／6日目 質問への回答／7日目 締切", "a-p3-fb1"),
        h3_success("a-p3-success-h3"),
        bullet("登録した人の1〜5％が申し込む", "a-p3-suc1"),
        h3_decide("a-p3-decide-h3"),
        field("モニターを落とす基準", bid="a-p3-field-screen"),
        field("申込後に面談するか（ZoomかLINE通話）", bid="a-p3-field-interview"),
        field("実績後に月何人受けるか（目安10人）", bid="a-p3-field-monthly"),
        h3_todo("a-p3-todo-h3"),
        T("magnet-todo-script"),
        T("magnet-todo-record"),
        T("magnet-todo-quiz"),
        T("sa-todo-line"),
        T("sa-todo-survey"),
        T("sa-todo-messages"),
        T("sa-todo-form"),
        T("sa-todo-recruit"),
        T("sb-todo-scenario"),
        T("sb-todo-iphone-notice"),
    ]

    # 柱4 アプリ
    b += [
        h2("柱4　アプリ", "a-p4-h2"),
        p("Android版を客に使える形にし、iPhone版を後から作る。", "a-p4-lead"),
        h3_plain("いま分かっていること", "a-p4-known-h3"),
        bullet("Android版はXの中の画像を出す前に判定して捨てる。一瞬も映らない", "a-p4-k1"),
        bullet("iPhone版も同じ方式で作れる。作れないのは「Xを開いた瞬間の差し替え」だけで、スクリーンタイムで代わりにする", "a-p4-k2"),
        note("iPhone版の費用はMac 9〜12万円＋実機3〜5万円＋登録料 年1.5万円。審査の期間は読めないので、客に期限は約束しない。", "a-p4-note"),
        h3_success("a-p4-success-h3"),
        bullet("客のスマホで、破られたら24時間以内に運営が気づける", "a-p4-suc1"),
        h3_decide("a-p4-decide-h3"),
        field("iPhone版にいつ着手するか", bid="a-p4-field-iphone"),
        field("アプリ単体をストアに出すか", bid="a-p4-field-store"),
        h3_todo("a-p4-todo-h3"),
        T("app-todo-silence"),
        T("app-todo-securefolder"),
        T("app-todo-proxy"),
        T("app-todo-fp"),
        T("app-todo-manual"),
        T("app-todo-admin"),
    ]

    # 節目
    b += [
        h2("節目", "a-ms-h2"),
        p("いまは第0段階。", "a-ms-lead"),
        numbered("第0段階　モニター3名（3万円・審査あり）。体験談を3件もらう", "a-ms-0"),
        numbered("第1段階　3ヶ月伴走して、実績を作る", "a-ms-1"),
        numbered("第2段階　10万円で募集を始める", "a-ms-2"),
        numbered("第3段階　LINEの流れを自動にして、月10人受ける", "a-ms-3"),
        numbered("第4段階　アプリ単体を月500〜1,000円で出す", "a-ms-4"),
    ]

    # 未解決の問い
    b += [
        h2("未解決の問い", "a-open-h2"),
        p("決まったら、上の該当する柱に移す。", "a-open-lead"),
        field("えるさんの200万円をどうするか", bid="a-open-field-eru"),
        note("ダンの意見：今は払わない。「リストができてから改めてお願いしたい」と返す。", "a-open-note-1"),
        field("「1〜2ヶ月で完成しなければ全額返金」で先に入金してもらうか", bid="a-open-field-prepay"),
        note("ダンは反対。審査の期間は自分では早められないので、守れない約束になる。", "a-open-note-2"),
        field("機種変の事前申告を契約に入れるか", bid="a-open-field-device"),
        field("買わなかった人に長期の配信を続けるか", bid="a-open-field-longterm"),
        field("海外展開（動画を翻訳してDiscordで集める）をいつ考えるか", bid="a-open-field-overseas"),
    ]
    return b


# ================================================================ 案B: 段階ボード型
def build_b() -> list[dict]:
    b: list[dict] = []
    b += [
        p("ポルノをやめたい人のスマホをこちらで設定し、3ヶ月伴走する。モニター3万円、その後10万円。YouTubeからLINEに集める。", "b-lead"),
        p("いまは「今」の段階。上から順に終わらせる。", "b-lead2"),
    ]

    # 今
    b += [
        h2c("今　モニター3名を集める", "b-now-h2", "blue"),
        h3_success("b-now-done-h3", "終わりの条件"),
        bullet("3人が申し込み、3ヶ月の伴走が始まっている", "b-now-d1"),
        bullet("契約書とスマホの設定手順が揃っている", "b-now-d2"),
        h3_todo("b-now-todo-h3"),
        T("product-todo-contract"),
        T("app-todo-manual"),
        T("app-todo-silence"),
        T("sa-todo-line"),
        T("sa-todo-survey"),
        T("magnet-todo-script"),
        T("magnet-todo-record"),
        T("magnet-todo-quiz"),
        T("traffic-todo-thumb"),
        T("traffic-todo-video1"),
        T("sa-todo-messages"),
        T("sa-todo-form"),
        T("sa-todo-recruit"),
        h3_decide("b-now-decide-h3"),
        field("モニターを落とす基準", bid="b-now-field-screen"),
        field("申込後に面談するか（ZoomかLINE通話）", bid="b-now-field-interview"),
        field("投稿の頻度（週何本）", bid="b-now-field-freq"),
        note("iPhoneの人は順番待ちに入れ、今は売らない。Xの中を止められず、破られても気づけないため。", "b-now-note"),
    ]

    # 次
    b += [
        h2c("次　3ヶ月伴走して実績を作る", "b-next1-h2", "purple"),
        h3_success("b-next1-done-h3", "終わりの条件"),
        bullet("3人が完走。体験談を3件もらえた。返金ゼロ", "b-next1-d1"),
        h3_todo("b-next1-todo-h3"),
        T("app-todo-securefolder"),
        T("app-todo-fp"),
        T("app-todo-proxy"),
        T("traffic-todo-other"),
        h2c("次　10万円で募集を始める", "b-next2-h2", "purple"),
        h3_success("b-next2-done-h3", "終わりの条件"),
        bullet("10万円で最初の1人が申し込む", "b-next2-d1"),
        bullet("7日間のLINE配信が自動で流れている", "b-next2-d2"),
        h3_todo("b-next2-todo-h3"),
        T("sb-todo-scenario"),
        h3_decide("b-next2-decide-h3"),
        field("月に何人受けるか（目安10人）", bid="b-next2-field-monthly"),
        note("買う人の目安は、登録した人の1〜5％。", "b-next2-note"),
    ]

    # いずれ
    b += [
        h2c("いずれ　自動化・iPhone版・アプリ単体", "b-later-h2", "gray"),
        h3_success("b-later-done-h3", "終わりの条件"),
        bullet("月10人が自動で回る", "b-later-d1"),
        bullet("iPhoneの順番待ちに案内できる", "b-later-d2"),
        bullet("アプリ単体を月500〜1,000円で出す", "b-later-d3"),
        h3_todo("b-later-todo-h3"),
        T("app-todo-admin"),
        T("sb-todo-iphone-notice"),
        h3_decide("b-later-decide-h3"),
        field("iPhone版にいつ着手するか", bid="b-later-field-iphone"),
        field("アプリ単体をストアに出すか", bid="b-later-field-store"),
        note("iPhone版の費用はMac 9〜12万円＋実機3〜5万円＋登録料 年1.5万円。審査の期間は読めないので、客に期限は約束しない。", "b-later-note"),
    ]

    # 決めたこと
    b += [
        h2("決めたこと", "b-fixed-h2"),
        h3_plain("商品", "b-fixed-product-h3"),
        bullet("3ヶ月の伴走。スマホをこちらで設定し、解除の鍵は運営が持つ。週1で報告をもらう。他の依存にも2つまで対応", "b-fx-1"),
        bullet("価格：モニター3万円 → 次の5名は5万円 → それ以降10万円", "b-fx-2"),
        h3_plain("集客", "b-fixed-traffic-h3"),
        bullet("YouTubeで話す順番：意志で無理 → 市販アプリは消せた → 自作 → 鍵を預けた → やめられた", "b-fx-3"),
        bullet("アプリは商品ではなく道具として話す", "b-fx-4"),
        h3_plain("LINE", "b-fixed-line-h3"),
        bullet("登録直後にアンケート1問「iPhoneかAndroidか」", "b-fx-5"),
        bullet("1通目は解説動画「鍵を妹に預けた話」", "b-fx-6"),
        bullet("モニター募集の順番：プレゼント → 抜け道診断 → 体験談 → 募集 → 申込フォーム → 締切", "b-fx-7"),
        bullet("実績後は登録日を1日目とする7日間：プレゼント／体験談／なぜ意志では無理か／モニターの声／案内／質問回答／締切", "b-fx-8"),
        h3_plain("アプリ", "b-fixed-app-h3"),
        bullet("Android版は画像を出す前に判定して捨てる方式。iPhone版も同じ方式で作れる", "b-fx-9"),
    ]

    # 未解決の問い
    b += [
        h2("未解決の問い", "b-open-h2"),
        p("決まったら「決めたこと」か、該当する段階に移す。", "b-open-lead"),
        field("年商目標", bid="b-open-field-revenue"),
        field("年間の受講人数", bid="b-open-field-people"),
        field("達成の期限", bid="b-open-field-deadline"),
        field("えるさんの200万円をどうするか", bid="b-open-field-eru"),
        note("ダンの意見：今は払わない。「リストができてから改めてお願いしたい」と返す。", "b-open-note-1"),
        field("「1〜2ヶ月で完成しなければ全額返金」で先に入金してもらうか", bid="b-open-field-prepay"),
        note("ダンは反対。審査の期間は自分では早められないので、守れない約束になる。", "b-open-note-2"),
        field("機種変の事前申告を契約に入れるか", bid="b-open-field-device"),
        field("買わなかった人に長期の配信を続けるか", bid="b-open-field-longterm"),
        field("海外展開（動画を翻訳してDiscordで集める）をいつ考えるか", bid="b-open-field-overseas"),
    ]
    return b


def _check_ids(blocks, label):
    ids = [x["id"] for x in blocks]
    dup = {i for i in ids if ids.count(i) > 1}
    assert not dup, "%s: block id が重複: %s" % (label, dup)
    todos = {x["id"] for x in blocks if x["type"] == "checkListItem"}
    missing = set(TODOS) - todos
    assert not missing, "%s: やることが漏れている: %s" % (label, missing)


def seed(replace: bool = False) -> None:
    svc = ArtifactDocumentsService()
    main_row = svc.get_row(MAIN_SLUG)
    main_key = (main_row or {}).get("edit_key")
    for slug, title, builder in ((SLUG_A, TITLE_A, build_a), (SLUG_B, TITLE_B, build_b)):
        blocks = builder()
        _check_ids(blocks, slug)
        row = svc.ensure(slug, title=title, blocks=blocks, room_id=ROOM_ID, owner_user_id=OWNER_USER_ID, replace=replace)
        if main_key and row.get("edit_key") != main_key:
            svc.supabase.table("artifact_documents").update({"edit_key": main_key}).eq("id", row["id"]).execute()
        todos = [x for x in blocks if x["type"] == "checkListItem"]
        print("slug=%s version=%s blocks=%d todos=%d key_synced=%s" % (slug, row.get("version"), len(blocks), len(todos), bool(main_key)))


if __name__ == "__main__":
    seed(replace="--replace" in sys.argv)
