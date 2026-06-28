"""Scaffold-graft: turn markush / open-valence OCSR output into specific structures, bypassing OCSR
of fused cores (the P1 wall). Two paths, both RDKit-arbitrated:

  cap_dummies  -- OpenChemIE coref SMILES frequently carry a '*' open-valence artifact while the
                  specific substituent is already drawn; capping '*'->H recovers the exact compound
                  (verified on the S0960894X09003679 SAR series: 8->acetamido, 4->nitrile, ...).
  graft        -- explicit markush enumeration: scaffold(*) + R(*) -> full molecule via molzip, for
                  when R is supplied separately (an R-group table column).

Every grafted/dummy-capped structure is flagged for review: the depiction->graph step is not certain
and '*' can also mean a genuinely external R. RDKit stays the validity arbiter.
"""
from __future__ import annotations
from typing import Optional, Tuple


def _rdkit():
    from rdkit import Chem
    from rdkit import RDLogger
    RDLogger.DisableLog("rdApp.*")
    return Chem


def cap_dummies(smiles: str) -> Tuple[Optional[str], int]:
    """Replace dummy atoms ('*') with H, sanitize, canonicalize. -> (smiles|None, n_dummies)."""
    Chem = _rdkit()
    m = Chem.MolFromSmiles(smiles) if smiles else None
    if m is None:
        return None, 0
    nd = sum(1 for a in m.GetAtoms() if a.GetAtomicNum() == 0)
    if nd == 0:
        return Chem.MolToSmiles(m), 0
    rw = Chem.RWMol(m)
    for a in rw.GetAtoms():
        if a.GetAtomicNum() == 0:
            a.SetAtomicNum(1)
            a.SetIsotope(0)
            a.SetAtomMapNum(0)
    try:
        m2 = rw.GetMol()
        Chem.SanitizeMol(m2)
        return Chem.MolToSmiles(Chem.RemoveHs(m2)), nd
    except Exception:
        return None, nd


def _tag_single_attachment(smiles, mapno=1):
    """Mol with exactly one dummy atom, tagged with map number `mapno`. Accepts '*' or [*:n]."""
    Chem = _rdkit()
    m = Chem.MolFromSmiles(smiles) if smiles else None
    if m is None:
        return None
    dummies = [a for a in m.GetAtoms() if a.GetAtomicNum() == 0]
    if len(dummies) != 1:
        return None
    dummies[0].SetAtomMapNum(mapno)
    return m


def graft(scaffold_smiles: str, r_smiles: str) -> Optional[str]:
    """Join scaffold + R, each carrying ONE attachment point ('*' or [*:1]), via RDKit molzip.
    -> canonical SMILES | None."""
    Chem = _rdkit()
    from rdkit.Chem import rdmolops
    s = _tag_single_attachment(scaffold_smiles, 1)
    r = _tag_single_attachment(r_smiles, 1)
    if s is None or r is None:
        return None
    try:
        zipped = rdmolops.molzip(Chem.CombineMols(s, r))
        Chem.SanitizeMol(zipped)
        return Chem.MolToSmiles(zipped)
    except Exception:
        return None


def resolve_coref(smiles: str) -> Tuple[Optional[str], str, str]:
    """Normalise an OpenChemIE coref SMILES to a specific structure.
    -> (smiles|None, status, note). status in {ok, review, failed}:
       ok     -- valid, no dummy atoms.
       review -- dummy-capped to a specific structure (verify the substituent).
       failed -- unparseable or unresolved markush."""
    Chem = _rdkit()
    if not smiles:
        return None, "failed", "empty"
    m = Chem.MolFromSmiles(smiles)
    if m is None:
        return None, "failed", "unparseable"
    nd = sum(1 for a in m.GetAtoms() if a.GetAtomicNum() == 0)
    if nd == 0:
        return Chem.MolToSmiles(m), "ok", ""
    capped, _ = cap_dummies(smiles)
    if capped:
        return capped, "review", "dummy-capped (%d): verify R" % nd
    return None, "failed", "unresolved markush (%d dummies)" % nd