# CollectStarInfo

## 中文使用说明

这是一个用于检索恒星/天体信息的工具，会整合 SIMBAD、Gaia DR3、MAST 等数据源，并输出结构化报告。交互式 Web 工作台采用本地账号、SQLite 目录数据库和 `warehouse/` 文件层；可查询目标、通过用户私有的 OpenAI 兼容接口完成总结和文献调研，从 MAST 检索/下载 TESS、Kepler、K2 光变曲线产品，并对本地光变曲线做去趋势、周期搜索和相位折叠。

命令行批处理仍可直接运行 `run_agent.py`；交互式工具见下方“Web 工作台”。

命令行继续使用 `config.yaml` 和可选的 `DSAPI.key`；Web 工作台的模型端点与 API Key 在登录后通过“插件中心 → 大模型接口”独立配置。

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

首次运行先创建管理员（公开注册默认关闭）：

```bash
.venv/bin/python -m backend.app.manage create-admin --username admin
```

命令会交互式读取密码。管理员登录后可创建或禁用用户，也可生成仅显示一次的临时密码；使用临时密码的用户必须在首次登录后修改密码。

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

前端默认连接 `http://127.0.0.1:8000`。工作台包含“恒星主页”“数据发现与入库”“光变实验室”“插件中心”和“数据管理”；管理员额外看到“用户管理”。目标快照和光变数据在用户间共享，模型配置、API Key、提示输入和 AI 历史只对其所有者可见。普通用户可查询、刷新、下载和分析，但删除共享数据、缓存清理和目录重建只允许管理员执行。

### 默认 SQLite + warehouse 存储

默认 `PERSISTENCE_BACKEND=sqlite-warehouse`，权威元数据位于 `warehouse/db/target_info.sqlite`，正文与数组保存在文件层：

```text
warehouse/
  db/target_info.sqlite
  objects/targets/<target-id>/<snapshot-id>/
  objects/lightcurves/<target-id>/<dataset-id>/
  objects/llm/<user-id>/<target-id>/<run-id>/
  cache/{mast-search,products,derived,analysis}/
  manifests/
  secrets/master.key
```

本地首次需要加密模型密钥时会原子生成权限为 `0600` 的 `warehouse/secrets/master.key`。服务器和容器部署应改用 `APP_MASTER_KEY` 注入 32 字节密钥，例如：

```bash
python -c 'import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())'
```

API Key 使用 AES-GCM 加密，接口、日志和管理页面都不会返回明文。会话使用数据库中的不透明令牌、HttpOnly/SameSite Cookie，并对所有写请求校验 CSRF Token。

### 迁移现有数据

迁移遵循“预检—复制—校验—切换”，不会删除或修改 `results/`、`data/lightcurves/` 及旧缓存。指定的所有者账号用于接收旧摘要和 DeepSeek 配置：

```bash
.venv/bin/python scripts/migrate_to_warehouse.py --dry-run --owner admin
.venv/bin/python scripts/migrate_to_warehouse.py --execute --owner admin
.venv/bin/python scripts/migrate_to_warehouse.py --verify warehouse/manifests/migration-UUID.json
```

复制使用临时文件、原子重命名和 SHA-256 校验，并按目标、产品 URI 与内容哈希去重。命令可安全重复执行；冲突记录到报告而不会静默覆盖。管理员页面只读展示迁移状态，迁移本身只能通过 CLI 发起。

### PostgreSQL + MinIO/S3 分离式存储

生产环境可以设置 `PERSISTENCE_BACKEND=postgres-s3`：账号、工作台目录及对象索引使用同一套关系模型，PostgreSQL 作为权威元数据源，MinIO 或兼容 S3 的服务保存 JSON、FITS、CSV 等对象。旧 PostgreSQL/S3 表和对象镜像继续兼容，业务接口不需要判断具体存储后端。

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
APP_MASTER_KEY=<base64-url-encoded-32-byte-key>
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

应用启动时会自动创建所需表；需要由 DBA 预建表时，依次执行 `migrations/001_postgres_s3.sql` 和 `migrations/002_workspace.sql`。数据库记录和对象上传均为幂等 upsert，迁移脚本可以安全重跑。

目标查询默认优先载入 SQLite 目录中的最新快照，迁移前也会兼容读取 `results/<target>.json`；“强制重新检索”会重新调用 SIMBAD/Gaia/MAST 并保存新的共享快照。LLM 失败不会影响科学检索结果，其总结作为当前用户的独立运行记录保存。

MAST 光变曲线使用三层缓存。用户可见的数据集写入：

```text
warehouse/objects/lightcurves/<target>/<timestamp>-<uuid>/
```

其中包含产品硬链接（文件系统不支持时自动复制）、`selected_products.json`、带完整性信息的 `manifest.json` 和后端自动转换出的 `lightcurve.csv`。`results/` 继续只作为目标查询报告目录，不再混放下载数据。旧版时间戳目录和 manifest 保持兼容，无需手动迁移。

内部共享缓存位于 `warehouse/cache/`：

- `mast-search/`：按目标/坐标、半径、任务和数量参数缓存 MAST 检索结果，默认 TTL 为 6 小时；可通过 `LIGHTCURVE_SEARCH_CACHE_TTL` 修改。
- `products/`：按产品 URI 缓存单个 FITS，并保存文件大小和 SHA-256；不同目标别名和产品组合可以共享同一文件。
- `derived/`：按 FITS 指纹、flux column、质量过滤规则缓存标准化数组。
- `analysis/`：按数据指纹、降采样、去趋势和周期搜索参数缓存分析结果。

数据集下载使用文件锁、`.partial` 临时目录和原子重命名。缓存命中前会检查 manifest、下载状态、文件存在性和大小；深度校验还会检查 SHA-256。CSV 只在输入或处理参数变化时重新生成。

MAST 检索会把坐标、半径、任务集合和 `timeseries` 产品类型直接传给
远端服务，避免先拉取目标的全部观测再在本地过滤。外部服务采用独立超时：
SIMBAD 默认连接/读取超时为 10/20 秒，MAST 为 10/90 秒；MAST 遇到连接或
读取超时时默认重试一次。可通过
`SIMBAD_CONNECT_TIMEOUT_SECONDS`、`SIMBAD_READ_TIMEOUT_SECONDS`、
`MAST_CONNECT_TIMEOUT_SECONDS`、`MAST_READ_TIMEOUT_SECONDS`、
`MAST_MAX_ATTEMPTS` 和 `MAST_RETRY_BACKOFF_SECONDS` 调整。

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
