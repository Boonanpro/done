"""inspector_writeback_core: JSX ファイルへの直接書き込みロジック。

scripts/inspector_writeback.py から共通ロジックを抽出した版。
直書き API（DB をバイパスして JSX を直接更新）と一括 writeback の両方から使う。

制約:
- spans (部分テキスト装飾) は未対応 → 警告のみ
- className 編集は未対応
- 同 editId が複数ファイルに出る場合は最初のヒットのみ
- text 子要素に JSX 式が含まれる場合は text 適用をスキップ（壊れるため）
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

_TAG_NAME_RE = re.compile(r"^<([A-Za-z][A-Za-z0-9_.-]*)")

ALLOWED_ATTRS = {"href", "src", "alt", "title", "aria-label", "data-edit-id"}


def find_artifact_tsx_files(slug: str) -> list[Path]:
    base = PROJECT_ROOT / "frontend" / "src" / "app" / "artifacts" / slug
    if not base.exists():
        return []
    return list(base.rglob("*.tsx"))


def normalize_to_v2(styles: dict | None, attrs: dict | None) -> dict | None:
    """API 入力 (styles + attrs) を writeback の v2 model に正規化。

    全部空なら None を返す（書き込み不要）。
    """
    styles = styles or {}
    attrs = attrs or {}
    out = {"text": None, "blockStyle": dict(styles), "spans": [], "extraAttrs": {}}

    if isinstance(attrs.get("model_v2"), str):
        try:
            model = json.loads(attrs["model_v2"])
        except json.JSONDecodeError:
            model = None
        if isinstance(model, dict):
            if model.get("v") == 2:
                if isinstance(model.get("text"), str):
                    out["text"] = model["text"]
                if isinstance(model.get("blockStyle"), dict):
                    out["blockStyle"].update(model["blockStyle"])
                if isinstance(model.get("spans"), list):
                    out["spans"] = model["spans"]
                extra = model.get("attrs") or model.get("extraAttrs")
                if isinstance(extra, dict):
                    out["extraAttrs"].update(extra)
    if attrs.get("v") == 2:
        if isinstance(attrs.get("text"), str):
            out["text"] = attrs["text"]
        if isinstance(attrs.get("blockStyle"), dict):
            out["blockStyle"].update(attrs["blockStyle"])
        if isinstance(attrs.get("spans"), list):
            out["spans"] = attrs["spans"]
        if isinstance(attrs.get("extraAttrs"), dict):
            out["extraAttrs"] = attrs["extraAttrs"]
    elif isinstance(attrs.get("text"), str) and attrs.get("text"):
        out["text"] = attrs["text"]

    if not out["text"] and not out["blockStyle"] and not out["extraAttrs"] and not out["spans"]:
        return None
    return out


def _find_open_tag(src: str, edit_id: str):
    needle = 'data-edit-id="' + edit_id + '"'
    idx = src.find(needle)
    if idx < 0:
        return None
    lt = src.rfind("<", 0, idx)
    if lt < 0:
        return None
    depth = 0
    pos = lt + 1
    while pos < len(src):
        c = src[pos]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c == ">" and depth == 0:
            return (lt, pos + 1, src[lt:pos + 1])
        pos += 1
    return None


def _tag_name(t: str):
    m = _TAG_NAME_RE.match(t)
    return m.group(1) if m else None


def _is_self_closing(t: str) -> bool:
    return t.rstrip().endswith("/>")


def _apply_text(src: str, open_start: int, open_end: int, tag_html: str, new_text: str) -> str:
    if _is_self_closing(tag_html):
        return src
    name = _tag_name(tag_html)
    if not name:
        return src
    close = "</" + name + ">"
    close_idx = src.find(close, open_end)
    if close_idx < 0:
        return src
    inner = src[open_end:close_idx]
    if "{" in inner and "}" in inner:
        return src  # JSX 式が混ざっていたら壊れるので skip
    return src[:open_end] + new_text + src[close_idx:]


def _merge_or_insert_style(tag_html: str, block_style: dict) -> str:
    if not block_style:
        return tag_html
    pairs = []
    for k, v in block_style.items():
        v_str = str(v).replace('"', '\\"')
        pairs.append('"{}": "{}"'.format(k, v_str))
    style_obj = ", ".join(pairs)
    new_prop = "style={{" + style_obj + "}}"
    m = re.search(r"\bstyle=\{\{([^}]*)\}\}", tag_html)
    if m:
        existing = m.group(1).strip().rstrip(",")
        merged = (existing + ", " + style_obj) if existing else style_obj
        return tag_html[:m.start()] + "style={{" + merged + "}}" + tag_html[m.end():]
    if tag_html.rstrip().endswith("/>"):
        cut = tag_html.rfind("/>")
        return tag_html[:cut] + " " + new_prop + " " + tag_html[cut:]
    cut = tag_html.rfind(">")
    return tag_html[:cut] + " " + new_prop + tag_html[cut:]


def _set_attr(tag_html: str, attr_name: str, value: str) -> str:
    pattern = re.compile(r"\b" + re.escape(attr_name) + r'="[^"]*"')
    new_assign = '{}="{}"'.format(attr_name, value)
    if pattern.search(tag_html):
        return pattern.sub(new_assign, tag_html, count=1)
    if tag_html.rstrip().endswith("/>"):
        cut = tag_html.rfind("/>")
        return tag_html[:cut] + " " + new_assign + " " + tag_html[cut:]
    cut = tag_html.rfind(">")
    return tag_html[:cut] + " " + new_assign + tag_html[cut:]


def apply_override_to_file(file_path: Path, edit_id: str, model: dict) -> tuple[bool, bool]:
    """指定ファイルの data-edit-id 要素に override を適用。

    Returns (found, changed).
    """
    src = file_path.read_text(encoding="utf-8")
    original = src
    found = _find_open_tag(src, edit_id)
    if not found:
        return False, False
    open_start, open_end, tag_html = found
    new_tag = tag_html
    if model.get("blockStyle"):
        new_tag = _merge_or_insert_style(new_tag, model["blockStyle"])
    for name, val in (model.get("extraAttrs") or {}).items():
        if name in ALLOWED_ATTRS:
            new_tag = _set_attr(new_tag, name, str(val))
    if new_tag != tag_html:
        src = src[:open_start] + new_tag + src[open_end:]
        found2 = _find_open_tag(src, edit_id)
        if found2:
            _, open_end, new_tag = found2
    if model.get("text") is not None:
        src = _apply_text(src, open_start, open_end, new_tag, model["text"])
    changed = src != original
    if changed:
        file_path.write_text(src, encoding="utf-8")
    return True, changed


def apply_override_for_slug(slug: str, element_key: str, styles: dict | None, attrs: dict | None) -> dict[str, Any]:
    """slug の artifact 配下から element_key に対応する JSX を見つけて override を適用。

    Returns: {"applied": bool, "file": str | None, "reason": str | None}
    """
    if not element_key.startswith("@"):
        return {"applied": False, "file": None, "reason": "legacy element_key (DOM path) not supported"}
    edit_id = element_key[1:]

    model = normalize_to_v2(styles, attrs)
    if not model:
        return {"applied": False, "file": None, "reason": "empty override (no text/style/attrs)"}

    files = find_artifact_tsx_files(slug)
    if not files:
        return {"applied": False, "file": None, "reason": "no artifact files for slug={}".format(slug)}

    for f in files:
        found, changed = apply_override_to_file(f, edit_id, model)
        if found:
            return {
                "applied": changed,
                "file": str(f.relative_to(PROJECT_ROOT)),
                "reason": None if changed else "no diff (already up-to-date)",
            }

    return {"applied": False, "file": None, "reason": "data-edit-id={} not found in any artifact file".format(edit_id)}
