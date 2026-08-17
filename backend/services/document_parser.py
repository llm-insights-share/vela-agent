import io
import re
from typing import Callable, Dict, List


def parse_pdf(file_bytes: bytes) -> str:
    from PyPDF2 import PdfReader
    reader = PdfReader(io.BytesIO(file_bytes))
    parts = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            parts.append(text.strip())
    return "\n\n".join(parts)


def parse_docx(file_bytes: bytes) -> str:
    from docx import Document
    doc = Document(io.BytesIO(file_bytes))
    parts = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def parse_txt(file_bytes: bytes) -> str:
    return file_bytes.decode("utf-8", errors="replace")


def parse_markdown(file_bytes: bytes) -> str:
    text = file_bytes.decode("utf-8", errors="replace")
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[*_~>|]", "", text)
    return text


def parse_xlsx(file_bytes: bytes) -> str:
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    parts = []
    for sheet in wb.worksheets:
        parts.append(f"[Sheet: {sheet.title}]")
        for row in sheet.iter_rows(values_only=True):
            cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
            if cells:
                parts.append("\t".join(cells))
    wb.close()
    return "\n".join(parts)


def parse_xls(file_bytes: bytes) -> str:
    import xlrd
    try:
        book = xlrd.open_workbook(file_contents=file_bytes)
        parts = []
        for sheet in book.sheets():
            parts.append(f"[Sheet: {sheet.name}]")
            for row_idx in range(sheet.nrows):
                cells = []
                for col_idx in range(sheet.ncols):
                    val = sheet.cell_value(row_idx, col_idx)
                    if val is None or val == "":
                        continue
                    text = str(val).strip()
                    if text:
                        cells.append(text)
                if cells:
                    parts.append("\t".join(cells))
        return "\n".join(parts)
    except Exception as e:
        raise ValueError(f"无法解析 .xls 文件: {e}") from e


def parse_image(file_bytes: bytes) -> str:
    return ""


PARSERS: Dict[str, Callable[[bytes], str]] = {
    ".pdf": parse_pdf,
    ".docx": parse_docx,
    ".doc": parse_docx,
    ".txt": parse_txt,
    ".md": parse_markdown,
    ".markdown": parse_markdown,
    ".xlsx": parse_xlsx,
    ".xls": parse_xls,
    ".png": parse_image,
    ".jpg": parse_image,
    ".jpeg": parse_image,
    ".webp": parse_image,
    ".gif": parse_image,
}

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

SUPPORTED_EXTENSIONS = sorted(PARSERS.keys())


def chunk_by_paragraph(text: str, target_size: int = 500, min_size: int = 100) -> List[str]:
    raw_paragraphs = re.split(r"\n\s*\n", text)
    paragraphs = [p.strip() for p in raw_paragraphs if p.strip()]
    if not paragraphs:
        return []

    chunks = []
    current = ""

    for para in paragraphs:
        if len(para) >= target_size:
            if current:
                chunks.append(current.strip())
                current = ""
            start = 0
            while start < len(para):
                end = start + target_size
                chunks.append(para[start:end].strip())
                start = end
        elif current and len(current) + len(para) + 2 > target_size:
            chunks.append(current.strip())
            current = para
        else:
            if current:
                current += "\n\n" + para
            else:
                current = para

    if current:
        chunks.append(current.strip())

    result = []
    for chunk in chunks:
        if len(chunk) >= min_size:
            result.append(chunk)

    return result


def parse_file(file_bytes: bytes, filename: str) -> tuple[str, bool]:
    """Parse file bytes. Returns (text, is_image)."""
    import os
    ext = os.path.splitext(filename)[1].lower()
    parser = PARSERS.get(ext)
    if parser is None:
        supported = ", ".join(SUPPORTED_EXTENSIONS)
        raise ValueError(f"不支持的文件格式 {ext or '(无扩展名)'}，支持: {supported}")

    is_image = ext in IMAGE_EXTS
    text = parser(file_bytes)
    if is_image:
        text = f"[图片] {filename}"
    elif not text or not text.strip():
        raise ValueError("文件内容为空或无法解析")
    return text, is_image
