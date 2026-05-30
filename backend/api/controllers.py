"""
Controller layer — input validation for the API.

Routes call controllers; controllers call services.
Controllers never touch the database directly.
"""

import os
from dotenv import load_dotenv

from fastapi import UploadFile, BackgroundTasks
from sqlalchemy.orm import Session

from backend.api import services
from backend.api.exceptions import ValidationError

load_dotenv()

ALLOWED_EXTENSIONS: set[str] = {".txt", ".log", ".csv"}
MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "100"))
MAX_FILE_SIZE_BYTES: int = MAX_FILE_SIZE_MB * 1024 * 1024


async def handle_upload(
    files: list[UploadFile],
    background_tasks: BackgroundTasks,
    db: Session,
) -> dict:
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

    session_id = services.create_analysis(file_data, background_tasks, db)
    return {"session_id": session_id}


def handle_get_status(session_id: str, db: Session) -> dict:
    if not session_id or not session_id.strip():
        raise ValidationError("session_id is required")

    return services.get_session_status(session_id, db)


def handle_cancel_session(session_id: str, db: Session) -> dict:
    if not session_id or not session_id.strip():
        raise ValidationError("session_id is required")

    return services.cancel_session(session_id, db)


async def handle_list_models() -> dict:
    return await services.list_models(MAX_FILE_SIZE_MB)


def handle_kg_data(service_name: str | None = None) -> dict:
    return services.get_kg_data(service_name)


async def handle_kg_insight(insight_text: str, related_entities: list[str], service_name: str | None = None) -> dict:
    if not insight_text:
        raise ValidationError("Insight text is required")
    return await services.add_kg_insight(insight_text, related_entities, service_name)


async def handle_kg_explain(model: str | None = None, service_name: str | None = None) -> dict:
    return await services.explain_kg(model, service_name)


async def handle_kg_restructure(instructions: str, model: str | None = None, service_name: str | None = None) -> dict:
    return await services.restructure_kg(instructions, model, service_name)


def handle_kg_summary(service_name: str | None = None) -> dict:
    return services.get_kg_summary(service_name)


def handle_kg_clear(service_name: str | None = None) -> dict:
    return services.clear_kg(service_name)
