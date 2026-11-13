"""X1 feasibility counts only; no models, participant rows, or result interpretation.

Rules: thresholds v0.5 and the User's rounds 1-7, including the subsequent
provisional pooled DIAGNOSIS mapping and duplicate-visit resolution. Importing
qc_values is for shared input utilities only; its main function is not called.
"""

import sys

# Prevent importing our helper from creating an untracked __pycache__ before
# the required clean-working-tree check.
sys.dont_write_bytecode = True

import hashlib
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from qc_values import (
    ROOT, FILES, InputError, column_specs, load_config, missing, number,
    quoted, read_table, token,
)


OUTCOMES = {"ADNI_MEM": "ADNI_MEM", "ADNI_EF": "ADNI_EF", "CDR_SB": "CDRSB"}
# Explicitly authorized by the User; A5 remains provisional pending review.
DX_CODES = {"1": "CN", "2": "MCI", "3": "Dementia"}


def usable_key(key, columns):
    """Blank VISCODE2 is a literal key component, not an excluded visit."""
    return all(not missing(value) or (column == "VISCODE2" and not value.strip())
               for column, value in zip(columns, key))


def has_pending_theorist(value):
    if isinstance(value, dict):
        return any(has_pending_theorist(item) for item in value.values())
    if isinstance(value, list):
        return any(has_pending_theorist(item) for item in value)
    return value == "PENDING_THEORIST"


def git(*args):
    result = subprocess.run(
        ["git", "-C", str(ROOT), *args], capture_output=True, text=True,
    )
    if result.returncode:
        raise InputError("Git precondition failed: git " + " ".join(args))
    return result.stdout.strip()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rid_hash(rids):
    # Unique RID strings, lexicographic sort, UTF-8, one trailing LF per RID.
    payload = "".join(rid + "\n" for rid in sorted(set(rids)))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def preflight(now):
    for filename in ("thresholds.yaml", "decisions.md", "count_x1.py", "qc_values.py"):
        git("ls-files", "--error-unmatch", "--", filename)
    git("diff", "--quiet", "--", "thresholds.yaml")
    git("diff", "--cached", "--quiet", "--", "thresholds.yaml")
    if git("status", "--porcelain=v1", "--untracked-files=all"):
        raise InputError("Working tree must be clean, including staged and untracked files")
    stamp = git("log", "-1", "--format=%ct", "--", "thresholds.yaml")
    if not stamp:
        raise InputError("thresholds.yaml has no committed history")
    committed = datetime.fromtimestamp(int(stamp), timezone.utc)
    if committed >= now:
        raise InputError("thresholds.yaml last commit timestamp must be earlier than run time: "
                         f"commit_UTC={committed.isoformat()}; run_UTC={now.isoformat()}")
    return git("rev-parse", "HEAD"), committed


def parsed_date(value, table, column):
    if missing(value):
        return None
    try:
        text = value.strip()
        result = date.fromisoformat(text)
        if result.isoformat() != text:
            raise ValueError
        return result
    except ValueError as exc:
        raise InputError(f"{table}.{column}: non-missing date must be YYYY-MM-DD") from exc


@dataclass
class Item:
    row: object
    rid: str
    day: date
    value: object = None


@dataclass
class Index:
    day: date
    tau: Item
    mri: Item
    amyloid: Item


