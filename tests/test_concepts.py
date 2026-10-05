"""The vendored mimic-code concepts and the views they read (crrt.concepts).

No MIMIC data is read. The concepts themselves are mimic-code's and are
not re-tested here; these tests hold the repo to running them unmodified,
in an order that builds every dependency first, on sources whose times are
times of availability.
"""

import hashlib
import re
from datetime import datetime, timedelta

import pytest

from crrt.concepts import CONCEPTS, CONCEPTS_DIR, SOURCES, create_sources

duckdb = pytest.importorskip("duckdb")

T0 = datetime(2150, 1, 1)


def sql(concept: str) -> str:
    return (CONCEPTS_DIR / f"{concept}.sql").read_text()


def test_every_vendored_file_matches_its_checksum():
    """sql/mimic_code/README.md: the files are mimic-code's, byte for byte."""
    sums = dict(reversed(line.split()) for line in (CONCEPTS_DIR / "SHA256SUMS").read_text().splitlines())
    on_disk = {str(p.relative_to(CONCEPTS_DIR)) for p in CONCEPTS_DIR.rglob("*.sql")}
    assert set(sums) == on_disk
    for path, digest in sums.items():
        assert hashlib.sha256((CONCEPTS_DIR / path).read_bytes()).hexdigest() == digest, path


def test_every_vendored_concept_is_built_and_nothing_else():
    on_disk = {str(p.relative_to(CONCEPTS_DIR)).removesuffix(".sql") for p in CONCEPTS_DIR.rglob("*.sql")}
    assert sorted(CONCEPTS) == sorted(on_disk)
    assert len(set(CONCEPTS)) == len(CONCEPTS)


def test_every_concept_is_built_after_the_concepts_it_reads():
    built: set[str] = set()
    for concept in CONCEPTS:
        name = concept.split("/")[-1]
        reads = set(re.findall(r"mimiciv_derived\.(\w+)", sql(concept))) - {name}
        assert reads <= built, f"{concept} reads {sorted(reads - built)} before they are built"
        built.add(name)


def test_every_table_a_concept_reads_has_a_source_view():
    read = {f"{schema}/{table}" for concept in CONCEPTS
            for schema, table in re.findall(r"mimiciv_(hosp|icu)\.(\w+)", sql(concept))}
    assert read == set(SOURCES)


def test_source_views_carry_times_of_availability():
    """A row counts from greatest(time, storetime): a value stored two hours
    after its charttime is at its storetime; one with a storetime before its
    charttime (a few daily weights) stays at its charttime. Pass-through
    tables are unchanged."""
    con = duckdb.connect()
    for qualified, column in SOURCES.items():
        name = qualified.split("/")[1]
        time = column or "charttime"
        con.execute(f"CREATE TABLE main.{name} (k INTEGER, {time} TIMESTAMP, storetime TIMESTAMP)")
        con.executemany(f"INSERT INTO main.{name} VALUES (?, ?, ?)",
                        [(1, T0, T0 + timedelta(hours=2)), (2, T0, T0 - timedelta(minutes=1))])
    create_sources(con)
    for qualified, column in SOURCES.items():
        schema, name = qualified.split("/")
        time = column or "charttime"
        got = dict(con.execute(f"SELECT k, {time} FROM mimiciv_{schema}.{name}").fetchall())
        assert got == {1: T0 + timedelta(hours=2) if column else T0, 2: T0}, qualified
