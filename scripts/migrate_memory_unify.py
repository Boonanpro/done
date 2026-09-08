"""Unify Dan's two long-term memories into ~/.dan/workspace/memory/.

Before (two diverging stores):
  * Claude Code auto-memory: ~/.claude/projects/D--dan-workspace/memory/ (index + topic files)
  * Dan workspace:           ~/.dan/workspace/MEMORY.md (long prose, read on demand)

After (one store, read by every backend):
  ~/.dan/workspace/memory/MEMORY.md   index (<=200 lines / 25KB, Claude auto-load limits)
  ~/.dan/workspace/memory/<topic>.md  one file per memory (Claude topic files moved here,
                                      workspace sections split into files)
  ~/.dan/workspace/MEMORY.md          3-line pointer to the index
  ~/.claude/projects/D--dan-workspace/memory/MOVED.md   pointer left behind

Claude Code is pointed at the new dir via autoMemoryDirectory (settings.json).
Originals are archived under memory/_archive/ before anything is touched.

Usage: python scripts/migrate_memory_unify.py [--apply]   (default = dry run)
"""

from __future__ import annotations

import re
import shutil
import sys
from datetime import date
from pathlib import Path

HOME = Path.home()
CLAUDE_MEM = HOME / ".claude" / "projects" / "D--dan-workspace" / "memory"
WS = HOME / ".dan" / "workspace"
WS_MEMORY_MD = WS / "MEMORY.md"
MEM = WS / "memory"
ARCHIVE = MEM / "_archive"
TODAY = date.today().isoformat()

APPLY = "--apply" in sys.argv

# workspace MEMORY.md "## " section title (prefix match) -> (topic file, index line hook)
# Sections merged INTO an existing Claude topic file are marked with append=True.
SECTION_MAP = [
    ("アカウント情報", "accounts.md", "フロントエンド開発/楽天/Amazon/メルカリ/note/Gmail/iCloud/アメックス/楽天銀行/Fish Audio/LINE公式(スタイルアップ・吉川特装)/StyleUp Stripe。IDのみ、パスワードは credentials DB"),
    ("技術プロジェクト", "archive-2026-02-dev-notes.md", "2026-02 時点の Heartbeat・自己改善ログ・未コミット作業・当時のバグメモ（古い）"),
    ("Heartbeat (2026-02-28", "archive-2026-02-dev-notes.md", None),
    ("事業プロジェクト", "business-ideas-clinic-followsure.md", "性依存症治療クリニック（TMS/自由診療・リサーチと11ステップ計画）と FollowSure メールリマインダーSaaS の起点"),
    ("電管ナレッジ検索", "denki-knowledge-site.md", "朝6時 DenkiKnowledgeRefresh で自動更新、公開URL denki-knowledge-done.vercel.app、掲載先への挨拶連絡の到達状況（CF7+reCAPTCHA v3 はフォーム自動送信不可）"),
    ("電管ナレッジ 質問・相談掲示板", "denki-qa-board.md", "Supabase denki_qa_*、回答時は Gmail SMTP で即時通知、予備は DenkiQaNotify 15分タスク"),
    ("PayPal", "paypal-business-account.md", "shub6923@gmail.com/株式会社パイナ名義、法人デビット3666を3Dセキュア確認済み。個人PayPal(bold1315)は使わない。法人番号・登記住所・本人生年月日もここ"),
    ("Meta広告の支払いが通らない件", "meta-ads-payment-block.md", "NEOBANKデビットは3Dセキュア必須で保存カード請求が弾かれる／再試行上限で24時間全滅。恒久策はPayPal経由（連携ポップアップはbrowserで操作不可）"),
    ("UTAGE / Lステップ 解約プロジェクト", "utage-lstep-cancel.md", "年52万円の継続課金を止める。会員通知はメールのみ。退避データは artifacts/itsuki-members/（202名・63レッスン・動画取得済）"),
    ("財布紛失・カード再発行の状況", "project-wallet-loss-card-reissue-2026-08.md", None),  # append to Claude topic
    ("株式会社パイナ 決算資料メモ", "paina-tax-social-insurance.md", "社保滞納2か月分342,466円の説明、源泉所得税227,228円(納期特例・8/24納付)、e-Tax法人ログイン、社保整理番号、納期限と口座振替の罠"),
    ("株式会社パイナ 税金・社会保険", "paina-tax-social-insurance.md", None),
    ("ドコモSMTBネット銀行", "smtb-bank-rakuten-securities.md", "銀行の住所変更はWEB取引パスワード（未保管）が必要・リンクはdispatchEventで遷移。楽天証券はパスキー必須化中→ダン側ブラウザにパスキー追加が恒久策。PIN 683375 は credentials"),
    ("第2期本決算（R7.8〜R8.7）の県民税・市民税", "project-paina-eltax-card-payment.md", None),  # append to Claude topic
]

