# CollectStarInfo 工作指南

适用于本目录及其子目录；同时遵守上级 [BJPcloudServer 工作指南](../AGENTS.md)。2026-10-28 根据路径修复、仓库化门户适配及原生服务迁移整理。

## 开始工作

1. 阅读 [README](README.md)、[当前架构](docs/interactive_architecture.md) 和 [部署核验](docs/DEPLOYMENT.md)，修改前检查本仓库 `git status --short`，保留已有改动。
2. 科学检索相关工作同时参考 `.github/instructions/astronomy-target-search.instructions.md`；CLI 与 Web 的能力、存储和鉴权边界分别核对实际实现。
3. 本目录是独立 Git 仓库，不把上级目录或其他子项目的文件混入提交。不自动提交或推送。

## 实现入口

- `src/astro_agent/`：坐标解析、SIMBAD/Gaia/MAST 客户端、目标汇总及模型客户端；`run_agent.py` 为 CLI。
- `backend/app/main.py`：FastAPI 路由和静态前端；`workspace_routes.py`：账号、管理员、模型配置及私有运行历史。
- `backend/app/auth.py`：登录、角色与 CSRF；`services/workspace_service.py`：关系目录、会话、密钥加密和私有对象。
- `services/lightcurve_*`：MAST 产品、FITS 读取、缓存及分析；`catalog_service.py`：数据管理目录；`persistence_service.py`：可选 PostgreSQL/S3 镜像。
- `frontend/`：React + JavaScript + Vite，使用 npm 和现有 `package-lock.json`；没有独立 lint 脚本。

## 开发和验证

- 线上原生 Python 3.12 虚拟环境与独立 Node.js 22；生产依赖使用 `requirements-server.lock` 和 npm 锁文件，本地开发可使用 `requirements.txt`。
- 按 README 分别启动开发进程，或使用 `launch_web.py`/`start.sh`；默认绑定回环地址，不再停止其他服务或强杀端口进程。本项目不保留 Docker 启动分支。
- 应用启动会初始化/升级目录数据库、创建目录并可能重建索引；启动目录统一来自 `backend/app/paths.py`，不再在项目上级创建 `results/`。测试不指向生产库、warehouse 或密钥；`scripts/verify.sh` 使用临时源码副本。
- `migrate_to_warehouse.py` 的 `--dry-run` 也会初始化目录库、写迁移记录和清单；`--verify` 之前同样会初始化目录库。`migrate_to_postgres_s3.py --dry-run` 会先初始化远端持久化。迁移必须先读代码、明确环境及授权，不能用于线上纯只读核验。

在项目根目录执行后端测试：

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
```

在 `frontend/` 执行：

```bash
npm ci
npm test
npm run build
```

仅文档变更检查引用、命令依据、内容一致性和敏感信息即可。修改检索逻辑时，按科学检索指令验证单目标、目标列表及 `--no-llm`，外部调用须在允许联网的环境进行。

## 云服务器边界

- 5 号机源码 `/home/cang_tq/CollectStarInfo`，由 `cang_tq` 操作 Git、安装项目依赖及运行应用；systemd 单元安装与重启由管理员执行。
- `backend/app/portal.py` 是生产入口，保留门户身份、稳定用户 ID/CSRF 派生、超级管理员映射、模型请求限流和有界 SIMBAD 文献查询；`main.py` 是独立账号开发入口。
- `deploy/collectstarinfo.service` 是模板，实际服务 `collectstarinfo.service` 仅监听 `127.0.0.1:8780`，门户入口仍为 HTTPS 30001 下的 `/apps/stars/`。网关鉴权和身份头覆盖不可移除。
- 发布按用户选定流程：先提交/推送 GitHub，再在服务器运行 `sudo /home/cang_tq/CollectStarInfo/scripts/update-server.sh`。脚本拒绝脏工作树和非 main 分支，仅 fast-forward 拉取，以应用账户安装锁定依赖、测试、构建，再安装单元和重启、检查健康 JSON。
- 初次原生环境准备使用 `scripts/bootstrap-runtime.sh`（应用账户，仅允许联网节点）；后续更新使用 `prepare-app.sh`。运行时在应用账户下独立管理，不替换系统 Python/Node。
- 不自动提交或推送；取得本次明确授权后可以执行。生产发布、重启、数据库写入和账户/权限操作也须属于已授权任务，已有授权无需反复询问。
- 纯只读排查不伪造门户身份，不创建测试账号/会话。测试身份、限流及 CSRF 在隔离数据上验证；真实门户验证需使用正常会话。
- 2026-10-28 按用户要求移除项目 Docker 部署文件和旧仓库外适配，不创建旧 Docker 框架备份。不要重新引入旧编排或兼容挂载；数据与密钥仍须保留。

## 数据和安全

- SQLite + warehouse 为当前默认及线上模式；不能把 `warehouse/` 当缓存删除。模型配置和 AI 运行记录按用户隔离，科学快照与光变数据共享。
- 删除共享数据、清理缓存、修复与目录重建保留管理员检查；写请求保留 CSRF 校验；生产门户网关保留登录校验、身份头覆盖和回环监听。
- 不读取或输出生产 `.env`、部署 `environment`/`env.sh`、`DSAPI.key`、主密钥、会话值或数据库连接凭据。不要打印整个容器 inspect、进程参数或环境变量。
- 不提交 `warehouse/`、`data/`、`results/`、密钥、数据库、备份、依赖或前端构建产物。备份必须覆盖数据库、对象文件和受控密钥；恢复验证与快照现状见部署文档。
- 修改部署、端口、目录或发布链路时同步更新 README、部署文档及工作区上级指南；仅按任务授权范围操作生产。
