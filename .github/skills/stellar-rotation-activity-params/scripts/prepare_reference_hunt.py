from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import re
import tarfile
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

PARAMETER_PATTERNS: dict[str, tuple[str, ...]] = {
    "Period": (
        "rotation period",
        "rotational",
        "period",
        "modulation",
        "frequency",
    ),
    "Mass": (
        "mass",
        "masses",
        "dynamical mass",
        "seismic mass",
    ),
    "Teff": (
        "teff",
        "t_eff",
        "effective temperature",
    ),
    "log g": (
        "log g",
        "logg",
        "surface gravity",
    ),
    "vsini": (
        "v sin i",
        "vsini",
        "projected rotational velocity",
    ),
    "RV": (
        "radial velocity",
        "radial velocities",
        "rv",
        "systemic velocity",
    ),
    "INCL": (
        "inclination",
        "orbital inclination",
        "spin inclination",
    ),
    "<Bl>": (
        "mean longitudinal magnetic field",
        "longitudinal magnetic field",
        "magnetic field",
        "spectropolar",
        "b_l",
        "bz",
    ),
}

JOURNAL_PREFIXES: tuple[tuple[str, str], ...] = (
    ("A&A", "J/A+A"),
    ("ApJ", "J/ApJ"),
    ("AJ", "J/AJ"),
    ("MNRAS", "J/MNRAS"),
    ("ApJS", "J/ApJS"),
    ("PASP", "J/PASP"),
)

USER_AGENT = "Mozilla/5.0 (compatible; TargetInfoSearch/1.0)"


def fetch_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8", errors="replace")


def fetch_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=120) as response:
        return response.read()


def extract_arxiv_id(text: str) -> str | None:
    match = re.search(r"arXiv:(\d{4}\.\d{4,5}(?:v\d+)?)", text)
    if match is None:
        return None
    return match.group(1)


def safe_extract_tar(archive_path: Path, destination: Path) -> list[str]:
    extracted: list[str] = []
    with tarfile.open(archive_path) as archive:
        for member in archive.getmembers():
            member_path = destination / member.name
            resolved_destination = destination.resolve()
            resolved_member = member_path.resolve()
            if resolved_destination not in resolved_member.parents and resolved_member != resolved_destination:
                continue
            archive.extract(member, destination)
            extracted.append(member.name)
    return extracted


def sanitize_target_name(name: str) -> str:
    return re.sub(r"[\\/:*?\"<>|]+", "_", name).strip() or "unknown-target"


def default_asset_dir(json_path: Path, target_name: str) -> Path:
    return json_path.parent / sanitize_target_name(target_name)


def default_output_markdown(json_path: Path, target_name: str) -> Path:
    safe_name = sanitize_target_name(target_name)
    return json_path.parent / f"{safe_name}_extrapar+.md"


def extract_numbers(line: str) -> list[str]:
    normalized = line.replace("\\,", "")
    math_spans = re.findall(r"\$([^$]+)\$", normalized)
    if math_spans:
        numbers: list[str] = []
        for span in math_spans[1:]:
            if any(char.isdigit() for char in span):
                numbers.extend(re.findall(r"[+-]?\d+(?:\.\d+)?", span))
        if numbers:
            return numbers
    return re.findall(r"[+-]?\d+(?:\.\d+)?", normalized)


def find_target_table_blocks(tex_content: str, target_name: str) -> list[str]:
    blocks = re.findall(r"\\begin\{table\*?\}(.*?)\\end\{table\*?\}",
                        tex_content,
                        flags=re.DOTALL)
    normalized_target = re.sub(r"\W+", "", target_name).lower()
    matched_blocks: list[str] = []
    for block in blocks:
        normalized_block = re.sub(r"\W+", "", block).lower()
        if normalized_target not in normalized_block:
            continue
        if "Orbital and physical parameters derived" not in block and "Analysis of disentangled spectra" not in block:
            continue
        matched_blocks.append(block)
    return matched_blocks


