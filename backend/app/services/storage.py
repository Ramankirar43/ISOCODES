import hashlib
import secrets
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from app.core.config import settings

ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
ALLOWED_CONTENT_TYPES = {"application/pdf", "image/jpeg", "image/png"}


def save_private_upload(upload: UploadFile) -> tuple[str, str, int]:
    extension = Path(upload.filename or "").suffix.lower()
    if extension not in ALLOWED_EXTENSIONS or upload.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Unsupported document type")
    root = Path(settings.local_storage_path).resolve()
    root.mkdir(parents=True, exist_ok=True)
    key = f"{secrets.token_urlsafe(24)}{extension}"
    destination = root / key
    digest = hashlib.sha256()
    size = 0
    with destination.open("wb") as target:
        while chunk := upload.file.read(1024 * 1024):
            size += len(chunk)
            if size > settings.max_upload_size_bytes:
                destination.unlink(missing_ok=True)
                raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File is too large")
            digest.update(chunk)
            target.write(chunk)
    return key, digest.hexdigest(), size
