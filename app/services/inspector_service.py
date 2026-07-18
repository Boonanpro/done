"""
inspector のビジネスロジック

React の Fiber debug source (fileName + lineNumber + columnNumber) で特定された
JSX 要素に、Inspector で調整したスタイル/属性を書き戻す。
"""
import re
import logging
from pathlib import Path
from typing import Optional, Dict

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _format_jsx_value(value: str) -> str:
    """CSS 値を JSX スタイルオブジェクトの値形式にする。"""
    v = str(value).strip()
    # React の style prop は !important を object 形式でサポートしないので除去
    v = re.sub(r"\s*!important\s*$", "", v)
    if v.startswith("'") or v.startswith('"') or v.startswith('`') or v.startswith('{'):
        return v
    if re.fullmatch(r"-?\d+(\.\d+)?", v):
        return v
    return f"'{v}'"


def _to_camel_case(prop: str) -> str:
    """CSS プロパティ名を React style オブジェクト向けに camelCase 化。
    例: background-color → backgroundColor, aspect-ratio → aspectRatio"""
    if not prop or "-" not in prop:
        return prop
    parts = prop.split("-")
    return parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:] if p)


def _find_jsx_tag_end(contents: str, start_pos: int) -> int:
    """start_pos の '<' から始まる JSX 開始タグの終端 '>' の位置を返す。
    内側に {} や文字列がある場合もネストを追って正しく終端を見つける。"""
    depth_brace = 0
    in_string: Optional[str] = None
    pos = start_pos
    n = len(contents)
    while pos < n:
        ch = contents[pos]
        if in_string:
            if ch == "\\":
                pos += 2
                continue
            if ch == in_string:
                in_string = None
        elif ch in ("'", '"', "`"):
            in_string = ch
        elif ch == "{":
            depth_brace += 1
        elif ch == "}":
            depth_brace -= 1
        elif depth_brace == 0 and ch == ">":
            return pos
        pos += 1
    return -1


def _parse_style_object(raw: str) -> Dict[str, str]:
    """`key: val, key2: val2` 形式を雑にパース。ネスト {} 非対応の MVP 実装"""
    result: Dict[str, str] = {}
    # カンマで分割（crude）
    depth = 0
    parts = []
    current = []
    for ch in raw:
        if ch == "{":
            depth += 1
            current.append(ch)
        elif ch == "}":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current))
    for pair in parts:
        pair = pair.strip()
        if not pair or ":" not in pair:
            continue
        k, v = pair.split(":", 1)
        k = k.strip().strip("'\"")
        result[k] = v.strip()
    return result


def _merge_style_attr(tag: str, new_styles: Dict[str, str]) -> str:
    """開始タグ内の style={{ ... }} をマージ or 新規追加。
    プロパティ名は React の style prop 向けに camelCase 化する。"""
    if not new_styles:
        return tag
    # kebab-case → camelCase
    camel_styles: Dict[str, str] = {
        _to_camel_case(k): v for k, v in new_styles.items()
    }
    m = re.search(r"style=\{\{([^{}]*)\}\}", tag)
    existing: Dict[str, str] = {}
    if m:
        # 既存 style も camelCase で格納されているはず。キーを念のため camelCase 化
        parsed = _parse_style_object(m.group(1))
        existing = {_to_camel_case(k): v for k, v in parsed.items()}
    for k, v in camel_styles.items():
        existing[k] = _format_jsx_value(v)
    content = ", ".join(f"{k}: {existing[k]}" for k in existing)
    new_style_expr = "style={{ " + content + " }}"
    if m:
        return tag[: m.start()] + new_style_expr + tag[m.end() :]
    if tag.endswith("/>"):
        return tag[:-2].rstrip() + " " + new_style_expr + " />"
    return tag[:-1].rstrip() + " " + new_style_expr + ">"


def _merge_attr(tag: str, name: str, value: str) -> str:
    """開始タグ内の属性 name=... を置換 or 追加"""
    # src / alt / poster など文字列属性。既存が単純な文字列リテラルなら置換
    pattern = rf'\b{re.escape(name)}=(?:"[^"]*"|\'[^\']*\'|\{{[^{{}}]*\}})'
    if re.search(pattern, tag):
        return re.sub(pattern, f'{name}="{value}"', tag, count=1)
    # 追加
    insertion = f' {name}="{value}"'
    if tag.endswith("/>"):
        return tag[:-2].rstrip() + insertion + " />"
    return tag[:-1].rstrip() + insertion + ">"


def apply_edit(
    file_path: str,
    line_number: int,
    column_number: Optional[int],
    styles: Optional[Dict[str, str]],
    attrs: Optional[Dict[str, str]],
) -> Dict:
    # パス検証
    resolved = Path(file_path).resolve()
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError:
        raise PermissionError(f"File outside project root: {file_path}")
    if not resolved.exists():
        raise FileNotFoundError(file_path)

    contents = resolved.read_text(encoding="utf-8")
    lines = contents.split("\n")
    if line_number < 1 or line_number > len(lines):
        raise ValueError(f"line_number {line_number} out of range (file has {len(lines)} lines)")

    # 指定された行・列付近の '<' を探す
    # column_number が与えられていればそこを起点に、
    # なければその行の最初の '<' を使う
    line_start_pos = sum(len(l) + 1 for l in lines[: line_number - 1])
    target_line = lines[line_number - 1]
    if column_number and 0 <= column_number - 1 < len(target_line):
        lt_in_line = target_line.find("<", column_number - 1)
    else:
        lt_in_line = target_line.find("<")
    if lt_in_line < 0:
        # 行に < がない場合、行内を後ろから or 次の行を探す
        lt_in_line = target_line.find("<")
    if lt_in_line < 0:
        raise ValueError(f"No JSX opening '<' found at line {line_number}")

    start_pos = line_start_pos + lt_in_line
    end_pos = _find_jsx_tag_end(contents, start_pos)
    if end_pos < 0:
        raise ValueError(f"Could not find matching '>' for tag at line {line_number}")

    tag = contents[start_pos : end_pos + 1]
    patched = tag
    if styles:
        patched = _merge_style_attr(patched, styles)
    if attrs:
        for k, v in attrs.items():
            patched = _merge_attr(patched, k, v)
    if patched == tag:
        return {
            "success": True,
            "file_path": str(resolved),
            "line_number": line_number,
            "patched_tag": None,
            "error": "no-op",
        }

    new_contents = contents[:start_pos] + patched + contents[end_pos + 1 :]
    resolved.write_text(new_contents, encoding="utf-8")
    logger.info(f"[inspector] patched {resolved}:{line_number}")

    return {
        "success": True,
        "file_path": str(resolved),
        "line_number": line_number,
        "patched_tag": patched,
    }
