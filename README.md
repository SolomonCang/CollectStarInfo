# CollectStarInfo

## 中文使用说明

这是一个用于批量检索恒星/天体信息的工具，会整合 SIMBAD、Gaia DR3、MAST 等数据源，并输出结构化报告。

重点：可以直接运行 `run_agent.py`，无需额外封装脚本。

配置方式：统一使用 `config.yaml`，不再使用环境变量文件。

1. 安装依赖
   - `python3 -m venv .venv && source .venv/bin/activate`
   - `pip install -r requirements.txt`
2. 准备目标列表
   - 在 `targets_input.txt` 中每行写一个目标名（例如 `GJ 65A`、`AD Leo`）。
3. 直接运行查询（不使用 LLM，总结更稳定）
   - `python run_agent.py --targets-file targets_input.txt --format both --no-llm`
4. 直接运行查询（启用 LLM 总结）
   - 先在 `config.yaml` 中配置 DeepSeek API Key
   - 再执行 `python run_agent.py --targets-file targets_input.txt --format both --use-llm`
5. 查看输出
   - 结果默认写入 `results/`，每个目标会生成同名 `.json` 和 `.md` 报告。

提示：如果只想跑单个目标，可用 `--targets "Proxima Centauri"` 直接传参。

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
Set `deepseek.api_key` in `config.yaml`.

Use `config.yaml` in project root to configure runtime parameters
(DeepSeek API, run switches, output defaults, and agent defaults).

Supported run switches in `config.yaml`:
- `run.use_llm`: default LLM behavior
- `run.targets`: default target list when `--targets` is omitted
- `run.targets_file`: default targets file when `--targets-file` is omitted

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
