"""
Episodic memory: remembers past runs
"""
import json
from pathlib import Path
from datetime import datetime

MEM_FILE = Path("data/episodic_memory.jsonl")

def log_run(query: str, best_seq: str, score: float):
    MEM_FILE.parent.mkdir(exist_ok=True)
    entry = {"ts": datetime.now().isoformat(), "query": query, "best_seq": best_seq[:50], "score": score}
    with open(MEM_FILE, "a") as f:
        f.write(json.dumps(entry)+"")

def load_history():
    if not MEM_FILE.exists():
        return []
    return [json.loads(l) for l in open(MEM_FILE)]