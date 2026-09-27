"""Reproduce Bell PDF mapping repairs using exact installed-font glyph outlines.

Run from the project root on Windows. Requires fontTools (in the pinned environment).
No PDF is modified. Only absent ToUnicode mappings with an unambiguous match are
recovered. The resulting manifest is portable; ingestion needs no installed fonts.
"""
import hashlib
import io
import json
from pathlib import Path
import re
from collections import defaultdict

import pymupdf
from fontTools.ttLib import TTFont


FONTS = {
    'Constantia': 'constan.ttf', 'Constantia-Italic': 'constani.ttf',
    'Constantia-Bold': 'constanb.ttf', 'Constantia-BoldItalic': 'constanz.ttf',
    'Calibri': 'calibri.ttf', 'Calibri-Bold': 'calibrib.ttf',
    'Calibri-BoldItalic': 'calibriz.ttf', 'ArialMT': 'arial.ttf',
    'TimesNewRomanPSMT': 'times.ttf',
}


def outline(font, glyph):
    coordinates, ends, flags = font['glyf'][glyph].getCoordinates(font['glyf'])
    return (font['head'].unitsPerEm, tuple(coordinates), tuple(ends), tuple(flags),
            font['hmtx'][glyph])


def reference_shapes(path):
    font = TTFont(path)
    labels = defaultdict(set)
    for code, glyph in font.getBestCmap().items():
        labels[glyph].add(code)
    # Propagate Unicode labels to stylistic alternates (e.g. lining digits).
    for _ in range(10):
        before = sum(map(len, labels.values()))
        if 'GSUB' in font:
            for lookup in font['GSUB'].table.LookupList.Lookup:
                for table in lookup.SubTable:
                    table = getattr(table, 'ExtSubTable', table)
                    for original, replacement in getattr(table, 'mapping', {}).items():
                        if isinstance(replacement, str):
                            labels[replacement].update(labels[original])
                    for original, alternatives in getattr(table, 'alternates', {}).items():
                        for replacement in alternatives:
                            labels[replacement].update(labels[original])
        if before == sum(map(len, labels.values())):
            break
    shapes = defaultdict(set)
    for glyph in font.getGlyphOrder():
        shapes[outline(font, glyph)].update(labels[glyph])
    return shapes


def main():
    references = {}
    documents = []
    for path in sorted(Path('data/corpus').glob('Bell 2022*.pdf')):
        repairs = []
        with pymupdf.open(path) as document:
            fonts = {font[0]: font for page in document for font in page.get_fonts()}
            for xref, font in fonts.items():
                family = font[3].split('+')[-1]
                if family not in FONTS:
                    continue
                kind, value = document.xref_get_key(xref, 'ToUnicode')
                if kind != 'xref':
                    continue
                target = int(value.split()[0])
                stream = document.xref_stream(target)
                # These source PDFs use only simple sequential bfrange sections.
                if b'beginbfchar' in stream or b'[' in stream:
                    raise ValueError('Unexpected CMap syntax; inspect before proceeding')
                mapped = set()
                for section in re.findall(rb'beginbfrange(.*?)endbfrange', stream, re.S):
                    for low, high, dest in re.findall(rb'<([0-9a-fA-F]+)>\s*<([0-9a-fA-F]+)>\s*<([0-9a-fA-F]+)>', section):
                        mapped.update(range(int(low, 16), int(high, 16) + 1))
                embedded = TTFont(io.BytesIO(document.extract_font(xref)[3]))
                if family not in references:
                    references[family] = reference_shapes(Path('C:/Windows/Fonts') / FONTS[family])
                additions = {}
                for table in embedded['cmap'].tables:
                    if table.platformID != 1 or table.platEncID != 0:
                        continue
                    for code, glyph in table.cmap.items():
                        if code in mapped:
                            continue
                        candidates = references[family].get(outline(embedded, glyph), set())
                        if len(candidates) != 1:
                            raise ValueError(f'Ambiguous or unmatched glyph: {path.name} {family} {code}: {candidates}')
                        additions[f'{code:02x}'] = chr(next(iter(candidates)))
                if additions:
                    repairs.append({'font': family, 'stream_xref': target,
                                    'stream_sha256': hashlib.sha256(stream).hexdigest(),
                                    'mappings': additions})
        documents.append({'filename': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                          'repairs': repairs})
    if len(documents) != 2:
        raise ValueError('Expected the two inspected Bell PDFs')
    output = Path('data/pdf_text_repairs/bell_2022.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({'method': 'exact glyph outlines and metrics, with Unicode/GSUB labels from installed Windows fonts',
                                  'documents': documents}, indent=2, ensure_ascii=True) + '\n', encoding='utf-8')
    print(f'Wrote {output}; {sum(len(r["mappings"]) for d in documents for r in d["repairs"])} verified mappings')


if __name__ == '__main__':
    main()
