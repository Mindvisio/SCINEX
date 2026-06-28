"""hw_chemdb — no-LLM chemical-data extraction from PDFs -> curated CSV.

Implements the curation pipeline from the lecture
'Анализ, очистка и стандартизация химических данных' with DETERMINISTIC tools only
(no LLM): PyMuPDF (PDF), regex + OPSIN (text), table parser, MolScribe + DECIMER
(figure->SMILES, RDKit-arbitrated), OPSIN (name->structure), RDKit (canonicalisation/validation),
PubChem PUG-REST (cross-identifier resolution), pint (unit standardisation), RapidFuzz (record
linkage). Output = code + chem_db.csv + processing report.
"""
__all__ = ["record", "pipeline"]