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
ARTIFACTS_ROOT = PROJECT_ROOT / "frontend" / "src" / "app" / "artifacts"

_TAG_NAME_RE = re.compile(r"^<([A-Za-z][A-Za-z0-9_.-]*)")

ALLOWED_ATTRS = {"href", "src", "alt", "title", "aria-label", "data-edit-id"}


class WritebackScopeError(RuntimeError):
    """Inspector writeback がアーティファクトのスコープ外に書き出そうとした時に上がる。"""


def _artifact_root(slug: str) -> Path:
    if not slug or "/" in slug or "\\" in slug or ".." in slug:
        raise WritebackScopeError(f"invalid slug: {slug!r}")
    return ARTIFACTS_ROOT / slug


def _ensure_under_artifact(file_path: Path, slug: str) -> Path:
    """resolve したパスが frontend/src/app/artifacts/<slug>/ 配下であることを保証する。

    Inspector writeback の唯一の意図は「指定アーティファクトの JSX を書き換える」こと。
    ここを越えた書き込みは構造的なバグかパストラバーサルなので例外で止める。
    """
    root = _artifact_root(slug).resolve()
    target = Path(file_path).resolve()
    try:
        target.relative_to(root)
    except ValueError as e:
        raise WritebackScopeError(
            f"writeback target {target} is outside artifact scope {root}"
        ) from e
    return target


def find_artifact_tsx_files(slug: str) -> list[Path]:
    base = _artifact_root(slug)
    if not base.exists():
        return []
    # rglob は base に閉じているので追加の path-traversal チェックは不要。
    # ただし symlink がアーティファクト外に貼られているとすり抜けるので、
    # _ensure_under_artifact を通してフィルタする。
    out: list[Path] = []
    for f in base.rglob("*.tsx"):
        try:
            _ensure_under_artifact(f, slug)
        except WritebackScopeError:
            continue
        out.append(f)
    return out


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


def apply_override_to_file(
    file_path: Path,
    edit_id: str,
    model: dict,
    *,
    slug: str,
) -> tuple[bool, bool, str | None, str | None]:
    """指定ファイルの data-edit-id 要素に override を適用。

    Returns (found, changed, before_content, after_content).
    before/after は Undo 用。変更なしなら after_content=None。
    file_path はかならず frontend/src/app/artifacts/<slug>/ 配下でなければならない。
    """
    file_path = _ensure_under_artifact(file_path, slug)
    src = file_path.read_text(encoding="utf-8")
    original = src
    found = _find_open_tag(src, edit_id)
    if not found:
        return False, False, None, None
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
        return True, True, original, src
    return True, False, original, None


def apply_override_for_slug(slug: str, element_key: str, styles: dict | None, attrs: dict | None) -> dict[str, Any]:
    """slug の artifact 配下から element_key に対応する JSX を見つけて override を適用。

    Returns: {"applied": bool, "file": str | None, "reason": str | None,
              "before_content": str | None, "after_content": str | None}
    """
    if not element_key.startswith("@"):
        return {
            "applied": False, "file": None,
            "reason": "legacy element_key (DOM path) not supported",
            "before_content": None, "after_content": None,
        }
    edit_id = element_key[1:]

    model = normalize_to_v2(styles, attrs)
    if not model:
        return {
            "applied": False, "file": None,
            "reason": "empty override (no text/style/attrs)",
            "before_content": None, "after_content": None,
        }

    files = find_artifact_tsx_files(slug)
    if not files:
        return {
            "applied": False, "file": None,
            "reason": "no artifact files for slug={}".format(slug),
            "before_content": None, "after_content": None,
        }

    for f in files:
        found, changed, before, after = apply_override_to_file(f, edit_id, model, slug=slug)
        if found:
            return {
                "applied": changed,
                "file": str(f.relative_to(PROJECT_ROOT)),
                "reason": None if changed else "no diff (already up-to-date)",
                "before_content": before,
                "after_content": after,
            }

    return {
        "applied": False, "file": None,
        "reason": "data-edit-id={} not found in any artifact file".format(edit_id),
        "before_content": None, "after_content": None,
    }


# ============================================================================
# 要素削除（ハード削除）
# ============================================================================

# 削除を拒否するタグ（ページ全体を壊す）
_DELETE_REFUSED_TAGS = {"html", "body", "head", "main"}


def _find_matching_close(src: str, tag_name: str, scan_from: int) -> int | None:
    """`<tag_name ...>` の開きタグに対応する `</tag_name>` を探し、その末尾位置を返す。

    scan_from は開きタグの直後（`>` の次）を指している前提。
    JSX 式 `{...}` 内のブレース深さを尊重しつつ、同名タグのネストを正しく数える。
    自己閉じタグ `<tag_name ... />` は depth に影響しない。
    見つからなければ None。
    """
    n = len(src)
    pos = scan_from
    depth = 1  # 開きタグ 1 個分は既に入っている
    brace = 0

    # 単語境界を担保: `<TagNameFoo` を `<TagName` と誤マッチしない
    open_re = re.compile(r"<" + re.escape(tag_name) + r"(?=[\s/>])")
    close_re = re.compile(r"</" + re.escape(tag_name) + r"\s*>")

    while pos < n:
        c = src[pos]
        if c == "{":
            brace += 1
            pos += 1
            continue
        if c == "}":
            brace -= 1
            pos += 1
            continue
        if brace > 0:
            pos += 1
            continue
        if c != "<":
            pos += 1
            continue
        # 閉じタグ優先で試す
        cm = close_re.match(src, pos)
        if cm:
            depth -= 1
            if depth == 0:
                return cm.end()
            pos = cm.end()
            continue
        # 同名の開きタグ
        om = open_re.match(src, pos)
        if om:
            # 開きタグの末尾を探す（自己閉じか否かを判定するため）
            t_brace = 0
            t_pos = pos + 1
            t_end: int | None = None
            while t_pos < n:
                ch = src[t_pos]
                if ch == "{":
                    t_brace += 1
                elif ch == "}":
                    t_brace -= 1
                elif ch == ">" and t_brace == 0:
                    t_end = t_pos + 1
                    break
                t_pos += 1
            if t_end is None:
                return None  # 不正
            tag_html = src[pos:t_end]
            if not tag_html.rstrip().endswith("/>"):
                depth += 1
            pos = t_end
            continue
        pos += 1
    return None


