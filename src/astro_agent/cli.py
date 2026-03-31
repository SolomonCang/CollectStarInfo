from __future__ import annotations

import argparse
from collections import Counter
import json
import re
from datetime import datetime
from pathlib import Path

from .agent import TargetInfoAgent
from .clients.deepseek_client import DeepSeekClient
from .config import load_settings
from .models import TargetResult
from .utils import parse_targets


def _safe_target_filename(target: str) -> str:
    # Keep human-readable names while removing path/OS-invalid characters.
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", target).strip()
    return safe or "unknown_target"


def _write_json(path: Path, result: TargetResult) -> None:
    payload = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "target": result.to_dict(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def _summarize_reference_years(
    references: list[dict[str, str | list[str]]], ) -> list[tuple[str, int]]:
    year_counts = Counter()
    for ref in references:
        raw_year = ref.get("year")
        year = str(raw_year).strip() if raw_year is not None else "Unknown"
        year_counts[year or "Unknown"] += 1

    numeric_years = sorted(
        ((int(year), count)
         for year, count in year_counts.items() if year.isdigit()),
        reverse=True,
    )
    other_years = sorted(
        ((year, count)
         for year, count in year_counts.items() if not year.isdigit()),
        key=lambda item: item[0],
    )
    return [(str(year), count) for year, count in numeric_years] + other_years


def _write_markdown(path: Path, item: TargetResult) -> None:
    lines: list[str] = ["# Astronomy Target Search Report", ""]
    lines.append(f"Generated at: {datetime.utcnow().isoformat()}Z")
    lines.append("")
    lines.append(f"## {item.target}")
    lines.append("")

    if item.simbad is not None:
        lines.append("### SIMBAD")
        lines.append(f"- Object: {item.simbad.object_name}")
        lines.append(f"- RA (deg): {item.simbad.ra_deg}")
        lines.append(f"- DEC (deg): {item.simbad.dec_deg}")
        lines.append(f"- Spectral type: {item.simbad.spectral_type}")
        lines.append(f"- References count: {len(item.simbad.references)}")
        if item.simbad.references:
            lines.append("- References by year:")
            for year, count in _summarize_reference_years(
                    item.simbad.references):
                lines.append(f"  - {year}: {count}")
    else:
        lines.append("### SIMBAD")
        lines.append("- No result")

    lines.append("")
    if item.gaia is not None:
        lines.append("### Gaia")
        lines.append(f"- Source ID: {item.gaia.source_id}")
        lines.append(f"- Gmag: {item.gaia.gmag}")
        lines.append(f"- Parallax (mas): {item.gaia.parallax_mas}")
        lines.append(f"- Parallax error (mas): {item.gaia.parallax_error_mas}")
        lines.append(f"- Distance (pc): {item.gaia.distance_pc}")
        lines.append(f"- Distance error (pc): {item.gaia.distance_error_pc}")
    else:
        lines.append("### Gaia")
        lines.append("- No result")

    lines.append("")
    if item.mast is not None:
        lines.append("### MAST")
        lines.append(
            f"- TIC IDs: {', '.join(item.mast.tic_ids) if item.mast.tic_ids else 'None'}"
        )
        lines.append(
            f"- EPIC IDs: {', '.join(item.mast.epic_ids) if item.mast.epic_ids else 'None'}"
        )
        lines.append(
            f"- KIC IDs: {', '.join(item.mast.kic_ids) if item.mast.kic_ids else 'None'}"
        )
        lines.append(
            f"- Regional mission coverage radius (deg): {item.mast.region_radius_deg}"
        )
        lines.append(
            f"- Total mission observations in region: {item.mast.total_mission_observations}"
        )
        if item.mast.mission_observations:
            lines.append("- Mission observation counts in region:")
            for mission, count in item.mast.mission_observations.items():
                info = item.mast.mission_time_info.get(mission, "")
                suffix = f"  ({info})" if info else ""
                lines.append(f"  - {mission}: {count}{suffix}")
    else:
        lines.append("### MAST")
        lines.append("- No result")

    lines.append("")
    if item.literature_workflow is not None:
        lines.append("### Literature Workflow")
        lines.append(
            f"- Analysis order: {' -> '.join(item.literature_workflow.analysis_order)}"
        )
        lines.append(
            f"- obj_freq threshold: {item.literature_workflow.min_obj_freq}")
        lines.append(
            f"- References analyzed: {item.literature_workflow.references_analyzed}/{item.literature_workflow.total_references}"
        )
        if item.literature_workflow.overview:
            lines.append(f"- Overview: {item.literature_workflow.overview}")
        if item.literature_workflow.observations:
            lines.append("- Observations inferred from references:")
            for summary in item.literature_workflow.observations:
                evidence = ", ".join(
                    f"{source}={count}"
                    for source, count in summary.evidence_by_source.items())
                lines.append(
                    f"  - {summary.category}: {summary.count} refs ({evidence})"
                )
                if summary.sample_references:
                    lines.append("    Sample references:")
                    for sample in summary.sample_references:
                        lines.append(f"      - {sample}")
        if item.literature_workflow.research_topics:
            lines.append("- Research topics inferred from references:")
            for summary in item.literature_workflow.research_topics:
                evidence = ", ".join(
                    f"{source}={count}"
                    for source, count in summary.evidence_by_source.items())
                lines.append(
                    f"  - {summary.category}: {summary.count} refs ({evidence})"
                )
                if summary.sample_references:
                    lines.append("    Sample references:")
                    for sample in summary.sample_references:
                        lines.append(f"      - {sample}")
        lines.append("")

    lines.append("")
    lines.append("### Summary")
    lines.append(item.summary or "- LLM summary skipped or unavailable")
    lines.append("")

    if item.notes:
        lines.append("### Notes")
        for note in item.notes:
            lines.append(f"- {note}")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def _write_text(path: Path, item: TargetResult) -> None:
    # Plain-text output mirrors markdown content for easy viewing in terminals.
    lines: list[str] = ["Astronomy Target Search Report", ""]
    lines.append(f"Generated at: {datetime.utcnow().isoformat()}Z")
    lines.append("")
    lines.append(f"Target: {item.target}")
    lines.append("")

    if item.simbad is not None:
        lines.append("SIMBAD")
        lines.append(f"- Object: {item.simbad.object_name}")
        lines.append(f"- RA (deg): {item.simbad.ra_deg}")
        lines.append(f"- DEC (deg): {item.simbad.dec_deg}")
        lines.append(f"- Spectral type: {item.simbad.spectral_type}")
        lines.append(f"- References count: {len(item.simbad.references)}")
    else:
        lines.append("SIMBAD")
        lines.append("- No result")

    lines.append("")
    if item.gaia is not None:
        lines.append("Gaia")
        lines.append(f"- Source ID: {item.gaia.source_id}")
        lines.append(f"- Gmag: {item.gaia.gmag}")
        lines.append(f"- Parallax (mas): {item.gaia.parallax_mas}")
        lines.append(f"- Parallax error (mas): {item.gaia.parallax_error_mas}")
        lines.append(f"- Distance (pc): {item.gaia.distance_pc}")
        lines.append(f"- Distance error (pc): {item.gaia.distance_error_pc}")
    else:
        lines.append("Gaia")
        lines.append("- No result")

    lines.append("")
    if item.mast is not None:
        lines.append("MAST")
        lines.append(
            f"- TIC IDs: {', '.join(item.mast.tic_ids) if item.mast.tic_ids else 'None'}"
        )
        lines.append(
            f"- EPIC IDs: {', '.join(item.mast.epic_ids) if item.mast.epic_ids else 'None'}"
        )
        lines.append(
            f"- KIC IDs: {', '.join(item.mast.kic_ids) if item.mast.kic_ids else 'None'}"
        )
        lines.append(
            f"- Regional mission coverage radius (deg): {item.mast.region_radius_deg}"
        )
        lines.append(
            f"- Total mission observations in region: {item.mast.total_mission_observations}"
        )
    else:
        lines.append("MAST")
        lines.append("- No result")

    lines.append("")
    lines.append("Summary")
    lines.append(item.summary or "- LLM summary skipped or unavailable")

    if item.notes:
        lines.append("")
        lines.append("Notes")
        for note in item.notes:
            lines.append(f"- {note}")

    path.write_text("\n".join(lines), encoding="utf-8")


def build_parser(defaults) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=
        "Astronomy target information search and summarization agent", )
    default_targets = ",".join(defaults.default_targets)
    parser.add_argument("--targets",
                        type=str,
                        default=(default_targets if default_targets else None),
                        help="Comma-separated target names")
    parser.add_argument("--targets-file",
                        type=str,
                        default=defaults.default_targets_file,
                        help="TXT/CSV file for target names")
    parser.add_argument("--output-dir",
                        type=str,
                        default=defaults.default_output_dir,
                        help="Output directory")
    parser.add_argument("--format",
                        choices=["json", "md", "txt", "both", "all"],
                        default=defaults.default_output_format)
    parser.set_defaults(use_llm=defaults.default_use_llm)
    parser.add_argument("--use-llm",
                        dest="use_llm",
                        action="store_true",
                        help="Enable DeepSeek summarization")
    parser.add_argument("--no-llm",
                        dest="use_llm",
                        action="store_false",
                        help="Disable DeepSeek summarization")
    parser.add_argument("--config",
                        type=str,
                        default=None,
                        help="Custom config.yaml path")
    parser.add_argument("--dotenv",
                        type=str,
                        default=defaults.default_dotenv_path,
                        help="Custom .env path")
    parser.add_argument("--cone-radius-arcsec",
                        type=float,
                        default=defaults.default_gaia_cone_radius_arcsec,
                        help="Gaia cone search radius")
    parser.add_argument("--mast-radius-deg",
                        type=float,
                        default=defaults.default_mast_radius_deg,
                        help="MAST regional search radius in degrees")
    parser.add_argument(
        "--simbad-reference-time-range",
        choices=["all", "recent10"],
        default=defaults.default_simbad_reference_time_range,
        help="Reference coverage mode: all papers or only recent 10 years",
    )
    parser.add_argument(
        "--literature-min-obj-freq",
        type=int,
        default=defaults.default_literature_min_obj_freq,
        help=(
            "Minimum SIMBAD obj_freq used by literature workflow analysis; "
            "references below this threshold are excluded from topic inference"
        ),
    )
    return parser