def parse_disentangled_table(
    block: str,
    bibcode: str,
) -> list[dict[str, str]]:
    measurements: list[dict[str, str]] = []
    current_section = ""
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if "From fitting synthetic spectra" in line:
            current_section = "From fitting synthetic spectra"
            continue
        if "From spectral disentangling" in line:
            current_section = "From spectral disentangling"
            continue
        if "Initial estimate from restricted fitting" in line:
            current_section = "Initial estimate from restricted fitting"
            continue
        if "Analysis of disentangled spectra" in line:
            current_section = "Analysis of disentangled spectra"
            continue

        numbers = extract_numbers(line)
        if not numbers:
            continue

        if current_section == "From fitting synthetic spectra" and "$P\\,(\\mathrm{days})$" in line and len(
                numbers) >= 2:
            measurements.append({
                "parameter": "Period (orbital)",
                "component": "system",
                "value": numbers[0],
                "uncertainty": numbers[1],
                "unit": "d",
                "method": "Keplerian orbit from synthetic spectra",
                "source_bibcode": bibcode,
                "source_location":
                "Table fundparams1, From fitting synthetic spectra",
                "notes": "SB2 orbital period",
            })
        elif current_section == "From fitting synthetic spectra" and "$\\gamma\\,(\\mathrm{km\\,s}^{-1})$" in line and len(
                numbers) >= 2:
            measurements.append({
                "parameter": "RV (systemic gamma)",
                "component": "system",
                "value": numbers[0],
                "uncertainty": numbers[1],
                "unit": "km s^-1",
                "method": "Keplerian orbit from synthetic spectra",
                "source_bibcode": bibcode,
                "source_location":
                "Table fundparams1, From fitting synthetic spectra",
                "notes": "Systemic radial velocity",
            })
        elif current_section == "From fitting synthetic spectra" and "$K\\,(\\mathrm{km\\,s}^{-1})$" in line and len(
                numbers) >= 4:
            measurements.extend([
                {
                    "parameter": "RV (semi-amplitude K)",
                    "component": "A",
                    "value": numbers[0],
                    "uncertainty": numbers[1],
                    "unit": "km s^-1",
                    "method": "Keplerian orbit from synthetic spectra",
                    "source_bibcode": bibcode,
                    "source_location":
                    "Table fundparams1, From fitting synthetic spectra",
                    "notes": "Primary RV semi-amplitude",
                },
                {
                    "parameter": "RV (semi-amplitude K)",
                    "component": "B",
                    "value": numbers[2],
                    "uncertainty": numbers[3],
                    "unit": "km s^-1",
                    "method": "Keplerian orbit from synthetic spectra",
                    "source_bibcode": bibcode,
                    "source_location":
                    "Table fundparams1, From fitting synthetic spectra",
                    "notes": "Secondary RV semi-amplitude",
                },
            ])
        elif current_section == "From fitting synthetic spectra" and "$\\mathcal{M}\\sin^3 i_\\mathrm{orb}\\,(\\mathcal{M}_{\\sun})$" in line and len(
                numbers) >= 4:
            measurements.extend([
                {
                    "parameter": "Mass sin^3(i_orb)",
                    "component": "A",
                    "value": numbers[0],
                    "uncertainty": numbers[1],
                    "unit": "Msun",
                    "method": "Spectroscopic orbit",
                    "source_bibcode": bibcode,
                    "source_location":
                    "Table fundparams1, From fitting synthetic spectra",
                    "notes": "Lower-limit spectroscopic mass",
                },
                {
                    "parameter": "Mass sin^3(i_orb)",
                    "component": "B",
                    "value": numbers[2],
                    "uncertainty": numbers[3],
                    "unit": "Msun",
                    "method": "Spectroscopic orbit",
                    "source_bibcode": bibcode,
                    "source_location":
                    "Table fundparams1, From fitting synthetic spectra",
                    "notes": "Lower-limit spectroscopic mass",
                },
            ])
        elif current_section == "Analysis of disentangled spectra" and "$T_\\mathrm{eff}\\,(\\mathrm{K})$" in line and len(
                numbers) >= 4:
            measurements.extend([
                {
                    "parameter": "Teff",
                    "component": "A",
                    "value": numbers[0],
                    "uncertainty": numbers[1],
                    "unit": "K",
                    "method": "Analysis of disentangled spectra",
                    "source_bibcode": bibcode,
                    "source_location":
                    "Table fundparams1, Analysis of disentangled spectra",
                    "notes": "Final spectroscopic Teff",
                },
                {
                    "parameter": "Teff",
                    "component": "B",
                    "value": numbers[2],
                    "uncertainty": numbers[3],
                    "unit": "K",
                    "method": "Analysis of disentangled spectra",
                    "source_bibcode": bibcode,
                    "source_location":
                    "Table fundparams1, Analysis of disentangled spectra",
                    "notes": "Final spectroscopic Teff",
                },
            ])
        elif current_section == "Analysis of disentangled spectra" and "$\\log g\\,\\mathrm{(cgs)}$" in line and len(
                numbers) >= 4:
            measurements.extend([
                {
                    "parameter": "log g",
                    "component": "A",
                    "value": numbers[0],
                    "uncertainty": numbers[1],
                    "unit": "cgs",
                    "method": "Analysis of disentangled spectra",
                    "source_bibcode": bibcode,
                    "source_location":
                    "Table fundparams1, Analysis of disentangled spectra",
                    "notes": "Final spectroscopic log g",
                },
                {
                    "parameter": "log g",
                    "component": "B",
                    "value": numbers[2],
                    "uncertainty": numbers[3],
                    "unit": "cgs",
                    "method": "Analysis of disentangled spectra",
                    "source_bibcode": bibcode,
                    "source_location":
                    "Table fundparams1, Analysis of disentangled spectra",
                    "notes": "Final spectroscopic log g",
                },
            ])
        elif current_section == "Analysis of disentangled spectra" and "$v \\sin i_\\mathrm{rot}\\,(\\mathrm{km\\,s}^{-1})$" in line and len(
                numbers) >= 4:
            measurements.extend([
                {
                    "parameter": "vsini",
                    "component": "A",
                    "value": numbers[0],
                    "uncertainty": numbers[1],
                    "unit": "km s^-1",
                    "method": "Analysis of disentangled spectra",
                    "source_bibcode": bibcode,
                    "source_location":
                    "Table fundparams1, Analysis of disentangled spectra",
                    "notes": "Projected rotational velocity",
                },
                {
                    "parameter": "vsini",
                    "component": "B",
                    "value": numbers[2],
                    "uncertainty": numbers[3],
                    "unit": "km s^-1",
                    "method": "Analysis of disentangled spectra",
                    "source_bibcode": bibcode,
                    "source_location":
                    "Table fundparams1, Analysis of disentangled spectra",
                    "notes": "Projected rotational velocity",
                },
            ])
    return measurements