class Engine:
    def __init__(self, config, tables):
        self.c = config
        self.tables = tables
        self.diagnostics = Counter()
        self.tie_queries = defaultdict(dict)
        self.duplicate_conflicts = defaultdict(set)
        self.duplicate_completeness = defaultdict(set)
        self.duplicate_keys = {}
        self.groups = {}
        self.visit_cache = {}
        self.item_cache = {}
        self.edges = Counter()
        for name, table in tables.items():
            for issue, count in (table.issues or {}).items():
                self.edges[(name + "." + issue, "exclude affected raw record", "records")] += count
            if table.problem:
                self.edges[(name + ".unavailable_table", "dependent counts NOT EVALUATED", "tables")] += 1
            else:
                absent = column_specs(config)[name] - table.columns
                if absent:
                    self.edges[(name + ".missing_mapped_columns", "dependent counts NOT EVALUATED", "columns")] += len(absent)

    def edge(self, case, rule, unit, count=1):
        self.edges[(case, rule, unit)] += count

    def day(self, value, name, column, unit="records"):
        try:
            return parsed_date(value, name, column)
        except InputError:
            self.edge(f"{name}.{column}.invalid_date", "exclude affected record or visit", unit)
            return None

    def numeric(self, value, name, column):
        try:
            return number(value, name, column)
        except InputError:
            self.edge(f"{name}.{column}.invalid_numeric", "exclude affected record for this measurement", "records")
            return None

    def ids(self, name):
        ids = self.c["identifiers"]
        return [ids[kind][name] for kind in ("participant", "visit", "date")]

    def need(self, name, fields):
        reason = self.tables[name].require(fields)
        return f"{name}: {reason}" if reason else ""

    def add_keys(self, name):
        if name in self.groups:
            return self.groups[name]
        columns = self.ids(name)
        if self.need(name, columns):
            return None
        groups = defaultdict(list)
        for row in self.tables[name].rows:
            key = tuple(row.values[col].strip() for col in columns)
            groups[key].append(row)
        self.groups[name] = groups
        self.duplicate_keys[name] = {key for key, rows in groups.items() if len(rows) > 1}
        return groups

    def items(self, name):
        if name in self.item_cache:
            return self.item_cache[name]
        rid_col, _, day_col = self.ids(name)
        result = []
        for row in self.tables[name].rows:
            rid = row.values[rid_col].strip()
            day = self.day(row.values[day_col], name, day_col)
            invalid = False
            if missing(rid):
                self.diagnostics[f"{name}.missing_RID_rows"] += 1
                self.edge(f"{name}.missing_RID", "exclude affected record", "records")
                invalid = True
            if day is None:
                suffix = "missing_date_rows" if missing(row.values[day_col]) else "invalid_date_rows"
                self.diagnostics[f"{name}.{suffix}"] += 1
                if missing(row.values[day_col]):
                    self.edge(f"{name}.missing_date", "exclude affected record", "records")
                invalid = True
            if invalid:
                self.diagnostics[f"{name}.ineligible_missing_RID_or_date_rows"] += 1
            if not invalid:
                result.append(Item(row, rid, day))
        self.item_cache[name] = result
        return result

    @staticmethod
    def by_rid(items):
        result = defaultdict(list)
        for item in items:
            result[item.rid].append(item)
        for rows in result.values():
            rows.sort(key=lambda item: (item.day, item.row.position))
        return result

    def nearest(self, items, rid, anchor, window, stage):
        candidates = [item for item in items.get(rid, [])
                      if abs((item.day - anchor).days) <= window]
        if not candidates:
            return None
        distance = min(abs((item.day - anchor).days) for item in candidates)
        tied = [item for item in candidates if abs((item.day - anchor).days) == distance]
        if len(tied) > 1:
            # Count each distinct stage/RID/anchor selection query once, even
            # when multiple tau records reuse the same matching query.
            self.tie_queries[stage][(rid, anchor)] = len(tied)
        # All candidates have complete required fields before selection.
        return min(tied, key=lambda item: (item.day, item.row.position))

    def visits(self, name, column, diagnosis=False):
        cache_key = (name, column, diagnosis)
        if cache_key in self.visit_cache:
            return self.visit_cache[cache_key]
        groups = self.add_keys(name)
        result = []
        conflicts = set()
        completeness = set()
        collapsed = 0
        for key, rows in groups.items():
            if not usable_key(key, self.ids(name)):
                self.diagnostics[f"{name}.{column}.missing_visit_key_rows"] += len(rows)
                self.edge(f"{name}.{column}.missing_visit_key", "exclude affected visit", "visit_keys")
                continue
            day = self.day(key[2], name, self.ids(name)[2], "visit_keys")
            if day is None:
                continue
            valid = []
            for row in rows:
                raw = row.values[column]
                if diagnosis and not missing(raw) and token(raw) not in {*DX_CODES, "10"}:
                    self.edge(f"{name}.unmapped_DIAGNOSIS", "exclude affected record", "records")
                    continue
                if not diagnosis and not missing(raw) and self.numeric(raw, name, column) is None:
                    continue
                valid.append(row)
            rows = valid
            if not rows:
                continue
            # Only the column-specific missing values share a missing category.
            def category(row):
                raw = row.values[column]
                if missing(raw):
                    return None
                return DX_CODES.get(token(raw)) if diagnosis else token(raw)
            values = {category(row) for row in rows}
            if len(rows) > 1 and len(values - {None}) > 1:
                conflicts.add(key)
                self.duplicate_conflicts[name].add(key)
                self.edge(f"{name}.{column}.true_conflict", "exclude affected visit for this outcome; retain diagnosis conflict marker", "visit_keys")
                continue
            if len(rows) > 1 and None in values and len(values) > 1:
                completeness.add(key)
                self.duplicate_completeness[name].add(key)
            if len(rows) > 1:
                collapsed += 1
            required = self.ids(name) + [column]
            row = min(rows, key=lambda r: (
                -int(category(r) is not None),
                -sum(not missing(r.values[col]) for col in required), r.position,
            ))
            if diagnosis:
                value = DX_CODES.get(token(row.values[column]))
            else:
                value = number(row.values[column], name, column)
            if value is not None:
                result.append(Item(row, key[0], day, value))
        self.diagnostics[f"{name}.{column}.duplicate_keys_collapsed"] = collapsed
        self.diagnostics[f"{name}.{column}.duplicate_keys_conflicting"] = len(conflicts)
        self.diagnostics[f"{name}.{column}.duplicate_keys_collapsed_by_completeness"] = len(completeness)
        result = self.by_rid(result)
        self.visit_cache[cache_key] = result
        return result

    def modalities(self, strict_pass_only=False):
        c = self.c
        mn, an, tn = (c[key]["source"] for key in ("mri", "amyloid", "tau"))
        mq = c["mri"]["qc_flag"]
        aq = c["amyloid"]["columns"]["amyqc"]
        qn = aq["source"]
        mcols = []
        for field in c["mri"]["required_fields"]:
            mapped = c["mri"]["columns"][field]
            mcols.extend([mapped] if isinstance(mapped, str) else [mapped["left"], mapped["right"]])
        checks = (
            (mn, self.ids(mn) + mcols + [mq["column"]] +
             ([] if strict_pass_only else [mq["accept_blank_when"]["column"]])),
            (an, self.ids(an) + [c["amyloid"]["columns"]["centiloid_global"],
                                c["amyloid"]["columns"]["qc"]["column"]] + aq["join_keys"]),
            (tn, self.ids(tn) + [c["tau"]["columns"]["meta_temporal_suvr"],
                                c["tau"]["columns"]["qc"]["column"]]),
            (qn, aq["join_keys"] + [aq["column"]]),
        )
        problems = [self.need(name, fields) for name, fields in checks]
        if any(problems):
            return None, "; ".join(p for p in problems if p)
        mri = []
        for item in self.items(mn):
            values = [self.numeric(item.row.values[col], mn, col) for col in mcols]
            overall = item.row.values[mq["column"]]
            strict_pass = overall == mq["pass_token"]
            allowed_pending = (not strict_pass_only and missing(overall) and
                               item.row.values[mq["accept_blank_when"]["column"]] ==
                               mq["accept_blank_when"]["equals"])
            passed = strict_pass or allowed_pending
            if not passed:
                self.diagnostics["MRI.rejected_QC_rows"] += 1
            if any(missing(item.row.values[col]) for col in mcols):
                self.diagnostics["MRI.rejected_missing_required_measurement_rows"] += 1
            if any(value is None and not missing(item.row.values[col]) for col, value in zip(mcols, values)):
                self.diagnostics["MRI.rejected_invalid_numeric_rows"] += 1
            if passed and all(value is not None for value in values):
                measurements = {}
                by_column = dict(zip(mcols, values))
                for field in c["mri"]["required_fields"]:
                    mapped = c["mri"]["columns"][field]
                    measurements[field] = (by_column[mapped] if isinstance(mapped, str) else
                                           (by_column[mapped["left"]] + by_column[mapped["right"]]) / 2)
                item.value = measurements
                mri.append(item)
        qc_groups = defaultdict(list)
        for row in self.tables[qn].rows:
            key = tuple(row.values[col].strip() for col in aq["join_keys"])
            if usable_key(key, aq["join_keys"]):
                qc_groups[key].append(row)
        amyloid = []
        for row in self.tables[an].rows:
            key = tuple(row.values[col].strip() for col in aq["join_keys"])
            if not usable_key(key, aq["join_keys"]):
                self.diagnostics["AMYQC.amyloid_scans_invalid_join_key"] += 1
                self.edge("amyloid.invalid_AMYQC_join_key", "exclude affected scan", "scans")
                continue
            matches = qc_groups.get(key, [])
            # Five mutually exclusive scan categories: conflicting multiple
            # records are counted separately from nonconflicting duplicates.
            if not matches:
                self.diagnostics["AMYQC.amyloid_scans_missing_QC_record"] += 1
            elif len(matches) == 1:
                passed = token(matches[0].values[aq["column"]]) == token(str(aq["pass_value"]))
                label = "one_pass" if passed else "one_fail"
                self.diagnostics["AMYQC.amyloid_scans_" + label] += 1
            else:
                if len({token(r.values[aq["column"]]) for r in matches}) > 1:
                    self.diagnostics["AMYQC.amyloid_scans_conflicting_QC_records"] += 1
                else:
                    self.diagnostics["AMYQC.amyloid_scans_duplicate_QC_records"] += 1
        for item in self.items(an):
            row = item.row
            key = tuple(row.values[col].strip() for col in aq["join_keys"])
            key_valid = usable_key(key, aq["join_keys"])
            matches = qc_groups.get(key, []) if key_valid else []
            qc = c["amyloid"]["columns"]["qc"]
            own_pass = token(row.values[qc["column"]]) == token(str(qc["pass_value"]))
            extra_pass = key_valid and (
                (not matches and aq["missing_record"] == "not_required") or
                (len(matches) == 1 and
                 token(matches[0].values[aq["column"]]) == token(str(aq["pass_value"])))
            )
            value = self.numeric(row.values[c["amyloid"]["columns"]["centiloid_global"]],
                                 an, c["amyloid"]["columns"]["centiloid_global"])
            if not own_pass:
                self.diagnostics["amyloid.rejected_own_QC_rows"] += 1
            if not extra_pass:
                self.diagnostics["amyloid.rejected_AMYQC_rows"] += 1
            if value is None:
                label = ("missing_Centiloid_rows" if missing(row.values[c["amyloid"]["columns"]["centiloid_global"]])
                         else "invalid_Centiloid_rows")
                self.diagnostics["amyloid.rejected_" + label] += 1
            if own_pass and extra_pass and value is not None:
                amyloid.append(Item(row, item.rid, item.day, value))
        return (self.by_rid(mri), self.by_rid(amyloid), self.items(tn)), ""

    def indices(self, mri, amyloid, tau):
        c = self.c
        tn = c["tau"]["source"]
        tc = c["tau"]["columns"]
        result = {}
        self.diagnostics["tau.skipped_scans"] += self.diagnostics[f"{tn}.ineligible_missing_RID_or_date_rows"]
        self.diagnostics["tau.skipped.missing_RID"] = self.diagnostics[f"{tn}.missing_RID_rows"]
        self.diagnostics["tau.skipped.missing_date"] = self.diagnostics[f"{tn}.missing_date_rows"]
        self.diagnostics["tau.skipped.invalid_date"] = self.diagnostics[f"{tn}.invalid_date_rows"]
        for rid, scans in self.by_rid(tau).items():
            for offset, scan in enumerate(scans):
                reasons = []
                value = self.numeric(scan.row.values[tc["meta_temporal_suvr"]], tn, tc["meta_temporal_suvr"])
                if value is None:
                    reasons.append("missing_tau_measurement" if missing(scan.row.values[tc["meta_temporal_suvr"]])
                                   else "invalid_tau_measurement")
                if token(scan.row.values[tc["qc"]["column"]]) != token(str(tc["qc"]["pass_value"])):
                    reasons.append("tau_QC_not_pass")
                mr = self.nearest(mri, rid, scan.day, c["windows_days"]["mri_from_index"], "index_MRI")
                am = self.nearest(amyloid, rid, scan.day, c["windows_days"]["amyloid_from_index"], "index_amyloid")
                if mr is None:
                    reasons.append("no_qualifying_MRI_in_window")
                if am is None:
                    reasons.append("no_qualifying_amyloid_in_window")
                if mr is not None and am is not None:
                    if abs((mr.day - am.day).days) > c["windows_days"]["mri_to_amyloid_max"]:
                        reasons.append("MRI_amyloid_interval_exceeds_window")
                if reasons:
                    self.diagnostics["tau.skipped_scans"] += 1
                    for reason in reasons:
                        self.diagnostics["tau.skipped." + reason] += 1
                    continue
                result[rid] = Index(scan.day, scan, mr, am)
                self.diagnostics["tau.not_examined_after_index_selected"] += len(scans) - offset - 1
                break
        return result

    def cohort(self, indices, dx):
        c = self.c
        baselines = {}
        for rid, index in indices.items():
            baseline = self.nearest(dx, rid, index.day,
                                    c["windows_days"]["diagnosis_baseline"], "diagnosis_baseline")
            if baseline is None:
                self.diagnostics["cohort.excluded_no_diagnosis_baseline"] += 1
            elif baseline.value == "Dementia":
                self.diagnostics["cohort.excluded_dementia_baseline"] += 1
            else:
                baselines[rid] = baseline
        per_outcome = {}
        problems = {}
        for outcome, column in OUTCOMES.items():
            name = c["cognition"]["cdr_source" if outcome == "CDR_SB" else "primary_source"]
            problem = self.need(name, self.ids(name) + [column])
            if problem:
                per_outcome[outcome] = None
                problems[outcome] = problem
                continue
            visits = self.visits(name, column)
            eligible = set()
            for rid in baselines:
                index = indices[rid]
                baseline = self.nearest(visits, rid, index.day,
                                        c["windows_days"]["cognition_baseline"], outcome + "_baseline")
                if baseline is None:
                    self.diagnostics[outcome + ".excluded_no_baseline"] += 1
                    continue
                end = index.day + timedelta(days=c["cognition"]["followups"]["until_days_from_index"])
                followups = [v for v in visits.get(rid, []) if baseline.day < v.day <= end]
                enough = len(followups) >= c["cognition"]["min_assessments_total"] - 1
                span = bool(followups) and (followups[-1].day - baseline.day).days >= c["cognition"]["min_span_days"]
                if not enough:
                    self.diagnostics[outcome + ".excluded_insufficient_followups"] += 1
                if not span:
                    self.diagnostics[outcome + ".excluded_insufficient_span"] += 1
                if enough and span:
                    eligible.add(rid)
            per_outcome[outcome] = eligible
        cohort = None if problems else set().union(*per_outcome.values())
        return cohort, baselines, per_outcome, problems

    def events(self, cohort, indices, baselines, dx):
        confirmed, unconfirmed, conflict_next = set(), set(), set()
        for rid in cohort:
            baseline = baselines[rid]
            if baseline.value != "MCI":
                continue
            end = indices[rid].day + timedelta(days=self.c["units"]["censor_days"])
            visits = [v for v in dx.get(rid, []) if baseline.day < v.day <= end]
            event = next((v for v in visits if v.value == "Dementia"), None)
            if event is None:
                continue
            name = self.c["diagnosis"]["source"]
            later = [(v.day, v.row.position, v.value) for v in visits if v.day > event.day]
            for key in self.duplicate_conflicts[name]:
                if key[0] != rid or not usable_key(key, self.ids(name)):
                    continue
                day = self.day(key[2], name, self.ids(name)[2], "visit_keys")
                if day is None:
                    continue
                if event.day < day <= end:
                    position = min(row.position for row in self.groups[name][key])
                    later.append((day, position, "CONFLICT"))
            following = min(later, key=lambda entry: (entry[0], entry[1])) if later else None
            if following is None:
                unconfirmed.add(rid)
            elif following[2] == "CONFLICT":
                conflict_next.add(rid)
                self.edge("conversion.conflicting_next_diagnosis_visit",
                          "UNCONFIRMED_CONFLICT_NEXT_VISIT; do not skip ahead", "events")
            elif following[2] == "Dementia":
                confirmed.add(rid)
            else:
                self.diagnostics["conversion.first_events_removed_by_next_visit_reversion"] += 1
        return confirmed, unconfirmed, conflict_next

    def training(self, indices, mri, amyloid, dx):
        c = self.c
        pool = c["brain_age_training_pool"]
        cutoff = Decimal(str(c["amyloid"]["negative_rule"]["cutoff"]))
        # The any-later-non-CN exclusion considers every recorded mapped
        # diagnosis, including records in a conflicting duplicate group.
        # A conflict cannot establish a CN baseline, and cannot erase a
        # recorded later MCI/dementia diagnosis from this exclusion check.
        dn = c["diagnosis"]["source"]
        dc = c["diagnosis"]["columns"]["diagnosis"]
        later_non_cn = defaultdict(list)
        for item in self.items(dn):
            if DX_CODES.get(token(item.row.values[dc])) in ("MCI", "Dementia"):
                later_non_cn[item.rid].append(item.day)
        conflicting_non_cn = defaultdict(list)
        for key in self.duplicate_conflicts[dn]:
            if not usable_key(key, self.ids(dn)):
                continue
            day = self.day(key[2], dn, self.ids(dn)[2], "visit_keys")
            if day is not None and any(
                DX_CODES.get(token(row.values[dc])) in ("MCI", "Dementia")
                for row in self.groups[dn][key]
            ):
                conflicting_non_cn[key[0]].append(day)
        result = set()
        for rid, scans in mri.items():
            if rid in indices:
                self.diagnostics["training.excluded_index_eligible_RIDs_with_usable_MRI"] += 1
                continue
            # Earliest usable MRI, with no fallback to another MRI.
            scan = scans[0]
            am = self.nearest(amyloid, rid, scan.day, pool["amyloid_within_days_of_mri"], "training_amyloid")
            baseline = self.nearest(dx, rid, scan.day, pool["cn_at_mri"]["diagnosis_within_days"], "training_diagnosis")
            reasons = []
            if am is None:
                reasons.append("no_qualifying_amyloid_in_window")
            elif not am.value < cutoff:
                reasons.append("not_amyloid_negative")
            if baseline is None:
                reasons.append("no_diagnosis_in_window")
            elif baseline.value != "CN":
                reasons.append("not_CN_at_MRI")
            if any(day > scan.day for day in later_non_cn.get(rid, [])):
                reasons.append("later_non_CN")
            if any(day > scan.day for day in conflicting_non_cn.get(rid, [])):
                self.diagnostics["training.excluded_due_to_later_conflicting_nonCN_group_RIDs"] += 1
                self.edge("training.later_conflicting_group_contains_nonCN",
                          "exclude entire RID from training", "RIDs")
            if reasons:
                for reason in reasons:
                    self.diagnostics["training.excluded." + reason] += 1
            else:
                result.add(rid)
        return result

    def plasma(self, cohort, indices):
        c = self.c
        name = c["plasma_subset"]["source"]
        reason = self.need(name, self.ids(name) + ["pT217_F"])
        if reason:
            return None, reason
        candidates = []
        for item in self.items(name):
            value = self.numeric(item.row.values["pT217_F"], name, "pT217_F")
            if value is not None:
                candidates.append(Item(item.row, item.rid, item.day, value))
        visits = self.by_rid(candidates)
        result = {rid for rid in cohort if self.nearest(
            visits, rid, indices[rid].day, c["plasma_subset"]["ptau217_within_days"], "plasma",
        ) is not None}
        return result, ""


