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
import sys

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
    async def test_extract_pdf_invalid_data(self):
        """無効なPDFデータでエラーハンドリングが動作する"""
        result = await PDFExtractor.extract(b"not a pdf", "test.pdf")
        
        # 無効なPDFなのでsuccessはFalse
        assert result.success is False
        assert result.error is not None
        assert result.method == ExtractionMethod.PDF_PDFPLUMBER
    
    @pytest.mark.asyncio
    async def test_extract_pdf_empty_data(self):
        """空のPDFデータでエラーハンドリングが動作する"""
        result = await PDFExtractor.extract(b"", "empty.pdf")
        
        assert result.success is False
        assert result.error is not None


# ==================== 6B: OCR Extraction Tests ====================

class TestOCRExtractor:
    """OCR抽出のテスト"""
    
    @pytest.mark.asyncio
    async def test_ocr_invalid_image(self):
        """無効な画像データでエラーハンドリングが動作する"""
        extractor = OCRExtractor()
        result = await extractor.extract_with_tesseract(b"not an image")
        
        # 無効な画像なのでsuccessはFalse
        assert result.success is False
        assert result.error is not None
        assert result.method == ExtractionMethod.OCR_TESSERACT
    
    @pytest.mark.asyncio
    async def test_ocr_extract_method(self):
        """extractメソッドがデフォルトでtesseractを使用する"""
        extractor = OCRExtractor()
        result = await extractor.extract(b"not an image")
        
        # エラーになるが、methodはocr_tesseract
        assert result.method == ExtractionMethod.OCR_TESSERACT


# ==================== 6C: URL Extraction Tests ====================

class TestURLExtractor:
    """URL先コンテンツ取得のテスト"""
    
    @pytest.mark.asyncio
    async def test_extract_url_with_requests(self):
        """requestsを使用したURL抽出（モック）"""
        with patch('requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = """
            <html>
            <head><title>Test Page</title></head>
            <body><main>This is test content</main></body>
            </html>
            """
            mock_response.url = "https://example.com"
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response
            
            result = await URLExtractor.extract_with_requests("https://example.com")
            
            assert result.success is True
            assert result.method == ExtractionMethod.URL_REQUESTS
            assert result.title == "Test Page"
            assert "test content" in result.text.lower()


# ==================== 6D: Content Classification Tests ====================

class TestContentClassifier:
    """コンテンツ分類のテスト（モックなし - 結果の型チェック）"""
    
    def test_classification_result_structure(self):
        """ClassificationResultの構造が正しい"""
        result = ClassificationResult(
            category=ContentCategory.INVOICE,
            confidence=ContentConfidence.HIGH,
            confidence_score=0.95,
            reasoning="請求書と判定",
            extracted_data={"amount": 50000},
        )
        
        assert result.category == ContentCategory.INVOICE
        assert result.confidence == ContentConfidence.HIGH
        assert result.confidence_score == 0.95
        assert result.extracted_data["amount"] == 50000


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
        assert ExtractionMethod.URL_REQUESTS.value == "url_requests"
    
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


# ==================== 手動テスト確認済みシナリオ ====================
# 以下は手動テスト(2024-12-22)で動作確認したシナリオを自動テスト化

class TestManualVerifiedScenarios:
    """手動テストで動作確認済みのシナリオ"""
    
    @pytest.mark.asyncio
    async def test_6c_url_extract_example_com(self):
        """
        6C: URL先取得API - example.comからテキスト取得
        手動テスト結果: success=True, title="Example Domain"
        """
        result = await URLExtractor.extract("https://example.com")
        
        assert result.success is True
        assert result.method == ExtractionMethod.URL_REQUESTS
        assert result.title == "Example Domain"
        assert "example" in result.text.lower()
    
    @pytest.mark.asyncio
    async def test_6a_pdf_extract_error_handling(self):
        """
        6A: PDF解析API - 無効なPDFに適切なエラーを返す
        手動テスト結果: success=False, error="No /Root object!"
        """
        result = await PDFExtractor.extract(b"not a pdf", "test.pdf")
        
        assert result.success is False
        assert result.error is not None
        assert "pdf" in result.error.lower() or "root" in result.error.lower()
    
    @pytest.mark.asyncio
    async def test_6b_ocr_extract_error_handling(self):
        """
        6B: 画像OCR API - 無効な画像に適切なエラーを返す
        手動テスト結果: success=False, error="cannot identify image file"
        """
        extractor = OCRExtractor()
        result = await extractor.extract(b"not an image")
        
        assert result.success is False
        assert result.error is not None
        assert "image" in result.error.lower() or "identify" in result.error.lower()
    
    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not pytest.importorskip("anthropic", reason="anthropic not installed"),
        reason="Requires anthropic SDK and API key"
    )
    async def test_6d_classify_invoice_real(self):
        """
        6D: コンテンツ分類API - 請求書テキストをinvoiceに分類
        手動テスト結果: category="invoice", confidence_score=0.98
        
        注意: このテストは実際のClaude APIを呼び出すため、
        ANTHROPIC_API_KEYが設定されていない場合はスキップされます
        """
        import os
        if not os.getenv("ANTHROPIC_API_KEY"):
            pytest.skip("ANTHROPIC_API_KEY not set")
        
        result = await ContentClassifier.classify(
            text="""請求書
株式会社テスト
請求金額: ¥50,000
支払期日: 2024年1月31日
振込先: みずほ銀行 本店 普通 1234567""",
            subject="1月分請求書のお送り",
            sender="billing@test.co.jp"
        )
        
        assert result.category == ContentCategory.INVOICE
        assert result.confidence_score >= 0.9
        assert result.extracted_data is not None
