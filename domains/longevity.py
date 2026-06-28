"""Longevity / aging domain preset (stub): interventions, organisms, genes, biomarkers, claims."""
from __future__ import annotations

from extraction.schema import EntityType
from domains.base import DomainPreset, register

# TODO tools: ClinicalTrials.gov linkage; gene/protein normalization (UniProt/HGNC);
#   retraction/contradiction signal (e.g. a retracted rapamycin lifespan study).
LONGEVITY = register(DomainPreset(
    name="longevity",
    description="Aging biology: interventions, hallmarks, model organisms, biomarkers, trials.",
    focus_types=[EntityType.RELATION, EntityType.CLAIM, EntityType.ENTITY, EntityType.MEASUREMENT],
    entity_kinds=["intervention", "organism", "gene", "protein", "biomarker", "disease", "hallmark"],
    id_schemes=["taxon", "uniprot", "hgnc", "ensembl", "ncbi_gene", "refseq", "mesh",
                "chembl", "drugbank", "go", "kegg"],
    extract_hint=("Intervention->outcome as relation (context: model_organism e.g. mouse/C. elegans, "
                  "dose) with effect direction; biomarkers + hallmarks as entities; claims with "
                  "polarity for contradiction detection."),
    validators={},
))
