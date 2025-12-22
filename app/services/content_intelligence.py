"""
Content Intelligence Service - Phase 6: コンテンツ解析

6A: PDF解析 - PDFからテキスト抽出
6B: 画像OCR - 画像からテキスト抽出
6C: URL先コンテンツ取得 - URLにアクセスしてページ内容を取得
6D: コンテンツ分類AI - 文章から請求書・領収書・通知等を判定
"""
import logging
import time
import re
from typing import Optional, Tuple, List, Dict, Any
from pathlib import Path
from io import BytesIO

from app.config import settings
from app.models.content_schemas import (
    ExtractionMethod,
    ContentCategory,
    ContentConfidence,
    TextExtractionResult,
    PDFExtractionResult,
    OCRExtractionResult,
    URLExtractionResult,
    ClassificationResult,
    InvoiceData,
    OTPData,
    ConfirmationData,
)

logger = logging.getLogger(__name__)


class PDFExtractor:
    """6A: PDF解析 - PDFからテキスト抽出"""
    
    @staticmethod
    async def extract(file_data: bytes, filename: str = "") -> PDFExtractionResult:
        """
        PDFからテキストを抽出
        
        Args:
            file_data: PDFファイルのバイナリデータ
            filename: ファイル名（ログ用）
        
        Returns:
            PDFExtractionResult
        """
        start_time = time.time()
        
        try:
            import pdfplumber
            
            pages_text = []
            tables = []
            
            with pdfplumber.open(BytesIO(file_data)) as pdf:
                page_count = len(pdf.pages)
                
                for i, page in enumerate(pdf.pages):
                    # テキスト抽出
                    text = page.extract_text() or ""
                    pages_text.append(text)
                    
                    # テーブル抽出
                    page_tables = page.extract_tables()
                    if page_tables:
                        for table in page_tables:
                            tables.append({
                                "page": i + 1,
                                "data": table
                            })
                
                full_text = "\n\n".join(pages_text)
                
                processing_time = int((time.time() - start_time) * 1000)
                
                return PDFExtractionResult(
                    success=True,
                    text=full_text,
                    method=ExtractionMethod.PDF_PDFPLUMBER,
                    page_count=page_count,
                    pages=pages_text,
                    tables=tables if tables else None,
                    confidence=0.95,
                    processing_time_ms=processing_time,
                    metadata={
                        "filename": filename,
                        "has_tables": len(tables) > 0,
                        "table_count": len(tables),
                    }
                )
                
        except ImportError:
            logger.error("pdfplumber not installed")
            return PDFExtractionResult(
                success=False,
                method=ExtractionMethod.PDF_PDFPLUMBER,
                error="pdfplumber not installed. Run: pip install pdfplumber",
                processing_time_ms=int((time.time() - start_time) * 1000)
            )
        except Exception as e:
            logger.error(f"PDF extraction failed: {e}")
            return PDFExtractionResult(
                success=False,
                method=ExtractionMethod.PDF_PDFPLUMBER,
                error=str(e),
                processing_time_ms=int((time.time() - start_time) * 1000)
            )