class Report:
    def __init__(self):
        self.lines = ["X1 FEASIBILITY COUNTS"]

    def add(self, label, value=None, reason=""):
        if value is None:
            text = "NOT EVALUATED" + (f" ({reason})" if reason else "")
        elif isinstance(value, (dict, list)):
            text = quoted(value)
        else:
            text = str(value)
        self.lines.append(f"{label}: {text}")

    def threshold(self, label, observed, threshold, blocked=False):
        if threshold == "PENDING_THEORIST":
            self.add(label, reason="PENDING_THEORIST")
        elif not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
            self.add(label, reason="no numeric X1 count threshold")
        elif observed is None or blocked:
            self.add(label, reason="required count unavailable or X4a BLOCKED")
        else:
            verdict = "PASS" if observed >= threshold else "FAIL"
            self.add(label, f"{verdict}; n={observed}; required_n>={threshold}")


def validate(config):
    if config.get("status") != "FINAL":
        raise InputError("count_x1.py runs only with status FINAL; DRAFT execution is disabled")
    if has_pending_theorist(config):
        raise InputError("status FINAL is forbidden while any PENDING_THEORIST value remains")
    expected = (
        (config["execution"]["count_x1_status"], "FINAL"),
        (config["mri"]["qc_flag"]["pass_token"], "Pass"),
        (config["mri"]["columns"]["status"], "STATUS"),
        (config["mri"]["qc_flag"]["accept_blank_when"], {"column": "STATUS", "equals": "partial"}),
        (config["mri"]["qc_flag"]["excluded_tokens"], ["Fail", "Partial", "Hippocampus Only"]),
        (config["mri"]["qc_flag"]["strict_pass_only_sensitivity"], True),
        (config["identifiers"]["join_keys"]["APOERES"], ["RID"]),
        (config["index"]["rule"], "earliest_tau_scan_meeting_all"),
        (config["index"]["outcome_data_used"], False),
        (config["selection"]["tie_break"], ["complete_values", "earlier_record", "lowest_row_id"]),
        (config["cognition"]["baseline"], "nearest_visit_with_non_missing_outcome"),
        (config["cognition"]["followups"]["after"], "outcome_baseline"),
        (config["cognition"]["followups"]["per_outcome"], True),
        (config["cognition"]["cohort_requires"], "at_least_one_outcome"),
        (config["cognition"]["outcomes"], list(OUTCOMES)),
        (config["conversion"]["event"], "first_post_baseline_dementia"),
        (config["conversion"]["confirmation"]["rule"], "next_diagnosis_visit_only"),
        (config["amyloid"]["negative_rule"]["operator"], "<"),
        (config["brain_age_training_pool"]["one_mri_per_rid"], "earliest_usable"),
        (config["brain_age_training_pool"]["exclude_rids"], "all_rids_with_index_eligible_scan"),
        (config["brain_age_training_pool"]["exclude_if_any_later_non_cn"], True),
        (config["identifiers"]["row_id"]["source"], "original_csv_row_position"),
        (config["identifiers"]["phase"]["derive_pet_phase"], False),
        (config["mri"]["freesurfer_version"]["expected_by_phase"], None),
    )
    if any(actual != required for actual, required in expected):
        raise InputError("Unsupported change to X1 rules; implementation requires review")
    for field in config["mri"]["required_fields"]:
        mapping = config["mri"]["columns"][field]
        if isinstance(mapping, dict) and (
            mapping["aggregation"] != "mean" or mapping["require_both_non_missing"] is not True
        ):
            raise InputError("Unsupported bilateral thickness rule")