def remove_element_from_file(
    file_path: Path,
    edit_id: str,
    *,
    slug: str,
) -> tuple[bool, bool, str | None, str | None, str | None]:
    """指定ファイルから data-edit-id=<edit_id> の JSX 要素を完全削除する。

    Returns: (found, removed, reason_if_not_removed, before_content, after_content)
    file_path はかならず frontend/src/app/artifacts/<slug>/ 配下でなければならない。
    """
    file_path = _ensure_under_artifact(file_path, slug)
    src = file_path.read_text(encoding="utf-8")
    found = _find_open_tag(src, edit_id)
    if not found:
        return False, False, None, None, None
    open_start, open_end, tag_html = found
    tag_name = _tag_name(tag_html)
    if not tag_name:
        return True, False, "tag name not parsable", None, None
    if tag_name.lower() in _DELETE_REFUSED_TAGS:
        return True, False, "refuse to delete root tag <{}>".format(tag_name), None, None

    if _is_self_closing(tag_html):
        delete_end = open_end
    else:
        close_end = _find_matching_close(src, tag_name, open_end)
        if close_end is None:
            return True, False, "matching </{}> not found".format(tag_name), None, None
        delete_end = close_end

    # その行の前方の whitespace と末尾の改行も一緒に除去（見た目を綺麗に保つ）
    delete_start = open_start
    line_start = src.rfind("\n", 0, delete_start) + 1
    leading = src[line_start:delete_start]
    if leading.strip() == "":
        delete_start = line_start
        if delete_end < len(src) and src[delete_end] == "\n":
            delete_end += 1

    new_src = src[:delete_start] + src[delete_end:]
    if new_src == src:
        return True, False, "no diff", src, None
    file_path.write_text(new_src, encoding="utf-8")
    return True, True, None, src, new_src


def remove_element_for_slug(slug: str, element_key: str) -> dict[str, Any]:
    """slug の artifact 配下から element_key に対応する JSX 要素を完全削除。

    Returns: {"removed": bool, "file": str | None, "reason": str | None, "tag": str | None,
              "before_content": str | None, "after_content": str | None}
    """
    if not element_key.startswith("@"):
        return {
            "removed": False, "file": None,
            "reason": "legacy element_key (DOM path) not supported",
            "tag": None, "before_content": None, "after_content": None,
        }
    edit_id = element_key[1:]

    files = find_artifact_tsx_files(slug)
    if not files:
        return {
            "removed": False, "file": None,
            "reason": "no artifact files for slug={}".format(slug),
            "tag": None, "before_content": None, "after_content": None,
        }

    for f in files:
        found, removed, reason, before, after = remove_element_from_file(f, edit_id, slug=slug)
        if found:
            return {
                "removed": removed,
                "file": str(f.relative_to(PROJECT_ROOT)),
                "reason": reason, "tag": None,
                "before_content": before, "after_content": after,
            }

    return {
        "removed": False, "file": None,
        "reason": "data-edit-id={} not found in any artifact file".format(edit_id),
        "tag": None, "before_content": None, "after_content": None,
    }


# ============================================================================
# Undo 用: ファイル完全書き戻し
# ============================================================================


def restore_file_content(slug: str, file_path_rel: str, content: str) -> dict[str, Any]:
    """artifact 配下のファイルを指定内容で完全置換する（Undo用）。

    安全策:
    - file_path_rel は `frontend/src/app/artifacts/<slug>/` 配下のファイルに限定
    - .tsx / .ts / .css のみ許可（誤って .py を書き換える事故防止）

    Returns: {"restored": bool, "file": str | None, "reason": str | None,
              "before_content": str | None}
    """
    target = (PROJECT_ROOT / file_path_rel).resolve()
    expected_base = (PROJECT_ROOT / "frontend" / "src" / "app" / "artifacts" / slug).resolve()
    try:
        target.relative_to(expected_base)
    except ValueError:
        return {
            "restored": False, "file": None,
            "reason": "file path outside artifact dir for slug={}".format(slug),
            "before_content": None,
        }
    if target.suffix not in {".tsx", ".ts", ".css", ".js", ".jsx"}:
        return {
            "restored": False, "file": None,
            "reason": "unsupported file extension: {}".format(target.suffix),
            "before_content": None,
        }
    before: str | None = None
    if target.exists():
        before = target.read_text(encoding="utf-8")
        if before == content:
            return {
                "restored": False, "file": file_path_rel,
                "reason": "no diff (content unchanged)",
                "before_content": before,
            }
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {
        "restored": True,
        "file": file_path_rel,
        "reason": None,
        "before_content": before,
    }
