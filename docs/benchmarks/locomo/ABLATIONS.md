# LOCOMO Ablations

This file tracks the benchmark matrix we want to run.

## Minimum Ablation Set

1. `RawContext`
2. `RawRetrieval`
3. `ABCD-B`
4. `ABCD-BC`

## Questions To Answer

- Does dreaming outperform raw retrieval?
- Which categories improve the most?
- Does C-cluster retrieval help multi-hop enough to justify its cost?
- Where does dreamed retrieval lose detail versus raw chunks?
- How poor is adversarial abstention before tuning?