class OCRExtractor:
    """6B: 画像OCR - 画像からテキスト抽出"""
    
    @staticmethod
    async def extract_with_tesseract(file_data: bytes, language: str = "jpn+eng") -> OCRExtractionResult:
        """
        Tesseractを使用してOCR
        
        Args:
            file_data: 画像ファイルのバイナリデータ
            language: OCR言語（jpn+eng, eng など）
        
        Returns:
            OCRExtractionResult
        """
        start_time = time.time()
        
        try:
            import pytesseract
            from PIL import Image
            
            # Tesseractコマンドのパス設定（必要な場合）
            try:
                tesseract_cmd = settings.TESSERACT_CMD
            except AttributeError:
                tesseract_cmd = ''
            if tesseract_cmd:
                pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
            
            # 画像を開く
            image = Image.open(BytesIO(file_data))
            
            # OCR実行
            text = pytesseract.image_to_string(image, lang=language)
            
            # 詳細データ取得（オプション）
            data = pytesseract.image_to_data(image, lang=language, output_type=pytesseract.Output.DICT)
            
            words = []
            for i, word in enumerate(data['text']):
                if word.strip():
                    words.append({
                        "text": word,
                        "x": data['left'][i],
                        "y": data['top'][i],
                        "width": data['width'][i],
                        "height": data['height'][i],
                        "confidence": data['conf'][i],
                    })
            
            # 平均信頼度を計算
            confidences = [w['confidence'] for w in words if w['confidence'] > 0]
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0
            
            processing_time = int((time.time() - start_time) * 1000)
            
            return OCRExtractionResult(
                success=True,
                text=text.strip(),
                method=ExtractionMethod.OCR_TESSERACT,
                language=language,
                words=words,
                confidence=avg_confidence / 100,  # 0-1に正規化
                processing_time_ms=processing_time,
                metadata={
                    "word_count": len(words),
                    "image_size": f"{image.width}x{image.height}",
                }
            )
            
        except ImportError as e:
            logger.error(f"OCR dependencies not installed: {e}")
            return OCRExtractionResult(
                success=False,
                method=ExtractionMethod.OCR_TESSERACT,
                error="pytesseract or Pillow not installed. Run: pip install pytesseract Pillow",
                processing_time_ms=int((time.time() - start_time) * 1000)
            )
        except Exception as e:
            logger.error(f"Tesseract OCR failed: {e}")
            return OCRExtractionResult(
                success=False,
                method=ExtractionMethod.OCR_TESSERACT,
                error=str(e),
                processing_time_ms=int((time.time() - start_time) * 1000)
            )
    
    @staticmethod
    async def extract_with_google_vision(file_data: bytes) -> OCRExtractionResult:
        """
        Google Cloud Vision APIを使用してOCR
        
        Args:
            file_data: 画像ファイルのバイナリデータ
        
        Returns:
            OCRExtractionResult
        """
        start_time = time.time()
        
        try:
            from google.cloud import vision
            
            client = vision.ImageAnnotatorClient()
            image = vision.Image(content=file_data)
            
            # テキスト検出
            response = client.text_detection(image=image)
            
            if response.error.message:
                raise Exception(response.error.message)
            
            texts = response.text_annotations
            
            if not texts:
                return OCRExtractionResult(
                    success=True,
                    text="",
                    method=ExtractionMethod.OCR_GOOGLE_VISION,
                    confidence=1.0,
                    processing_time_ms=int((time.time() - start_time) * 1000),
                    metadata={"message": "No text found in image"}
                )
            
            # 最初の要素は全体のテキスト
            full_text = texts[0].description
            
            # 個別の単語情報
            words = []
            for text in texts[1:]:
                vertices = text.bounding_poly.vertices
                words.append({
                    "text": text.description,
                    "x": vertices[0].x if vertices else 0,
                    "y": vertices[0].y if vertices else 0,
                    "confidence": 0.95,  # Vision APIは個別信頼度を返さない
                })
            
            processing_time = int((time.time() - start_time) * 1000)
            
            return OCRExtractionResult(
                success=True,
                text=full_text,
                method=ExtractionMethod.OCR_GOOGLE_VISION,
                words=words,
                confidence=0.95,
                processing_time_ms=processing_time,
                metadata={
                    "word_count": len(words),
                }
            )
            
        except ImportError:
            logger.error("google-cloud-vision not installed")
            return OCRExtractionResult(
                success=False,
                method=ExtractionMethod.OCR_GOOGLE_VISION,
                error="google-cloud-vision not installed. Run: pip install google-cloud-vision",
                processing_time_ms=int((time.time() - start_time) * 1000)
            )
        except Exception as e:
            logger.error(f"Google Vision OCR failed: {e}")
            return OCRExtractionResult(
                success=False,
                method=ExtractionMethod.OCR_GOOGLE_VISION,
                error=str(e),
                processing_time_ms=int((time.time() - start_time) * 1000)
            )
    
    async def extract(self, file_data: bytes, language: str = "jpn+eng") -> OCRExtractionResult:
        """
        設定に基づいてOCRプロバイダを選択して実行
        """
        # デフォルトでtesseractを使用
        try:
            ocr_provider = settings.OCR_PROVIDER
        except AttributeError:
            ocr_provider = "tesseract"
        
        if ocr_provider == "google_vision":
            return await self.extract_with_google_vision(file_data)
        else:
            return await self.extract_with_tesseract(file_data, language)


