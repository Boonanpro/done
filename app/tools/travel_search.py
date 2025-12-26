"""
Travel Search Tools - 交通検索（電車・バス・航空機）
Playwright を使用して各サービスから検索結果を取得
"""
from typing import Optional
from datetime import datetime
from langchain_core.tools import tool
from playwright.async_api import async_playwright, Browser, Page, TimeoutError as PlaywrightTimeout
import asyncio
import re

from app.models.schemas import SearchResult, SearchResultCategory


# ブラウザインスタンス管理（travel_search専用）
_browser: Optional[Browser] = None


async def _get_browser() -> Browser:
    """ブラウザインスタンスを取得"""
    global _browser
    if _browser is None or not _browser.is_connected():
        playwright = await async_playwright().start()
        _browser = await playwright.chromium.launch(
            headless=True,  # バックグラウンドで実行
        )
    return _browser


async def _create_page() -> Page:
    """新しいページを作成"""
    browser = await _get_browser()
    context = await browser.new_context(
        viewport={"width": 1280, "height": 720},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )
    page = await context.new_page()
    return page


@tool
async def search_train(
    departure: str,
    arrival: str,
    date: Optional[str] = None,
    time: Optional[str] = None,
) -> list[dict]:
    """
    電車・新幹線の経路を検索します（Yahoo!乗換案内を使用）
    
    Args:
        departure: 出発駅（例: "新大阪"）
        arrival: 到着駅（例: "博多"）
        date: 出発日（YYYY-MM-DD形式、省略時は今日）
        time: 出発時刻（HH:MM形式、省略時は現在時刻）
        
    Returns:
        検索結果のリスト（SearchResult形式）
    """
    try:
        # 日時のパース
        if date:
            dt = datetime.strptime(date, "%Y-%m-%d")
        else:
            dt = datetime.now()
        
        if time:
            hour, minute = map(int, time.split(":"))
        else:
            hour, minute = datetime.now().hour, datetime.now().minute
        
        # Yahoo!乗換案内のURL構築
        url = (
            f"https://transit.yahoo.co.jp/search/result"
            f"?from={departure}&to={arrival}"
            f"&y={dt.year}&m={dt.month:02d}&d={dt.day:02d}"
            f"&hh={hour:02d}&m2={minute // 10}&m1={minute % 10}"
            f"&type=1&ticket=ic&expkind=1&userpass=1&ws=3&s=0"
        )
        
        page = await _create_page()
        
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            
            # ページ読み込み待機（動的コンテンツのため）
            await asyncio.sleep(2)
            
            # 経路情報を抽出
            results = await page.evaluate("""
                () => {
                    const routes = [];
                    
                    // 経路リストを取得
                    const routeElements = document.querySelectorAll('.routeList li, .route');
                    
                    routeElements.forEach((el, index) => {
                        if (index >= 5) return; // 最大5件
                        
                        try {
                            // 時刻情報
                            const timeEl = el.querySelector('.time, .routeTime');
                            const timeText = timeEl ? timeEl.innerText.trim() : '';
                            
                            // 料金情報
                            const fareEl = el.querySelector('.fare, .routeFare');
                            const fareText = fareEl ? fareEl.innerText.trim() : '';
                            
                            // 所要時間
                            const durationEl = el.querySelector('.requiredTime, .duration');
                            const durationText = durationEl ? durationEl.innerText.trim() : '';
                            
                            // 乗り換え回数
                            const transferEl = el.querySelector('.transfer, .transferCount');
                            const transferText = transferEl ? transferEl.innerText.trim() : '';
                            
                            // 経路詳細
                            const summaryEl = el.querySelector('.summary, .routeSummary');
                            const summaryText = summaryEl ? summaryEl.innerText.trim() : '';
                            
                            if (timeText || fareText) {
                                routes.push({
                                    time: timeText,
                                    fare: fareText,
                                    duration: durationText,
                                    transfer: transferText,
                                    summary: summaryText
                                });
                            }
                        } catch (e) {
                            // 個別のエラーは無視
                        }
                    });
                    
                    // 代替: より汎用的なセレクタ
                    if (routes.length === 0) {
                        const allText = document.body.innerText;
                        const lines = allText.split('\\n').filter(l => l.includes('発') || l.includes('着'));
                        lines.slice(0, 10).forEach((line, i) => {
                            routes.push({
                                time: line.trim(),
                                fare: '',
                                duration: '',
                                transfer: '',
                                summary: ''
                            });
                        });
                    }
                    
                    return routes;
                }
            """)
            
            # SearchResult形式に変換
            search_results = []
            for i, route in enumerate(results[:5]):
                # 料金から数値を抽出
                price = None
                if route.get("fare"):
                    price_match = re.search(r"(\d[\d,]*)", route["fare"].replace(",", ""))
                    if price_match:
                        price = int(price_match.group(1).replace(",", ""))
                
                search_results.append({
                    "id": f"train_{i}",
                    "category": SearchResultCategory.TRAIN.value,
                    "title": route.get("time") or f"経路 {i+1}",
                    "url": url,
                    "price": price,
                    "status": None,
                    "details": {
                        "departure": departure,
                        "arrival": arrival,
                        "date": date or dt.strftime("%Y-%m-%d"),
                        "duration": route.get("duration", ""),
                        "transfer": route.get("transfer", ""),
                        "summary": route.get("summary", ""),
                        "fare_text": route.get("fare", ""),
                    },
                    "execution_params": {
                        "service": "yahoo_transit",
                        "requires_login": False,
                    }
                })
            
            return search_results if search_results else [{
                "id": "train_0",
                "category": SearchResultCategory.TRAIN.value,
                "title": f"{departure} → {arrival}",
                "url": url,
                "price": None,
                "status": None,
                "details": {
                    "message": "Failed to retrieve route info. Please check the URL directly.",
                    "departure": departure,
                    "arrival": arrival,
                },
                "execution_params": {
                    "service": "yahoo_transit",
                    "requires_login": False,
                }
            }]
            
        finally:
            await page.close()
            
    except PlaywrightTimeout:
        return [{
            "error": "検索がタイムアウトしました",
            "fallback": True
        }]
    except Exception as e:
        return [{
            "error": f"検索に失敗しました: {str(e)}",
            "fallback": True
        }]


