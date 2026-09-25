"""Durable JSON records, including a reader for the old concatenated format."""
import json
from pathlib import Path
from datetime import datetime, timezone

MEM_FILE = Path("data/episodic_memory.jsonl")


def append_record(path: Path, entry: dict):
    """Append one UTF-8 JSONL record; callers use a separate file per run."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, ensure_ascii=False, allow_nan=False)
    separator = ""
    if path.exists() and path.stat().st_size:
        with path.open("rb") as stream:
            stream.seek(-1, 2)
            if stream.read(1) != b"\n":
                separator = "\n"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(separator + line + "\n")
        stream.flush()


def log_run(query: str, best_seq: str, score: float | None, *, path=None,
            run_id=None, status=None):
    """Store the full sequence and nullable score in the selected run's memory."""
    append_record(Path(path) if path is not None else MEM_FILE, {
        "ts": datetime.now(timezone.utc).isoformat(), "run_id": run_id,
        "status": status, "query": query, "best_seq": best_seq, "score": score,
    })


def load_history(path=None):
    """Read JSONL and legacy adjacent JSON objects without altering the file.

    Malformed content raises an error instead of silently dropping evidence.
    """
    path = Path(path) if path is not None else MEM_FILE
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    decoder = json.JSONDecoder()
    entries = []
    position = 0
    while position < len(text):
        if text[position].isspace():
            position += 1
            continue
        entry, position = decoder.raw_decode(text, position)
        if not isinstance(entry, dict):
            raise ValueError("Memory records must be JSON objects")
        entries.append(entry)
    return entries