class URLExtractor:
    """6C: URL先コンテンツ取得 - URLにアクセスしてページ内容を取得"""
    
    @staticmethod
    async def extract_with_requests(url: str, timeout_ms: int = 30000) -> URLExtractionResult:
        """
        requestsを使ったシンプルなURL取得（JavaScript不要なページ向け）
        """
        import requests
        from bs4 import BeautifulSoup
        
        start_time = time.time()
        
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            response = requests.get(url, headers=headers, timeout=timeout_ms / 1000)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # スクリプト・スタイルを削除
            for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
                tag.decompose()
            
            # タイトル取得
            title = soup.title.string if soup.title else None
            
            # メインコンテンツを探す
            content = None
            for selector in ['article', 'main', '[role="main"]', '.content', '#content']:
                element = soup.select_one(selector)
                if element and len(element.get_text(strip=True)) > 100:
                    content = element.get_text(separator='\n', strip=True)
                    break
            
            # フォールバック: body全体
            if not content:
                body = soup.body
                if body:
                    content = body.get_text(separator='\n', strip=True)
                else:
                    content = soup.get_text(separator='\n', strip=True)
            
            # 不要な空白を整理
            content = re.sub(r'\n{3,}', '\n\n', content)
            content = content.strip()
            
            processing_time = int((time.time() - start_time) * 1000)
            
            return URLExtractionResult(
                success=True,
                text=content[:50000],
                method=ExtractionMethod.URL_REQUESTS,
                title=title,
                url=url,
                final_url=response.url if response.url != url else None,
                confidence=0.85,
                processing_time_ms=processing_time,
                metadata={
                    "content_length": len(content),
                    "status_code": response.status_code,
                }
            )
            
        except Exception as e:
            logger.error(f"Requests URL extraction failed: {e}")
            return URLExtractionResult(
                success=False,
                method=ExtractionMethod.URL_REQUESTS,
                url=url,
                error=str(e),
                processing_time_ms=int((time.time() - start_time) * 1000)
            )
    
    @staticmethod
    async def extract(
        url: str,
        wait_for_selector: Optional[str] = None,
        timeout_ms: int = 30000,
        use_playwright: bool = False
    ) -> URLExtractionResult:
        """
        URLにアクセスしてテキストコンテンツを取得
        
        Args:
            url: 取得するURL
            wait_for_selector: 待機するCSSセレクタ（オプション）
            timeout_ms: タイムアウト（ミリ秒）
            use_playwright: Playwrightを使用するか（デフォルト: False）
        
        Returns:
            URLExtractionResult
        """
        # デフォルトはrequestsを使用（軽量・高速）
        if not use_playwright and not wait_for_selector:
            result = await URLExtractor.extract_with_requests(url, timeout_ms)
            if result.success:
                return result
            # 失敗した場合、Playwrightにフォールバック
            logger.info(f"Requests failed, falling back to Playwright: {result.error}")
        
        start_time = time.time()
        
        try:
            from playwright.async_api import async_playwright
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    viewport={"width": 1280, "height": 720},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                )
                page = await context.new_page()
                
                try:
                    # ページにアクセス
                    await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                    
                    # 追加の待機（必要な場合）
                    if wait_for_selector:
                        await page.wait_for_selector(wait_for_selector, timeout=timeout_ms)
                    
                    # タイトル取得
                    title = await page.title()
                    
                    # 最終URL（リダイレクト後）
                    final_url = page.url
                    
                    # メインコンテンツのテキストを取得
                    content = await page.evaluate("""
                        () => {
                            // メインコンテンツを探す
                            const selectors = [
                                'article',
                                'main',
                                '[role="main"]',
                                '.content',
                                '#content',
                                '.main-content',
                                '#main-content',
                            ];
                            
                            for (const selector of selectors) {
                                const el = document.querySelector(selector);
                                if (el && el.innerText.trim().length > 100) {
                                    return el.innerText;
                                }
                            }
                            
                            // フォールバック: body全体
                            return document.body.innerText;
                        }
                    """)
                    
                    # 不要な空白を整理
                    content = re.sub(r'\n{3,}', '\n\n', content)
                    content = content.strip()
                    
                    processing_time = int((time.time() - start_time) * 1000)
                    
                    return URLExtractionResult(
                        success=True,
                        text=content[:50000],  # 最大50KB
                        method=ExtractionMethod.URL_PLAYWRIGHT,
                        title=title,
                        url=url,
                        final_url=final_url if final_url != url else None,
                        confidence=0.9,
                        processing_time_ms=processing_time,
                        metadata={
                            "content_length": len(content),
                            "redirected": final_url != url,
                        }
                    )
                    
                finally:
                    await browser.close()
                    
        except ImportError:
            logger.error("playwright not installed")
            return URLExtractionResult(
                success=False,
                method=ExtractionMethod.URL_PLAYWRIGHT,
                url=url,
                error="playwright not installed. Run: pip install playwright && playwright install chromium",
                processing_time_ms=int((time.time() - start_time) * 1000)
            )
        except Exception as e:
            logger.error(f"URL extraction failed: {e}")
            return URLExtractionResult(
                success=False,
                method=ExtractionMethod.URL_PLAYWRIGHT,
                url=url,
                error=str(e),
                processing_time_ms=int((time.time() - start_time) * 1000)
            )