def augment_with_text_measurements(
    tex_content: str,
    bibcode: str,
    orbital_period_days: float | None,
) -> list[dict[str, str]]:
    measurements: list[dict[str, str]] = []
    radius_match = re.search(r"median radius of \$([0-9.]+)\\,R_\{\\sun\}\$",
                             tex_content)
    i_rot_match = re.search(
        r"\$i_\\mathrm\{rot\}\$ of \$\\sim([0-9.]+)\\degr\$", tex_content)
    mass_match = re.search(
        r"median mass of \$([0-9.]+)\\,\\mathcal\{M\}_\{\\sun\}\$",
        tex_content)
    i_orb_match = re.search(
        r"\$i_\\mathrm\{orb\}\$ of \$\\sim([0-9.]+)\\degr\$", tex_content)
    if radius_match is not None and i_rot_match is not None and mass_match is not None and i_orb_match is not None:
        radius_value = radius_match.group(1)
        i_rot_value = i_rot_match.group(1)
        mass_value = mass_match.group(1)
        i_orb_value = i_orb_match.group(1)
        measurements.extend([
            {
                "parameter":
                "Mass",
                "component":
                "A",
                "value":
                mass_value,
                "uncertainty":
                "",
                "unit":
                "Msun",
                "method":
                "Seismic/tidal interpretation model comparison",
                "source_bibcode":
                bibcode,
                "source_location":
                "Text near pulsationcheck1 discussion",
                "notes":
                f"Median model mass; associated median radius {radius_value} Rsun",
            },
            {
                "parameter":
                "INCL",
                "component":
                "A (rotation axis)",
                "value":
                i_rot_value,
                "uncertainty":
                "",
                "unit":
                "deg",
                "method":
                "Model comparison using vsini and candidate rotation frequency",
                "source_bibcode":
                bibcode,
                "source_location":
                "Text near pulsationcheck1 discussion",
                "notes":
                "Approximate i_rot from preferred f_rot=(7/6) f_SB2 interpretation",
            },
            {
                "parameter": "INCL",
                "component": "system (orbital)",
                "value": i_orb_value,
                "uncertainty": "",
                "unit": "deg",
                "method":
                "Model comparison using median mass and M sin^3(i_orb)",
                "source_bibcode": bibcode,
                "source_location": "Text near pulsationcheck1 discussion",
                "notes": "Approximate i_orb estimate",
            },
        ])

    if orbital_period_days is not None:
        rotation_period = orbital_period_days * 6.0 / 7.0
        measurements.append({
            "parameter":
            "Period (rotation candidate)",
            "component":
            "A",
            "value":
            f"{rotation_period:.3f}",
            "uncertainty":
            "",
            "unit":
            "d",
            "method":
            "Derived from preferred f_rot=(7/6) f_SB2 text interpretation",
            "source_bibcode":
            bibcode,
            "source_location":
            "Text near pulsationcheck1 discussion",
            "notes":
            "Indirect candidate rotation period; paper states no direct rotational modulation detection",
        })

    return measurements


