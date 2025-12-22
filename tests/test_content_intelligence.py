"""
Tests for Phase 6: Content Intelligence

6A: PDF解析
6B: 画像OCR
6C: URL先コンテンツ取得
6D: コンテンツ分類AI
"""
import pytest
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.content_schemas import (
    ExtractionMethod,
    ContentCategory,
    ContentConfidence,
    TextExtractionResult,
    PDFExtractionResult,
    OCRExtractionResult,
    URLExtractionResult,
    ClassificationResult,
)
from app.services.content_intelligence import (
    PDFExtractor,
    OCRExtractor,
    URLExtractor,
    ContentClassifier,
    ContentIntelligenceService,
)


# ==================== 6A: PDF Extraction Tests ====================

class TestPDFExtractor:
    """PDF抽出のテスト"""
    
    @pytest.mark.asyncio
    async def test_extract_pdf_success(self):
        """PDFからテキスト抽出が成功する"""
        # pdfplumberをモック
        with patch('app.services.content_intelligence.pdfplumber') as mock_pdfplumber:
            # モックページを作成
            mock_page = MagicMock()
            mock_page.extract_text.return_value = "これはテスト請求書です。\n金額: 10,000円"
            mock_page.extract_tables.return_value = []
            
            # モックPDFを作成
            mock_pdf = MagicMock()
            mock_pdf.pages = [mock_page]
            mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
            mock_pdf.__exit__ = MagicMock(return_value=False)
            
            mock_pdfplumber.open.return_value = mock_pdf
            
            # テスト実行
            result = await PDFExtractor.extract(b"fake pdf data", "test.pdf")
            
            assert result.success is True
            assert result.method == ExtractionMethod.PDF_PDFPLUMBER
            assert "請求書" in result.text
            assert result.page_count == 1
    
    @pytest.mark.asyncio
    async def test_extract_pdf_with_tables(self):
        """PDFテーブル抽出のテスト"""
        with patch('app.services.content_intelligence.pdfplumber') as mock_pdfplumber:
            mock_page = MagicMock()
            mock_page.extract_text.return_value = "テーブルを含むPDF"
            mock_page.extract_tables.return_value = [
                [["項目", "金額"], ["商品A", "1000"], ["商品B", "2000"]]
            ]
            
            mock_pdf = MagicMock()
            mock_pdf.pages = [mock_page]
            mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
            mock_pdf.__exit__ = MagicMock(return_value=False)
            
            mock_pdfplumber.open.return_value = mock_pdf
            
            result = await PDFExtractor.extract(b"fake pdf data")
            
            assert result.success is True
            assert result.tables is not None
            assert len(result.tables) == 1
    
    @pytest.mark.asyncio
    async def test_extract_pdf_import_error(self):
        """pdfplumberがインストールされていない場合"""
        with patch.dict('sys.modules', {'pdfplumber': None}):
            with patch('app.services.content_intelligence.pdfplumber', None):
                # ImportErrorをシミュレート
                with patch('builtins.__import__', side_effect=ImportError("No module named 'pdfplumber'")):
                    # Note: 実際のテストではモジュールのインポートをモックする必要がある
                    pass


# ==================== 6B: OCR Extraction Tests ====================

class TestOCRExtractor:
    """OCR抽出のテスト"""
    
    @pytest.mark.asyncio
    async def test_extract_with_tesseract_success(self):
        """Tesseract OCRが成功する"""
        with patch('app.services.content_intelligence.pytesseract') as mock_tesseract:
            with patch('app.services.content_intelligence.Image') as mock_image_module:
                # モック設定
                mock_tesseract.image_to_string.return_value = "認証コード: 123456"
                mock_tesseract.image_to_data.return_value = {
                    'text': ['認証コード:', '123456'],
                    'left': [10, 100],
                    'top': [10, 10],
                    'width': [80, 60],
                    'height': [20, 20],
                    'conf': [95, 98],
                }
                mock_tesseract.Output = MagicMock()
                mock_tesseract.Output.DICT = 'dict'
                
                mock_image = MagicMock()
                mock_image.width = 640
                mock_image.height = 480
                mock_image_module.open.return_value = mock_image
                
                # テスト実行
                result = await OCRExtractor.extract_with_tesseract(b"fake image data")
                
                assert result.success is True
                assert result.method == ExtractionMethod.OCR_TESSERACT
                assert "123456" in result.text
    
    @pytest.mark.asyncio
    async def test_extract_with_google_vision_success(self):
        """Google Vision OCRが成功する"""
        with patch('app.services.content_intelligence.vision') as mock_vision:
            # モック設定
            mock_client = MagicMock()
            mock_vision.ImageAnnotatorClient.return_value = mock_client
            mock_vision.Image.return_value = MagicMock()
            
            # レスポンスをモック
            mock_text = MagicMock()
            mock_text.description = "請求書\n株式会社テスト\n金額: ¥50,000"
            mock_vertex = MagicMock()
            mock_vertex.x = 10
            mock_vertex.y = 10
            mock_text.bounding_poly.vertices = [mock_vertex]
            
            mock_response = MagicMock()
            mock_response.error.message = ""
            mock_response.text_annotations = [mock_text]
            
            mock_client.text_detection.return_value = mock_response
            
            # テスト実行
            result = await OCRExtractor.extract_with_google_vision(b"fake image data")
            
            assert result.success is True
            assert result.method == ExtractionMethod.OCR_GOOGLE_VISION
            assert "請求書" in result.text