@tool
async def search_bus(
    departure: str,
    arrival: str,
    date: Optional[str] = None,
) -> list[dict]:
    """
    高速バスを検索します（高速バスネットを使用）
    
    Args:
        departure: 出発地（例: "東京"）
        arrival: 到着地（例: "大阪"）
        date: 出発日（YYYY-MM-DD形式、省略時は今日）
        
    Returns:
        検索結果のリスト（SearchResult形式）
    """
    try:
        if date:
            dt = datetime.strptime(date, "%Y-%m-%d")
        else:
            dt = datetime.now()
        
        # 高速バスネットの検索URL（簡易版）
        url = f"https://www.kousokubus.net/JpnBus/search?dep={departure}&arr={arrival}&date={dt.strftime('%Y%m%d')}"
        
        page = await _create_page()
        
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            
            # ページ読み込み待機
            await asyncio.sleep(3)
            
            # 検索結果を抽出
            results = await page.evaluate("""
                () => {
                    const buses = [];
                    
                    // バス情報を取得
                    const busElements = document.querySelectorAll('.bus-item, .search-result-item, .route-item');
                    
                    busElements.forEach((el, index) => {
                        if (index >= 5) return;
                        
                        try {
                            const timeEl = el.querySelector('.time, .departure-time');
                            const priceEl = el.querySelector('.price, .fare');
                            const nameEl = el.querySelector('.bus-name, .name');
                            const statusEl = el.querySelector('.status, .availability');
                            
                            buses.push({
                                time: timeEl ? timeEl.innerText.trim() : '',
                                price: priceEl ? priceEl.innerText.trim() : '',
                                name: nameEl ? nameEl.innerText.trim() : '',
                                status: statusEl ? statusEl.innerText.trim() : ''
                            });
                        } catch (e) {}
                    });
                    
                    return buses;
                }
            """)
            
            search_results = []
            for i, bus in enumerate(results[:5]):
                price = None
                if bus.get("price"):
                    price_match = re.search(r"(\d[\d,]*)", bus["price"].replace(",", ""))
                    if price_match:
                        price = int(price_match.group(1).replace(",", ""))
                
                search_results.append({
                    "id": f"bus_{i}",
                    "category": SearchResultCategory.BUS.value,
                    "title": bus.get("name") or bus.get("time") or f"バス {i+1}",
                    "url": url,
                    "price": price,
                    "status": bus.get("status"),
                    "details": {
                        "departure": departure,
                        "arrival": arrival,
                        "date": date or dt.strftime("%Y-%m-%d"),
                        "time": bus.get("time", ""),
                    },
                    "execution_params": {
                        "service": "kousokubus",
                        "requires_login": False,
                    }
                })
            
            # 結果がない場合はフォールバック
            if not search_results:
                search_results.append({
                    "id": "bus_0",
                    "category": SearchResultCategory.BUS.value,
                    "title": f"{departure} → {arrival} 高速バス",
                    "url": url,
                    "price": None,
                    "status": None,
                    "details": {
                        "message": "Failed to retrieve bus info. Please check the URL directly.",
                        "departure": departure,
                        "arrival": arrival,
                    },
                    "execution_params": {
                        "service": "kousokubus",
                        "requires_login": False,
                    }
                })
            
            return search_results
            
        finally:
            await page.close()
            
    except PlaywrightTimeout:
        return [{
            "error": "検索がタイムアウトしました",
            "fallback": True
        }]
    except Exception as e:
        return [{
            "error": f"検索に失敗しました: {str(e)}",
            "fallback": True
        }]