def raw_report(engine, report):
    c, tables = engine.c, engine.tables
    mn = c["mri"]["source"]
    fs = c["mri"]["columns"]["freesurfer_version"]
    for name, table in tables.items():
        report.add(f"table.{name}.rows", None if table.problem else table.raw_count, table.problem)
        report.add(f"table.{name}.excluded_malformed_records",
                   None if table.problem else (table.issues or {}).get("malformed_record_width", 0), table.problem)
        blank_problem = table.require(["VISCODE2"])
        if not blank_problem and table.issues:
            blank_problem = "malformed records prevent complete blank VISCODE2 counts"
        report.add(f"table.{name}.rows_with_blank_VISCODE2",
                   None if blank_problem else sum(not row.values["VISCODE2"].strip() for row in table.rows),
                   blank_problem)
        problem = table.require(["PHASE"])
        if not problem and table.issues:
            problem = "malformed records prevent complete raw phase counts"
        report.add(f"table.{name}.native_PHASE_counts",
                   None if problem else dict(Counter(r.values["PHASE"] for r in table.rows)), problem)
        if name != mn:
            report.add(f"table.{name}.native_FSVER_counts", reason="no mapped native FreeSurfer-version field")
    problem = tables[mn].require(["PHASE", fs])
    if not problem and tables[mn].issues:
        problem = "malformed records prevent complete raw version counts"
    versions = defaultdict(Counter)
    missing_versions = Counter()
    if not problem:
        for row in tables[mn].rows:
            phase = row.values["PHASE"]
            if missing(row.values[fs]):
                missing_versions[phase] += 1
                versions[phase]
            else:
                versions[phase][row.values[fs]] += 1
    report.add("MRI.FSVER_by_native_PHASE", None if problem else {
        phase: {"observed_counts": dict(counts), "missing_rows": missing_versions[phase],
                "mixed_versions": int(len(counts) > 1), "missing_PHASE": int(missing(phase))}
        for phase, counts in versions.items()
    }, problem)
    report.add("MRI.expected_version_mismatch", reason="expected_by_phase is unspecified")
    qc = c["mri"]["qc_flag"]["column"]
    problem = tables[mn].require([qc])
    if not problem and tables[mn].issues:
        problem = "malformed records prevent complete strict-Pass QC counts"
    report.add("MRI.strict_Pass_QC_rows", None if problem else
               sum(row.values[qc] == c["mri"]["qc_flag"]["pass_token"] for row in tables[mn].rows), problem)


