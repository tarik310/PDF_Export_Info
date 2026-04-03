"""
PDF Export API
==============
Docling kütüphanesi ile PDF dosyalarını markdown, JSON, doctags ve text
formatlarına dönüştüren REST API servisi.

Kullanım:
    python app.py

Ortam değişkenleri (opsiyonel):
    PDF_ALLOWED_DIR  - Path tabanlı isteklerde izin verilen dizin (varsayılan: çalışma dizini)
    PDF_MAX_SIZE_MB  - Maksimum dosya boyutu MB cinsinden (varsayılan: 10)
    PDF_API_PORT     - Sunucu portu (varsayılan: 5952)
    PDF_API_KEY      - API anahtarı (belirtilmezse otomatik üretilir ve .api_key dosyasına yazılır)
    PDF_CONVERSION_TIMEOUT - Dönüşüm zaman aşımı, saniye (varsayılan: 300)

Kimlik doğrulama:
    POST endpoint'leri X-API-Key header'ı gerektirir.
    GET / (health check) endpoint'i auth gerektirmez.

Desteklenen giriş yöntemleri:
    1. Multipart form-data ile dosya yükleme  (field adı: "file")
    2. JSON body ile base64 kodlu PDF         {"base64": "...", "filename": "opsiyonel.pdf"}
    3. JSON body ile dosya yolu               {"path": "izinli/dizin/dosya.pdf"}

Endpoint'ler:
    GET  /                    - Sunucu durum bilgisi
    POST /export_to_markdown  - PDF -> Markdown
    POST /export_to_json      - PDF -> JSON
    POST /export_to_doctags   - PDF -> Doctags
    POST /export_to_text      - PDF -> Plain Text
"""

import os
import base64
import logging
import secrets
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path

from flask import Flask, request, jsonify
from flask_cors import CORS
from docling.document_converter import DocumentConverter
from dotenv import load_dotenv
load_dotenv()
# ---------------------------------------------------------------------------
# Konfigürasyon
# Ortam değişkenleri ile override edilebilir; bu sayede aynı kod farklı
# ortamlarda (geliştirme, test, üretim) farklı ayarlarla çalıştırılabilir.
# ---------------------------------------------------------------------------

HOST = "127.0.0.1"
PORT = int(os.environ.get("PDF_API_PORT", 5952))

# Path tabanlı isteklerde yalnızca bu dizin altındaki PDF dosyalarına
# erişilebilir. Path traversal saldırılarını önlemek için resolve() ile
# canonical path karşılaştırması yapılır.
ALLOWED_DIR = Path(os.environ.get("PDF_ALLOWED_DIR", Path.cwd())).resolve()

# Maksimum dosya boyutu (byte cinsinden).
# Base64 encoding ~%33 overhead eklediğinden, Flask'ın MAX_CONTENT_LENGTH
# değeri buna göre ayarlanır.
MAX_FILE_SIZE = int(os.environ.get("PDF_MAX_SIZE_MB", 10)) * 1024 * 1024

# Dönüşüm zaman aşımı (saniye cinsinden).
# Bozuk veya aşırı karmaşık PDF dosyaları sunucuyu süresiz bloke edebilir.
# Bu limit aşıldığında istek 504 Gateway Timeout ile sonlandırılır.
CONVERSION_TIMEOUT = int(os.environ.get("PDF_CONVERSION_TIMEOUT", 300))

# ---------------------------------------------------------------------------
# API Key Yönetimi
# Basit ama etkili bir kimlik doğrulama katmanı. Aynı makinedeki diğer
# uygulamaların (SSRF, tarayıcı vb.) API'yi yetkisiz kullanmasını önler.
#
# Öncelik sırası:
#   1. PDF_API_KEY ortam değişkeni (CI/deployment senaryoları için)
#   2. .api_key dosyasındaki mevcut anahtar
#   3. Hiçbiri yoksa: yeni anahtar üretilir ve .api_key dosyasına kaydedilir
# ---------------------------------------------------------------------------
API_KEY_FILE = Path(__file__).parent / ".api_key"


