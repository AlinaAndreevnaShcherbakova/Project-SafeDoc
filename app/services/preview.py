import asyncio
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote

from fastapi import HTTPException, status
from fastapi.responses import Response

CONVERTIBLE_EXTENSIONS = {
    ".doc",
    ".docx",
    ".odt",
    ".rtf",
    ".ppt",
    ".pptx",
    ".odp",
    ".xls",
    ".xlsx",
    ".ods",
}

SAFE_INLINE_MEDIA_TYPES_BY_EXTENSION = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".txt": "text/plain; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".ogv": "video/ogg",
    ".mov": "video/quicktime",
}


def build_inline_content_disposition(filename: str) -> str:
    fallback = filename.encode("ascii", "ignore").decode("ascii").strip() or "preview"
    encoded = quote(filename, safe="")
    return f"inline; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"


class PreviewService:
    #Предпросмотр пытается отдать браузеру безопасный формат без скачивания исходного файла.
    def _needs_pdf_conversion(self, filename: str) -> bool:
        ext = Path(filename or "").suffix.lower()
        return ext in CONVERTIBLE_EXTENSIONS

    def _safe_inline_media_type(self, filename: str) -> str | None:
        ext = Path(filename or "").suffix.lower()
        return SAFE_INLINE_MEDIA_TYPES_BY_EXTENSION.get(ext)

    def _convert_to_pdf_sync(self, data: bytes, filename: str) -> bytes | None:
        safe_name = Path(filename or "document").name
        suffix = Path(safe_name).suffix or ".bin"

        with tempfile.TemporaryDirectory(prefix="safedoc-preview-") as tmpdir:
            temp_dir = Path(tmpdir)
            source_path = temp_dir / f"source{suffix}"
            source_path.write_bytes(data)

            command = [
                "soffice",
                "--headless",
                "--nologo",
                "--nofirststartwizard",
                "--convert-to",
                "pdf",
                "--outdir",
                str(temp_dir),
                str(source_path),
            ]

            try:
                subprocess.run(
                    command,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=40,
                )
            except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                return None

            expected_pdf = temp_dir / f"source.pdf"
            if expected_pdf.exists():
                return expected_pdf.read_bytes()

            first_pdf = next(temp_dir.glob("*.pdf"), None)
            if first_pdf is None:
                return None
            return first_pdf.read_bytes()

    async def build_preview_payload(self, data: bytes, filename: str) -> tuple[bytes, str, str]:
        if self._needs_pdf_conversion(filename=filename):
            converted_pdf = await asyncio.to_thread(self._convert_to_pdf_sync, data, filename)
            if converted_pdf is not None:
                pdf_name = f"{Path(filename).stem or 'preview'}.pdf"
                return converted_pdf, "application/pdf", pdf_name
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Preview is not available for this file",
            )

        media_type = self._safe_inline_media_type(filename)
        if media_type is None:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Preview is not available for this file",
            )

        return data, media_type, filename

    async def build_preview_response(self, data: bytes, filename: str) -> Response:
        payload, media_type, output_filename = await self.build_preview_payload(data=data, filename=filename)

        return Response(
            content=payload,
            media_type=media_type,
            headers={
                "Content-Disposition": build_inline_content_disposition(output_filename),
                "Cache-Control": "no-store",
            },
        )


preview_service = PreviewService()

