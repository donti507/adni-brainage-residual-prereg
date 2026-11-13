"""X1 raw-column audit. Importing this module does not read any data.

Run from any directory with Python 3.10+ and PyYAML installed. Data inputs
are restricted to data/raw; thresholds.yaml is read only as configuration.
Only OVERALLQC distinct values and per-column sentinel counts are printed.
"""

import csv
import json
import sys
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent
# Exact filenames supplied in docs/headers.txt; no filename inference.
FILES = {
    name: name + "_12Nov2026.csv"
    for name in (
        "UCSFFSX7", "UCBERKELEY_AMY_6MM", "UCBERKELEY_TAU_6MM",
        "AMYQC", "UWNPSYCHSUM", "CDR", "DXSUM", "PTDEMOG",
        "UPENN_PLASMA_FUJIREBIO_QUANTERIX", "ADSP_PHC_COGN", "APOERES",
    )
}
SENTINELS = ("-1", "-2", "-4", "BLANK")


class InputError(Exception):
    pass


def quoted(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def token(value):
    """Normalize numeric spellings, but do not interpret undocumented codes."""
    value = value.strip()
    if not value:
        return ""
    try:
        number = Decimal(value)
        if number.is_finite():
            return format(number.normalize(), "f") if number else "0"
    except InvalidOperation:
        pass
    return value


def sentinel(value):
    value = value.strip()
    if not value:
        return "BLANK"
    try:
        number = Decimal(value)
        if number in (Decimal(-1), Decimal(-2), Decimal(-4)):
            return str(int(number))
    except InvalidOperation:
        pass
    return None


def missing(value):
    return sentinel(value) is not None


def number(value, table, column):
    if missing(value):
        return None
    try:
        result = Decimal(value.strip())
        if result.is_finite():
            return result
    except InvalidOperation:
        pass
    raise InputError(f"{table}.{column}: non-missing value is not a finite number")


def load_config():
    try:
        with (ROOT / "thresholds.yaml").open(encoding="utf-8-sig") as stream:
            config = yaml.safe_load(stream)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise InputError("Cannot read thresholds.yaml as valid UTF-8 YAML") from exc
    if not isinstance(config, dict):
        raise InputError("thresholds.yaml must be a mapping")
    return config


def column_specs(config):
    """Explicit v0.3 mappings plus the User-approved X1 audit columns."""
    specs = {name: set() for name in FILES}
    identifiers = config["identifiers"]
    for kind in ("participant", "visit", "date"):
        for table, column in identifiers[kind].items():
            if table not in specs or not isinstance(column, str):
                raise InputError(f"Unsupported {kind} mapping")
            specs[table].add(column)
    mri = config["mri"]
    for field in mri["required_fields"]:
        mapping = mri["columns"][field]
        if isinstance(mapping, str):
            specs[mri["source"]].add(mapping)
        else:
            specs[mri["source"]].update((mapping["left"], mapping["right"]))
    specs[mri["source"]].update((
        mri["qc_flag"]["column"], mri["columns"]["freesurfer_version"],
        identifiers["phase"]["column"],
    ))
    amy = config["amyloid"]
    specs[amy["source"]].update((
        amy["columns"]["centiloid_global"], amy["columns"]["qc"]["column"],
    ))
    aq = amy["columns"]["amyqc"]
    specs[aq["source"]].update(aq["join_keys"] + [aq["column"]])
    tau = config["tau"]
    specs[tau["source"]].update((
        tau["columns"]["meta_temporal_suvr"], tau["columns"]["qc"]["column"],
    ))
    dx = config["diagnosis"]
    specs[dx["source"]].update((
        dx["columns"]["diagnosis"], dx["columns"]["phase_for_raw_value_counts"],
    ))
    specs[config["cognition"]["primary_source"]].update(("ADNI_MEM", "ADNI_EF"))
    specs[config["cognition"]["cdr_source"]].add("CDRSB")
    specs[config["plasma_subset"]["source"]].add("pT217_F")
    specs[config["reserve"]["source"]].add("PTWORK")
    for table in specs:
        if table not in (amy["source"], tau["source"]):
            specs[table].add("PHASE")
    return specs


@dataclass
class Row:
    position: int
    values: dict


@dataclass
class Table:
    name: str
    columns: set
    rows: list
    problem: str = ""
    raw_count: int | None = None
    issues: dict | None = None

    def require(self, columns):
        if self.problem:
            return self.problem
        absent = sorted(set(columns) - self.columns)
        return "missing columns: " + ", ".join(absent) if absent else ""


def read_table(name, columns, exclude_bad_records=False):
    """Read only the approved raw CSV; retain requested fields and native PHASE."""
    path = ROOT / "data" / "raw" / FILES[name]
    try:
        csv.field_size_limit(2**31 - 1)
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(stream, strict=True)
            header = next(reader, None)
            if not header or len(set(header)) != len(header):
                return Table(name, set(), [], "absent or duplicate column headers")
            retained = set(columns) | {"PHASE"}
            selected = [(i, c) for i, c in enumerate(header) if c in retained]
            rows = []
            raw_count = 0
            issues = Counter()
            for position, cells in enumerate(reader, 1):
                raw_count += 1
                if len(cells) != len(header):
                    if not exclude_bad_records:
                        return Table(name, set(header), [], "malformed CSV record width")
                    issues["malformed_record_width"] += 1
                    continue
                rows.append(Row(position, {c: cells[i] for i, c in selected}))
        return Table(name, set(header), rows, raw_count=raw_count, issues=dict(issues))
    except FileNotFoundError:
        return Table(name, set(), [], "missing raw CSV")
    except (OSError, UnicodeError, csv.Error):
        return Table(name, set(), [], "cannot read complete valid UTF-8 CSV")


def main():
    config = load_config()
    specs = column_specs(config)
    output = []
    failed = False
    for name, columns in specs.items():
        table = read_table(name, columns)
        if name == config["mri"]["source"]:
            qc = config["mri"]["qc_flag"]["column"]
            reason = table.require([qc])
            if reason:
                output.append(f"{name}.{qc}: NOT EVALUATED ({reason})")
                failed = True
            else:
                for value, count in sorted(Counter(r.values[qc] for r in table.rows).items()):
                    output.append(f"{name}.{qc} value={quoted(value)} count={count}")
                if not table.rows:
                    output.append(f"{name}.{qc}: distinct_values=0")
        for column in sorted(columns):
            reason = table.require([column])
            if reason:
                output.append(f"{name}.{column} sentinels: NOT EVALUATED ({reason})")
                failed = True
                continue
            counts = Counter(sentinel(r.values[column]) for r in table.rows)
            output.append(f"{name}.{column} sentinels: " + " ".join(
                f"{value}={counts[value]}" for value in SENTINELS
            ))
    print("\n".join(output))
    return int(failed)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (InputError, KeyError, TypeError) as exc:
        message = str(exc) if isinstance(exc, InputError) else "Unsupported thresholds.yaml schema"
        print("ERROR: " + message, file=sys.stderr)
        raise SystemExit(1)