def collect_local_measurements(
    asset_dir: Path,
    target_name: str,
    ranked: list[dict[str, Any]],
) -> list[dict[str, str]]:
    preferred_bibcode = ranked[0]["bibcode"] if ranked else "unknown"
    measurements: list[dict[str, str]] = []
    seen_rows: set[tuple[str, str, str, str, str]] = set()
    orbital_period_days: float | None = None
    for tex_path in sorted(asset_dir.glob("*.tex")):
        tex_content = tex_path.read_text(encoding="utf-8", errors="replace")
        matching_blocks = find_target_table_blocks(tex_content, target_name)
        if not matching_blocks:
            continue
        for block in matching_blocks:
            block_measurements = parse_disentangled_table(
                block, preferred_bibcode)
            for item in block_measurements:
                row_key = (
                    item["parameter"],
                    item["component"],
                    item["value"],
                    item["uncertainty"],
                    item["source_location"],
                )
                if row_key in seen_rows:
                    continue
                seen_rows.add(row_key)
                measurements.append(item)
                if item["parameter"] == "Period (orbital)":
                    orbital_period_days = float(item["value"])
        for item in augment_with_text_measurements(tex_content,
                                                   preferred_bibcode,
                                                   orbital_period_days):
            row_key = (
                item["parameter"],
                item["component"],
                item["value"],
                item["uncertainty"],
                item["source_location"],
            )
            if row_key in seen_rows:
                continue
            seen_rows.add(row_key)
            measurements.append(item)

    unique_measurements: list[dict[str, str]] = []
    final_seen: set[tuple[str, str, str, str, str]] = set()
    for item in measurements:
        row_key = (
            item["parameter"],
            item["component"],
            item["value"],
            item["uncertainty"],
            item["source_location"],
        )
        if row_key in final_seen:
            continue
        final_seen.add(row_key)
        unique_measurements.append(item)
    return unique_measurements


def not_found_rows(ranked: list[dict[str, Any]]) -> list[dict[str, str]]:
    primary_bibcode = ranked[0]["bibcode"] if ranked else "unknown"
    return [
        {
            "parameter":
            "<Bl>",
            "status":
            "not found",
            "checked_source":
            primary_bibcode,
            "notes":
            "No mean longitudinal magnetic field measurement identified in the locally reviewed paper source or reference metadata.",
        },
    ]


