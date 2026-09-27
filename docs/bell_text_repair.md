# Bell 2022 PDF text extraction repair

## What was repaired

The two local Bell PDFs displayed correctly but omitted 52 character mappings
from embedded fonts' ToUnicode streams. Extractors substituted raw character
codes for digits: for example, the manuscript abstract yielded `ML.N` instead
of `82.5`. This also affected numerical conditions and residue numbers in the
supplement.

The missing mappings were recovered by matching exact embedded glyph outlines,
contour flags, font units, and horizontal metrics against installed Windows
fonts. Unicode cmap labels and single-glyph GSUB stylistic substitutions identify
the matched characters, including lining digits. Ambiguous or unmatched glyphs
cause the builder to fail; no global text substitution or language-model guess
is used. Only missing mappings are added.

`data/pdf_text_repairs/bell_2022.json` stores the verified mappings, the original
PDF SHA-256 hashes, and hashes of the affected mapping streams. It contains no
embedded font files or article text. `src/memory/pdf_text.py` applies it in memory
before ingestion extracts pages. The PDFs on disk are never overwritten.

## Normal use

The local index was refreshed successfully after repair: **508 chunks from eight
PDFs**, including 50 manuscript chunks and 57 supplement chunks marked as
repaired. Two local retrieval queries returned Bell evidence with page citations.
The previous index was backed up at
`data/cache/chroma-before-bell-repair-20260926-194938`. No paid API or folding
calls were made. Source PDFs, CIF files, and the retrieval index remain local;
the repository contains the repair implementation, manifest, tests, and reports.

Run the ordinary ingestion command from the project root:

```powershell
.\venv\Scripts\python.exe -m src.memory.semantic_store --corpus-dir data/corpus --db-path data/chroma
```

The manifest is portable: ingestion does not require Windows fonts or fontTools.
Unrelated PDFs follow ordinary extraction. Renamed copies with identical bytes
are recognized. A known filename with different bytes fails explicitly and needs
inspection before its manifest is updated. The runtime also checks each original
mapping stream before applying changes.

Chunk metadata retains original filename and one-based PDF page and adds
`text_mapping_repaired`. The manifest is the authoritative record of which
source bytes received repairs. This is a targeted fix for these documents, not
a general detector of corrupt extraction in arbitrary PDFs.

## Verification

- Both original file hashes remained unchanged.
- All 45 pages rendered pixel-identically before and after the in-memory repair
  at the verification resolution (17 manuscript pages, 28 supplement pages).
- No unmapped replacement characters remained with CID fallback disabled across
  those 45 pages.
- The abstract's `13,000`, `21`, `82.5`, and `60-70` values matched the rendered
  manuscript page 2.
- Supplement page 2 correctly extracted `0.25`, `300 micron`, `29.8%`, `39.9%`,
  and `100 mM`; mutation labels on page 6 included `S61V`, `K95N`, `Q182M`,
  `N241C`, and `K252M`, matching the inspected table.
- **186 offline tests passed**, including repair application, source-file
  preservation, stale PDF/stream rejection, renamed files, unrelated PDFs, and
  ingestion of repaired text with provenance.

Visual identity and recovered character mapping do not guarantee perfect table
reading order or extraction of text drawn inside images. Figures and complex
tables still require source-page review for scientific interpretation. Original
PDFs opened or extracted in other applications still have their original text
mapping issue; this repair is applied by Enzyme Atelier during ingestion.

## Reproducing the manifest

For maintenance on this Windows machine, the pinned environment includes
fontTools via matplotlib. The builder additionally needs the matching installed
Windows fonts; it fails if they are absent or their outlines differ:

```powershell
.\venv\Scripts\python.exe tools/build_bell_text_repairs.py
```

The generator does not modify PDFs. Review regenerated mappings and rerun source
and rendering checks before ingesting changed documents. The known source hashes
are recorded in the manifest.
