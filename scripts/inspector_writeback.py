#!/usr/bin/env python3
"""inspector_writeback: DB の Inspector 編集を JSX に書き戻す。

Usage: python scripts/inspector_writeback.py --slug kittoku [--dry-run] [--keep-overrides]

仕組み:
1. inspector_overrides テーブルから artifact_slug=<slug> の行を取得
2. element_key が `@<editId>` 形式の v2 エントリだけ処理
3. frontend/src/app/artifacts/<slug>/ 配下の .tsx を全て読み、
   data-edit-id="<editId>" を持つ JSX タグに以下を適用:
   - text: 開始タグ ~ 閉じタグの間のテキストを置換
   - blockStyle/styles: style={{...}} prop を追加 or マージ
   - extraAttrs: src/href/alt/title 等を上書き
4. 適用成功した override 行を DB から削除（--keep-overrides で保持可）

制約:
- spans (部分テキスト装飾) は未対応 → 警告のみ
- className 編集は未対応（Tailwind マージが面倒）
- 同 editId が複数ファイルに出る場合は最初のヒットのみ
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _supabase_client():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL と SUPABASE_SERVICE_ROLE_KEY が必要")
    from supabase import create_client
    return create_client(url, key)


def _fetch_overrides(slug):
    sb = _supabase_client()
    res = sb.table("inspector_overrides").select("*").eq("artifact_slug", slug).execute()
    return res.data or []


def _delete_overrides(ids):
    if not ids:
        return 0
    sb = _supabase_client()
    res = sb.table("inspector_overrides").delete().in_("id", ids).execute()
    return len(res.data or [])


def _normalize_to_v2(row):
    """v2 (attrs.v=2) または v1 (styles のみ) の override を統一形式に。

    全部空（styles={}, text/blockStyle/extraAttrs/spans 全て空）なら None を返す
    → 呼び出し側で「ゴミ行」としてスキップ＋削除候補にできる。
    """
    attrs = row.get("attrs") or {}
    styles = row.get("styles") or {}
    out = {"text": None, "blockStyle": dict(styles), "spans": [], "extraAttrs": {}}
    if attrs.get("v") == 2:
        if isinstance(attrs.get("text"), str):
            out["text"] = attrs["text"]
        if isinstance(attrs.get("blockStyle"), dict):
            out["blockStyle"].update(attrs["blockStyle"])
        if isinstance(attrs.get("spans"), list):
            out["spans"] = attrs["spans"]
        if isinstance(attrs.get("extraAttrs"), dict):
            out["extraAttrs"] = attrs["extraAttrs"]
    # v1 でも attrs に html/text が入ってることがある（後方互換）
    elif isinstance(attrs.get("text"), str) and attrs.get("text"):
        out["text"] = attrs["text"]

    # 何も中身が無ければ None（ゴミ行）
    if not out["text"] and not out["blockStyle"] and not out["extraAttrs"] and not out["spans"]:
        return None
    return out


def _find_tsx_files(slug):
    base = PROJECT_ROOT / "frontend" / "src" / "app" / "artifacts" / slug
    if not base.exists():
        return []
    return list(base.rglob("*.tsx"))


def _find_open_tag(src, edit_id):
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


_TAG_NAME_RE = re.compile(r"^<([A-Za-z][A-Za-z0-9_.-]*)")


def _tag_name(t):
    m = _TAG_NAME_RE.match(t)
    return m.group(1) if m else None


def _is_self_closing(t):
    return t.rstrip().endswith("/>")


def _apply_text(src, open_start, open_end, tag_html, new_text):
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
        sys.stderr.write(
            "  [skip text] {} child has JSX expr: {}\n".format(name, inner.strip()[:60])
        )
        return src
    return src[:open_end] + new_text + src[close_idx:]


def _merge_or_insert_style(tag_html, block_style):
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


def _set_attr(tag_html, attr_name, value):
    pattern = re.compile(r"\b" + re.escape(attr_name) + r'="[^"]*"')
    new_assign = '{}="{}"'.format(attr_name, value)
    if pattern.search(tag_html):
        return pattern.sub(new_assign, tag_html, count=1)
    if tag_html.rstrip().endswith("/>"):
        cut = tag_html.rfind("/>")
        return tag_html[:cut] + " " + new_assign + " " + tag_html[cut:]
    cut = tag_html.rfind(">")
    return tag_html[:cut] + " " + new_assign + tag_html[cut:]


def _apply_to_file(file_path, edit_id, model):
    src = file_path.read_text(encoding="utf-8")
    found = _find_open_tag(src, edit_id)
    if not found:
        return False
    open_start, open_end, tag_html = found
    new_tag = tag_html
    if model.get("blockStyle"):
        new_tag = _merge_or_insert_style(new_tag, model["blockStyle"])
    for name, val in (model.get("extraAttrs") or {}).items():
        if name in {"href", "src", "alt", "title", "aria-label", "data-edit-id"}:
            new_tag = _set_attr(new_tag, name, str(val))
        else:
            sys.stderr.write(
                "  [skip attr] {} {} not supported in MVP\n".format(edit_id, name)
            )
    if new_tag != tag_html:
        src = src[:open_start] + new_tag + src[open_end:]
        found2 = _find_open_tag(src, edit_id)
        if found2:
            _, open_end, new_tag = found2
    if model.get("text") is not None:
        if model.get("spans"):
            sys.stderr.write("  [warn spans] {} partial-style not supported\n".format(edit_id))
        src = _apply_text(src, open_start, open_end, new_tag, model["text"])
    file_path.write_text(src, encoding="utf-8")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep-overrides", action="store_true")
    args = ap.parse_args()
    print("[writeback] slug={} dry_run={}".format(args.slug, args.dry_run))
    overrides = _fetch_overrides(args.slug)
    print("[writeback] {} overrides fetched".format(len(overrides)))
    files = _find_tsx_files(args.slug)
    print("[writeback] target .tsx files: {}".format(len(files)))
    applied_ids = []
    empty_ids = []  # 中身ゼロのゴミ行（消すだけ）
    skipped = []
    for row in overrides:
        ek = row.get("element_key", "")
        if not ek.startswith("@"):
            skipped.append((row.get("id"), "legacy element_key"))
            continue
        edit_id = ek[1:]
        model = _normalize_to_v2(row)
        if not model:
            empty_ids.append(row["id"])
            continue
        applied = False
        for f in files:
            if _apply_to_file(f, edit_id, model):
                print("  [apply] {} -> {}".format(edit_id, f.relative_to(PROJECT_ROOT)))
                applied = True
                break
        if applied:
            applied_ids.append(row["id"])
        else:
            skipped.append((row.get("id"), "data-edit-id={} not found".format(edit_id)))
    print()
    print("[writeback] applied: {}".format(len(applied_ids)))
    print("[writeback] empty (will delete): {}".format(len(empty_ids)))
    print("[writeback] skipped: {}".format(len(skipped)))
    for sid, reason in skipped[:10]:
        print("  - {}: {}".format(sid, reason))
    if not args.dry_run and not args.keep_overrides:
        to_delete = applied_ids + empty_ids
        if to_delete:
            deleted = _delete_overrides(to_delete)
            print("[writeback] deleted {} rows from DB ({} applied + {} empty)".format(
                deleted, len(applied_ids), len(empty_ids)
            ))
    elif args.dry_run:
        print("[writeback] dry-run: files modified but DB intact")
    return 0


if __name__ == "__main__":
    sys.exit(main())
