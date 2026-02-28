from pathlib import Path

from docx import Document


def docx_to_md(source: Path, target: Path) -> None:
    doc = Document(str(source))
    lines = [para.text for para in doc.paragraphs]
    text = "\n".join(lines)
    target.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    base = Path(__file__).resolve().parent
    source = base / "系统提示词.docx"
    target = base / "系统提示词.md"
    docx_to_md(source, target)

