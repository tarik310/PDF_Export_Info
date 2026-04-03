import os
from pathlib import Path


ALLOWED_DIR = Path(os.environ.get("PDF_ALLOWED_DIR", Path.cwd())).resolve()


print(f"Allowed directory: {ALLOWED_DIR}")