class ContentClassifier:
    """6D: コンテンツ分類AI - 文章から請求書・領収書・通知等を判定"""
    
    CLASSIFICATION_PROMPT = """あなたはメッセージ・文書を分類するAIです。
以下のテキストを分析し、カテゴリを判定してください。

## カテゴリ一覧
- invoice: 請求書（支払い期日、振込先情報、請求金額がある）
- receipt: 領収書（支払い済み、受領証明）
- notification: 通知・お知らせ（サービスからの一般的な通知）
- otp: ワンタイムパスワード・認証コード
- confirmation: 予約確認・注文確認・登録確認
- newsletter: ニュースレター・メルマガ・宣伝
- personal: 個人的なメッセージ
- spam: スパム・迷惑メール
- unknown: 上記に該当しない

## 入力情報
件名: {subject}
送信者: {sender}

本文:
{text}

## 出力形式（JSONのみ）
{{
  "category": "カテゴリ名",
  "confidence_score": 0.0-1.0の数値,
  "reasoning": "判定理由（1-2文）",
  "extracted_data": {{抽出された重要データ}},
  "secondary_categories": ["該当する可能性のある他のカテゴリ"]
}}

invoiceの場合、extracted_dataには以下を含めてください：
- amount: 金額（数値）
- due_date: 支払期日（YYYY-MM-DD形式）
- invoice_number: 請求書番号
- issuer_name: 発行元名
- bank_info: 振込先情報（銀行名、支店名、口座番号など）

otpの場合、extracted_dataには以下を含めてください：
- code: 認証コード
- service_name: サービス名
- expires_in: 有効期限（秒）

confirmationの場合、extracted_dataには以下を含めてください：
- confirmation_type: 確認の種類（reservation/order/registration等）
- confirmation_number: 確認番号
- service_name: サービス名
- details: その他の詳細情報

JSONのみを出力してください。"""

    @staticmethod
    async def classify(
        text: str,
        subject: Optional[str] = None,
        sender: Optional[str] = None,
    ) -> ClassificationResult:
        """
        テキストを分類
        
        Args:
            text: 分類するテキスト
            subject: 件名（オプション）
            sender: 送信者（オプション）
        
        Returns:
            ClassificationResult
        """
        try:
            from langchain_anthropic import ChatAnthropic
            import json
            
            # プロンプト作成
            prompt = ContentClassifier.CLASSIFICATION_PROMPT.format(
                subject=subject or "(なし)",
                sender=sender or "(不明)",
                text=text[:10000]  # 最大10KB
            )
            
            # Claude APIを呼び出し
            llm = ChatAnthropic(
                model="claude-sonnet-4-20250514",
                api_key=settings.ANTHROPIC_API_KEY,
                temperature=0,
                max_tokens=1024,
            )
            
            response = await llm.ainvoke(prompt)
            response_text = response.content
            
            # JSONを抽出
            # コードブロック内にある場合の処理
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # 直接JSONの場合
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                json_str = json_match.group(0) if json_match else response_text
            
            result = json.loads(json_str)
            
            # カテゴリをEnumに変換
            category_str = result.get("category", "unknown").lower()
            try:
                category = ContentCategory(category_str)
            except ValueError:
                category = ContentCategory.UNKNOWN
            
            # 信頼度スコア
            confidence_score = float(result.get("confidence_score", 0.5))
            
            # 信頼度レベルを判定
            if confidence_score >= 0.9:
                confidence = ContentConfidence.HIGH
            elif confidence_score >= 0.7:
                confidence = ContentConfidence.MEDIUM
            elif confidence_score >= 0.5:
                confidence = ContentConfidence.LOW
            else:
                confidence = ContentConfidence.UNCERTAIN
            
            # セカンダリカテゴリ
            secondary = result.get("secondary_categories", [])
            secondary_categories = []
            for s in secondary:
                try:
                    secondary_categories.append(ContentCategory(s.lower()))
                except ValueError:
                    pass
            
            return ClassificationResult(
                category=category,
                confidence=confidence,
                confidence_score=confidence_score,
                reasoning=result.get("reasoning"),
                extracted_data=result.get("extracted_data"),
                secondary_categories=secondary_categories if secondary_categories else None,
            )
            
        except Exception as e:
            logger.error(f"Content classification failed: {e}")
            return ClassificationResult(
                category=ContentCategory.UNKNOWN,
                confidence=ContentConfidence.UNCERTAIN,
                confidence_score=0.0,
                reasoning=f"分類に失敗しました: {str(e)}",
            )


