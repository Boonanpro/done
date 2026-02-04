"""
Skill Updater - 学習ルールに基づくスキルファイル自動更新

learned_rules を読み取り、対応するSKILL.mdやactions/*.mdを更新する。
DANは使えば使うほど正しい手順書を持つようになる。
"""

import logging
import json
import difflib
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

import google.generativeai as genai

from app.config import settings
from app.services import learning_service

logger = logging.getLogger(__name__)

# スキルディレクトリ
SKILLS_DIR = Path(__file__).parent.parent.parent / ".claude" / "skills"


@dataclass
class SkillUpdateProposal:
    """スキルファイル更新提案"""
    skill_name: str              # "amazon"
    file_path: str               # ".claude/skills/amazon/actions/add-to-cart.md"
    update_type: str             # "add_prerequisite", "add_step", "add_warning"
    current_content: str         # 現在のファイル内容
    proposed_content: str        # 更新後の内容
    diff: str                    # 差分表示
    source_rules: List[str]      # 根拠となるルールID
    confidence: float            # 平均信頼度
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_name": self.skill_name,
            "file_path": self.file_path,
            "update_type": self.update_type,
            "diff": self.diff,
            "source_rules": self.source_rules,
            "confidence": self.confidence,
            "created_at": self.created_at.isoformat(),
        }


def _find_skill_for_site(site: str) -> Optional[str]:
    """
    サイトドメインからスキル名を特定

    例: amazon.co.jp → amazon
    """
    if not SKILLS_DIR.exists():
        return None

    # サイトドメインからスキル名を推測
    site_lower = site.lower()

    for skill_dir in SKILLS_DIR.iterdir():
        if not skill_dir.is_dir():
            continue
        skill_name = skill_dir.name

        # スキル名がサイトに含まれているか
        if skill_name in site_lower:
            return skill_name

        # SKILL.md の domain フィールドをチェック
        skill_md = skill_dir / "SKILL.md"
        if skill_md.exists():
            content = skill_md.read_text(encoding="utf-8")
            if site in content:
                return skill_name

    return None


def _get_skill_file_path(skill_name: str, action: Optional[str] = None) -> Optional[Path]:
    """
    スキル名とアクションからファイルパスを取得

    Args:
        skill_name: スキル名
        action: アクション名（省略時はSKILL.md）

    Returns:
        ファイルパス
    """
    skill_dir = SKILLS_DIR / skill_name
    if not skill_dir.exists():
        return None

    if action:
        # アクションファイル
        action_file = skill_dir / "actions" / f"{action}.md"
        if action_file.exists():
            return action_file
        # アンダースコア/ハイフン変換
        action_alt = action.replace("-", "_")
        action_file_alt = skill_dir / "actions" / f"{action_alt}.md"
        if action_file_alt.exists():
            return action_file_alt

    # SKILL.md
    skill_md = skill_dir / "SKILL.md"
    if skill_md.exists():
        return skill_md

    return None


async def _generate_updated_content(
    current_content: str,
    rules: List[learning_service.LearnedRule],
    file_path: str,
) -> Optional[str]:
    """
    Gemini 2.5 Flash でスキルファイルの更新版を生成

    Args:
        current_content: 現在のファイル内容
        rules: 適用するルール
        file_path: ファイルパス（コンテキスト用）

    Returns:
        更新後の内容
    """
    if not settings.GOOGLE_GEMINI_API_KEY:
        logger.warning("GOOGLE_GEMINI_API_KEY not set, skipping content generation")
        return None

    try:
        genai.configure(api_key=settings.GOOGLE_GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-2.5-flash")

        # ルール情報を整形
        rules_info = []
        for rule in rules:
            rules_info.append({
                "pattern_type": rule.pattern_type,
                "observed_pattern": rule.observed_pattern,
                "inferred_rule": rule.inferred_rule,
                "confidence": rule.confidence,
            })

        prompt = f"""You are updating a browser automation skill file based on learned rules.

## Current File Content
File: {file_path}

```markdown
{current_content}
```

## Active Learned Rules (ONLY these rules should be reflected)
{json.dumps(rules_info, indent=2)}

## Instructions
1. Analyze the active learned rules and update the skill file accordingly
2. If a rule indicates a prerequisite, add it to a "前提条件" section
3. If a rule indicates action order, add steps at the beginning of procedures
4. If a rule is a causal inference, add warnings in a "注意事項" section

5. IMPORTANT - This is a REPLACEMENT update:
   - ONLY include learning-based content that corresponds to the active rules above
   - REMOVE any learning-based sections (前提条件, 注意事項, warnings) that do NOT have a corresponding active rule
   - If a rule was previously applied but is no longer in the active rules list, its content should be removed

6. Keep the original structure intact:
   - Actions table, basic descriptions, parameters - do not modify these
   - Only modify/add/remove learning-based sections

7. Use Japanese for all content
8. If no rules apply to this file, return the original content exactly as-is

## Output
Return ONLY the updated markdown content. No explanation, no code blocks."""

        response = await model.generate_content_async(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.3,
                max_output_tokens=4000,
            ),
        )

        return response.text.strip()

    except Exception as e:
        logger.error(f"Failed to generate updated content: {e}")
        return None


def _generate_diff(current: str, proposed: str) -> str:
    """
    差分を生成
    """
    current_lines = current.splitlines(keepends=True)
    proposed_lines = proposed.splitlines(keepends=True)

    diff = difflib.unified_diff(
        current_lines,
        proposed_lines,
        fromfile="current",
        tofile="proposed",
        lineterm="",
    )

    return "".join(diff)


