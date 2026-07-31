# CollectStarInfo

## 中文使用说明

这是一个用于检索恒星/天体信息的工具，会整合 SIMBAD、Gaia DR3、MAST 等数据源，并输出结构化报告。当前已新增交互式 Web 架构：FastAPI 后端复用原有检索逻辑，React 前端可查询目标、调用 DeepSeek 做文献调研，从 MAST 检索/下载 TESS、Kepler、K2 光变曲线产品，并对本地光变曲线做去趋势、周期搜索和相位折叠。

命令行批处理仍可直接运行 `run_agent.py`；交互式工具见下方“Web 工作台”。

配置方式：统一使用 `config.yaml`，不再使用环境变量文件。

1. 安装依赖
   - `python3 -m venv .venv && source .venv/bin/activate`
   - `pip install -r requirements.txt`
2. 准备目标列表
   - 在 `targets_input.txt` 中每行写一个目标名（例如 `GJ 65A`、`AD Leo`）。
   - 也可以直接写坐标，支持常见格式，例如 `217.428938 -62.679492` 或 `14:29:42.95 -62:40:46.2`。
3. 直接运行查询（不使用 LLM，总结更稳定）
   - `python run_agent.py --targets-file targets_input.txt --format both --no-llm`
4. 直接运行查询（启用 LLM 总结）
   - 先在项目根目录的 `DSAPI.key` 中写入 DeepSeek API Key
   - 再执行 `python run_agent.py --targets-file targets_input.txt --format both --use-llm`
5. 查看输出
   - 结果默认写入 `results/`，每个目标会生成同名 `.json` 和 `.md` 报告。

## Web 工作台

后端：

```bash
.venv/bin/uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

前端：

```bash
cd frontend
npm install
npm run dev
```

前端默认连接 `http://127.0.0.1:8000`。工作台分为“目标信息”和“光变曲线”两个页面；文献调研面板会使用 `DSAPI.key` 中的 DeepSeek API Key 和 `config.yaml` 中的模型配置，对当前目标的 SIMBAD references 和 literature workflow 做中文分析。

### PostgreSQL + MinIO/S3 分离式存储

默认的 `PERSISTENCE_BACKEND=filesystem` 完全兼容原来的本地目录模式。生产环境可以设置
`PERSISTENCE_BACKEND=postgres-s3`：PostgreSQL 作为目标结果、数据集及统一目录的权威元数据源，
MinIO 或兼容 S3 的服务保存 JSON、FITS、CSV 等对象。本地 `results/` 和 `data/` 在该模式下只作为
可丢弃的计算缓存；任意 API 节点收到分析请求后都会按需从对象存储恢复数据集。

本机启动完整环境：

```bash
cp .env.storage.example .env.storage
# 先修改 .env.storage 中的两个密码
docker compose --env-file .env.storage \
  -f docker-compose.storage.yml up -d --build
```

- Web/API：`http://127.0.0.1:8000`
- MinIO API：`http://127.0.0.1:9000`
- MinIO 控制台：`http://127.0.0.1:9001`
- `/api/health` 会分别报告应用和持久化后端状态。

如果宿主机的 `8000` 端口已占用，可在 `.env.storage` 中设置
`TARGET_INFO_PORT=18000`，然后通过 `http://127.0.0.1:18000` 访问。

连接已有的独立服务器时，只需给 API 容器设置：

```bash
PERSISTENCE_BACKEND=postgres-s3
DATABASE_URL=postgresql+psycopg://user:password@postgres.example:5432/target_info
S3_ENDPOINT_URL=https://minio.example
S3_ACCESS_KEY=...
S3_SECRET_KEY=...
S3_BUCKET=target-info-search
S3_REGION=us-east-1
S3_CREATE_BUCKET=false
```

AWS S3 可省略 `S3_ENDPOINT_URL`。生产环境应通过 Docker secret、Kubernetes Secret 或密钥管理服务
注入密码，不要提交真实 `.env.storage`。多个 API 实例之间通过 PostgreSQL advisory lock 协调数据集
写入，不再依赖跨服务器文件锁。

已有本地数据可无损复制到远端（脚本不会删除本地文件）：

```bash
export PERSISTENCE_BACKEND=postgres-s3
export DATABASE_URL='postgresql+psycopg://...'
export S3_ENDPOINT_URL='https://minio.example'
export S3_ACCESS_KEY='...'
export S3_SECRET_KEY='...'
export S3_BUCKET='target-info-search'

python scripts/migrate_to_postgres_s3.py --dry-run
python scripts/migrate_to_postgres_s3.py
```

应用启动时会自动创建所需表；需要由 DBA 预建表时，可执行
`migrations/001_postgres_s3.sql`。数据库记录和对象上传均为幂等 upsert，迁移脚本可以安全重跑。

目标查询默认会优先载入 `results/<target>.json` 中已有信息，避免重复访问外部数据库；在前端勾选“强制重新检索”后，会重新调用 SIMBAD/Gaia/MAST/DeepSeek，并把新的 JSON 写回 `results/`。

MAST 光变曲线使用三层缓存。用户可见的数据集写入：

```text
data/lightcurves/<target>/<timestamp>-<uuid>/
```