def main() -> None:
    bootstrap_parser = argparse.ArgumentParser(add_help=False)
    bootstrap_parser.add_argument("--config", type=str, default=None)
    bootstrap_parser.add_argument("--dotenv", type=str, default=None)
    bootstrap_args, _ = bootstrap_parser.parse_known_args()

    defaults = load_settings(
        dotenv_path=bootstrap_args.dotenv,
        config_path=bootstrap_args.config,
    )

    parser = build_parser(defaults)
    args = parser.parse_args()

    targets = parse_targets(args.targets, args.targets_file)
    if not targets:
        raise ValueError(
            "No targets provided. Use --targets or --targets-file")

    settings = load_settings(
        dotenv_path=args.dotenv,
        config_path=args.config,
    )

    deepseek_client = None
    use_llm = args.use_llm
    if use_llm and settings.deepseek_api_key:
        deepseek_client = DeepSeekClient(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
            timeout_sec=settings.timeout_sec,
        )

    agent = TargetInfoAgent(
        gaia_cone_radius_arcsec=args.cone_radius_arcsec,
        mast_radius_deg=args.mast_radius_deg,
        simbad_reference_time_range=args.simbad_reference_time_range,
        literature_min_obj_freq=args.literature_min_obj_freq,
        deepseek_client=deepseek_client,
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[batch] incremental save enabled, total_targets={len(targets)}")
    for index, target in enumerate(targets, start=1):
        print(f"[batch] processing {index}/{len(targets)}: {target}")
        item = agent.run_target(target, use_llm=use_llm)
        base_name = _safe_target_filename(item.target)
        json_path = output_dir / f"{base_name}.json"
        md_path = output_dir / f"{base_name}.md"
        txt_path = output_dir / f"{base_name}.txt"

        if args.format in {"json", "both", "all"}:
            _write_json(json_path, item)
            print(f"JSON saved: {json_path}")

        if args.format in {"md", "both", "all"}:
            _write_markdown(md_path, item)
            print(f"Markdown saved: {md_path}")

        if args.format in {"txt", "all"}:
            _write_text(txt_path, item)
            print(f"Text saved: {txt_path}")

        print(f"[batch] saved outputs for: {item.target}")


if __name__ == "__main__":
    main()
