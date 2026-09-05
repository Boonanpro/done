"""
ポルノブロッカー事業ロードマップの本文を artifact_documents に投入する。

  python scripts/seed_artifact_documents.py            # 無ければ作る（既にあれば触らない）
  python scripts/seed_artifact_documents.py --replace  # 本文を初期内容で上書きする（ダン編集扱い・通知なし）

方針（2026-09-05 みきさんの指摘）:
  - チェックボックスは「やること」にだけ付ける。決まったことには付けない
  - 未定の補足は関係する場所に「補足」（引用ブロック）として添える
  - 決める必要のある値は、チェックではなく書き込む欄（太字の見出し＋黄色い値）にする
  - 文は短く平易に。理由の補足は判断に要るものだけ、1文で（2026-09-05 みきさん「無駄なこと書くな」）
  - 見出し（h3）に色を持たせる: 緑=決まっていること / オレンジ=決めること / 青=やること
本文は BlockNote のブロック配列。ページ側（Notion 風エディタ）で全文を書き換えられる。
"""
from __future__ import annotations

import sys

sys.path.insert(0, "D:\\done")

from app.services.artifact_documents_service import ArtifactDocumentsService  # noqa: E402

SLUG = "pornblocker-roadmap"
TITLE = "ポルノブロッカー事業ロードマップ"
ROOM_ID = "a588ca6f-95b1-484a-a13d-cf7771ebffb8"
OWNER_USER_ID = "2582a188-ff24-4a4f-b989-6063034d90b2"

_counter = {"n": 0}


def _id(prefix: str) -> str:
    _counter["n"] += 1
    return "%s-%02d" % (prefix, _counter["n"])


def txt(text: str, **styles):
    return {"type": "text", "text": text, "styles": styles}


def block(btype: str, content, props=None, children=None, bid: str | None = None):
    return {
        "id": bid or _id(btype[:2]),
        "type": btype,
        "props": props or {},
        "content": content if isinstance(content, list) else [txt(content)],
        "children": children or [],
    }


# 色分け（h3 の見出しに色を持たせる。ページ側の CSS が色ごとに帯・記号を付ける）
COLOR_DECIDED = "green"   # 決まっていること
COLOR_DECIDE = "orange"   # 決めること（みきさんの判断待ち）
COLOR_TODO = "blue"       # やること（チェック付き）
COLOR_INFO = "default"    # それ以外の見出し（サービス内容・配信の順番・候補）


def h2(text, bid=None):
    return block("heading", text, {"level": 2}, bid=bid)


def h3(text, bid=None, color=COLOR_INFO):
    return block("heading", text, {"level": 3, "textColor": color}, bid=bid)


def h3_decided(bid):
    return h3("決まっていること", bid, COLOR_DECIDED)


def h3_decide(bid):
    return h3("決めること", bid, COLOR_DECIDE)


def h3_todo(bid):
    return h3("やること", bid, COLOR_TODO)


def p(text, bid=None):
    return block("paragraph", text, bid=bid)


def bullet(text, bid=None, children=None):
    return block("bulletListItem", text, bid=bid, children=children)


def numbered(text, bid=None):
    return block("numberedListItem", text, bid=bid)


def todo(text, bid, checked=False):
    return block("checkListItem", text, {"checked": checked}, bid=bid)


def note(text, bid=None):
    """補足。関係する項目の直後に置く。短く書く。"""
    return block("quote", text, bid=bid)


def field(label: str, value: str = "未記入", bid=None):
    """決める必要のある値。太字ラベル＋黄色い書き込み欄。値の部分を書き換えて使う。"""
    return block(
        "paragraph",
        [txt(label + "：", bold=True), txt(value, backgroundColor="yellow")],
        bid=bid,
    )


