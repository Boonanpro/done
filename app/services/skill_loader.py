"""
Skill Loader - 生成されたスキルを読み込む

.claude/skills/*/SKILL.md から生成されたスキルを検出し、
visual_browseで使用するセレクタヒントを提供する。
"""

import re
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import yaml

logger = logging.getLogger(__name__)

# スキルディレクトリのパス
SKILLS_DIR = Path(__file__).parent.parent.parent / ".claude" / "skills"


@dataclass
class GeneratedSkill:
    """生成されたスキルの情報"""
    name: str
    title: str
    description: str  # スキルの説明
    domain: str  # 例: duckduckgo.com
    original_task: str
    actions: List[str]
    selectors_hints: Optional[str]
    skill_md_path: Path
    generated_at: Optional[str] = None


class SkillLoader:
    """スキルを読み込み、サイトに対応するヒントを提供"""

    def __init__(self):
        self._cache: Dict[str, GeneratedSkill] = {}
        self._domain_map: Dict[str, GeneratedSkill] = {}
        self._loaded = False

    def load_all(self, force: bool = False) -> List[GeneratedSkill]:
        """全てのスキルを読み込む"""
        if self._loaded and not force:
            return list(self._cache.values())

        self._cache.clear()
        self._domain_map.clear()

        if not SKILLS_DIR.exists():
            logger.warning(f"Skills directory not found: {SKILLS_DIR}")
            return []

        for skill_dir in SKILLS_DIR.iterdir():
            if not skill_dir.is_dir():
                continue

            # 除外するディレクトリ
            if skill_dir.name.startswith("_") or skill_dir.name in ["core"]:
                continue

            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue

            skill = self._parse_skill(skill_dir, skill_md)
            if skill:
                self._cache[skill.name] = skill
                if skill.domain:
                    self._domain_map[skill.domain] = skill
                    logger.info(f"Loaded skill: {skill.name} (domain: {skill.domain})")

        self._loaded = True
        return list(self._cache.values())

    def _parse_skill(self, skill_dir: Path, skill_md: Path) -> Optional[GeneratedSkill]:
        """SKILL.mdをパースしてスキル情報を取得"""
        try:
            content = skill_md.read_text(encoding="utf-8")

            # YAML frontmatter をパース
            name = skill_dir.name
            description = ""
            domain = None

            frontmatter_match = re.match(r'^---\n(.*?)\n---\n', content, re.DOTALL)
            if frontmatter_match:
                try:
                    meta = yaml.safe_load(frontmatter_match.group(1))
                    if meta:
                        name = meta.get('name', skill_dir.name)
                        description = meta.get('description', '')
                        domain = meta.get('domain')
                except yaml.YAMLError:
                    logger.warning(f"Failed to parse YAML frontmatter in {skill_md}")
                # frontmatter以降を本文として扱う
                body = content[len(frontmatter_match.group(0)):]
            else:
                body = content

            # 生成日時を確認（生成されたスキルかどうか）
            generated_at = None
            gen_match = re.search(r"生成日時:\s*(.+)", body)
            if gen_match:
                generated_at = gen_match.group(1).strip()

            # タイトル（frontmatterがない場合のフォールバック）
            title_match = re.search(r"^#\s+(.+)", body, re.MULTILINE)
            title = title_match.group(1).strip() if title_match else name

            # 元タスク
            task_match = re.search(r"元タスク\s*\n(.+?)(?=\n##|\n\n|$)", body, re.DOTALL)
            original_task = task_match.group(1).strip() if task_match else ""

            # ドメイン（frontmatterになければ本文から抽出）
            if not domain:
                # まず domain: 形式を試す
                domain_match = re.search(r"^domain:\s*(\S+)", body, re.MULTILINE)
                if domain_match:
                    domain = domain_match.group(1).strip()
                else:
                    # URL形式からも抽出を試みる
                    url_match = re.search(r"https?://([^/\s]+)", body)
                    if url_match:
                        domain = url_match.group(1)

            # アクション一覧
            actions = []
            action_matches = re.findall(r"\|\s*`(\w+(?:-\w+)*)`\s*\|", body)
            actions = action_matches if action_matches else []

            # セレクタヒント
            selectors_hints = None
            hints_file = skill_dir / "selectors_hints.txt"
            if hints_file.exists():
                selectors_hints = hints_file.read_text(encoding="utf-8")

            return GeneratedSkill(
                name=name,
                title=title,
                description=description,
                domain=domain,
                original_task=original_task,
                actions=actions,
                selectors_hints=selectors_hints,
                skill_md_path=skill_md,
                generated_at=generated_at,
            )
        except Exception as e:
            logger.error(f"Failed to parse skill {skill_dir}: {e}")
            return None

    def get_skill_by_domain(self, domain: str) -> Optional[GeneratedSkill]:
        """ドメインに対応するスキルを取得"""
        if not self._loaded:
            self.load_all()

        # 完全一致
        if domain in self._domain_map:
            return self._domain_map[domain]

        # 部分一致（サブドメイン対応）
        for skill_domain, skill in self._domain_map.items():
            if domain.endswith(skill_domain) or skill_domain.endswith(domain):
                return skill

        return None

    def get_skill_by_name(self, name: str) -> Optional[GeneratedSkill]:
        """名前でスキルを取得"""
        if not self._loaded:
            self.load_all()
        return self._cache.get(name)

    def get_hints_for_site(self, site: str) -> Optional[str]:
        """サイトに対応するセレクタヒントを取得"""
        # siteからドメインを抽出
        domain = site.lower().replace("https://", "").replace("http://", "")
        domain = domain.split("/")[0]  # パスを除去

        skill = self.get_skill_by_domain(domain)
        if skill and skill.selectors_hints:
            return skill.selectors_hints

        return None

    def get_generated_skills_summary(self) -> str:
        """生成されたスキルのサマリーを取得（プロンプト注入用）"""
        if not self._loaded:
            self.load_all()

        generated = [s for s in self._cache.values() if s.generated_at]
        if not generated:
            return ""

        lines = ["## 自動生成されたスキル"]
        lines.append("")
        lines.append("以下のスキルは過去の成功操作から自動生成されました。**専用ツールとして使用可能**です。")
        lines.append("")

        for skill in generated:
            domain_info = f" ({skill.domain})" if skill.domain else ""
            lines.append(f"- **{skill.name}**{domain_info}")
            if skill.description:
                lines.append(f"  - 説明: {skill.description}")
            if skill.original_task:
                lines.append(f"  - タスク: {skill.original_task}")
            lines.append(f"  - 使い方: `[TOOL: {skill.name} execute]`")

        lines.append("")
        lines.append("### 重要：生成スキルの優先使用")
        lines.append("同じサイト・同じタスクには、visual_browseではなく**生成されたスキルを使う**。")
        lines.append("スキルは過去の成功パターンを再現するため、より高速で確実。")

        return "\n".join(lines)


# シングルトンインスタンス
_loader: Optional[SkillLoader] = None


def get_skill_loader() -> SkillLoader:
    """SkillLoaderのシングルトンを取得"""
    global _loader
    if _loader is None:
        _loader = SkillLoader()
    return _loader
