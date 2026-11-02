"""
domains/geetabitan/ingestion/nazrul_docx_to_raw.py

Converts the BanglaMusicStylo / IEEE DataPort (DOI 10.21227/qsbr-kw16)
"Kazi Nazrul Islam" lyricist folder of .docx files into the flat
domains/geetabitan/data/nazrul_songs_raw.json that nazrul_lyrics_loader.py
expects.

Verified against the actual downloaded dataset:
  - 620 files, each named "song<N>_<title>.docx" (N = 1..620, no gaps/dupes).
  - Inside each .docx, every lyric line is its own paragraph, with an empty
    paragraph marking a stanza break (confirmed by direct inspection — this
    is a real structural signal from python-docx, not guesswork).
  - The filename's title is the dataset's own (sometimes shortened) title;
    it can differ from the literal first lyric line, exactly like the
    existing Rabindra Sangeet schema's separate title/first_line fields.

category/raag/taal are not present in this dataset at all (lyrics-only) —
left "" here. Backfill by hand in the output JSON from the Nazrul
Institute's published catalog only where you can actually confirm them;
leave "" rather than guessing.

Usage:
    PYTHONPATH=$(pwd) python -m domains.geetabitan.ingestion.nazrul_docx_to_raw \\
        --source-dir "/path/to/BanglaMusicStylo Dataset/Data/Kazi Nazrul Islam"

Writes domains/geetabitan/data/nazrul_songs_raw.json (overwrites each run).
"""

import argparse
import json
import re
from pathlib import Path

from docx import Document

OUT_PATH = Path(__file__).parent.parent / "data" / "nazrul_songs_raw.json"

FILENAME_RE = re.compile(r"^song(\d+)_(.+)\.docx$", re.IGNORECASE)


def _title_from_filename(path: Path) -> tuple[str, str]:
    """Returns (song_number_as_str, title). Falls back to the bare
    filename stem as title if it doesn't match the dataset's own
    'song<N>_<title>.docx' naming convention."""
    m = FILENAME_RE.match(path.name)
    if m:
        return m.group(1), m.group(2).strip()
    return "", path.stem.strip()


def _stanzas_from_docx(path: Path) -> list[str]:
    """Group paragraphs into stanzas, splitting on blank paragraphs —
    this docx format uses a real empty paragraph as the stanza separator,
    not just visual spacing."""
    doc = Document(str(path))
    stanzas: list[str] = []
    current: list[str] = []
    for p in doc.paragraphs:
        text = p.text.strip()
        if text:
            current.append(text)
        elif current:
            stanzas.append("\n".join(current))
            current = []
    if current:
        stanzas.append("\n".join(current))
    return stanzas


def convert(source_dir: Path) -> list[dict]:
    songs: list[dict] = []
    skipped: list[str] = []

    docx_files = sorted(source_dir.glob("*.docx"))
    if not docx_files:
        raise FileNotFoundError(f"No .docx files found directly under {source_dir}")

    for path in docx_files:
        try:
            stanzas = _stanzas_from_docx(path)
        except Exception as exc:
            skipped.append(f"{path.name} (unreadable: {exc})")
            continue

        if not stanzas:
            skipped.append(f"{path.name} (empty)")
            continue

        song_num, title = _title_from_filename(path)
        first_line = stanzas[0].split("\n")[0]
        lyrics_full = "\n\n".join(stanzas)

        songs.append({
            "id":          f"nazrul_song{song_num}" if song_num else path.stem,
            "title":       title,
            "first_line":  first_line,
            "stanzas":     stanzas,
            "lyrics_full": lyrics_full,
            "excerpt":     lyrics_full[:400],
            "category":    "",
            "raag":        "",
            "taal":        "",
            "source_note": f"BanglaMusicStylo / IEEE DataPort qsbr-kw16 — Data/Kazi Nazrul Islam/{path.name}",
        })

    OUT_PATH.write_text(json.dumps(songs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Converted {len(songs)} .docx files -> {OUT_PATH}")
    if skipped:
        print(f"Skipped {len(skipped)} files:")
        for s in skipped:
            print(f"  - {s}")
    return songs


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-dir", required=True, type=Path,
                         help='Path to the "Kazi Nazrul Islam" folder inside the downloaded dataset')
    args = parser.parse_args()
    convert(args.source_dir.expanduser().resolve())