def _load_or_generate_api_key() -> str:
    """
    API anahtarını yükler veya ilk çalıştırmada otomatik üretir.

    Ortam değişkeni tanımlıysa onu kullanır. Değilse .api_key dosyasından
    okur. Dosya da yoksa 32 byte'lık kriptografik olarak güvenli bir token
    üretir ve dosyaya yazar. Bu sayede anahtar sunucu yeniden başlatmalarında
    korunur.

    Returns:
        API key string'i
    """
    # 1. Ortam değişkeni kontrolü
    env_key = os.environ.get("PDF_API_KEY")
    if env_key:
        return env_key.strip()

    # 2. Dosyadan okuma
    if API_KEY_FILE.exists():
        key = API_KEY_FILE.read_text(encoding="utf-8").strip()
        if key:
            return key

    # 3. Yeni anahtar üret ve kaydet
    # secrets.token_urlsafe: kriptografik PRNG ile URL-safe token üretir
    key = secrets.token_urlsafe(32)
    API_KEY_FILE.write_text(key, encoding="utf-8")
    return key


API_KEY = _load_or_generate_api_key()

# Desteklenen export formatları ve karşılık gelen docling metotları.
# _convert_and_export() bu sözlüğü kullanarak doğru export metodunu çağırır.
# Yeni format eklerken buraya bir satır + aşağıya bir endpoint eklenmeli.
EXPORT_FORMATS = {
    "markdown": "export_to_markdown",
    "json":     "export_to_dict",
    "doctags":  "export_to_doctags",
    "text":     "export_to_text",
}

# ---------------------------------------------------------------------------
# Uygulama Başlatma
# ---------------------------------------------------------------------------

app = Flask(__name__)

# Flask'ın kendi büyük istek koruması. Base64 overhead'i hesaba katarak
# dosya limitinin ~1.5 katı olarak ayarlanır.
app.config["MAX_CONTENT_LENGTH"] = int(MAX_FILE_SIZE * 1.5)

# CORS: Kurum içi kullanımda farklı port/origin'lerden gelen isteklere
# izin verir. Örn. localhost:3000'deki bir frontend bu API'yi çağırabilir.
CORS(app)

