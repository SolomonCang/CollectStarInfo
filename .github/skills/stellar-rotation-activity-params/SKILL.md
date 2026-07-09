---
name: stellar-rotation-activity-params
description: 'Use when analyzing a target result JSON to find stellar rotation and activity parameters from the references list, including Period, Mass, Teff, log g, vsini, RV, inclination, and mean longitudinal magnetic field <Bl>. Follow the JSON -> reference triage -> ADS/VizieR/arXiv -> parameter extraction workflow, and use the bundled script to prepare a ranked literature hunt from results/*.json files.'
argument-hint: 'Provide a target JSON path or target name, plus any parameters you want prioritized.'
user-invocable: true
---

# Stellar Rotation And Activity Parameters

## What This Skill Produces

This skill turns one target JSON report in results into a reproducible literature-search workflow for stellar rotation and activity parameters. It is designed for cases where the JSON already contains a populated references list from SIMBAD and you want to find parameter measurements in papers, VizieR tables, and arXiv versions.

It can also generate an independent markdown file named like results/KIC 4931738_extrapar.md without modifying the original target report markdown.

Primary parameters in scope:
- Period
- Mass
- Teff
- log g
- vsini
- RV
- INCL
- <Bl>

Secondary context in scope when it helps interpret those parameters:
- object aliases and catalog IDs
- component labels for binaries or multiples
- observation type and instrument
- whether a value is photometric, spectroscopic, seismic, magnetic, or catalog-derived

## When To Use

- You have a file like results/KIC 4931738.json and need parameter-level follow-up.
- The references list is long and you need to prioritize the papers most likely to contain measurements.
- You need a consistent workflow for checking article metadata, VizieR tables, and arXiv full text.
- You want a reusable checklist before writing a final target summary or parameter table.

## Inputs

- One target JSON file under results
- The target name and aliases from the JSON
- The references list under target.simbad.references
- Optional user emphasis on a subset of parameters
- Optional request to download source assets into results/<target>/

## Procedure

1. Confirm target identity before searching.
   - Read query_target, object_name, identifiers, coordinates, spectral type, and any Gaia or TIC or KIC IDs.
   - For binaries or multiples, note whether the target may appear in papers under a component name, catalog alias, or system-level designation.

2. Inspect the JSON references list and rank likely high-value papers.
   - Prefer references with high obj_freq.
   - Prioritize titles, keywords, and abstracts that mention spectroscopy, radial velocity, v sin i, rotation, period, magnetic field, binaries, asteroseismology, abundance analysis, or stellar parameters.
   - Down-rank papers that only classify variability without giving physical parameters.

3. Generate a first-pass search plan.
   - Use the bundled script [prepare_reference_hunt.py](./scripts/prepare_reference_hunt.py) to produce a ranked checklist from the JSON file.
   - By default, the script keeps and processes the full references list; only pass --top N when you intentionally want to cap the review scope.
   - When --download-assets is enabled, the script still checks the full ranked list but only downloads high-priority candidate assets by default, so large targets do not stall on thousands of full-text fetches.
   - Review the output table, ADS link, candidate VizieR catalog code, and arXiv query for each prioritized paper.
   - When you need a reusable artifact, run the same script with --write-extrapar-markdown so it writes a standalone parameter table markdown next to the JSON file.

4. Check the paper record first.
   - Open the ADS record from the bibcode.
   - Verify the paper is directly about the target rather than only a large-sample mention.
   - Determine whether the likely parameter source is the main text, appendix, online table, or external catalog.

5. Check VizieR for machine-readable tables.
   - Use the candidate VizieR link or query terms from the script.
   - Search by target identifier if the paper-level catalog link is missing or incorrect.
   - Look for tables containing stellar parameters, orbital solutions, spectroscopy results, magnetic measurements, or rotation products.

6. Check arXiv when the abstract is not enough.
   - Use the generated arXiv query or search by exact title.
   - Inspect PDF tables, appendices, and supplementary material when VizieR is incomplete.
   - If arXiv and journal versions disagree, prefer the refereed journal value unless the later preprint clearly supersedes it.

7. Extract parameter values with provenance.
   - Record the numeric value, uncertainty, unit, measurement type, component label, and source location.
   - Keep separate entries when multiple papers report different values.
   - Do not merge system-level and component-level values.

8. Resolve common ambiguities.
   - Period: distinguish rotation period, orbital period, pulsation period, and modulation frequency.
   - RV: distinguish systemic velocity from epoch-specific radial velocities.
   - INCL: distinguish orbital inclination from stellar spin inclination.
   - <Bl>: confirm it is mean longitudinal magnetic field rather than another magnetic observable.
   - Mass: confirm whether it is evolutionary, dynamical, or seismic.

9. Decide whether scripting is needed.
   - If there are many references or repeated targets, extend the workflow with a helper script instead of manual browsing.
   - Scripts should automate ranking, query construction, and output formatting, not invent parameter values.
   - Any downloaded paper source, ADS page, or VizieR page must be stored under results/<target>/, where <target> is the target name from the JSON.

10. Produce a final parameter table.
   - Include one row per parameter measurement.
   - Add target alias used in the source, component tag if relevant, value, uncertainty, units, method, bibcode, and notes.
   - Mark missing parameters explicitly as not found after checked references.
   - Write the table to a separate markdown file named <target>_extrapar.md so the original <target>.md report remains unchanged.

## Quality Checks

- Every reported number must map to a paper, table, catalog entry, or explicit text location.
- Values from different components must not be conflated.
- Rotation-related quantities must not be confused with orbital or pulsational quantities.
- If only a large-sample catalog mentions the target, note that the parameter is catalog-derived and may not be target-focused.
- If no reliable value is found, report not found rather than guessing from context.

## Recommended Output Shape

Use this structure in notes or downstream JSON fragments:

| Parameter | Value | Uncertainty | Unit | Component | Method | Source bibcode | Source location | Notes |
|---|---|---|---|---|---|---|---|---|
| Teff |  |  | K | primary | spectroscopy |  | Table X |  |

## Tools In This Skill

- [prepare_reference_hunt.py](./scripts/prepare_reference_hunt.py): Reads a target JSON, ranks the full reference list by default, optionally downloads high-priority candidate assets into results/<target>/, and can write a standalone <target>_extrapar.md parameter table.
- [parameter-extraction.md](./references/parameter-extraction.md): Parameter synonyms, source heuristics, and ambiguity checks.

## Suggested Invocation Patterns

- Use this skill for results/KIC 4931738.json and prioritize Period, vsini, RV, INCL, and <Bl>.
- Use this skill on the current target JSON and generate a literature hunt table.
- Use this skill to inspect the references list and build a parameter summary for a Kepler B-type binary.
- Use this skill on results/KIC 4931738.json, download assets into results/KIC 4931738/, and write results/KIC 4931738_extrapar.md.