def build_blocks() -> list[dict]:
    b: list[dict] = []

    b += [
        p("ポルノ中毒から抜け出す伴走プログラムを売る事業の、全体の計画です。", "intro-lead"),
    ]

    # ---------------------------------------------------------- 段階
    b += [
        h2("いまの段階", "stage-h2"),
        p("いまは第0段階。モニター3名を集めるところです。", "stage-now"),
        numbered("第0段階　モニター3名（3万円・審査あり）。体験談を3件もらう", "stage-0"),
        numbered("第1段階　3ヶ月伴走して、実績を作る", "stage-1"),
        numbered("第2段階　10万円で募集を始める", "stage-2"),
        numbered("第3段階　LINEの流れを自動にして、月10人受ける", "stage-3"),
        numbered("第4段階　アプリ単体を月500〜1,000円で出す", "stage-4"),
    ]

    # ---------------------------------------------------------- 01 目標
    b += [
        h2("01 最終的な目標", "goal-h2"),
        p("ポルノをやめたい人に、意志に頼らずにやめられる方法を届ける。それを事業にする。", "goal-lead"),
        h3_decided("goal-decided-h3"),
        bullet("最初は伴走プログラムとして売る", "goal-decided-1"),
        bullet("アプリ単体の販売は、その後", "goal-decided-2"),
        h3_decide("goal-fields-h3"),
        field("年商目標", bid="goal-field-revenue"),
        field("年間の受講人数", bid="goal-field-people"),
        field("達成の期限", bid="goal-field-deadline"),
        note("補足：海外展開（動画を翻訳して、Discordで集める）は、国内で流れができてから考える。", "goal-note-overseas"),
    ]

    # ---------------------------------------------------------- 02 何を売るか
    b += [
        h2("02 何を売るか", "product-h2"),
        p("インターネットポルノ中毒から脱却するプログラム。", "product-lead"),
        h3("サービス内容", "product-service-h3"),
        bullet("期間：3ヶ月", "product-service-1"),
        bullet("相手のスマホにブロックを設定する。抜け道を1つずつ塞ぐ", "product-service-2"),
        bullet("解除の鍵は運営が持つ。本人は解除できない", "product-service-3"),
        bullet("週1回、本人から報告をもらい、返事をする", "product-service-4"),
        bullet("SNSやゲームなど、他の依存にも対応する（期間中2つまで）", "product-service-5"),
        h3_decide("product-decide-h3"),
        bullet("「10万円で一生保証」にするか、「3ヶ月＋その後は月1,000円」にするか", "product-decide-1"),
        note("ダンは後者を推す。一生保証は、売れるほど面倒を見るスマホが増えて、回らなくなる。", "product-note-1"),
        bullet("価格：モニター3万円 → 次の5名は5万円 → それ以降は10万円、でよいか", "product-decide-2"),
        bullet("解除の申請から実行まで、24時間あけるルールを入れるか", "product-decide-3"),
        note("深夜の「今日だけ解除して」を防ぐため。", "product-note-2"),
        field("3ヶ月後の月額", bid="product-field-monthly"),
        field("返金の条件", bid="product-field-refund"),
        field("売り主（法人パイナ／個人）", bid="product-field-seller"),
        field("支払い方法（カード・振込・分割）", bid="product-field-payment"),
        h3_todo("product-todo-h3"),
        todo("契約書・秘密保持・特定商取引法の表記を作る", "product-todo-contract"),
    ]

    # ---------------------------------------------------------- 03 集客
    b += [
        h2("03 どう人を集めるか", "traffic-h2"),
        p("YouTubeで体験談を出して、LINEに登録してもらう。", "traffic-lead"),
        h3_decided("traffic-decided-h3"),
        bullet("動画で話す順番：意志ではやめられなかった → 市販アプリは自分で消せた → 自作した → 鍵を人に預けた → やめられた", "traffic-decided-1"),
        bullet("アプリは「商品」ではなく「道具の1つ」として話す", "traffic-decided-2"),
        note("同じジャンルの実測：登録者2万人でも1本1,000〜2,000回。伸びにくい前提で組む。", "traffic-note-1"),
        h3_decide("traffic-decide-h3"),
        field("投稿の頻度（週何本）", bid="traffic-field-frequency"),
        h3_todo("traffic-todo-h3"),
        todo("サムネイルを決める", "traffic-todo-thumb"),
        todo("1本目の動画を撮って出す", "traffic-todo-video1"),
        todo("YouTube以外の入口を1つ試す（X、note、検索で読まれる記事）", "traffic-todo-other"),
    ]

    # ---------------------------------------------------------- 04 プレゼント
    b += [
        h2("04 LINEに登録してもらう理由（無料プレゼント）", "magnet-h2"),
        p("登録した人に、プレゼントを順番に渡す。", "magnet-lead"),
        h3_decide("magnet-decide-h3"),
        bullet("1通目を、解説動画「鍵を妹に預けた話」にするか", "magnet-decide-1"),
        note("みきさんの案。YouTubeではアプリを作ったところまで話し、続きをLINEで渡す。", "magnet-note-1"),
        h3("2通目以降の候補", "magnet-candidates-h3"),
        bullet("抜け道診断（10問。あなたのスマホに抜け道が◯個、と返す）", "magnet-cand-1"),
        bullet("自分で設定する完全マニュアル", "magnet-cand-2"),
        bullet("実演動画「市販のブロックアプリを全部すり抜けてみた」", "magnet-cand-3"),
        bullet("依存度チェック（18問で点数が出る）", "magnet-cand-4"),
        bullet("再発しやすい場面の一覧（機種変・旅行・深夜・酒の後・パソコン・ゲーム機）", "magnet-cand-5"),
        bullet("パートナー向け「責めずに助ける方法」", "magnet-cand-6"),
        h3_todo("magnet-todo-h3"),
        todo("1通目の動画の台本を書く", "magnet-todo-script"),
        todo("1通目の動画を撮る", "magnet-todo-record"),
        todo("抜け道診断を作る（ダン）", "magnet-todo-quiz"),
    ]

    # ---------------------------------------------------------- 05 LINE A
    b += [
        h2("05 LINEの流れ（A）モニター3名を集める時", "sa-h2"),
        p("目的は売上ではなく、体験談3件。審査で落とす前提で組む。", "sa-lead"),
        h3_decided("sa-decided-h3"),
        bullet("登録した直後に、アンケート1問「iPhoneかAndroidか」", "sa-decided-1"),
        bullet("iPhoneの人は順番待ちに入れる。今は売らない", "sa-decided-2"),
        note("iPhoneではXの中を止められず、破られても気づけないため。", "sa-note-1"),
        bullet("3万円は「体験談と引き換えの値段」と伝える", "sa-decided-3"),
        bullet("モニターの条件：週1の報告／終了後に体験談を出す／不具合に付き合う", "sa-decided-4"),
        h3("配信の順番", "sa-flow-h3"),
        numbered("プレゼント（鍵を人に預けた話の動画）", "sa-flow-1"),
        numbered("抜け道診断", "sa-flow-2"),
        numbered("みきさんの体験談（3年間・ED・何を試して駄目だったか）", "sa-flow-3"),
        numbered("モニター募集（3名・審査あり・3万円・今月中）", "sa-flow-4"),
        numbered("申込フォーム（何年悩んだか／試したこと／なぜ今か）", "sa-flow-5"),
        numbered("締切の連絡", "sa-flow-6"),
        h3_decide("sa-decide-h3"),
        field("落とす基準", bid="sa-field-reject"),
        field("申込後に面談するか（ZoomかLINE通話）", bid="sa-field-interview"),
        h3_todo("sa-todo-h3"),
        todo("この事業用のLINE公式アカウントを作る（ダン）", "sa-todo-line"),
        todo("登録直後のアンケートを設定する", "sa-todo-survey"),
        todo("6通のメッセージを書く", "sa-todo-messages"),
        todo("申込フォームを作る", "sa-todo-form"),
        todo("モニター3名を集める", "sa-todo-recruit"),
    ]

    # ---------------------------------------------------------- 06 LINE B
    b += [
        h2("06 LINEの流れ（B）実績ができた後", "sb-h2"),
        p("登録した日を1日目として、全員に同じ7日間の流れを送る。", "sb-lead"),
        h3_decided("sb-decided-h3"),
        bullet("登録直後のアンケートは同じ（iPhoneかAndroidか）", "sb-decided-1"),
        bullet("7日間の案：1日目 プレゼント／2日目 体験談／3日目 なぜ意志では無理か／4日目 モニターの声／5日目 案内（10万円）／6日目 質問への回答／7日目 締切", "sb-decided-2"),
        note("買う人の目安は、登録した人の1〜5％。", "sb-note-1"),
        h3_decide("sb-decide-h3"),
        field("月に何人受けるか（目安10人）", bid="sb-field-capacity"),
        bullet("締切を登録日から数えるか（一斉ではなく1人ずつ）", "sb-decide-1"),
        bullet("買わなかった人に、長期の配信を続けるか", "sb-decide-2"),
        h3_todo("sb-todo-h3"),
        todo("実績3件が揃ったら、7日間の配信を書く", "sb-todo-scenario"),
        todo("iPhone版ができたら、順番待ちの人に案内する", "sb-todo-iphone-notice"),
    ]

    # ---------------------------------------------------------- 07 アプリ
    b += [
        h2("07 アプリでやること", "app-h2"),
        p("アプリの開発と、客のスマホを設定する準備。", "app-lead"),
        h3_decided("app-decided-h3"),
        bullet("iPhone版も同じ方式で作れる（画面を読む必要がないため）", "app-decided-1"),
        bullet("iPhoneで作れないのは「Xを開いた瞬間の差し替え」だけ。スクリーンタイムでXを止めて代わりにする", "app-decided-2"),
        h3_decide("app-decide-h3"),
        bullet("機種変の事前申告を契約に入れるか（解除と同じ24時間ルール）", "app-decide-1"),
        field("iPhone版にいつ着手するか", bid="app-field-iphone-when"),
        note("費用はMac 9〜12万円＋実機3〜5万円＋登録料 年1.5万円。審査の期間は読めないので、客に期限は約束しない。", "app-note-3"),
        field("アプリ単体をストアに出すか", bid="app-field-store"),
        h3_todo("app-todo-h3"),
        todo("【最優先】24時間音沙汰のないスマホを運営に知らせる（機種変・電源オフ・アプリ削除に気づくため）", "app-todo-silence"),
        todo("セキュアフォルダの検知を「守りが立っているか」の判定に入れる", "app-todo-securefolder"),
        todo("iPhone向け「うちのサイト経由でXを見る」方式を、捨てアカウントで試す", "app-todo-proxy"),
        todo("誤検知を減らす（今は普通の投稿の3.5％が巻き添え）", "app-todo-fp"),
        todo("客のスマホを設定する手順書を作る", "app-todo-manual"),
        todo("複数人を管理する画面を作る（5人を超えたら）", "app-todo-admin"),
    ]

    # ---------------------------------------------------------- 08 判断待ち
    b += [
        h2("08 えるさんの200万円と、先に入金してもらう案", "open-h2"),
        p("みきさんの判断待ち。決まったら上の項目に反映する。", "open-lead"),
        h3_decide("open-decide-h3"),
        field("えるさんの200万円をどうするか", bid="open-field-eru"),
        note("ダンの意見：今は払わない。「リストができてから改めてお願いしたい」と返す。", "open-note-1"),
        field("「1〜2ヶ月で完成しなければ全額返金」で先に入金してもらうか", bid="open-field-prepay"),
        note("ダンは反対。審査の期間は自分では早められないので、守れない約束になる。", "open-note-2"),
    ]
    return b


def seed(replace: bool = False) -> None:
    svc = ArtifactDocumentsService()
    blocks = build_blocks()
    ids = [x["id"] for x in blocks]
    assert len(ids) == len(set(ids)), "block id が重複しています"
    row = svc.ensure(
        SLUG,
        title=TITLE,
        blocks=blocks,
        room_id=ROOM_ID,
        owner_user_id=OWNER_USER_ID,
        replace=replace,
    )
    todos = [x for x in blocks if x["type"] == "checkListItem"]
    print("slug=%s version=%s blocks=%d todos=%d" % (SLUG, row.get("version"), len(blocks), len(todos)))


if __name__ == "__main__":
    seed(replace="--replace" in sys.argv)