def auxiliary_report(engine, report):
    c, tables = engine.c, engine.tables
    dn = c["diagnosis"]["source"]
    dc = c["diagnosis"]["columns"]["diagnosis"]
    dp = c["diagnosis"]["columns"]["phase_for_raw_value_counts"]
    problem = tables[dn].require([dc, dp])
    if not problem and tables[dn].issues:
        problem = "malformed records prevent complete raw diagnosis counts"
    values, unmapped, no_diagnosis = defaultdict(Counter), Counter(), Counter()
    if not problem:
        for row in tables[dn].rows:
            phase, value = row.values[dp], row.values[dc]
            values[phase][value] += 1
            unmapped[phase] += int(missing(value) or token(value) not in {*DX_CODES, "10"})
            no_diagnosis[phase] += int(token(value) == "10")
    report.add("DXSUM.DIAGNOSIS_raw_value_counts_by_PHASE",
               None if problem else {p: dict(counts) for p, counts in values.items()}, problem)
    report.add("DXSUM.unmapped_DIAGNOSIS_rows_by_PHASE", None if problem else dict(unmapped), problem)
    report.add("DXSUM.no_diagnosis_code_10_rows_by_PHASE", None if problem else dict(no_diagnosis), problem)
    report.add("A5", "PROVISIONAL")
    pn = c["reserve"]["source"]
    problem = tables[pn].require(["PTWORK", "PHASE"])
    if not problem and tables[pn].issues:
        problem = "malformed records prevent complete occupation counts"
    occupation = Counter()
    if not problem:
        for row in tables[pn].rows:
            occupation[row.values["PHASE"]] += int(not missing(row.values["PTWORK"]))
    report.add("PTDEMOG.PTWORK_nonmissing_rows_by_PHASE", None if problem else dict(occupation), problem)
    report.add("PHC_MEM", reason="undocumented; excluded from X1 tiers")
    report.add("PHC_EXF", reason="undocumented; excluded from X1 tiers")