# Claude index lines to DROP (stale 2026-02 inline content now archived) — matched by prefix.
DROP_PREFIXES = (
    "- XREAL One", "- AirPods Max", "- 運用開始: 2026-02-22", "- 再起動は必ず `python scripts/start_backend.py`",
    "- 2026-02-28 10:48 Heartbeat", "- 2026-02-28 10:01 Heartbeat", "- 2026-02-28 10:00 Heartbeat", "- 2026-02-28 朝 Heartbeat",
    "- 2026-02-27 夜 Heartbeat", "- 約20ファイルに未コミット変更", "- project-list-panel.tsx", "- auto-title機能は",
    "- datetime.utcnow(): ゼロ件", "- console.log: ゼロ件", "- ハードコード認証情報: ゼロ件", "- RULES.md: 37行", "- 次回チェック: B",
    "- 合言葉: パイナップル",
)
DROP_HEADINGS = ("## 購入検討中", "### Amazonカート内", "## 技術プロジェクト", "### Heartbeat自律起動システム",
                 "### バックエンド注意事項", "### 自己改善ログ（直近）", "### 未コミットの作業（2026-02-27時点）",
                 "## Heartbeat (2026-02-28 10:48)", "## 記憶テスト", "### note詳細")


def split_sections(text: str) -> list[tuple[str, str]]:
    """Split markdown into (title, body) by '## ' headings; body keeps sub-headings."""
    out, cur, buf = [], None, []
    for line in text.splitlines():
        if line.startswith("## "):
            if cur is not None:
                out.append((cur, "\n".join(buf).strip()))
            cur, buf = line[3:].strip(), []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        out.append((cur, "\n".join(buf).strip()))
    return out


def frontmatter(name: str, desc: str, kind: str = "project") -> str:
    return f"---\nname: {name}\ndescription: {desc}\nmetadata:\n  type: {kind}\n  migrated_from: workspace MEMORY.md ({TODAY})\n---\n\n"


