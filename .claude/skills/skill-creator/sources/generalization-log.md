# 汎化の記録（skill-creator）

スキルの文章を変えるたびに、変更の理由を1項目ずつ足す。scripts/hook_skill_gate.py がこの記録を見て書き込みを通す。

## 2026-10-16 スキルの関所に合わせて記録の書き方を足す
- 種類: 操作
- 変更するファイル: SKILL.md
- 何を直したか: スキルの文章（.claude/skills の下の .md と SKILL.md）を書き換える前に、変更するスキルの sources/generalization-log.md に項目を書く手順と、項目の形式（種類が 指摘・実例・操作 のどれかと、種類ごとの欄）を SKILL.md に足す。D:/done/scripts/hook_skill_gate.py が Write/Edit の直前にこの記録を読み、欄がそろっていて別の AI の判定に通った時だけ書き込みを通すため、形式が書かれていないと書く側が止まった理由を直せない。
- 確かめたこと: 2026-10-16 にテスト用の一時スキル（D:/dan-workspace/hooktest/.claude/skills/gate-test）で、Claude CLI（sonnet）と Codex CLI（gpt-5.6-luna）の両方から書き込みを試した。手順書を読まない→止まる、読んだが記録なし→止まる、指摘の写しの記録→判定で止まる、汎化した記録→通る、を確認した。