def duplicate_report(engine, report):
    for name in engine.tables:
        groups = engine.add_keys(name)
        report.add(f"table.{name}.duplicate_keys",
                   None if groups is None else len(engine.duplicate_keys[name]),
                   engine.need(name, engine.ids(name)))
        report.add(f"table.{name}.duplicate_extra_rows",
                   None if groups is None else sum(len(rows) - 1 for rows in groups.values()),
                   engine.need(name, engine.ids(name)))
        report.add(f"table.{name}.rows_with_missing_duplicate_key_component",
                   None if groups is None else
                   sum(len(rows) for key, rows in groups.items() if not usable_key(key, engine.ids(name))),
                   engine.need(name, engine.ids(name)))


def selected_versions(engine, report, label, rids, indices):
    if rids is None:
        report.add(label, reason="required RID set unavailable")
        return
    c = engine.c
    mn = c["mri"]["source"]
    phase_col = c["identifiers"]["phase"]["column"]
    fs_col = c["mri"]["columns"]["freesurfer_version"]
    problem = engine.need(mn, [phase_col, fs_col])
    counts = defaultdict(Counter)
    missing_versions = Counter()
    if not problem:
        for rid in rids:
            selected = getattr(indices[rid], "mri", indices[rid])
            row = selected.row
            phase = row.values[phase_col]
            version = row.values[fs_col]
            counts[phase]
            if missing(version):
                missing_versions[phase] += 1
            else:
                counts[phase][version] += 1
    report.add(label, None if problem else {
        p: {"observed_counts": dict(v), "missing_rows": missing_versions[p], "mixed_versions": int(len(v) > 1)}
        for p, v in counts.items()
    }, problem)


def strict_pass_sensitivity(config, tables, report):
    """Re-select the index and re-evaluate the cohort under strict MRI Pass only.

    This sensitivity supplies counts only; primary tiers and training-pool
    exclusions continue to use the primary MRI rule.
    """
    engine = Engine(config, tables)
    data, problem = engine.modalities(strict_pass_only=True)
    indices = None if data is None else engine.indices(*data)
    prefix = "strict_Pass_only."
    report.add(prefix + "usable_MRI_rows", None if data is None else
               sum(len(rows) for rows in data[0].values()), problem)
    report.add(prefix + "index_eligible_RIDs", None if indices is None else len(indices), problem)
    dn = config["diagnosis"]["source"]
    dc = config["diagnosis"]["columns"]["diagnosis"]
    problem = problem or engine.need(dn, engine.ids(dn) + [dc])
    cohort = baselines = per_outcome = None
    outcome_problems = {}
    if not problem:
        dx = engine.visits(dn, dc, diagnosis=True)
        cohort, baselines, per_outcome, outcome_problems = engine.cohort(indices, dx)
        problem = "; ".join(outcome_problems.values())
    report.add(prefix + "analysis_cohort.RIDs", None if cohort is None else len(cohort), problem)
    for diagnosis in ("CN", "MCI"):
        report.add(prefix + "analysis_cohort." + diagnosis, None if cohort is None else
                   sum(baselines[rid].value == diagnosis for rid in cohort), problem)
    for outcome in OUTCOMES:
        rids = None if per_outcome is None else per_outcome[outcome]
        report.add(prefix + outcome + ".n", None if rids is None else len(rids),
                   outcome_problems.get(outcome, problem))
    report.lines.append("strict_Pass_only.edge_case_decisions:")
    report.lines.append("case | rule_applied | count | unit")
    for (case, rule, unit), count in sorted(engine.edges.items()):
        report.lines.append(f"{case} | {rule} | {count} | {unit}")


