# PDF Export API

Docling kutuphanesi ile PDF dosyalarini **Markdown**, **JSON**, **Doctags** ve **Plain Text** formatina donusturen lokal REST API servisi.

---

## Icindekiler

- [Kurulum](#kurulum)
- [Sunucu Yonetimi](#sunucu-yonetimi)
- [Kimlik Dogrulama](#kimlik-dogrulama)
- [API Referansi](#api-referansi)
  - [Health Check](#health-check)
  - [PDF Donusturme](#pdf-donusturme)
  - [Giris Yontemleri](#giris-yontemleri)
- [Yapilandirma](#yapilandirma)
- [Hata Kodlari](#hata-kodlari)
- [Testler](#testler)
- [Proje Yapisi](#proje-yapisi)
- [Sorun Giderme](#sorun-giderme)

---

## Kurulum

### Gereksinimler

- Python 3.10+
- pip

### Adimlar

**1. Proje dizinine gec:**

```bash
cd PDF_Export_Info
```

**2. Sanal ortam olustur ve aktif et:**

```bash
# macOS / Linux
python3 -m venv venv
source venv/bin/activate

# Windows
python -m venv venv
venv\Scripts\activate
```

**3. Bagimliliklari kur:**

```bash
pip install -r requirements.txt
```

> **Not:** `docling` ilk kurulumda model dosyalarini indirebilir. Bu islem internet baglantisi gerektirir ve birkaç dakika surebilir.

**4. (Opsiyonel) Ortam degiskenlerini ayarla:**

```bash
# macOS / Linux
export PDF_ALLOWED_DIR=/path/to/pdf/folder
export PDF_MAX_SIZE_MB=10
export PDF_CONVERSION_TIMEOUT=300

# Windows
set PDF_ALLOWED_DIR=C:\path\to\pdf\folder
set PDF_MAX_SIZE_MB=10
set PDF_CONVERSION_TIMEOUT=300
```

Ortam degiskenleri ayarlanmazsa varsayilan degerler kullanilir. Detaylar icin [Yapilandirma](#yapilandirma) bolumune bakiniz.

---

## Sunucu Yonetimi

### Baslatma

```bash
python app.py
```

Sunucu basladiginda asagidaki gibi bir cikti gorursunuz:

```
2026-02-28 10:00:00 [INFO] ============================================================
2026-02-28 10:00:00 [INFO] PDF Export API starting
2026-02-28 10:00:00 [INFO] Host: 127.0.0.1:5952
2026-02-28 10:00:00 [INFO] Allowed directory: /path/to/PDF_Export_Info
2026-02-28 10:00:00 [INFO] Max file size: 10 MB
2026-02-28 10:00:00 [INFO] Available formats: markdown, json, doctags, text
2026-02-28 10:00:00 [INFO] Conversion timeout: 300s
2026-02-28 10:00:00 [INFO] API Key [file (.api_key)]: xK7m9abc...
2026-02-28 10:00:00 [INFO] Usage:  curl -H 'X-API-Key: xK7m9abc...' -X POST ...
2026-02-28 10:00:00 [INFO] ============================================================
```

> Ilk calisitrmada `.api_key` dosyasina otomatik bir API anahtari uretilir. Bu anahtari konsol ciktisinda ve `.api_key` dosyasinda bulabilirsiniz.

### Windows'ta Baslatma

```bash
run_docling_app.bat
```

Batch dosyasi proje dizinine gecip `venv` icindeki Python ile `app.py`'yi calistirir.

### Durdurma

Konsol penceresinde `Ctrl+C` ile durdurabilirsiniz.

### Loglar

Loglar iki yere yazilir:

| Hedef | Aciklama |
|-------|----------|
| **Konsol** | Canli izleme icin |
| **app.log** | Kalici kayit, dosya boyutu limitlemesi yoktur |

Log icerigi: istek tipi, dosya adi, dosya boyutu, donusum suresi, auth hatalari, path traversal girisimleri.

---

## Kimlik Dogrulama

Tum POST endpoint'leri `X-API-Key` header'i gerektirir. Health check (`GET /`) muaftir.

### API Anahtari Nasil Alinir?

API anahtari su kaynaklardan (oncelik sirasina gore) belirlenir:

| Oncelik | Kaynak | Aciklama |
|---------|--------|----------|
| 1 | `PDF_API_KEY` ortam degiskeni | CI/deployment senaryolari icin |
| 2 | `.api_key` dosyasi | Sunucu yeniden baslatmalarinda korunur |
| 3 | Otomatik uretim | Ilk calistirmada `secrets.token_urlsafe(32)` ile uretilir |

### Anahtari Yenilemek

```bash
# .api_key dosyasini sil, sunucuyu yeniden baslat
rm .api_key
python app.py
# Yeni anahtar uretilir ve konsola yazdirilir
```

### Istek Ornegi

```bash
curl -H "X-API-Key: ANAHTARINIZ" \
     -H "Content-Type: application/json" \
     -d '{"path": "/path/to/dosya.pdf"}' \
     http://127.0.0.1:5952/export_to_markdown
```

---

## API Referansi

**Base URL:** `http://127.0.0.1:5952`

### Health Check

Sunucu durumunu ve yapilandirma bilgilerini doner. Auth gerektirmez.

```
GET /
```

**Ornek Yanit:**

```json
{
  "server": "running",
  "port": 5952,
  "allowed_dir": "/path/to/PDF_Export_Info",
  "max_file_size_mb": 10.0,
  "formats": ["markdown", "json", "doctags", "text"],
  "auth": "X-API-Key header required for POST endpoints",
  "message": "PDF Export API - Use POST /export_to_<format> to convert."
}
```

---

### PDF Donusturme

Dort format desteklenir. Tum endpoint'ler ayni istek/yanit yapisini kullanir.

| Endpoint | Cikis Formati | Aciklama |
|----------|---------------|----------|
| `POST /export_to_markdown` | Markdown | Basliklar, listeler, tablolar korunur |
| `POST /export_to_json` | JSON | Yapisal veri (sayfalar, paragraflar, tablolar) |
| `POST /export_to_doctags` | Doctags | Docling'e ozel etiket formati |
| `POST /export_to_text` | Plain Text | Sade metin, formatlama olmadan |

**Zorunlu Header:**

```
X-API-Key: ANAHTARINIZ
```

**Basarili Yanit (200):**

```json
{
  "format": "markdown",
  "content": "# Belge Basligi\n\nIcerik buraya...",
  "status": "success",
  "elapsed_seconds": 2.45
}
```

---

### Giris Yontemleri

PDF dosyasini uc farkli yontemle gonderebilirsiniz:

#### Yontem 1: Dosya Yolu (path)

Sunucu uzerindeki bir PDF'e yol belirterek donusum yapilir. Yol, `ALLOWED_DIR` altinda olmalidir.

```bash
curl -X POST http://127.0.0.1:5952/export_to_markdown \
  -H "X-API-Key: ANAHTARINIZ" \
  -H "Content-Type: application/json" \
  -d '{"path": "/izinli/dizin/belge.pdf"}'
```

#### Yontem 2: Dosya Yukleme (multipart form)

PDF dosyasini dogrudan yukleyerek donusum yapilir. Sunucuda dosyanin bulunmasina gerek yoktur.

```bash
curl -X POST http://127.0.0.1:5952/export_to_markdown \
  -H "X-API-Key: ANAHTARINIZ" \
  -F "file=@/yerel/yol/belge.pdf"
```

#### Yontem 3: Base64 Kodlu Veri

PDF dosyasini base64 olarak encode edip JSON body icinde gonderebilirsiniz.

```bash
# PDF'i base64'e donustur
BASE64_DATA=$(base64 -i belge.pdf)

# API'ye gonder
curl -X POST http://127.0.0.1:5952/export_to_json \
  -H "X-API-Key: ANAHTARINIZ" \
  -H "Content-Type: application/json" \
  -d "{\"base64\": \"$BASE64_DATA\", \"filename\": \"belge.pdf\"}"
```

> `filename` alani opsiyoneldir, sadece loglama amaclidir.

---

### Python Ornekleri

```python
import requests

API_URL = "http://127.0.0.1:5952"
API_KEY = "ANAHTARINIZ"  # .api_key dosyasindan veya konsol ciktisindan alinir
HEADERS = {"X-API-Key": API_KEY}


# --- Yontem 1: Dosya yolu ile ---
resp = requests.post(
    f"{API_URL}/export_to_markdown",
    json={"path": "/izinli/dizin/belge.pdf"},
    headers=HEADERS,
)
print(resp.json()["content"])


# --- Yontem 2: Dosya yukleme ile ---
with open("belge.pdf", "rb") as f:
    resp = requests.post(
        f"{API_URL}/export_to_text",
        files={"file": ("belge.pdf", f, "application/pdf")},
        headers=HEADERS,
    )
print(resp.json()["content"])


# --- Yontem 3: Base64 ile ---
import base64

with open("belge.pdf", "rb") as f:
    encoded = base64.b64encode(f.read()).decode()

resp = requests.post(
    f"{API_URL}/export_to_json",
    json={"base64": encoded, "filename": "belge.pdf"},
    headers=HEADERS,
)
print(resp.json()["content"])
```

---

## Yapilandirma

Tum ayarlar ortam degiskenleri ile override edilebilir. Hicbiri zorunlu degildir.

| Degisken | Varsayilan | Aciklama |
|----------|-----------|----------|
| `PDF_API_PORT` | `5952` | Sunucu portu |
| `PDF_ALLOWED_DIR` | Calisma dizini | Path yontemi icin izin verilen dizin |
| `PDF_MAX_SIZE_MB` | `10` | Maksimum dosya boyutu (MB) |
| `PDF_CONVERSION_TIMEOUT` | `300` | Donusum zaman asimi (saniye) |
| `PDF_API_KEY` | Otomatik uretilir | API anahtari |

### Ornek .env Kullanimi

Ortam degiskenleri `.env` dosyasindan da okunabilir (shell'de `source` ile):

```bash
# .env
export PDF_ALLOWED_DIR=/home/kullanici/pdf-arsiv
export PDF_MAX_SIZE_MB=20
export PDF_CONVERSION_TIMEOUT=600
export PDF_API_KEY=ozel-gizli-anahtariniz
```

```bash
source .env && python app.py
```

---

## Hata Kodlari

| HTTP Kodu | Durum | Aciklama | Ornek Yanit |
|-----------|-------|----------|-------------|
| **200** | Basari | Donusum tamamlandi | `{"status": "success", ...}` |
| **400** | Bad Request | Eksik/hatali istek parametresi | `{"error": "Only PDF files are supported"}` |
| **401** | Unauthorized | Eksik veya yanlis API anahtari | `{"error": "Missing X-API-Key header"}` |
| **403** | Forbidden | Izin verilmeyen dizine erisim | `{"error": "Access denied. Files must be under: ..."}` |
| **404** | Not Found | Dosya bulunamadi | `{"error": "File not found"}` |
| **413** | Payload Too Large | Dosya boyutu limiti asildi | `{"error": "File size (15.2 MB) exceeds the 10 MB limit"}` |
| **500** | Server Error | Donusum sirasinda beklenmedik hata | `{"error": "PDF conversion failed: ..."}` |
| **503** | Service Unavailable | Sunucu baska bir donusum ile mesgul | `{"error": "Server is busy...", "status": "busy"}` |
| **504** | Gateway Timeout | Donusum zaman asimina ugradi | `{"error": "Conversion timed out after 300 seconds", "status": "timeout"}` |

---

## Testler

Testler Docling converter'i mock'layarak calisir, gercek PDF donusumu yapilmaz.

```bash
# Tum testleri calistir
pytest test_app.py -v

# Belirli bir test sinifini calistir
pytest test_app.py::TestAuthentication -v

# Belirli bir testi calistir
pytest test_app.py::TestTimeout::test_conversion_timeout_returns_504 -v
```

### Test Siniflari

| Sinif | Test Sayisi | Kapsam |
|-------|-------------|--------|
| `TestHealthCheck` | 2 | Health check endpoint'i ve auth muafiyeti |
| `TestAuthentication` | 6 | API key dogrulama (eksik, yanlis, bos, gecerli) |
| `TestRequestValidation` | 4 | Istek body dogrulama (eksik alan, yanlis format) |
| `TestPathTraversal` | 2 | Path traversal saldiri engelleme |
| `TestFileSizeLimit` | 2 | Dosya boyutu limiti (path ve base64) |
| `TestSuccessfulConversion` | 4 | Basarili donusum (4 format) |
| `TestAlternativeInputs` | 4 | Base64 ve file upload girisleri |
| `TestBusyMechanism` | 1 | Eszamanlilik kontrolu (503 busy) |
| `TestErrorHandling` | 1 | Converter hata yakalama (500) |
| `TestTimeout` | 1 | Donusum zaman asimi (504) |

---

## Proje Yapisi

```
PDF_Export_Info/
├── app.py                 # Ana uygulama (Flask REST API)
├── test_app.py            # Test suite (pytest)
├── requirements.txt       # Python bagimliliklari
├── run_docling_app.bat    # Windows baslatici
├── .api_key               # Otomatik uretilen API anahtari (git'e dahil degil)
├── .gitignore             # Git dislamalari
├── app.log                # Uygulama loglari (git'e dahil degil)
└── README.md              # Bu dokuman
```

### Mimari

```
Istemci (curl / Python / Frontend)
    │
    ▼
┌─────────────────────────────────────┐
│  Flask REST API (app.py)            │
│  ├── Auth filtresi (before_request) │
│  ├── Istek dogrulama                │
│  ├── Mesgul kontrolu (busy lock)   │
│  └── Timeout koruması              │
└────────────┬────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│  Docling DocumentConverter          │
│  (PDF → Markdown/JSON/Doctags/Text) │
└─────────────────────────────────────┘
```

---

## Sorun Giderme

### Sunucu baslamiyor

- **Port mesgul:** `PDF_API_PORT` ile farkli bir port deneyin.
- **Docling kurulum hatasi:** `pip install docling==2.72.0` komutunu tekrar calistirin. Model indirmesi icin internet erisimi gereklidir.

### 401 Unauthorized hatasi

- API anahtarinizi kontrol edin: `cat .api_key`
- Header formatini dogrulayin: `X-API-Key: DEGER` (bosluk, tirnak olmadan)

### 403 Access denied hatasi

- Gonderdiginiz yol `ALLOWED_DIR` altinda mi? Sunucu baslarken konsola yazdirilan `Allowed directory` degerini kontrol edin.
- `PDF_ALLOWED_DIR` ortam degiskenini istediginiz dizine ayarlayin.

### 413 File too large hatasi

- Varsayilan limit 10 MB'tir. `PDF_MAX_SIZE_MB` ortam degiskeni ile artirabilirsiniz.

### 503 Busy hatasi

- Sunucu ayni anda yalnizca bir donusum isler. Onceki islemin bitmesini bekleyin ve tekrar deneyin.

### 504 Timeout hatasi

- Karmasik PDF dosyalari uzun surebilir. `PDF_CONVERSION_TIMEOUT` degerini artirabilirsiniz.
- Dosyanin bozuk olmadigini dogrulayin.

### Loglardan bilgi alma

```bash
# Son 50 log satiri
tail -50 app.log

# Sadece hatalari filtrele
grep ERROR app.log

# Auth hatalarini filtrele
grep "Auth failed" app.log
```
