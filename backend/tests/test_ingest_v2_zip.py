import io
import zipfile

from backend.routers.ingest_v2 import _extract_processed_zip_payload, _replace_image_references


def _build_zip(file_map: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, data in file_map.items():
            archive.writestr(path, data)
    return buffer.getvalue()


def test_extract_processed_zip_prefers_full_text_and_collects_images():
    zip_bytes = _build_zip(
        {
            "processed/notes.md": b"# Fallback markdown",
            "processed/full_text.md": b"# Preferred markdown\n\n![fig](images/a.png)",
            "processed/images/a.png": b"\x89PNG\r\n\x1a\n",
        }
    )

    content, images, markdown_entry = _extract_processed_zip_payload(zip_bytes)

    assert markdown_entry.endswith("full_text.md")
    assert "Preferred markdown" in content
    assert len(images) == 1
    assert images[0]["basename"] == "a.png"
    assert "images/a.png" in images[0]["references"]


def test_replace_image_references_updates_markdown_paths():
    content = "![fig](images/a.png)\n<img src=\"a.png\" />"
    replaced = _replace_image_references(
        content,
        ["images/a.png", "a.png"],
        "https://cdn.example.com/a.png",
    )
    assert "https://cdn.example.com/a.png" in replaced
    assert "images/a.png" not in replaced

