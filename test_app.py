"""
PDF Export API Test Suite
=========================
Docling converter mock'lanarak API endpoint'lerinin doğrulama mantığı,
hata yönetimi, boyut limiti, kimlik doğrulama ve eşzamanlılık kontrolü
test edilir.

Çalıştırma:
    pytest test_app.py -v
"""

import base64
import io
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Docling'i mock'la: Test ortamında gerçek PDF dönüşümü yapılmaz.
# Mock, converter.convert() çağrıldığında sahte bir result nesnesi döner.
mock_converter = MagicMock()
mock_document = MagicMock()
mock_document.export_to_markdown.return_value = "# Mock Markdown"
mock_document.export_to_dict.return_value = {"mock": "json"}
mock_document.export_to_doctags.return_value = "<doctag>mock</doctag>"
mock_document.export_to_text.return_value = "Mock plain text"
mock_result = MagicMock()
mock_result.document = mock_document
mock_converter.convert.return_value = mock_result

# DocumentConverter'ı import öncesinde mock'la
with patch("docling.document_converter.DocumentConverter", return_value=mock_converter):
    from app import app, ALLOWED_DIR, MAX_FILE_SIZE, API_KEY
    import app as app_module


def _auth_headers() -> dict:
    """Test isteklerinde kullanılacak geçerli auth header'ını döner."""
    return {"X-API-Key": API_KEY}


@pytest.fixture
def client():
    """Flask test client oluşturur. Her test için temiz bir istemci sağlar."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def sample_pdf(tmp_path):
    """
    ALLOWED_DIR altında küçük bir sahte PDF dosyası oluşturur.
    Gerçek bir PDF değil ama dosya varlık ve uzantı kontrollerini geçer.
    """
    pdf_file = ALLOWED_DIR / "test_sample.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 fake content for testing")
    yield pdf_file
    pdf_file.unlink(missing_ok=True)


# -----------------------------------------------------------------------
# Health Check
# -----------------------------------------------------------------------

class TestHealthCheck:
    """GET / endpoint'i testleri."""

    def test_home_returns_server_info(self, client):
        """Sunucu durum endpoint'i temel bilgileri döndürmeli."""
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["server"] == "running"
        assert "formats" in data
        assert "markdown" in data["formats"]

    def test_home_does_not_require_auth(self, client):
        """Health check endpoint'i auth olmadan erişilebilir olmalı."""
        resp = client.get("/")  # X-API-Key header yok
        assert resp.status_code == 200


# -----------------------------------------------------------------------
# Kimlik Doğrulama (Auth) Testleri
# -----------------------------------------------------------------------

class TestAuthentication:
    """API key tabanlı kimlik doğrulama testleri."""

    def test_missing_api_key_returns_401(self, client):
        """X-API-Key header'ı olmadan POST istek 401 döndürmeli."""
        resp = client.post("/export_to_markdown", json={"path": "test.pdf"})
        assert resp.status_code == 401
        assert "Missing" in resp.get_json()["error"]

    def test_invalid_api_key_returns_401(self, client):
        """Yanlış API key ile POST istek 401 döndürmeli."""
        resp = client.post(
            "/export_to_markdown",
            json={"path": "test.pdf"},
            headers={"X-API-Key": "wrong-key-12345"},
        )
        assert resp.status_code == 401
        assert "Invalid" in resp.get_json()["error"]

    def test_empty_api_key_returns_401(self, client):
        """Boş API key header'ı 401 döndürmeli."""
        resp = client.post(
            "/export_to_markdown",
            json={"path": "test.pdf"},
            headers={"X-API-Key": ""},
        )
        assert resp.status_code == 401

    def test_valid_api_key_passes_auth(self, client, sample_pdf):
        """Doğru API key ile istek auth aşamasını geçmeli."""
        resp = client.post(
            "/export_to_markdown",
            json={"path": str(sample_pdf)},
            headers=_auth_headers(),
        )
        # Auth geçmeli, 401 dönmemeli
        assert resp.status_code != 401

    @pytest.mark.parametrize("endpoint", [
        "/export_to_markdown",
        "/export_to_json",
        "/export_to_doctags",
        "/export_to_text",
    ])
    def test_all_post_endpoints_require_auth(self, client, endpoint):
        """Tüm POST endpoint'leri auth gerektirmeli."""
        resp = client.post(endpoint, json={"path": "test.pdf"})
        assert resp.status_code == 401


# -----------------------------------------------------------------------
# İstek Doğrulama Testleri
# -----------------------------------------------------------------------