# ==================== 6C: URL Extraction Tests ====================

class TestURLExtractor:
    """URL先コンテンツ取得のテスト"""
    
    @pytest.mark.asyncio
    async def test_extract_url_success(self):
        """URLからテキスト取得が成功する"""
        with patch('app.services.content_intelligence.async_playwright') as mock_playwright:
            # モック設定
            mock_page = AsyncMock()
            mock_page.goto = AsyncMock()
            mock_page.title = AsyncMock(return_value="テストページ")
            mock_page.url = "https://example.com/page"
            mock_page.evaluate = AsyncMock(return_value="これはテストコンテンツです。")
            
            mock_context = AsyncMock()
            mock_context.new_page = AsyncMock(return_value=mock_page)
            
            mock_browser = AsyncMock()
            mock_browser.new_context = AsyncMock(return_value=mock_context)
            mock_browser.close = AsyncMock()
            
            mock_chromium = AsyncMock()
            mock_chromium.launch = AsyncMock(return_value=mock_browser)
            
            mock_pw = AsyncMock()
            mock_pw.chromium = mock_chromium
            
            mock_playwright_cm = AsyncMock()
            mock_playwright_cm.__aenter__ = AsyncMock(return_value=mock_pw)
            mock_playwright_cm.__aexit__ = AsyncMock()
            
            mock_playwright.return_value = mock_playwright_cm
            
            # テスト実行
            result = await URLExtractor.extract("https://example.com/page")
            
            assert result.success is True
            assert result.method == ExtractionMethod.URL_PLAYWRIGHT
            assert result.title == "テストページ"
            assert "テストコンテンツ" in result.text


# ==================== 6D: Content Classification Tests ====================

class TestContentClassifier:
    """コンテンツ分類のテスト"""
    
    @pytest.mark.asyncio
    async def test_classify_invoice(self):
        """請求書の分類テスト"""
        with patch('app.services.content_intelligence.ChatAnthropic') as mock_anthropic:
            # モック設定
            mock_llm = AsyncMock()
            mock_response = MagicMock()
            mock_response.content = '''
            {
                "category": "invoice",
                "confidence_score": 0.95,
                "reasoning": "支払期日、振込先情報、請求金額が含まれているため請求書と判定",
                "extracted_data": {
                    "amount": 50000,
                    "due_date": "2024-01-31",
                    "invoice_number": "INV-2024-001",
                    "issuer_name": "株式会社テスト"
                },
                "secondary_categories": []
            }
            '''
            mock_llm.ainvoke = AsyncMock(return_value=mock_response)
            mock_anthropic.return_value = mock_llm
            
            # テスト実行
            result = await ContentClassifier.classify(
                text="請求書\n株式会社テスト\n請求金額: ¥50,000\n支払期日: 2024年1月31日\n振込先: みずほ銀行 本店 普通 1234567",
                subject="1月分請求書のお送り",
                sender="billing@test.co.jp"
            )
            
            assert result.category == ContentCategory.INVOICE
            assert result.confidence == ContentConfidence.HIGH
            assert result.confidence_score >= 0.9
    
    @pytest.mark.asyncio
    async def test_classify_otp(self):
        """OTPの分類テスト"""
        with patch('app.services.content_intelligence.ChatAnthropic') as mock_anthropic:
            mock_llm = AsyncMock()
            mock_response = MagicMock()
            mock_response.content = '''
            {
                "category": "otp",
                "confidence_score": 0.98,
                "reasoning": "認証コードが含まれている",
                "extracted_data": {
                    "code": "123456",
                    "service_name": "Amazon",
                    "expires_in": 300
                },
                "secondary_categories": []
            }
            '''
            mock_llm.ainvoke = AsyncMock(return_value=mock_response)
            mock_anthropic.return_value = mock_llm
            
            result = await ContentClassifier.classify(
                text="Amazonからの認証コードです。\n\n認証コード: 123456\n\nこのコードは5分間有効です。",
                subject="Amazon認証コード"
            )
            
            assert result.category == ContentCategory.OTP
            assert result.extracted_data is not None
            assert result.extracted_data.get("code") == "123456"
    
    @pytest.mark.asyncio
    async def test_classify_confirmation(self):
        """予約確認メールの分類テスト"""
        with patch('app.services.content_intelligence.ChatAnthropic') as mock_anthropic:
            mock_llm = AsyncMock()
            mock_response = MagicMock()
            mock_response.content = '''
            {
                "category": "confirmation",
                "confidence_score": 0.92,
                "reasoning": "予約番号と予約詳細が含まれているため予約確認と判定",
                "extracted_data": {
                    "confirmation_type": "reservation",
                    "confirmation_number": "HT-20240115-001",
                    "service_name": "ホテル予約",
                    "details": {"checkin": "2024-02-01", "checkout": "2024-02-02"}
                },
                "secondary_categories": ["notification"]
            }
            '''
            mock_llm.ainvoke = AsyncMock(return_value=mock_response)
            mock_anthropic.return_value = mock_llm
            
            result = await ContentClassifier.classify(
                text="ご予約ありがとうございます。\n予約番号: HT-20240115-001\nチェックイン: 2024年2月1日",
                subject="【予約確認】ホテル予約完了"
            )
            
            assert result.category == ContentCategory.CONFIRMATION