# ---------------------------------------------------------------------------
# Loglama
# Hem konsola hem dosyaya yazar. Dönüşüm süreleri, hatalar ve güvenlik
# olayları (path traversal denemeleri vb.) kaydedilir.
# Not: Auth filtresi logger kullandığından, loglama auth'tan ÖNCE
# tanımlanmalıdır.
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("app.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Kimlik Doğrulama (Authentication)
# Her POST isteğinde X-API-Key header'ı kontrol edilir.
# GET / (health check) endpoint'i muaf tutulur; sunucu durumunu kontrol
# etmek için auth gerekmez.
# ---------------------------------------------------------------------------

@app.before_request
def _check_api_key():
    """
    İstek öncesi çalışan auth filtresi.

    Kurallar:
        - GET /  -> muaf (health check, monitoring amaçlı)
        - Diğer tüm istekler -> X-API-Key header'ı zorunlu
        - Yanlış veya eksik key -> 401 Unauthorized
        - Başarısız denemeler loglanır (güvenlik izleme)
    """
    # Health check endpoint'i auth gerektirmez
    if request.method == "GET" and request.path == "/":
        return None

    # CORS preflight (OPTIONS) istekleri auth gerektirmez;
    # tarayıcılar preflight'ta custom header gönderemez.
    if request.method == "OPTIONS":
        return None

    provided_key = request.headers.get("X-API-Key", "").strip()

    if not provided_key:
        logger.warning("Auth failed: missing API key from %s", request.remote_addr)
        return jsonify({"error": "Missing X-API-Key header"}), 401

    # Sabit zamanlı karşılaştırma: Timing attack'lara karşı koruma.
    # secrets.compare_digest byte/string karşılaştırmasını sabit sürede yapar,
    # böylece key'in hangi karakterinin yanlış olduğu zamanlama ile anlaşılamaz.
    if not secrets.compare_digest(provided_key, API_KEY):
        logger.warning("Auth failed: invalid API key from %s", request.remote_addr)
        return jsonify({"error": "Invalid API key"}), 401

    return None

# ---------------------------------------------------------------------------
# Converter ve Eşzamanlılık Kontrolü
# ---------------------------------------------------------------------------

# DocumentConverter ağır bir nesne olduğundan uygulama başlangıcında bir kez
# oluşturulur ve tüm isteklerde paylaşılır.
converter = DocumentConverter()

# Eşzamanlılık mekanizması: Aynı anda yalnızca bir dönüşüm işlemi çalışır.
# PDF dönüştürme CPU-yoğun olduğundan, kurum içi düşük trafikli kullanımda
# ardışık işleme en güvenli ve basit yaklaşımdır.
# İkinci bir istek gelirse 503 "busy" yanıtı döner.
_busy_lock = threading.Lock()
_is_busy = False

# Modül seviyesinde tek bir executor. Her istekte yeni executor oluşturmak
# gereksiz thread pool overhead'i yaratır. max_workers=1 çünkü busy lock
# zaten eşzamanlı dönüşümü engelliyor.
_executor = ThreadPoolExecutor(max_workers=1)


# ---------------------------------------------------------------------------
# Yardımcı Fonksiyonlar
# ---------------------------------------------------------------------------

def _check_file_size(file_path: Path) -> str | None:
    """
    Dosya boyutunu MAX_FILE_SIZE limitine göre kontrol eder.

    Returns:
        Limit aşılırsa hata mesajı (str), aşılmazsa None.
    """
    size = file_path.stat().st_size
    if size > MAX_FILE_SIZE:
        limit_mb = MAX_FILE_SIZE / (1024 * 1024)
        actual_mb = size / (1024 * 1024)
        return f"File size ({actual_mb:.1f} MB) exceeds the {limit_mb:.0f} MB limit"
    return None


def _resolve_pdf_from_request():
    """
    HTTP isteğinden PDF dosyasını çözümler. Üç giriş yöntemi desteklenir:

    1. Multipart form-data  -> geçici dosyaya kaydedilir
    2. JSON {"base64": ...} -> decode edilip geçici dosyaya yazılır
    3. JSON {"path": ...}   -> ALLOWED_DIR kontrolü ile doğrudan kullanılır

    Returns:
        (pdf_path, temp_path, error_response, status_code)
        - pdf_path:  Dönüşümde kullanılacak Path nesnesi
        - temp_path: Geçici dosya ise silinmesi gereken yol, yoksa None
        - error:     Hata varsa jsonify response, yoksa None
        - status:    HTTP status kodu veya None
    """

    # --- Yöntem 1: Multipart dosya yükleme ---
    if "file" in request.files:
        uploaded = request.files["file"]

        if not uploaded.filename:
            return None, None, jsonify({"error": "Empty filename"}), 400

        if not uploaded.filename.lower().endswith(".pdf"):
            return None, None, jsonify({"error": "Only PDF files are supported"}), 400

        # Güvenli geçici dosya oluştur ve yüklenen içeriği kaydet
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        uploaded.save(tmp)
        tmp.close()
        tmp_path = Path(tmp.name)

        size_err = _check_file_size(tmp_path)
        if size_err:
            tmp_path.unlink(missing_ok=True)
            return None, None, jsonify({"error": size_err}), 413

        logger.info(
            "File upload received: %s (%d bytes)",
            uploaded.filename,
            tmp_path.stat().st_size,
        )
        return tmp_path, tmp_path, None, None

    # --- JSON body gerekli (yöntem 2 ve 3 için) ---
    data = request.get_json(silent=True)
    if not data:
        return None, None, jsonify({
            "error": "Request must be JSON with 'path' or 'base64' field, "
                      "or multipart form with 'file' field"
        }), 400

    # --- Yöntem 2: Base64 kodlu PDF ---
    if "base64" in data:
        try:
            pdf_bytes = base64.b64decode(data["base64"], validate=True)
        except Exception:
            return None, None, jsonify({"error": "Invalid base64 data"}), 400

        if len(pdf_bytes) > MAX_FILE_SIZE:
            limit_mb = MAX_FILE_SIZE / (1024 * 1024)
            return None, None, jsonify({
                "error": f"Decoded data exceeds {limit_mb:.0f} MB limit"
            }), 413

        # Decode edilen byte'ları geçici dosyaya yaz
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmp.write(pdf_bytes)
        tmp.close()
        tmp_path = Path(tmp.name)

        filename = data.get("filename", "upload.pdf")
        logger.info("Base64 upload received: %s (%d bytes)", filename, len(pdf_bytes))
        return tmp_path, tmp_path, None, None

    # --- Yöntem 3: Dosya yolu (path) ---
    if "path" not in data:
        return None, None, jsonify({
            "error": "Missing 'path', 'base64', or file upload in request"
        }), 400

    path = Path(data["path"]).resolve()

    # Path traversal koruması: resolve() ile canonical path elde edilir,
    # ardından ALLOWED_DIR altında olup olmadığı kontrol edilir.
    # Bu sayede "../" ile üst dizinlere çıkma girişimleri engellenir.
    if not path.is_relative_to(ALLOWED_DIR):
        logger.warning("Path traversal attempt blocked: %s (allowed: %s)", data["path"], ALLOWED_DIR)
        return None, None, jsonify({"error": "Access denied"}), 403

    if not path.exists():
        return None, None, jsonify({"error": "File not found"}), 404

    if path.suffix.lower() != ".pdf":
        return None, None, jsonify({"error": "Only PDF files are supported"}), 400

    size_err = _check_file_size(path)
    if size_err:
        return None, None, jsonify({"error": size_err}), 413

    logger.info("Path-based request: %s (%d bytes)", path.name, path.stat().st_size)
    return path, None, None, None


def _convert_and_export(format_name: str):
    """
    Tüm export endpoint'lerinin kullandığı genel dönüşüm fonksiyonu.

    İstek doğrulama, meşguliyet kontrolü, PDF dönüşümü, hata yönetimi ve
    geçici dosya temizliği tek bir yerde toplanarak DRY prensibi sağlanır.

    Args:
        format_name: EXPORT_FORMATS sözlüğündeki format anahtarı
                     ("markdown", "json", "doctags", "text")

    Returns:
        Flask JSON response ile HTTP status kodu
    """
    global _is_busy

    # --- Eşzamanlılık kontrolü ---
    with _busy_lock:
        if _is_busy:
            logger.info("Request rejected: converter is busy")
            return jsonify({
                "error": "Server is busy with another conversion. Try again later.",
                "status": "busy",
            }), 503
        _is_busy = True

    temp_path = None
    try:
        # --- İstek doğrulama ve PDF dosyası çözümleme ---
        pdf_path, temp_path, error, status = _resolve_pdf_from_request()
        if error:
            return error, status

        # --- Dönüşüm işlemi (timeout korumalı) ---
        export_method = EXPORT_FORMATS[format_name]
        start_time = time.time()

        logger.info("Converting: %s -> %s (timeout: %ds)", pdf_path.name, format_name, CONVERSION_TIMEOUT)

        # Dönüşümü modül seviyesindeki _executor üzerinde çalıştır ve
        # CONVERSION_TIMEOUT kadar bekle. "with ThreadPoolExecutor" kullanılmaz
        # çünkü __exit__ metodu shutdown(wait=True) çağırarak timeout olsa bile
        # thread bitene kadar bloke olur. _executor.submit + future.result(timeout)
        # ile timeout aşıldığında istemci hemen 504 yanıtı alır.
        # Not: Timeout sonrası worker thread arka planda çalışmaya devam edebilir,
        # ancak _is_busy bayrağı serbest bırakılır ve istemci bloke olmaz.
        def _do_convert():
            result = converter.convert(pdf_path)
            return getattr(result.document, export_method)()

        future = _executor.submit(_do_convert)
        try:
            content = future.result(timeout=CONVERSION_TIMEOUT)
        except FuturesTimeoutError:
            future.cancel()
            elapsed = time.time() - start_time
            logger.error(
                "Conversion timed out: %s -> %s (%.2fs, limit: %ds)",
                pdf_path.name, format_name, elapsed, CONVERSION_TIMEOUT,
            )
            return jsonify({
                "error": f"Conversion timed out after {CONVERSION_TIMEOUT} seconds",
                "status": "timeout",
            }), 504

        elapsed = time.time() - start_time
        logger.info(
            "Conversion complete: %s -> %s (%.2fs)",
            pdf_path.name, format_name, elapsed,
        )

        return jsonify({
            "format": format_name,
            "content": content,
            "status": "success",
            "elapsed_seconds": round(elapsed, 2),
        })

    except Exception as e:
        # Docling hataları (bozuk PDF, desteklenmeyen yapı, bellek vb.)
        # ve diğer beklenmedik hatalar burada yakalanır.
        logger.exception("Conversion failed for format '%s'", format_name)
        return jsonify({"error": f"PDF conversion failed: {str(e)}"}), 500

    finally:
        # Geçici dosya temizliği: Upload ve base64 senaryolarında oluşturulan
        # dosyalar her durumda (başarı veya hata) silinir.
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)

        # Meşgul bayrağını serbest bırak
        with _busy_lock:
            _is_busy = False


