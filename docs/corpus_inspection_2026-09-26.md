# Corpus inspection — 2026-09-26

> Follow-up: the Bell encoding problem described below has now been repaired
> for ingestion, with original PDFs preserved. See [the repair report](bell_text_repair.md).
> The exclusion advice and six-PDF count below describe the earlier inspection.

## Index update

The local `petase_papers` collection now contains **401 chunks from six PDFs**.
The five existing PDFs were refreshed with one-based PDF page metadata, and
`Son 2019 - Supporting Information.pdf` was added (26 chunks, 18 pages).
All 401 chunks have page metadata. Two real local embedding/retrieval queries
succeeded; a query mentioning S121E, D186H, and R280A retrieved Son's Figure S7
caption on PDF page 11 among its first three results.

The pre-update collection had 335 chunks without page metadata. A full local
backup was saved at `data/cache/chroma-before-corpus-update-20260926-194048`.
Ingestion used six selected PDFs copied to
`data/cache/verified-corpus-20260926-194048`; original documents were unchanged.
No OpenAI planner, paid API, or folding calls were made.

## Bell PDFs: retained but not indexed

- `Bell 2022 - Directed Evolution of an Efficient and Thermostable PET Depolymerase.pdf`
  is a 17-page accepted author manuscript with a Manchester repository cover.
- `Bell 2022 - Supplementary information.pdf` has 28 pages.

Both display legible numbers but have incomplete text mappings. PyMuPDF and
pypdf both extract corrupted numeric characters. For example, the manuscript's
abstract visually states `82.5` degrees C and `21` mutations, but the extracted
text gives `ML.N` and `LI`. Supplementary experimental quantities are affected
as well. This is a document text-layer issue, not missing text or a failed scan.

Neither Bell document was inserted into the index. Do not run unrestricted
ingestion over `data/corpus` until these documents are repaired or replaced:
the current ingestion command checks for nonempty text, not this form of
silent corruption. Repair needs verified font mapping or OCR and comparison
against rendered pages; global character replacement would corrupt valid text.
Original PDFs should be preserved.

## Son supplement: useful evidence, with figure limitations

Figure S7 (PDF page 11, printed S11) names the S121E/D186H/R280A variant and
compares its PET-film degradation with wild type. Its caption extracts correctly
and is retrievable. The chart's bars, quantitative labels, and condition labels
are embedded graphically and are absent from the extracted text on that page.
The text-only index must not be treated as having captured those measurements.
The rendered figure was inspected, but no inferred quantitative transcription
was inserted into the index. Some other pages contain tables and primer
sequences; retrieval alone does not validate their scientific interpretation.

## Son CIF files

All four contain crystallographic reflection data (`_refln`), with placeholder
entry identifier `xxxx`, and no `_atom_site` coordinate records:

| File | Reflection rows |
| --- | ---: |
| cs9b00568_si_002.cif | 47,081 |
| cs9b00568_si_003.cif | 20,593 |
| cs9b00568_si_004.cif | 25,534 |
| cs9b00568_si_005.cif | 20,562 |

They remain in `data/structures/son_2019` and are not RAG inputs. They are not
standalone atom-coordinate models for mutation visualization. Variant/PDB
assignments have not been verified; corresponding coordinate models can be
identified separately if structural comparisons become part of the workflow.

## Remaining work

1. Repair or replace the Bell PDFs' text layers, verify numeric extraction, and
   then ingest them with the same filenames and page provenance.
2. Add document-quality checks to ingestion so nonempty but corrupted text
   cannot silently become evidence.
3. Curate figure/table evidence separately where the PDF text layer omits data,
   preserving exact source and page references and distinguishing transcription
   from author-written text.

The papers, structures, and index remain local. This report records the inspection
and does not redistribute the source documents.