class TestRequestValidation:
    """Tüm export endpoint'leri için ortak doğrulama testleri."""

    @pytest.mark.parametrize("endpoint", [
        "/export_to_markdown",
        "/export_to_json",
        "/export_to_doctags",
        "/export_to_text",
    ])
    def test_missing_body_returns_400(self, client, endpoint):
        """Boş istek gövdesi 400 hatası döndürmeli."""
        resp = client.post(endpoint, headers=_auth_headers())
        assert resp.status_code == 400

    @pytest.mark.parametrize("endpoint", [
        "/export_to_markdown",
        "/export_to_json",
        "/export_to_doctags",
        "/export_to_text",
    ])
    def test_missing_path_field_returns_400(self, client, endpoint):
        """path, base64 veya file olmadan gönderilen istek 400 döndürmeli."""
        resp = client.post(endpoint, json={"wrong_field": "value"}, headers=_auth_headers())
        assert resp.status_code == 400

    def test_nonexistent_file_returns_404(self, client):
        """Var olmayan dosya yolu 404 döndürmeli."""
        fake_path = str(ALLOWED_DIR / "nonexistent.pdf")
        resp = client.post("/export_to_markdown", json={"path": fake_path}, headers=_auth_headers())
        assert resp.status_code == 404

    def test_non_pdf_extension_returns_400(self, client, tmp_path):
        """PDF olmayan dosya uzantısı 400 döndürmeli."""
        txt_file = ALLOWED_DIR / "test_file.txt"
        txt_file.write_text("not a pdf")
        try:
            resp = client.post(
                "/export_to_markdown",
                json={"path": str(txt_file)},
                headers=_auth_headers(),
            )
            assert resp.status_code == 400
            assert "Only PDF" in resp.get_json()["error"]
        finally:
            txt_file.unlink(missing_ok=True)


# -----------------------------------------------------------------------
# Path Traversal Güvenlik Testleri
# -----------------------------------------------------------------------

class TestPathTraversal:
    """Path traversal saldırılarının engellendiğini doğrular."""

    def test_traversal_with_dotdot_returns_403(self, client):
        """../ ile üst dizine çıkma girişimi 403 döndürmeli."""
        resp = client.post(
            "/export_to_markdown",
            json={"path": str(ALLOWED_DIR / ".." / ".." / "etc" / "passwd.pdf")},
            headers=_auth_headers(),
        )
        assert resp.status_code == 403
        assert "Access denied" in resp.get_json()["error"]

    def test_absolute_path_outside_allowed_returns_403(self, client):
        """İzin verilen dizin dışındaki mutlak yol 403 döndürmeli."""
        resp = client.post(
            "/export_to_markdown",
            json={"path": "/tmp/secret.pdf"},
            headers=_auth_headers(),
        )
        # /tmp ALLOWED_DIR altında değilse 403 dönmeli
        if not Path("/tmp").resolve().is_relative_to(ALLOWED_DIR):
            assert resp.status_code == 403


# -----------------------------------------------------------------------
# Dosya Boyutu Limit Testleri
# -----------------------------------------------------------------------

class TestFileSizeLimit:
    """10 MB dosya boyutu limitinin uygulandığını doğrular."""

    def test_oversized_file_returns_413(self, client):
        """MAX_FILE_SIZE'ı aşan dosya 413 döndürmeli."""
        big_file = ALLOWED_DIR / "too_big.pdf"
        # Limitin 1 byte üzerinde dosya oluştur
        big_file.write_bytes(b"%PDF" + b"\x00" * (MAX_FILE_SIZE + 1))
        try:
            resp = client.post(
                "/export_to_markdown",
                json={"path": str(big_file)},
                headers=_auth_headers(),
            )
            assert resp.status_code == 413
            assert "exceeds" in resp.get_json()["error"]
        finally:
            big_file.unlink(missing_ok=True)

    def test_oversized_base64_returns_413(self, client):
        """Base64 ile gönderilen büyük veri 413 döndürmeli."""
        big_data = base64.b64encode(b"\x00" * (MAX_FILE_SIZE + 1)).decode()
        resp = client.post(
            "/export_to_markdown",
            json={"base64": big_data},
            headers=_auth_headers(),
        )
        assert resp.status_code == 413


# -----------------------------------------------------------------------
# Başarılı Dönüşüm Testleri
# -----------------------------------------------------------------------