# ---------------------------------------------------------------------------
# API Endpoint'leri
# ---------------------------------------------------------------------------

@app.route("/", methods=["GET"])
def home():
    """Sunucu durum kontrolü (health check). Konfigürasyon bilgilerini döner.
    Auth gerektirmez - monitoring ve bağlantı testi amaçlıdır."""
    return jsonify({
        "server": "running",
        "port": PORT,
        "allowed_dir": str(ALLOWED_DIR),
        "max_file_size_mb": MAX_FILE_SIZE / (1024 * 1024),
        "formats": list(EXPORT_FORMATS.keys()),
        "auth": "X-API-Key header required for POST endpoints",
        "message": "PDF Export API - Use POST /export_to_<format> to convert.",
    })


# Her export formatı için ayrı endpoint oluştur.
# Endpoint fonksiyonları ince birer sarmalayıcıdır (thin wrapper);
# tüm iş mantığı _convert_and_export içindedir.

@app.route("/export_to_markdown", methods=["POST"])
def post_export_to_markdown():
    """PDF -> Markdown dönüşümü."""
    return _convert_and_export("markdown")


@app.route("/export_to_json", methods=["POST"])
def post_export_to_json():
    """PDF -> Yapısal JSON dönüşümü."""
    return _convert_and_export("json")


