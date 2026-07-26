from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / ".github/finalize_a10_projection.py"
text = path.read_text(encoding="utf-8")
start = text.index("# Add list projection to the commitment repository.\n")
end = text.index("# Administrative mutations reject both governed task kinds.\n", start)
text = (
    text[:start]
    + "# Commitment repository already owns the canonical list_current projection.\n"
    + text[end:]
)
path.write_text(text, encoding="utf-8")
Path(__file__).unlink()
