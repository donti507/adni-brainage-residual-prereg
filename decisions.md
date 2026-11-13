# decisions.md  (status: DRAFT, 13 Nov 2026)

## D-000 Data provenance (honest record)
- 11 tables downloaded from IDA Study Files, versions dated 12 Nov 2026
  (plasma table dated 6 Nov 2026 on the site). Files saved 13 Nov 2026, 01:50-01:58 local
  (00:50-00:58 UTC).
- Download PRECEDED the first thresholds commit (f580e72, 01:09 UTC). Chat B to rule.
- Attestation: I attest that no CSV in data/raw has been opened, viewed, filtered or counted. MD Ali Ashraf Yad, 13 Nov 2026. MD Ali Ashraf Yad, 13 Nov 2026.
- The data zips were uploaded to the coordinator chat (Claude). It listed file names and
  sizes only and read no rows. The dictionary and header rows only were shared with Codex.
- Files: UCSFFSX7, UCBERKELEY_AMY_6MM, UCBERKELEY_TAU_6MM, UPENN_PLASMA_FUJIREBIO_QUANTERIX,
  UWNPSYCHSUM, ADSP_PHC_COGN, CDR, DXSUM, PTDEMOG, plus AMYQC and APOERES (not in proposal;
  added as QC check and optional covariate). Dictionary: DATADIC_12Nov2026.

## D-001 Changes from the coordinator's earlier draft to match the proposal
amyloid window 365 -> 180 days; Holm -> FDR; Centiloid x tau and FS_version moved out of the
primary residual model; comparators replaced by Ossenkoppele and Lyu measures; APOE4 dropped
from primary; Aim 2 labelled secondary; occupation conditional on being recorded.

## D-002 Fixes from Chat B's first BLOCKED verdict
1. Pass rule changed to CI excludes null, powered at the smallest effect of interest.
2. Training-pool cross-fitting fallback removed. Shortfall = STOP.
3. Approvers: Biomni is not a code reviewer and its model family is unverified.
   X4 code check: NAMED BY USER (human or different-family model). X3/X6 signer: NAMED BY USER,
   preferably a supervisor, not the project owner alone.

## D-003 Open decisions (not resolved)
- Timeline: 16 weeks (proposal) vs 12 Dec draft. User decides.
- Cognition: UW only, PHC only, or UW primary + PHC sensitivity (coordinator recommends the
  last; under it, ADNI-4 participants contribute only through CDR-SB).
- APOE4 in or out (coordinator recommends: out of primary, sensitivity only).
- Centiloid cutoff 20 and training-pool rule: Red Team to check.
- Numeric tiers: pending Theorist; Theorist must redo power under FDR, not Holm.
- OVERALLQC pass token: chosen from documentation (D-007), not from observed counts.
- A5 diagnosis coding: provisional until User reviews DIAGNOSIS counts per PHASE.
- Brain-age feature list: not specified (Theorist / Chat B).
- Column mappings for age, sex, education, APOE: needed before main analysis.
- Real X4a overlap check: must run on the actual training set in the build phase.
- All of the above that change n (cognition source, Centiloid cutoff, APOE4) must be fixed
  before count_x1.py runs.

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
- R6 (requested, pending): count_x1.py must refuse to run unless status is FINAL; DRAFT run
  mode removed (Chat B item 4).

## D-006 Commit record
72039dd  Initial commit (LICENSE)
f580e72  thresholds.yaml v0.2 created (GitHub web)
71611e3  decisions.md added (GitHub web)
846d181  .gitignore added
d804625  docs/headers.txt (header rows only)
489cb33  thresholds.yaml v0.3 (column mappings)
ad1f370  count_x1.py and qc_values.py (not run)
410fd29  thresholds.yaml v0.4 (round 5)
1841a64  decisions.md revised (GitHub web)
Disclosure: 489cb33, ad1f370 and 410fd29 were created in the Codex environment under the
User's git identity (+0000 timezone, double-space name). Contents were reviewed by the User
and the coordinator before use. The Engineer committing thresholds.yaml departs from the
"Engineer never edits thresholds" rule; Chat B to rule. From now on, only the User commits;
Codex outputs diffs only.

## D-007 QC pass codes (from documentation, recorded before qc_values.py runs)
- UCBERKELEY_AMY_6MM and UCBERKELEY_TAU_6MM qc_flag: 2 = Pass (DATADIC L72109, L72786)
- AMYQC SCANQLTY: 1 = Yes (DATADIC L7041, L7065)
- UCSFFSX7 OVERALLQC: token "Pass" (strict; "Partial" excluded). Source: ADNIMERGE2
  reference docs for UCSFFSX51 list OVERALLQC values Pass/Fail/Partial
  (atri-biostats.github.io/ADNIMERGE2/reference/UCSFFSX51_ADNI1_3T.html). The UCSFFSX7
  dictionary entry (DATADIC L77439) does not enumerate values, and the official UCSF
  FreeSurfer Methods PDF has not been checked. qc_values.py must confirm "Pass" exists in
  UCSFFSX7; if it does not, stop and revisit before any count.
## D-008 Deviations (for manuscript supplement)
   - Data downloaded before first thresholds commit. Accepted by Chat B, conditional on the
     true attestation (D-000) and disclosure in the manuscript.
   - Engineer committed thresholds.yaml (489cb33, 410fd29) under the User's git identity.
     Accepted by Chat B as a disclosed deviation.
   - Repeat after the rule was set: Codex committed and pushed Round 7 (1e8692b, e7115f0,
     thresholds v0.5) under the User's identity. Content reviewed by the coordinator.
     Chat B to rule.  
## D-009 Data-informed decisions after qc_values.py (13 Nov 2026)
- qc_values.py output seen. STOP rule in D-007 triggered: OVERALLQC blank in 11,137 rows,
  "Pass" in 674, plus an unplanned value "Hippocampus Only" (10 rows).
- Dictionary: UCSFFSX7 STATUS partial = no QC, not final; Complete = QC'd and finalized.
- MRI QC rule chosen: A. Accept OVERALLQC "Pass" OR blank with STATUS partial (not yet
  QC'd). Exclude Fail, Partial, "Hippocampus Only". DATA-INFORMED (counts seen).
  Strict Pass-only kept as a sensitivity analysis. Limitation for the manuscript: most
## D-010 Pre-count decisions (13 Nov 2026, before count_x1.py)
- Cognition: UW primary, PHC sensitivity; ADNI-4 contributes via CDR-SB only.
- Centiloid cutoff: < 20 primary (Red Team to check).
- APOE4: out of primary model; sensitivity only.
- Partial OVERALLQC rows: excluded; regional QC not used (brain age uses whole-brain features).
- Unreviewed MRIs: exclude if hippocampal volume/ICV or mean temporal thickness
  > 5 MAD from the all-MRI median; counts reported; sensitivity without the rule.
- Dictionary sources: STATUS L77437; pT217_F -4 L78290; qc_flag -1/-2 L72109, L72786.  
  segmentations are unreviewed.
- Sentinel bug fixed: -1/-2/-4 were wrongly treated as missing in continuous measures
  (Centiloid, tau SUVR, ADNI-Mem/EF, CDR-SB, FreeSurfer). Only pT217_F -4 is a missing code.
- PET qc_flag -1 (not assessed) and -2 (cannot be processed) are real codes; both fail.
- Occupation (PTWORK) blank in 4,888 rows: A3 fails; education is the only reserve proxy.
- APOE joined by RID only (VISCODE/date blank in 2,057 APOERES rows).