def main():
    now = datetime.now(timezone.utc)
    commit, threshold_time = preflight(now)
    config = load_config()
    validate(config)  # FINAL and complete thresholds required before raw-data I/O.
    protected = {name: sha(ROOT / name) for name in (
        "thresholds.yaml", "decisions.md", "count_x1.py", "qc_values.py",
    )}
    specs = column_specs(config)
    tables = {name: read_table(name, columns, exclude_bad_records=True) for name, columns in specs.items()}
    engine = Engine(config, tables)
    report = Report()
    report.add("git_HEAD", commit)
    for name, digest in protected.items():
        report.add("SHA256." + name, digest)
    report.add("thresholds_last_commit_UTC", threshold_time.isoformat())
    report.add("run_UTC", now.isoformat())
    raw_report(engine, report)
    modality_data, index_problem = engine.modalities()
    indices = None if modality_data is None else engine.indices(*modality_data)
    report.add("index_eligible_RIDs_training_exclusion", None if indices is None else len(indices), index_problem)
    selected_versions(engine, report, "index_eligible.by_selected_MRI_PHASE_and_FSVER", indices, indices)
    dn = config["diagnosis"]["source"]
    dc = config["diagnosis"]["columns"]["diagnosis"]
    dx_problem = engine.need(dn, engine.ids(dn) + [dc])
    dx = None if dx_problem else engine.visits(dn, dc, diagnosis=True)
    cohort = baselines = per_outcome = None
    outcome_problems = {}
    cohort_problem = index_problem or dx_problem
    if indices is not None and dx is not None:
        cohort, baselines, per_outcome, outcome_problems = engine.cohort(indices, dx)
        cohort_problem = "; ".join(outcome_problems.values())
    report.add("analysis_cohort.RIDs", None if cohort is None else len(cohort), cohort_problem)
    for diagnosis in ("CN", "MCI"):
        rids = None if cohort is None else {rid for rid in cohort if baselines[rid].value == diagnosis}
        report.add("analysis_cohort." + diagnosis,
                   None if rids is None else len(rids),
                   cohort_problem)
        selected_versions(engine, report, f"analysis_cohort.{diagnosis}.by_selected_MRI_PHASE_and_FSVER", rids, indices)
    outcome_counts = []
    for outcome in OUTCOMES:
        rids = None if per_outcome is None else per_outcome[outcome]
        problem = outcome_problems.get(outcome, cohort_problem)
        report.add(f"Aim1.{outcome}.n", None if rids is None else len(rids), problem)
        selected_versions(engine, report, f"Aim1.{outcome}.by_selected_MRI_PHASE_and_FSVER", rids, indices)
        if rids is not None:
            outcome_counts.append(len(rids))
        for diagnosis in ("CN", "MCI"):
            report.add(f"Aim1.{outcome}.{diagnosis}",
                       None if rids is None else sum(baselines[rid].value == diagnosis for rid in rids), problem)
    aim1 = min(outcome_counts) if len(outcome_counts) == len(OUTCOMES) else None
    report.add("Aim1.smallest_per_outcome_n", aim1, cohort_problem)
    selected_versions(engine, report, "analysis_cohort.by_selected_MRI_PHASE_and_FSVER", cohort, indices)
    strict_pass_sensitivity(config, tables, report)
    confirmed = unconfirmed = conflict_next = None
    event_problem = cohort_problem
    if cohort is not None:
        confirmed, unconfirmed, conflict_next = engine.events(cohort, indices, baselines, dx)
    report.add("Aim2.confirmed_events", None if confirmed is None else len(confirmed), event_problem)
    report.add("Aim2.UNCONFIRMED_events", None if unconfirmed is None else len(unconfirmed), event_problem)
    report.add("Aim2.UNCONFIRMED_CONFLICT_NEXT_VISIT",
               None if conflict_next is None else len(conflict_next), event_problem)
    report.add("Aim2.events_including_UNCONFIRMED",
               None if confirmed is None else len(confirmed | unconfirmed | conflict_next), event_problem)
    selected_versions(engine, report, "Aim2.confirmed.by_selected_MRI_PHASE_and_FSVER", confirmed, indices)
    selected_versions(engine, report, "Aim2.UNCONFIRMED.by_selected_MRI_PHASE_and_FSVER", unconfirmed, indices)
    selected_versions(engine, report, "Aim2.UNCONFIRMED_CONFLICT_NEXT_VISIT.by_selected_MRI_PHASE_and_FSVER",
                      conflict_next, indices)
    training_problem = index_problem or dx_problem
    training = None
    if indices is not None and dx is not None:
        training = engine.training(indices, modality_data[0], modality_data[1], dx)
    report.add("training_pool.RIDs", None if training is None else len(training), training_problem)
    training_scans = None if training is None else {rid: modality_data[0][rid][0] for rid in training}
    selected_versions(engine, report, "training_pool.by_selected_MRI_PHASE_and_FSVER", training, training_scans)
    plasma = None
    plasma_problem = cohort_problem
    if cohort is not None:
        plasma, plasma_problem = engine.plasma(cohort, indices)
    report.add("plasma_subset.RIDs", None if plasma is None else len(plasma), plasma_problem)
    selected_versions(engine, report, "plasma_subset.by_selected_MRI_PHASE_and_FSVER", plasma, indices)
    report.add("plasma_subset.confirmed_events",
               None if plasma is None or confirmed is None else len(plasma & confirmed), plasma_problem or event_problem)
    report.add("plasma_subset.UNCONFIRMED_events",
               None if plasma is None or unconfirmed is None else len(plasma & unconfirmed), plasma_problem or event_problem)
    report.add("plasma_subset.UNCONFIRMED_CONFLICT_NEXT_VISIT",
               None if plasma is None or conflict_next is None else len(plasma & conflict_next),
               plasma_problem or event_problem)
    auxiliary_report(engine, report)
    duplicate_report(engine, report)
    # Tables without visit deduplication have raw duplicate diagnostics only.
    visit_fields = {
        config["cognition"]["primary_source"]: ["ADNI_MEM", "ADNI_EF"],
        config["cognition"]["cdr_source"]: ["CDRSB"], dn: [dc],
    }
    for name in tables:
        for suffix in ("collapsed_to_one", "collapsed_by_completeness", "conflicting"):
            label = f"table.{name}.duplicate_keys_{suffix}"
            fields = visit_fields.get(name)
            processed = fields and all((name, col, name == dn) in engine.visit_cache for col in fields)
            if not processed:
                report.add(label, reason="visit deduplication not evaluated for this table")
            else:
                conflicts = engine.duplicate_conflicts[name]
                if suffix == "conflicting":
                    value = len(conflicts)
                elif suffix == "collapsed_by_completeness":
                    value = len(engine.duplicate_completeness[name] - conflicts)
                else:
                    value = len(engine.duplicate_keys[name] - conflicts)
                report.add(label, value)
    for stage in ("index_MRI", "index_amyloid", "diagnosis_baseline", "ADNI_MEM_baseline",
                  "ADNI_EF_baseline", "CDR_SB_baseline", "training_amyloid", "training_diagnosis", "plasma"):
        available = indices is not None
        if stage == "diagnosis_baseline":
            available = baselines is not None
        elif stage.endswith("_baseline"):
            outcome = stage.removesuffix("_baseline")
            available = per_outcome is not None and per_outcome.get(outcome) is not None
        elif stage.startswith("training_"):
            available = training is not None
        elif stage == "plasma":
            available = plasma is not None
        queries = engine.tie_queries[stage]
        report.add(f"ties.{stage}.groups", len(queries) if available else None)
        report.add(f"ties.{stage}.extra_records", sum(n - 1 for n in queries.values()) if available else None)
    # Include real zero counts for each evaluated rejection reason, not absent
    # Counter entries masquerading as evaluated results when inputs are missing.
    diagnostic_names = (
        "tau.skipped_scans", "tau.not_examined_after_index_selected",
        "tau.skipped.missing_RID", "tau.skipped.missing_date", "tau.skipped.invalid_date",
        "tau.skipped.missing_tau_measurement", "tau.skipped.invalid_tau_measurement", "tau.skipped.tau_QC_not_pass",
        "tau.skipped.no_qualifying_MRI_in_window", "tau.skipped.no_qualifying_amyloid_in_window",
        "tau.skipped.MRI_amyloid_interval_exceeds_window",
        "MRI.rejected_QC_rows", "MRI.rejected_missing_required_measurement_rows", "MRI.rejected_invalid_numeric_rows",
        "AMYQC.amyloid_scans_missing_QC_record", "AMYQC.amyloid_scans_duplicate_QC_records",
        "AMYQC.amyloid_scans_one_pass", "AMYQC.amyloid_scans_one_fail", "AMYQC.amyloid_scans_invalid_join_key",
        "AMYQC.amyloid_scans_conflicting_QC_records", "amyloid.rejected_own_QC_rows",
        "amyloid.rejected_AMYQC_rows", "amyloid.rejected_missing_Centiloid_rows", "amyloid.rejected_invalid_Centiloid_rows",
    )
    for label in diagnostic_names:
        report.add(label, engine.diagnostics[label] if indices is not None else None, index_problem)
    training_conflict_label = "training.excluded_due_to_later_conflicting_nonCN_group_RIDs"
    for label in sorted(set(engine.diagnostics) - set(diagnostic_names) - {training_conflict_label}):
        report.add(label, engine.diagnostics[label])
    report.add(training_conflict_label,
               None if training is None else engine.diagnostics[training_conflict_label],
               training_problem)
    report.lines.append("edge_case_decisions:")
    report.lines.append("case | rule_applied | count | unit")
    for (case, rule, unit), count in sorted(engine.edges.items()):
        report.lines.append(f"{case} | {rule} | {count} | {unit}")
    overlap = None if training is None or cohort is None else training & cohort
    blocked = overlap is not None and bool(overlap)
    for label, rids in (("train", training), ("analysis", cohort), ("index_eligible_exclusion", indices)):
        report.add(f"X4a.{label}.RID_count", None if rids is None else len(rids))
        report.add(f"X4a.{label}.sorted_RID_SHA256", None if rids is None else rid_hash(rids))
    report.add("X4a.overlap_RIDs", None if overlap is None else len(overlap))
    assertion = "BLOCKED" if blocked else "PASS"
    report.add("X4a.assertion (by construction)", None if overlap is None else assertion)
    for name, threshold in config["tiers"]["aim1"].items():
        report.threshold("threshold.Aim1." + name, aim1, threshold, blocked)
    report.threshold("threshold.Aim2.min_confirmed_events",
                     None if confirmed is None else len(confirmed),
                     config["tiers"]["aim2"]["min_confirmed_events"], blocked)
    report.threshold("threshold.training_pool.min_n", None if training is None else len(training),
                     config["brain_age_training_pool"]["min_n"], blocked)
    report.add("threshold.Aim3.reserve", reason="exploratory; no numeric X1 threshold")
    # Do not emit a report whose protected inputs changed during counting.
    if git("rev-parse", "HEAD") != commit or git("status", "--porcelain=v1", "--untracked-files=all"):
        raise InputError("Git state changed during counting; report withheld")
    if any(sha(ROOT / name) != digest for name, digest in protected.items()):
        raise InputError("Protected input changed during counting; report withheld")
    print("\n".join(report.lines))
    return 2 if blocked else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (InputError, KeyError, TypeError, ValueError, OSError) as exc:
        message = str(exc) if isinstance(exc, InputError) else "Invalid configuration or unavailable local prerequisite"
        print("ERROR: " + message, file=sys.stderr)
        raise SystemExit(1)
