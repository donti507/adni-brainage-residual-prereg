# decisions.md  (status: DRAFT, 13 Nov 2026)

## D-000 Data provenance (honest record)
- 11 tables downloaded from IDA Study Files, versions dated 12 Nov 2026
  (plasma table dated 6 Nov 2026 on the site). Files saved 13 Nov 2026, 01:50-01:58 local.
- Download PRECEDED this commit. No CSV has been opened or counted. [User attests: yes/no]
- Files: UCSFFSX7, UCBERKELEY_AMY_6MM, UCBERKELEY_TAU_6MM, UPENN_PLASMA_FUJIREBIO_QUANTERIX,
  UWNPSYCHSUM, ADSP_PHC_COGN, CDR, DXSUM, PTDEMOG, plus AMYQC and APOERES (not in proposal;
  added as QC check and optional covariate). Dictionary: DATADIC_12Nov2026.
- Chat B to rule whether download-before-commit is acceptable.

## D-001 Changes from my earlier draft to match the proposal
amyloid window 365 -> 180 days; Holm -> FDR; Centiloid x tau and FS_version moved out of the
primary residual model; comparators replaced by Ossenkoppele and Lyu measures; APOE4 dropped
from primary; Aim 2 labelled secondary; occupation conditional on being recorded.

## D-002 Fixes from Chat B's BLOCKED verdict
1. Pass rule changed to CI excludes null, powered at the smallest effect of interest.
2. Training-pool cross-fitting fallback removed. Shortfall = STOP.
3. Approvers: Biomni is not a code reviewer and its model family is unverified.
   X4 code check: NAMED BY USER (human or different-family model). X3/X6 signer: NAMED BY USER,
   preferably a supervisor, not the project owner alone.

## D-003 Open decisions (not resolved by me)
- Timeline: 16 weeks (proposal) vs 12 Dec draft. User decides.
- Cognition: UW only, PHC only, or UW primary + PHC sensitivity (my recommendation).
- APOE4 in or out.
- Centiloid cutoff 20 and training-pool rule: Red Team to check.
- Numeric tiers: pending Theorist; Theorist must redo power under FDR, not Holm.

## D-004 Assumptions the script cannot test (User records, dated)
A1 plasma advisory | A2 Centiloid both tracers | A3 occupation exists | A4 ADNI-Mem/EF coverage
A5 DXSUM coding consistent | A6 OASIS-3 applied | A7 OASIS-3 tau/plasma/FreeSurfer version