@tool
async def search_flight(
    departure: str,
    arrival: str,
    date: Optional[str] = None,
) -> list[dict]:
    """
    航空便を検索します（スカイスキャナーを使用）
    
    Args:
        departure: 出発空港（例: "東京" または "HND"）
        arrival: 到着空港（例: "大阪" または "ITM"）
        date: 出発日（YYYY-MM-DD形式、省略時は明日）
        
    Returns:
        検索結果のリスト（SearchResult形式）
    """
    try:
        if date:
            dt = datetime.strptime(date, "%Y-%m-%d")
        else:
            from datetime import timedelta
            dt = datetime.now() + timedelta(days=1)
        
        # スカイスキャナーの検索URL
        date_str = dt.strftime("%y%m%d")
        url = f"https://www.skyscanner.jp/transport/flights/{departure}/{arrival}/{date_str}/"
        
        page = await _create_page()
        
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            
            # ページ読み込み待機（動的コンテンツのため長めに）
            await asyncio.sleep(5)
            
            # 検索結果を抽出
            results = await page.evaluate("""
                () => {
                    const flights = [];
                    
                    // フライト情報を取得
                    const flightElements = document.querySelectorAll('[class*="flight"], [class*="itinerary"]');
                    
                    flightElements.forEach((el, index) => {
                        if (index >= 5) return;
                        
                        try {
                            const priceEl = el.querySelector('[class*="price"]');
                            const timeEl = el.querySelector('[class*="time"]');
                            const airlineEl = el.querySelector('[class*="airline"], [class*="carrier"]');
                            const durationEl = el.querySelector('[class*="duration"]');
                            
                            flights.push({
                                price: priceEl ? priceEl.innerText.trim() : '',
                                time: timeEl ? timeEl.innerText.trim() : '',
                                airline: airlineEl ? airlineEl.innerText.trim() : '',
                                duration: durationEl ? durationEl.innerText.trim() : ''
                            });
                        } catch (e) {}
                    });
                    
                    return flights;
                }
            """)
            
            search_results = []
            for i, flight in enumerate(results[:5]):
                price = None
                if flight.get("price"):
                    price_match = re.search(r"(\d[\d,]*)", flight["price"].replace(",", "").replace("¥", ""))
                    if price_match:
                        price = int(price_match.group(1).replace(",", ""))
                
                search_results.append({
                    "id": f"flight_{i}",
                    "category": SearchResultCategory.FLIGHT.value,
                    "title": flight.get("airline") or flight.get("time") or f"フライト {i+1}",
                    "url": url,
                    "price": price,
                    "status": None,
                    "details": {
                        "departure": departure,
                        "arrival": arrival,
                        "date": date or dt.strftime("%Y-%m-%d"),
                        "time": flight.get("time", ""),
                        "duration": flight.get("duration", ""),
                    },
                    "execution_params": {
                        "service": "skyscanner",
                        "requires_login": False,
                    }
                })
            
            # 結果がない場合はフォールバック
            if not search_results:
                search_results.append({
                    "id": "flight_0",
                    "category": SearchResultCategory.FLIGHT.value,
                    "title": f"{departure} → {arrival} 航空便",
                    "url": url,
                    "price": None,
                    "status": None,
                    "details": {
                        "message": "Failed to retrieve flight info. Please check the URL directly.",
                        "departure": departure,
                        "arrival": arrival,
                    },
                    "execution_params": {
                        "service": "skyscanner",
                        "requires_login": False,
                    }
                })
            
            return search_results
            
        finally:
            await page.close()
            
    except PlaywrightTimeout:
        return [{
            "error": "検索がタイムアウトしました",
            "fallback": True
        }]
    except Exception as e:
        return [{
            "error": f"検索に失敗しました: {str(e)}",
            "fallback": True
        }]


async def cleanup_travel_browser():
    """ブラウザリソースをクリーンアップ"""
    global _browser
    if _browser:
        await _browser.close()
        _browser = None
