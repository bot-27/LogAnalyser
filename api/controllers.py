"""
Controller layer — input validation for the API.

Routes call controllers; controllers call services.
Controllers never touch the database directly.
"""

import os
from dotenv import load_dotenv

from fastapi import UploadFile
from sqlalchemy.orm import Session

from api import services
from api.exceptions import ValidationError

load_dotenv()

ALLOWED_EXTENSIONS: set[str] = {".txt", ".log", ".csv"}
MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "100"))
MAX_FILE_SIZE_BYTES: int = MAX_FILE_SIZE_MB * 1024 * 1024


async def handle_upload(
    files: list[UploadFile],
    db: Session,
) -> dict:
    """
    Validate uploaded files, then delegate to the service layer.

    Validations performed:
      • At least one file must be provided.
      • Each file must have an allowed extension.
      • Each file must not exceed the size limit.

    Returns
    -------
    dict with ``session_id``.
    """
    if not files:
        raise ValidationError("No files provided")

    file_data: list[tuple[str, bytes]] = []

    for upload in files:
        filename = upload.filename or ""
        ext = os.path.splitext(filename)[1].lower()

        if ext not in ALLOWED_EXTENSIONS:
            raise ValidationError(
                f"Unsupported file type '{ext}'. "
                f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            )

        content = await upload.read()

        if len(content) > MAX_FILE_SIZE_BYTES:
            raise ValidationError(
                f"File '{filename}' is too large "
                f"({len(content) / 1024 / 1024:.1f} MB). "
                f"Maximum: {MAX_FILE_SIZE_MB} MB."
            )

        if not content.strip():
            raise ValidationError(f"File '{filename}' is empty")

        file_data.append((filename, content))

    session_id = services.create_analysis(file_data, db)
    return {"session_id": session_id}


def handle_get_status(session_id: str, db: Session) -> dict:
    """
    Validate the session_id and delegate to the service layer.
    """
    if not session_id or not session_id.strip():
        raise ValidationError("session_id is required")

    return services.get_session_status(session_id, db)