def build_index(claude_index: str, new_lines_by_section: dict[str, list[str]]) -> str:
    """Rewrite the Claude index: drop stale inline notes, reslot content, add new topic lines."""
    lines = claude_index.splitlines()
    out: list[str] = []
    skip_table = False
    for ln in lines:
        s = ln.strip()
        if any(s.startswith(p) for p in DROP_PREFIXES):
            continue
        if s in DROP_HEADINGS:
            continue
        # The inline account table moves to accounts.md
        if s.startswith("| サービス |") or s.startswith("|---|"):
            skip_table = True
            continue
        if skip_table and s.startswith("|"):
            continue
        skip_table = False
        if s.startswith("- プロフィールURL: https://note.com") or s.startswith("- **未完了**: 収益化設定") or s.startswith("- 目標: 月30万円収益化"):
            continue
        if s == "# 長期記憶":
            out.append("# 長期記憶（索引）")
            out.append("")
            out.append(f"各行1件。詳細は同じフォルダのリンク先ファイル。ここは200行/25KB以内に保つ（超えた分は読み込まれない）。統合: {TODAY}（Claude自動メモリ + workspace MEMORY.md）。")
            continue
        out.append(ln)
    text = "\n".join(out)
    # Insert new lines under the account heading and append other sections.
    acct_head = "## アカウント情報（認証情報はcredentials DBに保存。ここにはパスワードを書かない）"
    if acct_head in text and "accounts" in new_lines_by_section:
        text = text.replace(acct_head, acct_head + "\n\n" + "\n".join(new_lines_by_section["accounts"]), 1)
    extra = []
    for title, ls in new_lines_by_section.items():
        if title == "accounts":
            continue
        extra.append(f"\n## {title}\n" + "\n".join(ls))
    text = text.rstrip() + "\n" + "\n".join(extra) + "\n\n## 記憶テスト\n- 合言葉: みかん（2026-09-06、りんご→みかんに変更）\n"
    # collapse 3+ blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def main() -> int:
    claude_index = (CLAUDE_MEM / "MEMORY.md").read_text(encoding="utf-8")
    ws_text = WS_MEMORY_MD.read_text(encoding="utf-8")
    sections = split_sections(ws_text)
    print(f"workspace sections: {[t[:24] for t, _ in sections]}")

    planned_files: dict[str, list[str]] = {}   # file -> bodies
    hooks: dict[str, str] = {}
    for title, body in sections:
        for prefix, fname, hook in SECTION_MAP:
            if title.startswith(prefix):
                planned_files.setdefault(fname, []).append(f"## {title}\n\n{body}")
                if hook:
                    hooks[fname] = hook
                break
        else:
            if title.strip():
                print(f"  ! unmapped section: {title[:40]!r} (kept in archive only)")

    index_lines = {
        "accounts": [f"- [アカウント一覧](accounts.md) — {hooks['accounts.md']}"],
        "事業・サイト運用（workspaceから統合）": [
            f"- [電管ナレッジ検索サイト](denki-knowledge-site.md) — {hooks['denki-knowledge-site.md']}",
            f"- [電管ナレッジ Q&A掲示板](denki-qa-board.md) — {hooks['denki-qa-board.md']}",
            f"- [UTAGE/Lステップ解約](utage-lstep-cancel.md) — {hooks['utage-lstep-cancel.md']}",
            f"- [Meta広告の支払い不通](meta-ads-payment-block.md) — {hooks['meta-ads-payment-block.md']}",
            f"- [事業アイデア: クリニック/FollowSure](business-ideas-clinic-followsure.md) — {hooks['business-ideas-clinic-followsure.md']}",
        ],
        "パイナ法人 お金・口座（workspaceから統合）": [
            f"- [PayPalビジネスアカウント](paypal-business-account.md) — {hooks['paypal-business-account.md']}",
            f"- [税金・社会保険の納付履歴と罠](paina-tax-social-insurance.md) — {hooks['paina-tax-social-insurance.md']}",
            f"- [ドコモSMTB銀行・楽天証券の操作の壁](smtb-bank-rakuten-securities.md) — {hooks['smtb-bank-rakuten-securities.md']}",
            "- 財布紛失後の詳細（アメックス到着9/1・楽天銀行は住所変更未了・法人デビットは有効）は project-wallet-loss-card-reissue-2026-08.md に追記済み",
            "- 第2期県民税・市民税36,000円の納付詳細（AMEX立替・取引番号・控えの場所）は project-paina-eltax-card-payment.md に追記済み",
        ],
        "ダン運用メモ（古い）": [
            f"- [2026-02の開発メモ](archive-2026-02-dev-notes.md) — {hooks['archive-2026-02-dev-notes.md']}",
        ],
    }
    new_index = build_index(claude_index, index_lines)
    n_lines, n_bytes = len(new_index.splitlines()), len(new_index.encode("utf-8"))
    print(f"new index: {n_lines} lines / {n_bytes} bytes (limits 200 / 25600)")
    if n_lines > 200 or n_bytes > 25600:
        print("!! index over Claude auto-load limits; trim before applying")
    if not APPLY:
        print("---- DRY RUN: new index preview ----")
        print(new_index)
        print("---- files to create/append ----")
        for f, bodies in planned_files.items():
            mode = "append" if (CLAUDE_MEM / f).exists() else "create"
            print(f"  {mode}: {f} ({sum(len(b) for b in bodies)} chars)")
        return 0

    # ---- apply ----
    MEM.mkdir(parents=True, exist_ok=True)
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CLAUDE_MEM / "MEMORY.md", ARCHIVE / f"MEMORY.claude.{TODAY}.md")
    shutil.copy2(WS_MEMORY_MD, ARCHIVE / f"MEMORY.workspace.{TODAY}.md")
    # move Claude topic files (index rewritten below)
    for p in sorted(CLAUDE_MEM.glob("*.md")):
        if p.name == "MEMORY.md":
            continue
        dest = MEM / p.name
        if dest.exists():
            shutil.copy2(dest, ARCHIVE / f"{dest.stem}.workspace-copy.{TODAY}.md")
        shutil.move(str(p), str(dest))
    # workspace sections -> topic files (append to existing Claude topics where mapped)
    for fname, bodies in planned_files.items():
        dest = MEM / fname
        body = "\n\n".join(bodies)
        if dest.exists():
            with open(dest, "a", encoding="utf-8") as f:
                f.write(f"\n\n---\n\n<!-- merged from workspace MEMORY.md on {TODAY} -->\n\n{body}\n")
        else:
            desc = hooks.get(fname, fname)
            dest.write_text(frontmatter(dest.stem, desc) + body + "\n", encoding="utf-8")
    (MEM / "MEMORY.md").write_text(new_index, encoding="utf-8")
    (CLAUDE_MEM / "MEMORY.md").unlink()
    (CLAUDE_MEM / "MOVED.md").write_text(
        f"# 移動済み ({TODAY})\n\nダンの長期記憶は `~/.dan/workspace/memory/` に統合した。\n"
        "Claude Code は D:/dan-workspace/.claude/settings.json の autoMemoryDirectory でそこを使う。\n",
        encoding="utf-8",
    )
    WS_MEMORY_MD.write_text(
        f"# 長期記憶 → memory/MEMORY.md に移動（{TODAY}）\n\n"
        "索引は `~/.dan/workspace/memory/MEMORY.md`、各項目は同じフォルダの個別ファイル。\n"
        "新しい記憶はそこへ1件1ファイルで保存し、索引に1行足すこと。旧全文は memory/_archive/ に保管。\n",
        encoding="utf-8",
    )
    print("applied.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
