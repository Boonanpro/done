from playwright.sync_api import sync_playwright
import os
import math

def record_video():
    os.makedirs('frames', exist_ok=True)
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        frame_count = 0
        
        def save_frame():
            nonlocal frame_count
            page.screenshot(path=f"frames/f_{frame_count:05d}.png")
            frame_count += 1

        # ==========================================
        # シーン1: 検索モックアップ (0-149 frames)
        # ==========================================
        html = """
        <html><body style="font-family: sans-serif; padding: 50px; background: #fff;">
            <div style="max-width: 800px; margin: 0 auto; padding-top: 50px;">
                <h1 style="color: #4285F4; font-size: 48px; margin-bottom: 20px;">Google</h1>
                <input id="search-box" type="text" value="" style="width: 100%; padding: 15px 25px; font-size: 20px; border-radius: 24px; border: 1px solid #dfe1e5; outline: none; box-shadow: 0 1px 6px rgba(32,33,36,.28);" readonly/>
                <div style="margin-top: 40px;">
                    <div style="color: #202124; font-size: 14px; margin-bottom: 5px;">yoshikawa-tokuso.vercel.app</div>
                    <a href="#" style="color: #1a0dab; font-size: 24px; text-decoration: none;">吉川特装自動車 | 鳥取県の新明和認定サービス工場</a>
                    <div style="color: #4d5156; margin-top: 8px; font-size: 16px;">ダンプカー、タンクローリー、パワーゲート等の特装車の修理・整備はお任せください。</div>
                </div>
            </div>
        </body></html>
        """
        page.set_content(html)
        
        # タイピングアニメーション (0-29 frames)
        text = "鳥取 特装車 修理"
        for i in range(1, len(text) + 1):
            page.evaluate(f'document.getElementById("search-box").value = "{text[:i]}"')
            save_frame()
            save_frame()
            save_frame()
        for _ in range(3): save_frame()
        
        # クリックまでの待機 (30-59 frames)
        for _ in range(30): save_frame()
        
        # クリック直後の待機 (60-74 frames)
        for _ in range(15): save_frame()
        
        # HPへ遷移
        page.goto('https://yoshikawa-tokuso.vercel.app')
        page.wait_for_load_state('networkidle')
        page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
        page.wait_for_timeout(2000)
        page.evaluate('window.scrollTo(0, 0)')
        page.wait_for_timeout(1000)

        # ファーストビュー (75-149 frames)
        for _ in range(75): save_frame()
        
        # ==========================================
        # シーン2: ファーストビューインパクト (150-269 frames)
        # ==========================================
        for _ in range(120): save_frame()
        
        # ==========================================
        # シーン3: テキスト挿入待機 (270-329 frames)
        # ==========================================
        for _ in range(60): save_frame()
        
        # ==========================================
        # シーン4: スクロール (330-539 frames)
        # ==========================================
        for i in range(210):
            progress = i / 210
            ease_progress = progress * progress * (3 - 2 * progress)
            scroll_y = int(ease_progress * 2200)
            page.evaluate(f'window.scrollTo(0, {scroll_y})')
            save_frame()
            
        # ==========================================
        # シーン5: テキスト挿入待機 (540-599 frames)
        # ==========================================
        for _ in range(60): save_frame()
            
        # ==========================================
        # シーン6: 問い合わせスクロール (600-749 frames)
        # ==========================================
        start_y = 2200
        target_y = page.evaluate('document.body.scrollHeight') - 1080
        
        for i in range(150):
            progress = i / 150
            ease_progress = progress * progress * (3 - 2 * progress)
            scroll_y = int(start_y + ease_progress * (target_y - start_y))
            page.evaluate(f'window.scrollTo(0, {scroll_y})')
            save_frame()
            
        # ==========================================
        # シーン7: 締め待機 (750-839 frames)
        # ==========================================
        for _ in range(90): save_frame()
            
        browser.close()
        print(f"Total frames generated: {frame_count}")

if __name__ == "__main__":
    record_video()