其中包含产品硬链接（文件系统不支持时自动复制）、`selected_products.json`、带完整性信息的 `manifest.json` 和后端自动转换出的 `lightcurve.csv`。`results/` 继续只作为目标查询报告目录，不再混放下载数据。旧版时间戳目录和 manifest 保持兼容，无需手动迁移。

内部共享缓存位于 `data/lightcurves/_cache/`：

- `search/`：按目标/坐标、半径、任务和数量参数缓存 MAST 检索结果，默认 TTL 为 6 小时；可通过 `LIGHTCURVE_SEARCH_CACHE_TTL` 修改。
- `products/`：按产品 URI 缓存单个 FITS，并保存文件大小和 SHA-256；不同目标别名和产品组合可以共享同一文件。
- `derived/`：按 FITS 指纹、flux column、质量过滤规则缓存标准化数组。
- `analysis/`：按数据指纹、降采样、去趋势和周期搜索参数缓存分析结果。

数据集下载使用文件锁、`.partial` 临时目录和原子重命名。缓存命中前会检查 manifest、下载状态、文件存在性和大小；深度校验还会检查 SHA-256。CSV 只在输入或处理参数变化时重新生成。

下载完成后，前端会自动选中新数据集；也可以在独立“光变曲线”页面从“已下载数据集”下拉框选择历史下载。后端会读取该目录下的 `manifest.json` 和 FITS 文件，优先使用 `PDCSAP_FLUX`，应用 `QUALITY == 0` 过滤，生成 `time,flux,flux_error` CSV，并送入去趋势、Lomb-Scargle 周期搜索、频谱图和相位折叠分析。相位折叠周期可使用最佳周期，也可从频谱图点击选择或手动输入。

光变曲线页面同时提供缓存占用统计、完整性校验、按保留天数/容量清理预览、执行清理和单数据集删除。清理 API 默认为 `dry_run=true`；共享产品、派生结果和分析结果只有在不再被任何数据集引用时才会回收。相关接口为：

- `GET /api/lightcurves/cache/stats`
- `POST /api/lightcurves/cache/verify`
- `POST /api/lightcurves/cache/cleanup`
- `POST /api/lightcurves/datasets/delete`

也可以在项目根目录用启动器一次性启动前后端并打开网页：

```bash
python launch_web.py
```

如需只启动不打开浏览器：

```bash
python launch_web.py --no-open
```

提示：如果只想跑单个目标，可用 `--targets "Proxima Centauri"` 直接传参。
也可以直接传坐标，例如 `python run_agent.py --targets "14:29:42.95 -62:40:46.2" --no-llm`。

## 在 Copilot 中使用参数提取技能

仓库内提供了一个可直接调用的 Copilot Skill：
- `.github/skills/stellar-rotation-activity-params/SKILL.md`

适用场景：
- 你已经有 `results/<target>.json`，希望从 `target.simbad.references` 里继续追踪文献参数。
- 需要重点提取以下参数：`Period`、`Mass`、`Teff`、`log g`、`vsini`、`RV`、`INCL`、`<Bl>`。
- 希望将参数提取结果写到独立文件 `<target>_extrapar.md`，而不覆盖原始目标报告。

在 Copilot Chat 里的典型请求方式：
- `使用 stellar-rotation-activity-params 技能分析 results/KIC 4931738.json，优先 Period, vsini, RV, INCL, <Bl>。`
- `使用 stellar-rotation-activity-params 技能，下载文献资产到 results/KIC 4931738/，并生成 results/KIC 4931738_extrapar.md。`

如果你想先离线生成“文献追踪清单”，可直接运行技能附带脚本：

```bash
python .github/skills/stellar-rotation-activity-params/scripts/prepare_reference_hunt.py \
   "results/KIC 4931738.json" \
   --parameters Period vsini RV INCL "<Bl>"
```

生成独立参数 Markdown（并可选下载 ADS/VizieR/arXiv 资产）：

```bash
python .github/skills/stellar-rotation-activity-params/scripts/prepare_reference_hunt.py \
   "results/KIC 4931738.json" \
   --write-extrapar-markdown \
   --download-assets
```

说明：默认会在 JSON 同目录输出 `results/<target>_extrapar.md`，并在 `results/<target>/` 下保存下载资产（可用 `--output-markdown` 与 `--asset-dir` 覆盖）。
补充：脚本默认会筛查并保留该目标的全部参考文献；只有显式传入 `--top N` 时才会限制到前 N 篇。
补充：启用 `--download-assets` 时，默认只下载高优先级候选文献的资产，而不是把全部参考文献都下载到本地；若你确实要下载全部已排序文献，可显式加 `--download-all-assets`。

A Python agent-style tool for astronomy target lookup and summarization.

## Features
- Query SIMBAD for object match, coordinates, and spectral type.
- Accept coordinate inputs, resolve the nearest SIMBAD object name, then continue with the normal stellar-target workflow.
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
Put the DeepSeek API key in `DSAPI.key` at the project root. The file can contain either the raw key or a `DEEPSEEK_API_KEY=...` style line. `config.yaml` still controls `deepseek.base_url` and `deepseek.model`.

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

Run with coordinates directly:

python run_agent.py --targets "14:29:42.95 -62:40:46.2"

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