def render_parameter_markdown(
    metadata: dict[str, Any],
    ranked: list[dict[str, Any]],
    measurements: list[dict[str, str]],
    missing: list[dict[str, str]],
    asset_dir: Path,
) -> str:
    lines: list[str] = []
    lines.append(f"# {metadata['query_target']} extrapar+")
    lines.append("")
    lines.append(f"Generated at: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"Target: {metadata['query_target']}")
    lines.append(f"Primary name: {metadata['object_name']}")
    lines.append(f"Asset directory: {asset_dir}")
    lines.append("")
    lines.append("## Reviewed references")
    lines.append("")
    for item in ranked[:5]:
        lines.append(f"- {item['bibcode']}: {item['title']}")
    lines.append("")
    lines.append("## Parameter table")
    lines.append("")
    lines.append(
        "| Parameter | Component | Value | Uncertainty | Unit | Method | Source bibcode | Source location | Notes |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for item in measurements:
        lines.append(
            "| {parameter} | {component} | {value} | {uncertainty} | {unit} | {method} | {source_bibcode} | {source_location} | {notes} |"
            .format(**item, ))
    lines.append("")
    lines.append("## Not found after checked sources")
    lines.append("")
    lines.append("| Parameter | Status | Checked source | Notes |")
    lines.append("|---|---|---|---|")
    for item in missing:
        lines.append(
            f"| {item['parameter']} | {item['status']} | {item['checked_source']} | {item['notes']} |"
        )
    lines.append("")
    lines.append("## Stored assets")
    lines.append("")
    for child in sorted(asset_dir.iterdir()):
        lines.append(f"- {child.name}")
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- The original target report markdown was left unchanged.")
    lines.append(
        "- Values tagged as approximate or candidate come from narrative interpretation in the source text, not from a formal parameter table."
    )
    return "\n".join(lines)


def save_reference_assets(
    ranked: list[dict[str, Any]],
    asset_dir: Path,
) -> None:
    asset_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict[str, Any]] = {}
    for item in ranked[:3]:
        bibcode = item["bibcode"]
        record: dict[str, Any] = {
            "ads": item["ads"],
            "vizier_catalog": item["vizier_catalog"],
            "arxiv": item["arxiv"],
        }
        ads_html_path = asset_dir / f"{bibcode}_ads_abstract.html"
        if not ads_html_path.exists():
            ads_html_path.write_text(fetch_text(item["ads"]), encoding="utf-8")
        ads_html = ads_html_path.read_text(encoding="utf-8", errors="replace")
        record["ads_html"] = ads_html_path.name

        arxiv_id = extract_arxiv_id(ads_html)
        if arxiv_id:
            record["arxiv_id"] = arxiv_id
            source_tar_path = asset_dir / f"{bibcode}_source.tar"
            if not source_tar_path.exists():
                source_tar_path.write_bytes(
                    fetch_bytes(f"https://arxiv.org/e-print/{arxiv_id}"))
            record["source_tar"] = source_tar_path.name
            extracted = safe_extract_tar(source_tar_path, asset_dir)
            if extracted:
                record["extracted_files"] = extracted[:50]

        vizier_url = item["vizier_catalog"] or item["vizier_target_search"]
        if vizier_url:
            vizier_path = asset_dir / f"{bibcode}_vizier.html"
            if not vizier_path.exists():
                vizier_path.write_text(fetch_text(vizier_url),
                                       encoding="utf-8")
            record["vizier_html"] = vizier_path.name

        manifest[bibcode] = record

    manifest_path = asset_dir / "asset_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2,
                                        ensure_ascii=False),
                             encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(
        "Rank references in a target JSON file and print ADS, VizieR, "
        "and arXiv search hints for parameter hunting."))
    parser.add_argument("json_path",
                        type=Path,
                        help="Path to one results/*.json file")
    parser.add_argument(
        "--top",
        type=int,
        default=8,
        help="Maximum number of ranked references to print",
    )
    parser.add_argument(
        "--parameters",
        nargs="*",
        default=[],
        help="Optional list of parameter names to prioritize",
    )
    parser.add_argument(
        "--write-extrapar-markdown",
        action="store_true",
        help=
        "Write an independent target parameter markdown named <target>_extrapar+.md",
    )
    parser.add_argument(
        "--download-assets",
        action="store_true",
        help=
        "Download ADS/arXiv/VizieR assets into results/<target>/ before extraction",
    )
    parser.add_argument(
        "--asset-dir",
        type=Path,
        default=None,
        help=
        "Override asset download directory; default is results/<target>/ next to the JSON file",
    )
    parser.add_argument(
        "--output-markdown",
        type=Path,
        default=None,
        help=
        "Override the output markdown path; default is results/<target>_extrapar+.md",
    )
    return parser.parse_args()


