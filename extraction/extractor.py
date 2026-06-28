"""Bulk extractor agent. Paper text -> list[ExtractedRecord]. SPEC.md section 4.

Default model: deepseek-v4-pro (OpenRouter, direct, cheap, 1M ctx). Provenance is grounded by us:
the model returns a verbatim `quote`; we recompute char offsets via str.find and DROP records whose
quote is not found (anti-hallucination). Structured output + pydantic validation via call_json
(RawExtraction schema); the quote-grounding stays our job. Domain-agnostic; optional preset focuses.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.llm_clients import call_json                           # noqa: E402
from extraction.schema import (                                 # noqa: E402
    ExtractedRecord, PaperRef, Span, EntityType, ValidationStatus, RawExtraction,
)
from config import BULK_MODEL                                   # noqa: E402

_VALUES = {e.value for e in EntityType}

SYSTEM = (
    "You extract STRUCTURED, VERIFIABLE records from scientific papers. "
    "Never invent. Every record must quote the exact source text."
)

SCHEMA_HINT = """Return ONLY a JSON object: {"records": [ ... ]}. Each element of records:
{
  "entity_type": one of [entity, relation, claim, method, measurement],
  "value": short human-readable label,
  "normalized": type-specific object:
     entity {name, type, identifiers:{scheme:value}, formats:{fmt:value}}
        type = domain kind (molecule, reaction, gene, protein, organism, disease, material, ...);
        identifiers use known schemes (smiles, inchikey, pubchem_cid, cas | pdb_id, uniprot, hgnc,
        ensembl, taxon, mesh, ...); formats hold raw structures/sequences (smiles, xyz, pdb, fasta).
     relation {subject, relation, object, role, direction:"+|-|0", context:{...}}
        role = role of `subject` when recognizable: reactant, product, reagent, catalyst, solvent,
        reaction_medium, ligand, target, analyte, inhibitor (else omit). For a reaction emit ONE
        relation per participant: subject=participant, object=product, role=its role.
     claim {statement, subject, predicate, object, polarity:"+|-|0", retracted:true|false}
     method {name, category, software, params:{...}}
     measurement {metric, analyte, conditions:{...}}   (put the number in top-level "quantity"+"unit")
        analyte = the entity (by name, matching an entity record) the value characterizes (the
        compound/material whose property|yield|rejection this is); conditions hold T, pH, solvent, etc.
  "quantity": number or null,
  "unit": string or null,
  "quote": VERBATIM substring of the input (<=240 chars) supporting this record,
  "confidence": 0..1
}
If nothing is extractable, return {"records": []}."""


def extract_records(text: str, paper: PaperRef, *, model: str = BULK_MODEL,
                    domain=None, max_tokens: int = 8000) -> list:
    """Extract records. `domain` = optional DomainPreset; its extract_hint focuses the model."""
    hint = SCHEMA_HINT
    if domain is not None and getattr(domain, "extract_hint", ""):
        hint = f"{SCHEMA_HINT}\n\nDOMAIN ({domain.name}) FOCUS: {domain.extract_hint}"
        kinds = ", ".join(getattr(domain, "entity_kinds", []) or [])
        if kinds:
            hint += f"\nExpected entity kinds: {kinds}."
    prompt = f"{hint}\n\n=== PAPER TEXT ===\n{text}"
    sr = call_json(model, prompt, RawExtraction, system_prompt=SYSTEM,
                   temperature=0.0, max_tokens=max_tokens)

    records = []
    for it in sr.parsed.records:
        et = it.entity_type
        quote = (it.quote or "").strip()
        if et not in _VALUES or not quote:
            continue
        pos = text.find(quote)
        if pos == -1:                       # ungrounded -> drop
            continue
        records.append(ExtractedRecord(
            paper=paper,
            entity_type=EntityType(et),
            value=str(it.value)[:300],
            normalized=it.normalized or {},
            quantity=it.quantity,
            unit=it.unit,
            span=Span(quote=quote, char_start=pos, char_end=pos + len(quote)),
            extractor=model,
            confidence=it.confidence or 0.5,
            validation=ValidationStatus.UNVERIFIED,
        ))
    return records


if __name__ == "__main__":
    sample = (
        "We optimized the geometry of caffeine (SMILES CN1C=NC2=C1C(=O)N(C(=O)N2C)C) "
        "at the B3LYP/6-31G(d) level using Gaussian 16. The computed HOMO-LUMO gap was 5.1 eV. "
        "Rapamycin extended median lifespan in C. elegans by 21% relative to control."
    )
    recs = extract_records(sample, PaperRef(paper_id="smoke-1", title="smoke test"), max_tokens=2000)
    for r in recs:
        q = r.span.quote[:40] if r.span else None
        print(f"{r.entity_type.value:11s} | {r.value[:30]:30s} | {r.normalized} | q={q!r}")
    print(f"\n{len(recs)} records via {recs[0].extractor if recs else BULK_MODEL}")