async def propose_skill_updates(
    min_confidence: float = 0.7,
) -> List[SkillUpdateProposal]:
    """
    学習ルールに基づく更新提案を生成

    Args:
        min_confidence: 提案に含める最小信頼度

    Returns:
        各スキルファイルへの更新提案リスト
    """
    proposals = []

    try:
        # アクティブなルールを取得
        rules = await learning_service.get_all_active_rules()
        if not rules:
            logger.info("No active rules found")
            return []

        # 信頼度でフィルタ
        rules = [r for r in rules if r.confidence >= min_confidence]
        if not rules:
            logger.info(f"No rules with confidence >= {min_confidence}")
            return []

        # スキルファイルごとにルールをグループ化
        file_rules: Dict[str, List[learning_service.LearnedRule]] = {}

        for rule in rules:
            scope = rule.scope
            site = scope.get("site")
            action = scope.get("action")

            # スキル名を特定
            skill_name = None
            if site:
                skill_name = _find_skill_for_site(site)

            if not skill_name:
                logger.debug(f"Could not find skill for rule scope: {scope}")
                continue

            # ファイルパスを特定
            file_path = _get_skill_file_path(skill_name, action)
            if not file_path:
                logger.debug(f"Could not find file for skill={skill_name}, action={action}")
                continue

            path_str = str(file_path)
            if path_str not in file_rules:
                file_rules[path_str] = []
            file_rules[path_str].append(rule)

        # 各ファイルに対して更新提案を生成
        for file_path_str, rules_for_file in file_rules.items():
            file_path = Path(file_path_str)

            # 現在の内容を読み取り
            try:
                current_content = file_path.read_text(encoding="utf-8")
            except Exception as e:
                logger.error(f"Failed to read {file_path}: {e}")
                continue

            # 更新版を生成
            proposed_content = await _generate_updated_content(
                current_content,
                rules_for_file,
                str(file_path),
            )

            if not proposed_content:
                continue

            # 差分がなければスキップ
            if current_content.strip() == proposed_content.strip():
                logger.debug(f"No changes needed for {file_path}")
                continue

            # 差分を生成
            diff = _generate_diff(current_content, proposed_content)

            # スキル名を抽出
            skill_name = file_path.parent.name
            if skill_name == "actions":
                skill_name = file_path.parent.parent.name

            # 更新タイプを推測
            update_type = "modify"
            for rule in rules_for_file:
                if "requires_state" in rule.inferred_rule:
                    update_type = "add_prerequisite"
                elif "should_do_first" in rule.inferred_rule:
                    update_type = "add_step"

            # 平均信頼度
            avg_confidence = sum(r.confidence for r in rules_for_file) / len(rules_for_file)

            proposal = SkillUpdateProposal(
                skill_name=skill_name,
                file_path=str(file_path),
                update_type=update_type,
                current_content=current_content,
                proposed_content=proposed_content,
                diff=diff,
                source_rules=[r.id for r in rules_for_file],
                confidence=avg_confidence,
            )

            proposals.append(proposal)
            logger.info(f"Generated update proposal for {file_path}")

        return proposals

    except Exception as e:
        logger.error(f"Failed to generate skill update proposals: {e}")
        return []


async def apply_skill_update(
    proposal: SkillUpdateProposal,
    backup: bool = True,
) -> bool:
    """
    更新提案を実際に適用

    Args:
        proposal: 更新提案
        backup: バックアップを作成するか

    Returns:
        成功したか
    """
    try:
        file_path = Path(proposal.file_path)

        # バックアップ
        if backup:
            backup_path = file_path.with_suffix(f".md.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}")
            backup_path.write_text(proposal.current_content, encoding="utf-8")
            logger.info(f"Created backup: {backup_path}")

        # 更新を適用
        file_path.write_text(proposal.proposed_content, encoding="utf-8")
        logger.info(f"Applied update to {file_path}")

        # ルールに適用済みフラグを設定（将来実装）
        # for rule_id in proposal.source_rules:
        #     await learning_service.mark_rule_applied(rule_id)

        return True

    except Exception as e:
        logger.error(f"Failed to apply skill update: {e}")
        return False


async def auto_update_skills(
    min_confidence: float = 0.8,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """
    高信頼度ルールを自動適用

    Args:
        min_confidence: 自動適用の最小信頼度
        dry_run: Trueなら実際には書き込まない（propose相当）

    Returns:
        処理結果のサマリ
    """
    result = {
        "proposals_generated": 0,
        "proposals_applied": 0,
        "dry_run": dry_run,
        "proposals": [],
        "errors": [],
    }

    try:
        # 提案を生成
        proposals = await propose_skill_updates(min_confidence=min_confidence)
        result["proposals_generated"] = len(proposals)

        for proposal in proposals:
            result["proposals"].append(proposal.to_dict())

            if not dry_run:
                # 実際に適用
                success = await apply_skill_update(proposal)
                if success:
                    result["proposals_applied"] += 1
                else:
                    result["errors"].append(f"Failed to apply: {proposal.file_path}")

        logger.info(
            f"Auto-update complete: {result['proposals_generated']} proposals, "
            f"{result['proposals_applied']} applied (dry_run={dry_run})"
        )

        return result

    except Exception as e:
        logger.error(f"Auto-update failed: {e}")
        result["errors"].append(str(e))
        return result
