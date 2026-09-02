"""Inspector の手動編集機能を Playwright で実機動作確認するスクリプト。

前提:
- ローカル next.js dev server が http://localhost:3000 で動いている
- サンドボックス (port 8000) が DAN_DEV_NO_AUTH=1 で起動中
- /artifacts/test-edit と /test-inspector ページが配置済み

検証項目:
1. 削除ボタン: 「削除不可」と出ないか、押せるか、API が 200 を返すか
2. Ctrl+Z: 選択を外しても Undo が効くか
3. Ctrl+Y: Redo が効くか
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, Page, FrameLocator

ARTIFACT_FILE = Path("D:/done/frontend/src/app/artifacts/test-edit/page.tsx")

def snapshot_artifact() -> str:
    return ARTIFACT_FILE.read_text(encoding="utf-8")


def restore_artifact(content: str) -> None:
    ARTIFACT_FILE.write_text(content, encoding="utf-8")


def get_iframe(page: Page) -> FrameLocator:
    return page.frame_locator("iframe").first


def wait_for_element(page: Page, selector: str, timeout: int = 10000) -> None:
    page.wait_for_selector(selector, timeout=timeout)


def click_iframe_element(page: Page, edit_id: str) -> None:
    """iframe 内の data-edit-id を持つ要素をクリック。"""
    iframe = get_iframe(page)
    iframe.locator(f"[data-edit-id='{edit_id}']").first.click()
    time.sleep(0.4)


def main() -> int:
    original_content = snapshot_artifact()
    print(f"[setup] saved original artifact ({len(original_content)} chars)")

    results: list[tuple[str, bool, str]] = []

    def record(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))
        print(f"  {'OK' if ok else 'FAIL'} - {name}{(' - ' + detail) if detail else ''}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1400, "height": 900})
            page = context.new_page()
            page.on("console", lambda msg: print(f"  [console:{msg.type}] {msg.text}"))
            page.on("pageerror", lambda err: print(f"  [pageerror] {err}"))

            print("[step 1] Opening test-inspector harness...")
            page.goto("http://localhost:3000/test-inspector", wait_until="domcontentloaded")
            page.wait_for_selector("iframe", timeout=15000)
            # iframe が test-edit を読み込むまで待つ
            iframe = get_iframe(page)
            iframe.locator("[data-edit-id='te-h1']").first.wait_for(state="visible", timeout=15000)
            print("  iframe loaded with test-edit content")

            # ----- Case 1: data-edit-id を直接持つ要素を選択 → 削除ボタン状態 -----
            print("[case 1] Click h1 (has data-edit-id)")
            click_iframe_element(page, "te-h1")
            page.wait_for_timeout(500)

            # 削除ボタンを探す（Inspector ヘッダの中、Trash アイコン付き）
            delete_btn = page.locator("button:has(svg.lucide-trash-2)").first
            try:
                delete_btn.wait_for(state="visible", timeout=5000)
            except Exception as e:
                record("delete-btn-visible", False, f"button not visible: {e}")
                browser.close()
                return 1

            btn_text = delete_btn.text_content() or ""
            is_disabled = delete_btn.is_disabled()
            record(
                "case1: delete button enabled for h1 with data-edit-id",
                not is_disabled,
                f"text='{btn_text}', disabled={is_disabled}",
            )

            # ----- Case 2: wrapper (data-edit-id 無し、子に有り) を選択 -----
            # wrapper は data-edit-id を持たないので data-testid で選ぶ
            # （見た目クラスで選ぶとデザイン変更のたびにテストが壊れるため）。
            print("[case 2] Click wrapper without data-edit-id")
            iframe.locator("div[data-testid='te-case-wrapper-no-id']").first.click()
            page.wait_for_timeout(500)
            btn_text2 = delete_btn.text_content() or ""
            is_disabled2 = delete_btn.is_disabled()
            record(
                "case2: wrapper without data-edit-id offers descendant deletion",
                not is_disabled2,
                f"text='{btn_text2}', disabled={is_disabled2}",
            )

            # ----- Case 3: 完全に data-edit-id 無し（祖先も子も）-----
            print("[case 3] Click block with no data-edit-id anywhere")
            iframe.locator("div[data-testid='te-case-no-id']").first.click()
            page.wait_for_timeout(500)
            btn_text3 = delete_btn.text_content() or ""
            is_disabled3 = delete_btn.is_disabled()
            record(
                "case3: pure no-id block is disabled (expected)",
                is_disabled3,
                f"text='{btn_text3}', disabled={is_disabled3}",
            )

            # ----- Case 4: 削除を実行 → JSX が変わる -----
            print("[case 4] Delete te-final paragraph")
            click_iframe_element(page, "te-final")
            page.wait_for_timeout(300)
            btn_text4 = delete_btn.text_content() or ""
            print(f"  button before 1st click: '{btn_text4}'")
            delete_btn.click()  # 1回目: confirm 状態に
            page.wait_for_timeout(300)
            btn_text4b = delete_btn.text_content() or ""
            print(f"  button after 1st click: '{btn_text4b}'")
            delete_btn.click()  # 2回目: 実削除
            page.wait_for_timeout(1500)  # API完了待ち

            after_delete = snapshot_artifact()
            te_final_removed = "te-final" not in after_delete
            record(
                "case4: te-final removed from JSX",
                te_final_removed,
                f"file len {len(original_content)} -> {len(after_delete)}",
            )

            # ----- Case 5: 選択を外して Ctrl+Z で復元 -----
            print("[case 5] Press Escape to clear selection, then Ctrl+Z")
            # iframe にフォーカス
            iframe.locator("body").click(position={"x": 5, "y": 5})
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
            page.keyboard.press("Control+z")
            page.wait_for_timeout(2000)  # restore-file + iframe reload

            after_undo = snapshot_artifact()
            te_final_restored = "te-final" in after_undo
            record(
                "case5: Ctrl+Z restored te-final without selection",
                te_final_restored,
                f"after undo len={len(after_undo)} (orig={len(original_content)})",
            )

            # ----- Case 6: Ctrl+Y で再削除 -----
            print("[case 6] Ctrl+Y to redo")
            # iframe が reload されたのでもう一度 body にフォーカス
            iframe.locator("body").click(position={"x": 5, "y": 5})
            page.keyboard.press("Control+y")
            page.wait_for_timeout(2000)

            after_redo = snapshot_artifact()
            te_final_re_removed = "te-final" not in after_redo
            record(
                "case6: Ctrl+Y re-removed te-final",
                te_final_re_removed,
                f"after redo len={len(after_redo)}",
            )

            # 元に戻す
            page.keyboard.press("Control+z")
            page.wait_for_timeout(1500)

            # ----- Case 7: <p> 内に <strong> がある場合、<p> の dblclick は編集モードに入らない -----
            # 統一原則「子 Element を持つ要素は text 編集不可」の検証。
            # 太字消滅バグ防御。
            print("[case 7] dblclick on <p> containing <strong> must not enter edit mode")
            mixed_p = iframe.locator("[data-edit-id='te-strong-mixed']").first
            mixed_p.wait_for(state="visible", timeout=5000)
            mixed_p.dblclick()
            page.wait_for_timeout(400)
            # contenteditable 属性が付かなければ編集モードに入っていない
            ce_attr = mixed_p.get_attribute("contenteditable")
            record(
                "case7: <p> with <strong> child rejects inline edit",
                ce_attr is None,
                f"contenteditable={ce_attr!r} (expected None)",
            )
            # 念のため Escape で選択解除
            iframe.locator("body").click(position={"x": 5, "y": 5})
            page.keyboard.press("Escape")

            # ----- Case 8: <strong data-edit-id> 単独 leaf は dblclick で編集できる -----
            print("[case 8] dblclick on <strong data-edit-id> leaf enters edit mode")
            strong_leaf = iframe.locator("[data-edit-id='te-strong-only']").first
            strong_leaf.wait_for(state="visible", timeout=5000)
            strong_leaf.dblclick()
            page.wait_for_timeout(400)
            ce_attr2 = strong_leaf.get_attribute("contenteditable")
            record(
                "case8: <strong> leaf accepts inline edit",
                ce_attr2 in ("plaintext-only", "true"),
                f"contenteditable={ce_attr2!r}",
            )
            # 編集モードから出る (blur)
            iframe.locator("body").click(position={"x": 5, "y": 5})
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)

            # ----- Case 9: 仮に setLiveText を直接呼んでも <strong> を含む <p> は保存されない -----
            # （ガードが iframe-inspector だけでなく preview-store にも入っていることの検証）
            print("[case 9] direct setLiveText on <p> with <strong> is blocked at store level")
            # iframe 内で window.parent の preview-store を直接叩くのは難しいので、
            # 代わりに「select だけして setLiveText を試す」を simulate するために
            # iframe.locator で <p> をクリック (single click = select) し、
            # JS で usePreviewStore.getState().setLiveText を呼んで JSX が変わらないことを確認。
            iframe.locator("[data-edit-id='te-strong-mixed']").first.click()
            page.wait_for_timeout(300)
            snapshot_before = snapshot_artifact()
            # parent (test-inspector page) で preview-store を直接叩く。
            # 戻り値: 'invoked' = setLiveText を実行できた / 'no-store' = window.usePreviewStore 未定義
            invoke_result = page.evaluate("""
                () => {
                    const w = window;
                    if (!w.usePreviewStore) return 'no-store';
                    w.usePreviewStore.getState().setLiveText('hijacked');
                    return 'invoked';
                }
            """)
            page.wait_for_timeout(1500)
            snapshot_after = snapshot_artifact()
            # store が exposed されてない場合は「ガードが効いた」と誤判定するので明示的に分ける
            if invoke_result != "invoked":
                record(
                    "case9: direct setLiveText guard test could not be performed",
                    False,
                    f"window.usePreviewStore = {invoke_result!r} (expected 'invoked')",
                )
            else:
                record(
                    "case9: direct setLiveText on <strong>-containing <p> changes nothing",
                    snapshot_before == snapshot_after,
                    f"before/after equal={snapshot_before == snapshot_after}",
                )

            browser.close()
    finally:
        # 元の artifact 内容を念のため復元
        restore_artifact(original_content)
        print(f"\n[teardown] restored original artifact")

    print("\n=== Test results ===")
    ok_count = sum(1 for _, ok, _ in results if ok)
    fail_count = len(results) - ok_count
    for name, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}: {name}")
        if detail:
            print(f"        {detail}")
    print(f"\nTotal: {ok_count} passed, {fail_count} failed")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
