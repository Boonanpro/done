"""denkiouen.com の順位磨きの判定・題名の検査・直し方の切り替え（scripts/denki_seo_engines.py）。

2026-10-26: 判定が順位だけだったので、題名を狙いの語から離して表示が3分の1に減ったページも
「上がった」になっていた。表示回数とクリックも見ること、題名に主の検索語を残すこと、
効かなかった直し方を繰り返さないことを確かめる。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from denki_seo_engines import judge_experiment, next_polish_method, title_missing_terms  # noqa: E402


def _stats(impr, days, pos, clicks=0):
    return {"impressions": impr, "days": days, "position": pos, "clicks": clicks, "scope": "page"}


def test_impressions_drop_is_lost_even_if_position_improves():
    # 継電器試験の周期: 14日で35表示・5.1位 → 7日で3表示・3.0位。旧判定は won だった
    verdict, reason = judge_experiment(_stats(35, 14, 5.09, 2), _stats(3, 7, 3.0, 0))
    assert verdict == "lost"
    assert "表示" in reason


def test_mild_impressions_drop_with_better_position_is_neutral_not_won():
    # 表示が7割未満に減ったら、順位が上がっていても「上がった」とは言わない
    verdict, _ = judge_experiment(_stats(140, 14, 7.0, 3), _stats(40, 7, 5.5, 1))
    assert verdict == "neutral"


def test_better_position_with_kept_impressions_is_won():
    verdict, _ = judge_experiment(_stats(140, 14, 7.0, 3), _stats(75, 7, 5.5, 2))
    assert verdict == "won"


def test_more_clicks_outweigh_impressions_drop():
    # クリックが増えていれば、表示が減っても戻さない
    verdict, _ = judge_experiment(_stats(140, 14, 7.0, 2), _stats(40, 7, 7.0, 4))
    assert verdict != "lost"


def test_position_worsened_is_lost():
    verdict, _ = judge_experiment(_stats(140, 14, 7.0, 2), _stats(80, 7, 9.5, 1))
    assert verdict == "lost"


def test_no_impressions_before_and_after_is_neutral():
    verdict, _ = judge_experiment({"impressions": 0, "days": 14, "position": None, "clicks": 0}, {"impressions": 0, "days": 7, "position": None, "clicks": 0})
    assert verdict == "neutral"


def test_title_must_keep_main_keyword_terms():
    assert title_missing_terms("LGRとは？電気設備の漏電リレーとGR・漏電遮断器の違い", "地絡継電器 漏電リレー 違い") == ["地絡継電器"]
    assert title_missing_terms("三相の漏れ電流の測定方法：3線一括とB種接地線", "漏れ電流 測定方法 三相") == []
    # 「電気」は曖昧さを消すための語なので題名に無くてよい。「とは」は語幹が入っていればよい
    assert title_missing_terms("SOGとは？PASの地絡トリップとSO動作", "sog 電気") == []
    assert title_missing_terms("地絡継電器の役割と受電設備での実例", "地絡継電器とは") == []
    assert title_missing_terms("絶縁抵抗測定の放電方法｜放電用接地棒の違い", "絶縁抵抗測定 やり方") == ["やり方"]


def _ex(slug, status, method=None, day="2026-10-01"):
    return {"guide_slug": slug, "status": status, "started_on": day, "baseline": {"method": method} if method else {}}


def test_next_method_skips_what_did_not_work():
    exps = [_ex("a", "neutral", None, "2026-10-01")]  # 古い記録は method 無し＝rewrite
    assert next_polish_method("a", exps) == "body"
    exps.append(_ex("a", "lost", "body", "2026-10-10"))
    assert next_polish_method("a", exps) == "meta"
    exps.append(_ex("a", "neutral", "meta", "2026-10-20"))
    assert next_polish_method("a", exps) is None


def test_next_method_resets_after_a_win_and_ignores_other_pages():
    exps = [_ex("a", "neutral", "rewrite", "2026-10-01"), _ex("a", "won", "body", "2026-10-10"), _ex("b", "lost", "rewrite", "2026-10-12")]
    assert next_polish_method("a", exps) == "rewrite"
    assert next_polish_method("b", exps) == "body"
    assert next_polish_method("c", exps) == "rewrite"