def load_payload(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def normalize_parameter_name(name: str) -> str:
    lowered = name.strip().lower()
    aliases = {
        "period": "Period",
        "mass": "Mass",
        "teff": "Teff",
        "effective temperature": "Teff",
        "logg": "log g",
        "log g": "log g",
        "vsini": "vsini",
        "v sin i": "vsini",
        "rv": "RV",
        "radial velocity": "RV",
        "incl": "INCL",
        "inclination": "INCL",
        "<bl>": "<Bl>",
        "bl": "<Bl>",
        "bz": "<Bl>",
        "magnetic field": "<Bl>",
    }
    return aliases.get(lowered, name)


def extract_target_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    target = payload.get("target", {})
    simbad = target.get("simbad", {})
    return {
        "query_target":
        target.get("query_target") or payload.get("query_target") or "unknown",
        "object_name":
        simbad.get("object_name") or "unknown",
        "identifiers":
        simbad.get("identifiers") or [],
        "references":
        simbad.get("references") or [],
    }


def text_blob(reference: dict[str, Any]) -> str:
    keywords = reference.get("keywords") or []
    keyword_text = " ".join(str(item) for item in keywords)
    parts = [
        reference.get("title") or "",
        reference.get("abstract") or "", keyword_text
    ]
    return " ".join(parts).lower()


def safe_obj_freq(reference: dict[str, Any]) -> int:
    value = reference.get("obj_freq")
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def parameter_hits(reference: dict[str, Any]) -> dict[str, int]:
    blob = text_blob(reference)
    hits: dict[str, int] = {}
    for parameter, patterns in PARAMETER_PATTERNS.items():
        count = sum(1 for pattern in patterns if pattern in blob)
        if count:
            hits[parameter] = count
    return hits


def rank_reference(reference: dict[str, Any],
                   prioritized: set[str]) -> tuple[int, dict[str, int]]:
    hits = parameter_hits(reference)
    score = safe_obj_freq(reference) * 10
    score += sum(hits.values()) * 3
    if prioritized:
        score += sum(hits.get(name, 0) for name in prioritized) * 6

    title = str(reference.get("title") or "").lower()
    abstract = str(reference.get("abstract") or "").lower()
    if "spectroscop" in title or "spectroscop" in abstract:
        score += 4
    if "binary" in title or "binary" in abstract:
        score += 2
    if "magnetic" in title or "magnetic" in abstract:
        score += 2
    if "asteroseism" in title or "asteroseism" in abstract:
        score += 2
    return score, hits


def ads_url(bibcode: str) -> str:
    return f"https://ui.adsabs.harvard.edu/abs/{quote_plus(bibcode)}/abstract"


def arxiv_url(title: str, target_terms: list[str]) -> str:
    terms = [title.strip()] + [term for term in target_terms if term.strip()]
    query = " OR ".join(f'"{term}"' for term in terms[:4] if term)
    return (
        "https://arxiv.org/search/?query="
        f"{quote_plus(query)}&searchtype=all&abstracts=show&order=-announced_date_first&size=50"
    )


def parse_vizier_catalog_code(reference: dict[str, Any]) -> str | None:
    bibcode = str(reference.get("bibcode") or "").strip()
    journal = str(reference.get("journal") or "").strip()
    if len(bibcode) < 8:
        return None

    body = bibcode[4:]
    volume_match = re.search(r"(\d{3,4})", body)
    if volume_match is None:
        return None

    volume = volume_match.group(1)
    remainder = body[volume_match.end():].replace(".", "")
    if not remainder:
        return None

    if remainder[-1].isalpha():
        remainder = remainder[:-1]

    article = remainder or None
    if not volume or not article:
        return None

    for journal_name, vizier_prefix in JOURNAL_PREFIXES:
        if journal_name == journal:
            return f"{vizier_prefix}/{volume}/{article}"
    return None


def vizier_urls(reference: dict[str, Any],
                target_terms: list[str]) -> tuple[str | None, str]:
    catalog_code = parse_vizier_catalog_code(reference)
    catalog_url = None
    if catalog_code:
        catalog_url = f"https://vizier.cds.unistra.fr/viz-bin/VizieR?-source={quote_plus(catalog_code)}"
    target_query = target_terms[0] if target_terms else str(
        reference.get("title") or "")
    search_url = ("https://vizier.cds.unistra.fr/viz-bin/VizieR?-c="
                  f"{quote_plus(target_query)}&-c.rs=5")
    return catalog_url, search_url


def summarize_reference(
    reference: dict[str, Any],
    prioritized: set[str],
    target_terms: list[str],
) -> dict[str, Any]:
    score, hits = rank_reference(reference, prioritized)
    title = str(reference.get("title") or "").strip()
    bibcode = str(reference.get("bibcode") or "N/A").strip()
    catalog_url, target_search_url = vizier_urls(reference, target_terms)
    return {
        "bibcode": bibcode,
        "year": str(reference.get("year") or "").strip(),
        "journal": str(reference.get("journal") or "").strip(),
        "title": title,
        "obj_freq": safe_obj_freq(reference),
        "score": score,
        "hits": hits,
        "ads": ads_url(bibcode),
        "arxiv": arxiv_url(title, target_terms),
        "vizier_catalog": catalog_url,
        "vizier_target_search": target_search_url,
    }


def render(metadata: dict[str, Any], ranked: list[dict[str, Any]],
           prioritized: list[str]) -> str:
    lines: list[str] = []
    lines.append(f"# Literature Hunt: {metadata['query_target']}")
    lines.append("")
    lines.append(f"- Primary name: {metadata['object_name']}")
    lines.append(
        f"- Aliases: {', '.join(metadata['identifiers'][:8]) if metadata['identifiers'] else 'none'}"
    )
    lines.append(
        f"- Prioritized parameters: {', '.join(prioritized) if prioritized else 'all default parameters'}"
    )
    lines.append("")
    lines.append("## Ranked references")
    lines.append("")
    for index, item in enumerate(ranked, start=1):
        hit_text = ", ".join(f"{name} x{count}"
                             for name, count in sorted(item["hits"].items()))
        lines.append(f"### {index}. {item['bibcode']} | score {item['score']}")
        lines.append(f"- Title: {item['title']}")
        lines.append(f"- Journal: {item['journal']} {item['year']}")
        lines.append(f"- obj_freq: {item['obj_freq']}")
        lines.append(f"- Parameter hits: {hit_text if hit_text else 'none'}")
        lines.append(f"- ADS: {item['ads']}")
        if item["vizier_catalog"]:
            lines.append(f"- VizieR catalog guess: {item['vizier_catalog']}")
        lines.append(f"- VizieR target search: {item['vizier_target_search']}")
        lines.append(f"- arXiv search: {item['arxiv']}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    payload = load_payload(args.json_path)
    metadata = extract_target_metadata(payload)
    prioritized = [normalize_parameter_name(name) for name in args.parameters]
    prioritized_set = {
        name
        for name in prioritized if name in PARAMETER_PATTERNS
    }

    target_terms = [metadata["query_target"], metadata["object_name"]]
    target_terms.extend(str(item) for item in metadata["identifiers"][:6])

    summaries = [
        summarize_reference(reference, prioritized_set, target_terms)
        for reference in metadata["references"]
    ]
    ranked = sorted(
        summaries,
        key=lambda item: (item["score"], item["obj_freq"], item["year"]),
        reverse=True,
    )[:max(1, args.top)]
    output = render(metadata, ranked, prioritized)

    if args.write_extrapar_markdown:
        asset_dir = args.asset_dir or default_asset_dir(
            args.json_path, metadata["query_target"])
        asset_dir.mkdir(parents=True, exist_ok=True)
        if args.download_assets:
            save_reference_assets(ranked, asset_dir)
        measurements = collect_local_measurements(asset_dir,
                                                  metadata["query_target"],
                                                  ranked)
        missing = not_found_rows(ranked)
        markdown_text = render_parameter_markdown(
            metadata=metadata,
            ranked=ranked,
            measurements=measurements,
            missing=missing,
            asset_dir=asset_dir,
        )
        output_markdown = args.output_markdown or default_output_markdown(
            args.json_path, metadata["query_target"])
        output_markdown.write_text(markdown_text, encoding="utf-8")
        output = f"{output}\n\nExtra parameter markdown written to: {output_markdown}\nAssets stored in: {asset_dir}"

    print(output)


if __name__ == "__main__":
    main()