class ContentIntelligenceService:
    """Content Intelligence統合サービス"""
    
    def __init__(self):
        self.pdf_extractor = PDFExtractor()
        self.ocr_extractor = OCRExtractor()
        self.url_extractor = URLExtractor()
        self.classifier = ContentClassifier()
    
    async def extract_text_from_pdf(self, file_data: bytes, filename: str = "") -> PDFExtractionResult:
        """PDFからテキストを抽出"""
        return await self.pdf_extractor.extract(file_data, filename)
    
    async def extract_text_from_image(self, file_data: bytes, language: str = "jpn+eng") -> OCRExtractionResult:
        """画像からテキストを抽出（OCR）"""
        return await self.ocr_extractor.extract(file_data, language)
    
    async def extract_text_from_url(
        self,
        url: str,
        wait_for_selector: Optional[str] = None,
        timeout_ms: int = 30000
    ) -> URLExtractionResult:
        """URLからテキストを抽出"""
        return await self.url_extractor.extract(url, wait_for_selector, timeout_ms)
    
    async def classify_content(
        self,
        text: str,
        subject: Optional[str] = None,
        sender: Optional[str] = None,
    ) -> ClassificationResult:
        """コンテンツを分類"""
        return await self.classifier.classify(text, subject, sender)
    
    async def analyze_attachment(
        self,
        file_data: bytes,
        mime_type: str,
        filename: str = "",
        classify: bool = True,
    ) -> Tuple[TextExtractionResult, Optional[ClassificationResult]]:
        """
        添付ファイルを解析
        
        Args:
            file_data: ファイルデータ
            mime_type: MIMEタイプ
            filename: ファイル名
            classify: 分類も行うかどうか
        
        Returns:
            (抽出結果, 分類結果)
        """
        extraction_result: TextExtractionResult
        
        if mime_type == 'application/pdf':
            extraction_result = await self.extract_text_from_pdf(file_data, filename)
        elif mime_type.startswith('image/'):
            extraction_result = await self.extract_text_from_image(file_data)
        else:
            extraction_result = TextExtractionResult(
                success=False,
                method=ExtractionMethod.DIRECT_TEXT,
                error=f"Unsupported MIME type: {mime_type}"
            )
        
        classification_result = None
        if classify and extraction_result.success and extraction_result.text:
            classification_result = await self.classify_content(extraction_result.text)
        
        return extraction_result, classification_result
    
    async def process_detected_message(
        self,
        message_id: str,
        include_attachments: bool = True,
    ) -> Dict[str, Any]:
        """
        検知メッセージを処理
        
        Args:
            message_id: 検知メッセージID
            include_attachments: 添付ファイルも処理するか
        
        Returns:
            処理結果
        """
        from app.services.message_detection import get_detection_service
        from app.services.attachment_service import get_attachment_service
        from app.models.detection_schemas import DetectionStatus, ContentType
        
        detection_service = get_detection_service()
        attachment_service = get_attachment_service()
        
        # メッセージを取得
        message = await detection_service.get_detected_message(message_id)
        if not message:
            return {"success": False, "error": "Message not found"}
        
        results = {
            "message_id": message_id,
            "success": True,
            "text_classification": None,
            "attachment_results": [],
        }
        
        # 本文を分類
        if message.get("content"):
            classification = await self.classify_content(
                text=message["content"],
                subject=message.get("subject"),
                sender=message.get("sender_info", {}).get("email"),
            )
            results["text_classification"] = classification.model_dump()
        
        # 添付ファイルを処理
        if include_attachments:
            attachments = message.get("attachments", [])
            for att in attachments:
                try:
                    data, filename, mime_type = await attachment_service.get_attachment_data(att["id"])
                    extraction, classification = await self.analyze_attachment(
                        file_data=data,
                        mime_type=mime_type,
                        filename=filename,
                    )
                    results["attachment_results"].append({
                        "attachment_id": att["id"],
                        "filename": filename,
                        "extraction": extraction.model_dump(),
                        "classification": classification.model_dump() if classification else None,
                    })
                except Exception as e:
                    logger.error(f"Failed to process attachment {att['id']}: {e}")
                    results["attachment_results"].append({
                        "attachment_id": att["id"],
                        "error": str(e),
                    })
        
        # メッセージステータスを更新
        primary_classification = results.get("text_classification")
        if primary_classification:
            category = primary_classification.get("category")
            content_type = None
            if category == "invoice":
                content_type = ContentType.INVOICE
            elif category == "otp":
                content_type = ContentType.OTP
            elif category in ["notification", "confirmation", "newsletter"]:
                content_type = ContentType.NOTIFICATION
            else:
                content_type = ContentType.GENERAL
            
            await detection_service.update_message_status(
                message_id=message_id,
                status=DetectionStatus.PROCESSED,
                content_type=content_type,
                processing_result=results,
            )
        
        return results


# シングルトンインスタンス
_content_intelligence_service: Optional[ContentIntelligenceService] = None


def get_content_intelligence_service() -> ContentIntelligenceService:
    """Content Intelligenceサービスのインスタンスを取得"""
    global _content_intelligence_service
    if _content_intelligence_service is None:
        _content_intelligence_service = ContentIntelligenceService()
    return _content_intelligence_service



