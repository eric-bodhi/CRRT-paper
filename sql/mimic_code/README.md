# Vendored mimic-code concepts

Unmodified copies of 22 DuckDB concepts from
[MIT-LCP/mimic-code](https://github.com/MIT-LCP/mimic-code),
`mimic-iv/concepts_duckdb/`, at commit
`303d26c623dcc9c49cc0f204468d4acc2f063797` (`main`, 2026-09-01), fetched
2026-10-04. MIT licence, copied as `LICENSE`.

They are what SOFA and Sepsis-3 at CRRT start (`sql/static_features.sql`)
need, and nothing else: `score/sofa` and `sepsis/sepsis3` with every concept
they depend on. `crrt.concepts` runs them in the order of mimic-code's
`duckdb.sql`, on source views whose times are times of availability.
Decision: `docs/decisions.md` 2026-10-05, "Static features".

**Do not edit these files.** A correction belongs upstream, in mimic-code's
BigQuery `concepts/` folder, from which these are generated. Taking a newer
version means re-fetching every file at one commit, updating the commit
above and `SHA256SUMS`, and logging it in `docs/decisions.md`.
`tests/test_concepts.py` fails if a file differs from its checksum.

The repo rule that no number is typed into a `.sql` file (CLAUDE.md) does
not apply here. The numbers in these files are mimic-code's itemids and the
published SOFA and Sepsis-3 cut-points, and changing one would make the
concept no longer the validated one.
