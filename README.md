# CollectStarInfo

A Python agent-style tool for astronomy target lookup and summarization.

## Features
- Query SIMBAD for object match, coordinates, and spectral type.
- Query Gaia DR3 for G magnitude, parallax, and estimated distance.
- Extract TIC/EPIC/KIC IDs from SIMBAD identifiers and query NASA MAST for observation counts.
- Summarize regional MAST archive coverage by mission (TESS, K2, Kepler, JWST, HST).
- Check JWST/HST observation availability from MAST with configurable regional search radius.
- Summarize multi-source results with DeepSeek API (optional).
- Handle one or multiple targets from CLI args or TXT/CSV file.
- Export JSON and Markdown reports.

## Install
1. Create virtual environment (recommended):
   - macOS/Linux: python3 -m venv .venv && source .venv/bin/activate
2. Install dependencies:
   - pip install -r requirements.txt

## Configure DeepSeek (optional)
1. Copy .env.example to .env
2. Set DEEPSEEK_API_KEY in .env

You can also use `config.yaml` in project root to configure runtime parameters
(DeepSeek API, run switches, output defaults, and agent defaults).
`config.yaml` values take priority over environment variables.

Supported run switches in `config.yaml`:
- `run.use_llm`: default LLM behavior
- `run.targets`: default target list when `--targets` is omitted
- `run.targets_file`: default targets file when `--targets-file` is omitted
- `run.dotenv_path`: default dotenv file path

If no API key is provided, the tool still runs database lookup and skips LLM summary.

## Usage
Run with comma-separated targets:

python run_agent.py --targets "Proxima Centauri,AD Leo"

Run with custom config file:

python run_agent.py --config config.yaml --targets "Proxima Centauri"

Run with target file:

python run_agent.py --targets-file targets_example.txt

Disable LLM summary:

python run_agent.py --targets "Proxima Centauri" --no-llm

Enable LLM summary explicitly (useful when `run.use_llm: false` in config):

python run_agent.py --targets "Proxima Centauri" --use-llm

Custom output options:

python run_agent.py --targets-file targets_example.txt --format both --output-dir results

Customize MAST regional search radius:

python run_agent.py --targets-file targets_example.txt --mast-radius-deg 0.05

## Output
Generated files are placed in results/ with timestamp suffix:
- target_report_YYYYMMDD_HHMMSS.json
- target_report_YYYYMMDD_HHMMSS.md

## Notes
- Gaia query first tries Gaia source id extracted from SIMBAD identifiers.
- If source id is unavailable, the tool falls back to cone search around SIMBAD coordinates.
- Distance is estimated from parallax by d(pc)=1000/parallax(mas).
- MAST identifier counts are queried as mission-aligned collections: TIC->TESS, EPIC->K2, KIC->Kepler.
- Regional mission coverage is counted from a coordinate-based MAST query around the target position.
- JWST/HST checks first use target name, then fall back to coordinate-based regional query when needed.
