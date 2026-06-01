"""
Skill 系统：统一注册表管理 Skill 的元信息与完整内容。

SkillManifest —— 技能的元信息（名称、描述等）
SkillDocument —— 可被加载的完整技能（manifest + body）
SkillRegistry —— 统一注册表，回答"有哪些 skill"和"某个 skill 的完整内容是什么"
"""

import yaml

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


@dataclass(frozen=True)
class SkillManifest:
    """技能的元信息。"""
    name: str
    description: str


@dataclass(frozen=True)
class SkillDocument:
    """可被加载的完整技能。"""
    manifest: SkillManifest
    body: str


class SkillRegistry:
    """
    统一注册表，集中管理所有 Skill。

    用法:
        registry = SkillRegistry()
        registry.register(SkillDocument(...))
        registry.register(SkillDocument(...))

        # 有哪些 skill 可用
        registry.list_skills() -> [SkillManifest(...), ...]

        # 某个 skill 的完整内容
        registry.get_skill("code-review") -> SkillDocument(...)
    """

    def __init__(self):
        self._skills: Dict[str, SkillDocument] = {}

    def register(self, doc: SkillDocument) -> None:
        """注册一个 SkillDocument。"""
        name = doc.manifest.name
        if name in self._skills:
            raise KeyError(f"Skill '{name}' is already registered.")
        self._skills[name] = doc

    def register_from_raw(self, name: str, description: str, body: str) -> None:
        """从原始数据创建并注册 SkillDocument。"""
        manifest = SkillManifest(name=name, description=description)
        doc = SkillDocument(manifest=manifest, body=body)
        self.register(doc)

    def load_from_dir(self, skills_dir: str) -> int:
        """
        从指定目录加载所有 skill。

        目录结构:
            skills/
              code-review/
                SKILL.md
              git-workflow/
                SKILL.md

        每个 SKILL.md 文件格式:
            ---
            name: code-review
            description: Checklist for reviewing code changes
            ---
            ## Code Review Checklist
            ...

        返回成功加载的 skill 数量。
        """
        base = Path(skills_dir)
        if not base.is_dir():
            raise NotADirectoryError(f"Skills directory not found: {base}")

        loaded = 0
        for entry in sorted(base.iterdir()):
            if not entry.is_dir():
                continue
            skill_md = entry / "SKILL.md"
            if not skill_md.is_file():
                continue

            doc = self._parse_skill_md(skill_md)
            if doc is not None:
                self.register(doc)
                loaded += 1

        return loaded

    @staticmethod
    def _parse_skill_md(path: Path) -> Optional[SkillDocument]:
        """解析单个 SKILL.md 文件（YAML front matter + body），返回 SkillDocument。"""
        text = path.read_text(encoding="utf-8")

        # 用 yaml 解析 front matter（--- ... --- 之间的部分）
        if not text.startswith("---"):
            return None

        parts = text.split("---", 2)
        if len(parts) < 3:
            return None

        _, front_matter, body = parts
        meta = yaml.safe_load(front_matter)

        if not isinstance(meta, dict):
            return None

        name = meta.get("name")
        description = meta.get("description")
        if not name or not description:
            return None

        manifest = SkillManifest(name=name, description=description)
        return SkillDocument(manifest=manifest, body=body.strip())

    def list_skills(self) -> list[SkillManifest]:
        """返回所有已注册技能的元信息列表。"""
        return [doc.manifest for doc in self._skills.values()]

    def get_skill(self, name: str) -> Optional[SkillDocument]:
        """根据名称获取完整的 SkillDocument，不存在时返回 None。"""
        return self._skills.get(name)

    def has_skill(self, name: str) -> bool:
        """检查指定名称的技能是否已注册。"""
        return name in self._skills

    def remove(self, name: str) -> None:
        """移除指定名称的技能。"""
        self._skills.pop(name, None)

    def __len__(self) -> int:
        return len(self._skills)

    def __contains__(self, name: str) -> bool:
        return name in self._skills