class TestSuccessfulConversion:
    """Tüm formatlar için başarılı dönüşüm senaryoları."""

    def test_markdown_conversion(self, client, sample_pdf):
        """Path ile markdown dönüşümü başarılı olmalı."""
        resp = client.post("/export_to_markdown", json={"path": str(sample_pdf)}, headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["format"] == "markdown"
        assert data["content"] == "# Mock Markdown"
        assert "elapsed_seconds" in data

    def test_json_conversion(self, client, sample_pdf):
        """JSON dönüşümü başarılı olmalı."""
        resp = client.post("/export_to_json", json={"path": str(sample_pdf)}, headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["format"] == "json"
        assert data["content"] == {"mock": "json"}

    def test_doctags_conversion(self, client, sample_pdf):
        """Doctags dönüşümü başarılı olmalı."""
        resp = client.post("/export_to_doctags", json={"path": str(sample_pdf)}, headers=_auth_headers())
        assert resp.status_code == 200
        assert resp.get_json()["format"] == "doctags"

    def test_text_conversion(self, client, sample_pdf):
        """Text dönüşümü başarılı olmalı."""
        resp = client.post("/export_to_text", json={"path": str(sample_pdf)}, headers=_auth_headers())
        assert resp.status_code == 200
        assert resp.get_json()["format"] == "text"
        assert resp.get_json()["content"] == "Mock plain text"


# -----------------------------------------------------------------------
# Base64 ve File Upload Testleri
# -----------------------------------------------------------------------

class TestAlternativeInputs:
    """Base64 ve multipart file upload giriş yöntemleri."""

    def test_base64_upload(self, client):
        """Base64 kodlu PDF gönderimi başarılı olmalı."""
        pdf_bytes = b"%PDF-1.4 fake content"
        encoded = base64.b64encode(pdf_bytes).decode()
        resp = client.post(
            "/export_to_markdown",
            json={"base64": encoded, "filename": "test.pdf"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "success"

    def test_invalid_base64_returns_400(self, client):
        """Geçersiz base64 verisi 400 döndürmeli."""
        resp = client.post(
            "/export_to_markdown",
            json={"base64": "!!!invalid-base64!!!"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 400

    def test_file_upload(self, client):
        """Multipart form ile dosya yükleme başarılı olmalı."""
        data = {"file": (io.BytesIO(b"%PDF-1.4 fake"), "test.pdf")}
        resp = client.post(
            "/export_to_markdown",
            data=data,
            content_type="multipart/form-data",
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "success"

    def test_non_pdf_upload_returns_400(self, client):
        """PDF olmayan dosya yükleme 400 döndürmeli."""
        data = {"file": (io.BytesIO(b"not a pdf"), "readme.txt")}
        resp = client.post(
            "/export_to_markdown",
            data=data,
            content_type="multipart/form-data",
            headers=_auth_headers(),
        )
        assert resp.status_code == 400


# -----------------------------------------------------------------------
# Eşzamanlılık (Busy) Testleri
# -----------------------------------------------------------------------

class TestBusyMechanism:
    """Aynı anda yalnızca bir dönüşüm çalışmasını doğrular."""

    def test_busy_flag_returns_503(self, client, sample_pdf):
        """Converter meşgulken ikinci istek 503 döndürmeli."""
        # Meşgul bayrağını manuel olarak aç
        with app_module._busy_lock:
            app_module._is_busy = True

        try:
            resp = client.post(
                "/export_to_markdown",
                json={"path": str(sample_pdf)},
                headers=_auth_headers(),
            )
            assert resp.status_code == 503
            assert resp.get_json()["status"] == "busy"
        finally:
            # Bayrağı temizle
            with app_module._busy_lock:
                app_module._is_busy = False


# -----------------------------------------------------------------------
# Hata Yönetimi Testleri
# -----------------------------------------------------------------------

class TestErrorHandling:
    """Converter hatalarının düzgün yakalandığını doğrular."""

    def test_converter_exception_returns_500(self, client, sample_pdf):
        """Docling hatası 500 ile anlamlı mesaj döndürmeli."""
        mock_converter.convert.side_effect = RuntimeError("Corrupted PDF")
        try:
            resp = client.post(
                "/export_to_markdown",
                json={"path": str(sample_pdf)},
                headers=_auth_headers(),
            )
            assert resp.status_code == 500
            assert "conversion failed" in resp.get_json()["error"].lower()
        finally:
            # Mock'u eski haline döndür
            mock_converter.convert.side_effect = None
            mock_converter.convert.return_value = mock_result


# -----------------------------------------------------------------------
# Timeout Testleri
# -----------------------------------------------------------------------

class TestTimeout:
    """Dönüşüm zaman aşımı kontrolünü doğrular."""

    def test_conversion_timeout_returns_504(self, client, sample_pdf):
        """Timeout aşıldığında 504 döndürmeli."""
        import time as _time

        # Converter'ı yavaşlat: CONVERSION_TIMEOUT'u aşacak şekilde beklet
        def _slow_convert(*args, **kwargs):
            _time.sleep(5)
            return mock_result

        mock_converter.convert.side_effect = _slow_convert

        # Timeout'u kısa tut (1 saniye) böylece test hızlı çalışır
        original_timeout = app_module.CONVERSION_TIMEOUT
        app_module.CONVERSION_TIMEOUT = 1

        try:
            resp = client.post(
                "/export_to_markdown",
                json={"path": str(sample_pdf)},
                headers=_auth_headers(),
            )
            assert resp.status_code == 504
            data = resp.get_json()
            assert data["status"] == "timeout"
            assert "timed out" in data["error"].lower()
        finally:
            # Orijinal değerleri geri yükle
            app_module.CONVERSION_TIMEOUT = original_timeout
            mock_converter.convert.side_effect = None
            mock_converter.convert.return_value = mock_result
