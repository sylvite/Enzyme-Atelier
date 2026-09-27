"""Hash-bound recovery of verified missing PDF character mappings, in memory."""
import hashlib
import json
from pathlib import Path
import re

MANIFEST = Path(__file__).resolve().parents[2] / 'data/pdf_text_repairs/bell_2022.json'


def repair_text_mappings(document, pdf, manifest_path=MANIFEST):
    """Restore missing ToUnicode entries without modifying the original PDF.

    A known filename with different bytes is rejected rather than silently using
    stale repairs. Renamed byte-identical documents are recognized by hash.
    """
    entries = json.loads(Path(manifest_path).read_text(encoding='utf-8'))['documents']
    digest = hashlib.sha256(Path(pdf).read_bytes()).hexdigest()
    matches = [entry for entry in entries if entry['sha256'] == digest]
    if not matches:
        if any(entry['filename'] == Path(pdf).name for entry in entries):
            raise ValueError(f'{Path(pdf).name}: PDF changed; verify its text before updating the repair manifest')
        return False
    entry, = matches
    updates = []
    for repair in entry['repairs']:
        stream = document.xref_stream(repair['stream_xref'])
        if hashlib.sha256(stream).hexdigest() != repair['stream_sha256']:
            raise ValueError('PDF text mapping does not match its verified repair')
        mappings = repair['mappings']
        if not mappings or len(mappings) > 100 or stream.count(b'endcmap') != 1:
            raise ValueError('Invalid PDF text repair')
        rows = []
        for code, character in mappings.items():
            if not re.fullmatch('[0-9a-f]{2}', code) or len(character) != 1:
                raise ValueError('Invalid character mapping')
            rows.append(f'<{code}> <{character.encode("utf-16-be").hex()}>')
        addition = f'{len(rows)} beginbfchar\n' + '\n'.join(rows) + '\nendbfchar\nendcmap'
        updates.append((repair['stream_xref'], stream.replace(b'endcmap', addition.encode('ascii'))))
    # Validate every source stream before making any in-memory update.
    for xref, stream in updates:
        document.update_stream(xref, stream)
    return bool(updates)
