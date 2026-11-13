# decisions.md  (status: DRAFT, 13 Nov 2026)

## D-000 Data provenance (honest record)
- 11 tables downloaded from IDA Study Files, versions dated 12 Nov 2026
  (plasma table dated 6 Nov 2026 on the site). Files saved 13 Nov 2026, 01:50-01:58 local.
- Download PRECEDED the first thresholds commit. Chat B to rule whether this is acceptable.
- Attestation: [FILL IN: "No CSV in data/raw has been opened, viewed or counted" OR describe what was opened]
- The data zips were uploaded to the coordinator chat (Claude). It listed file names and
  sizes only and read no rows. The dictionary and header rows only were shared with Codex.
- Files: UCSFFSX7, UCBERKELEY_AMY_6MM, UCBERKELEY_TAU_6MM, UPENN_PLASMA_FUJIREBIO_QUANTERIX,
  UWNPSYCHSUM, ADSP_PHC_COGN, CDR, DXSUM, PTDEMOG, plus AMYQC and APOERES (not in proposal;
  added as QC check and optional covariate). Dictionary: DATADIC_12Nov2026.

## D-001 Changes from the coordinator's earlier draft to match the proposal
amyloid window 365 -> 180 days; Holm -> FDR; Centiloid x tau and FS_version moved out of the
primary residual model; comparators replaced by Ossenkoppele and Lyu measures; APOE4 dropped
from primary; Aim 2 labelled secondary; occupation conditional on being recorded.

## D-002 Fixes from Chat B's BLOCKED verdict
1. Pass rule changed to CI excludes null, powered at the smallest effect of interest.
2. Training-pool cross-fitting fallback removed. Shortfall = STOP.
3. Approvers: Biomni is not a code reviewer and its model family is unverified.
   X4 code check: NAMED BY USER (human or different-family model). X3/X6 signer: NAMED BY USER,
   preferably a supervisor, not the project owner alone.

## D-003 Open decisions (not resolved)
- Timeline: 16 weeks (proposal) vs 12 Dec draft. User decides.
- Cognition: UW only, PHC only, or UW primary + PHC sensitivity (coordinator recommends the last).
- APOE4 in or out.
- Centiloid cutoff 20 and training-pool rule: Red Team to check.
- Numeric tiers: pending Theorist; Theorist must redo power under FDR, not Holm.
- OVERALLQC pass token: User picks from qc_values.py output, before any cohort count.
- A5 diagnosis coding: provisional until User reviews DIAGNOSIS counts per PHASE.
- Brain-age feature list: not specified (Theorist / Chat B).
- Column mappings for age, sex, education, APOE: needed before main analysis.
- Real X4a overlap check: must run on the actual training set in the build phase.

## D-004 Assumptions the script cannot test (User records, dated)
A1 plasma advisory | A2 Centiloid both tracers | A3 occupation exists | A4 ADNI-Mem/EF coverage
A5 DXSUM coding consistent | A6 OASIS-3 applied | A7 OASIS-3 tau/plasma/FreeSurfer version

## D-005 Clarifications to the Engineer (all fixed before any count; none are deviations)
- R1: time units (12 mo = 365 d, 60 mo = 1826 d); confirmation = next diagnosis visit only;
  nearest qualifying record selected; DRAFT results labelled; FS versions reported, not checked.
- R2: index = earliest tau scan meeting tau, MRI and amyloid requirements; cohort needs >=1
  outcome; follow-ups after outcome baseline up to index + 1826 d; conversion time origin =
  index; status field DRAFT/FINAL; git and timestamp checks in both modes.
- R3: Codex column mappings accepted; thickness = mean of both hemispheres, both required;
  PET qc_flag == 2; AMYQC SCANQLTY == 1; phase and FSVER from selected MRI row; row ID = CSV
  row position; DIAGNOSIS 1/2/3 = CN/MCI/Dementia, 10 = no diagnosis; PHC excluded from X1;
  sentinels -1/-2/-4/blank = missing; MRI and amyloid picked independently, then
  |MRI - amyloid| <= 180 d; occupation reported only.
- R4: duplicate (RID, VISCODE2, date) = one visit; a recorded value beats a missing one; a
  true conflict makes the visit ineligible, per outcome; a conflicting next visit leaves the
  event UNCONFIRMED_CONFLICT_NEXT_VISIT; a later conflicting group with any non-CN value
  excludes the RID from training; standing rule for new edge cases = exclude and report.
- R5: correction of a coordinator error in R3. AMYQC covers ADNI3/4 only (per file title), so
  "missing QC record = ineligible" would have dropped ADNI2 scans. Now: AMYQC applies only
  where a record exists; blank VISCODE2 kept as a key component; X4a labelled "by
  construction"; status FINAL refused while any PENDING_THEORIST value remains.

## D-006 Commit record
- f580e72  thresholds.yaml v0.2 created (GitHub web)
- 846d181  decisions.md rename; .gitignore added
- d804625  docs/headers.txt (header rows only)
- [FILL IN]  thresholds.yaml v0.3 (column mappings)
- 410fd29  thresholds.yaml v0.4; count_x1.py and qc_values.py (not run)
Verify with: git log --oneline