# ==================== Integration Tests ====================

class TestContentIntelligenceService:
    """統合サービスのテスト"""
    
    @pytest.mark.asyncio
    async def test_analyze_pdf_attachment(self):
        """PDF添付ファイル解析の統合テスト"""
        with patch.object(PDFExtractor, 'extract') as mock_pdf:
            with patch.object(ContentClassifier, 'classify') as mock_classify:
                mock_pdf.return_value = PDFExtractionResult(
                    success=True,
                    text="請求書 金額: 10,000円",
                    method=ExtractionMethod.PDF_PDFPLUMBER,
                    page_count=1,
                )
                
                mock_classify.return_value = ClassificationResult(
                    category=ContentCategory.INVOICE,
                    confidence=ContentConfidence.HIGH,
                    confidence_score=0.95,
                )
                
                service = ContentIntelligenceService()
                extraction, classification = await service.analyze_attachment(
                    file_data=b"fake pdf",
                    mime_type="application/pdf",
                    filename="invoice.pdf",
                )
                
                assert extraction.success is True
                assert classification.category == ContentCategory.INVOICE
    
    @pytest.mark.asyncio
    async def test_analyze_image_attachment(self):
        """画像添付ファイル解析の統合テスト"""
        with patch.object(OCRExtractor, 'extract') as mock_ocr:
            with patch.object(ContentClassifier, 'classify') as mock_classify:
                mock_ocr.return_value = OCRExtractionResult(
                    success=True,
                    text="認証コード: 654321",
                    method=ExtractionMethod.OCR_TESSERACT,
                )
                
                mock_classify.return_value = ClassificationResult(
                    category=ContentCategory.OTP,
                    confidence=ContentConfidence.HIGH,
                    confidence_score=0.98,
                    extracted_data={"code": "654321"},
                )
                
                service = ContentIntelligenceService()
                extraction, classification = await service.analyze_attachment(
                    file_data=b"fake image",
                    mime_type="image/png",
                )
                
                assert extraction.success is True
                assert classification.category == ContentCategory.OTP
    
    @pytest.mark.asyncio
    async def test_unsupported_mime_type(self):
        """サポートされていないMIMEタイプの処理"""
        service = ContentIntelligenceService()
        extraction, classification = await service.analyze_attachment(
            file_data=b"some data",
            mime_type="application/zip",
        )
        
        assert extraction.success is False
        assert "Unsupported" in extraction.error
        assert classification is None


# ==================== Schema Tests ====================

class TestContentSchemas:
    """スキーマのテスト"""
    
    def test_extraction_method_values(self):
        """抽出方法の値が正しい"""
        assert ExtractionMethod.PDF_PDFPLUMBER.value == "pdf_pdfplumber"
        assert ExtractionMethod.OCR_TESSERACT.value == "ocr_tesseract"
        assert ExtractionMethod.URL_PLAYWRIGHT.value == "url_playwright"
    
    def test_content_category_values(self):
        """コンテンツカテゴリの値が正しい"""
        assert ContentCategory.INVOICE.value == "invoice"
        assert ContentCategory.RECEIPT.value == "receipt"
        assert ContentCategory.OTP.value == "otp"
        assert ContentCategory.CONFIRMATION.value == "confirmation"
    
    def test_classification_result_model(self):
        """分類結果モデルが正しく作成できる"""
        result = ClassificationResult(
            category=ContentCategory.INVOICE,
            confidence=ContentConfidence.HIGH,
            confidence_score=0.95,
            reasoning="請求書と判定",
        )
        
        assert result.category == ContentCategory.INVOICE
        assert result.confidence_score == 0.95


# ==================== API Tests ====================

class TestContentAPI:
    """Content Intelligence APIのテスト"""
    
    def test_classify_endpoint(self, client, auth_token):
        """分類APIエンドポイントのテスト"""
        # Note: 実際のテストではAPIモックが必要
        pass
    
    def test_extract_url_endpoint(self, client, auth_token):
        """URL抽出APIエンドポイントのテスト"""
        # Note: 実際のテストではPlaywrightモックが必要
        pass



