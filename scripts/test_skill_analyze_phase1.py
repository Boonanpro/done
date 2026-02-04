"""
Phase 1 スキル化判断ロジックのテスト

LLMがDECISION（create/extend/skip）を正しく返すか確認する。
"""

import asyncio
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.skill_generator_claude import (
    analyze_session_for_skill,
    _get_existing_skills_summary,
    SkillProposal,
)


async def test_existing_skills_summary():
    """既存スキルサマリの生成をテスト"""
    print("=" * 60)
    print("TEST 1: 既存スキルサマリの生成")
    print("=" * 60)

    summary = _get_existing_skills_summary()
    print(summary)
    print()

    # 検証
    assert "## 既存スキル一覧" in summary, "ヘッダーがない"
    print("[OK] 既存スキルサマリが正しく生成された")
    return True


async def test_analyze_with_existing_skill():
    """既存スキルがある状態での分析をテスト"""
    print("=" * 60)
    print("TEST 2: 既存スキルがある状態での分析")
    print("=" * 60)

    # 既存のYAMLログを使用
    # 楽天ログインのログ（既存スキルがあれば skip/extend になるはず）
    yaml_path = Path("D:/done/app/logs/browser/01cb44c8/20260130_225235_楽天にパスワード「Bold13151719」でログインする.yaml")

    if not yaml_path.exists():
        print(f"[SKIP] YAMLファイルが見つかりません: {yaml_path}")
        return False

    print(f"YAML: {yaml_path}")
    print("分析中（Claude Code CLI呼び出し、60秒程度かかる場合があります）...")

    proposal = await analyze_session_for_skill(str(yaml_path))

    if not proposal:
        print("[NG] 分析結果がNone")
        return False

    print()
    print("=== 分析結果 ===")
    print(f"  decision:         {proposal.decision}")
    print(f"  decision_reason:  {proposal.decision_reason}")
    print(f"  target_skill:     {proposal.target_skill}")
    print(f"  new_actions:      {proposal.new_actions}")
    print(f"  granularity_ok:   {proposal.granularity_ok}")
    print(f"  granularity_issue: {proposal.granularity_issue}")
    print(f"  should_create:    {proposal.should_create}")
    print(f"  skip_reason:      {proposal.skip_reason}")
    print()
    print(f"  skill_name:       {proposal.skill_name}")
    print(f"  description:      {proposal.description}")
    print(f"  site:             {proposal.site}")
    print(f"  actions:          {proposal.actions}")
    print()

    # 検証
    assert proposal.decision in ("create", "extend", "skip"), f"無効なdecision: {proposal.decision}"
    print(f"[OK] decision={proposal.decision} が返された")

    # ログインのみのタスクは粒度が細かすぎるはず
    if "ログイン" in str(yaml_path) and proposal.granularity_ok:
        print("[WARN] ログインのみのタスクだが granularity_ok=True")

    return True


async def test_analyze_skip_case():
    """skip判定のテスト（粒度が細かすぎるケース）"""
    print("=" * 60)
    print("TEST 3: skip判定（粒度チェック）")
    print("=" * 60)

    # ログインのみのログは粒度が細かすぎてskipになるはず
    # （上のテストと同じログを使用）
    yaml_path = Path("D:/done/app/logs/browser/01cb44c8/20260130_225235_楽天にパスワード「Bold13151719」でログインする.yaml")

    if not yaml_path.exists():
        print(f"[SKIP] YAMLファイルが見つかりません: {yaml_path}")
        return False

    proposal = await analyze_session_for_skill(str(yaml_path))

    if not proposal:
        print("[NG] 分析結果がNone")
        return False

    # ログインのみのタスクの期待動作:
    # - decision = "skip" かつ granularity_ok = False
    # または
    # - decision = "extend" で既存スキルに追加

    if proposal.decision == "skip":
        print(f"[OK] decision=skip が返された")
        print(f"     理由: {proposal.decision_reason}")
        if not proposal.granularity_ok:
            print(f"     粒度問題: {proposal.granularity_issue}")
    elif proposal.decision == "extend":
        print(f"[OK] decision=extend が返された")
        print(f"     対象スキル: {proposal.target_skill}")
    else:
        print(f"[INFO] decision=create が返された（新規スキル作成）")

    return True


async def main():
    """全テストを実行"""
    print("\n" + "=" * 60)
    print("Phase 1 スキル化判断ロジック テスト")
    print("=" * 60 + "\n")

    results = []

    # テスト1: 既存スキルサマリ（CLIを呼ばないのですぐ終わる）
    try:
        results.append(("既存スキルサマリ", await test_existing_skills_summary()))
    except Exception as e:
        print(f"[ERROR] {e}")
        results.append(("既存スキルサマリ", False))

    # テスト2, 3: 分析テスト（Claude Code CLI呼び出しで時間がかかる）
    # 実際に実行するか確認
    print()
    print("テスト2, 3はClaude Code CLIを呼び出すため、60秒程度かかります。")
    print("続行しますか？ (y/N): ", end="", flush=True)

    # 非対話モードの場合はスキップ
    try:
        import select
        if sys.stdin in select.select([sys.stdin], [], [], 5)[0]:
            answer = input().strip().lower()
        else:
            answer = "n"
            print("（タイムアウト）")
    except:
        # Windows では select が stdin で動かないので直接 input
        try:
            answer = input().strip().lower()
        except:
            answer = "n"

    if answer == "y":
        try:
            results.append(("分析テスト", await test_analyze_with_existing_skill()))
        except Exception as e:
            import traceback
            print(f"[ERROR] {e}")
            traceback.print_exc()
            results.append(("分析テスト", False))
    else:
        print("[SKIP] 分析テストをスキップ")
        results.append(("分析テスト", None))

    # 結果サマリ
    print("\n" + "=" * 60)
    print("テスト結果サマリ")
    print("=" * 60)
    for name, result in results:
        if result is None:
            status = "SKIP"
        elif result:
            status = "OK"
        else:
            status = "NG"
        print(f"  {name}: {status}")

    print()


if __name__ == "__main__":
    asyncio.run(main())