@app.route("/export_to_doctags", methods=["POST"])
def post_export_to_doctags():
    """PDF -> Doctags formatı dönüşümü."""
    return _convert_and_export("doctags")


@app.route("/export_to_text", methods=["POST"])
def post_export_to_text():
    """PDF -> Düz metin (plain text) dönüşümü."""
    return _convert_and_export("text")


# ---------------------------------------------------------------------------
# Sunucu Başlatma
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("PDF Export API starting")
    logger.info("Host: %s:%d", HOST, PORT)
    logger.info("Allowed directory: %s", ALLOWED_DIR)
    logger.info("Max file size: %.0f MB", MAX_FILE_SIZE / (1024 * 1024))
    logger.info("Available formats: %s", ", ".join(EXPORT_FORMATS.keys()))
    logger.info("Conversion timeout: %ds", CONVERSION_TIMEOUT)

    # API key'i başlangıçta konsola yazdır.
    # Kaynak: ortam değişkeni mi, dosya mı, yoksa yeni mi üretildi?
    key_source = "env" if os.environ.get("PDF_API_KEY") else f"file ({API_KEY_FILE})"
    logger.info("API Key [%s]: %s", key_source, API_KEY)
    logger.info("Usage:  curl -H 'X-API-Key: %s' -X POST ...", API_KEY)

    logger.info("=" * 60)
    app.run(host=HOST, debug=False, port=PORT)
