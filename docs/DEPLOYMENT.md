# CollectStarInfo 原生部署与维护

2026-10-28 按用户要求修复路径、将仓库外门户适配纳入源码，并迁移为 **Python 虚拟环境 + systemd**。用户选定的发布方式为：**推送 GitHub 后，在服务器执行更新脚本**。本项目不再维护 Dockerfile、Compose 或容器启动分支，不为旧 Docker 框架另建备份；业务数据和原有密钥继续保留。

## 生产布局

| 项目 | 位置或约定 |
| --- | --- |
| 服务器 | 5 号机 `BJP-DoR-05`，`123.59.0.92`，允许联网 |
| 管理 SSH | `ComputerCenter-05-DepResearch02-root`；应用账户别名 `ComputerCenter-05-DepResearch02-cang_tq`，端口 22333 |
| GitHub | `SolomonCang/CollectStarInfo`，部署分支 `main` |
| 源码、前端构建 | `/home/cang_tq/CollectStarInfo/`、`frontend/dist/` |
| 运行账户 | `cang_tq`（UID/GID 1005），不以 root 运行应用 |
| Python | 项目 `.venv/`，基于账户独立安装的 Python 3.12 |
| Node | `/home/cang_tq/.local/share/collectstarinfo/node/`，22.23.4，仅安装/构建时使用 |
| Python 运行时 | `/home/cang_tq/.local/share/collectstarinfo/python/`，由一次性准备脚本管理 |
| 服务模板 | 仓库 `deploy/collectstarinfo.service` → `/etc/systemd/system/collectstarinfo.service` |
| 生产入口 | `.venv/bin/python -m uvicorn backend.app.portal:app --host 127.0.0.1 --port 8780` |
| 外部入口 | [恒星信息工作台](https://123.59.0.92:30001/apps/stars/)，经门户登录校验 |
| 权威存储 | 项目 `warehouse/db/target_info.sqlite` 与 `warehouse/objects/`，默认 SQLite 模式 |

`collectstarinfo.service` 使用 `Type=simple`、`User=cang_tq`、失败自动重启，正常状态应为 `active (running)`。运行期只需要 Python，不需要 Node 开发服务器或容器引擎。单元的环境变量明确指向现有模型密钥文件、限流台账和本地缓存；不会读取旧容器的环境文件。

## 发布流程

本地先检查改动、验证、仅提交本次相关源码和文档，再推送 GitHub：

```bash
# 项目根目录，使用独立开发 Python 环境
PYTHON_BIN=/path/to/development/python bash scripts/verify.sh
cd frontend
npm ci
npm run build -- --base=/apps/stars/
cd ..
# 审阅暂存区后自行提交，或在明确授权的任务中提交
git push origin main
```

然后在 5 号机执行：

```bash
sudo /home/cang_tq/CollectStarInfo/scripts/update-server.sh
```

也可从本机发起同一命令：

```bash
ssh ComputerCenter-05-DepResearch02-root /home/cang_tq/CollectStarInfo/scripts/update-server.sh
```

更新脚本会：

1. 用 `flock` 防止重叠发布；拒绝脏工作树和非 `main` 分支。
2. 以 `cang_tq` 执行 `git fetch origin main` 和 `git merge --ff-only origin/main`，不覆盖服务器上的未知修改。
3. 以应用账户安装 `requirements-server.lock` 中的 Python 依赖及 npm 锁文件中的依赖。
4. 在临时源码副本中运行后端测试，再运行前端测试，按 `/apps/stars/` 构建静态资源。
5. 安装仓库内的 systemd 模板、重启应用，并核验 HTTP 与健康 JSON 的顶层、storage、workspace 三处状态。

安装时同时把旧 `/usr/local/sbin/update-collectstarinfo` 替换为指向仓库脚本的符号链接，保留原管理入口，不再维护仓库外的脚本副本。更新脚本会解析该链接以定位真实源码目录。

GitHub 推送本身不会触发自动部署。`--no-pull` 仅供已核对源码的初次安装或受控操作使用，正常发布不要使用它跳过 Git 检查。脚本失败不会被报告为发布成功；Git 更新、依赖安装及构建不是原子发布，运行中的 Python 进程可能已加载部分模块，因此构建失败后也应排查现场。脚本没有自动回滚或数据备份功能。

## 首次准备或重建运行环境

在 5 号机应用账户下执行：

```bash
cd /home/cang_tq/CollectStarInfo
bash scripts/bootstrap-runtime.sh
bash scripts/prepare-app.sh
```

准备脚本支持 Linux x86_64：临时安装固定版本 uv，下载独立 Python 3.12，下载固定 Node.js 22 并核对官网 SHA-256，生成项目 `.venv`；不替换系统 Python/Node。临时安装器和下载归档完成后删除，独立运行时须保留。服务器系统旧版 Python 3.10/Node 12 不用于应用运行或构建。

生产 Python 依赖锁来自迁移前正在运行的完整包版本集合；有意升级依赖时同步更新并验证锁文件。该锁文件面向 Linux，macOS 开发可按 `requirements.txt` 配置环境。前端固定使用 `package-lock.json` 和 `npm ci`，不再跳过锁文件。

首次安装系统单元需要管理员执行 `scripts/install-service.sh`；只有已授权的安装/发布任务才执行。该脚本假定依赖与静态资源已准备好，不创建业务账户、不重置数据和密钥。生产服务模板与 Python 适配均在仓库，仓库外仅保留安装后的系统单元及运行时，不另存第二份业务适配代码。

## 门户适配与安全边界

`backend/app/portal.py` 从原服务器 `deploy_app.py` 纳入维护，保持现有行为：

- Nginx `/apps/stars/` 先通过门户 `auth_request` 验证会话，再覆盖注入可信标记、用户 ID、用户名、角色和 CSRF 派生材料。后端只监听回环地址，不接受公网直连。
- 有效门户用户关联到稳定的本地工作区 ID；门户 `superadmin` 映射工作台 `admin`，门户 `admin`/`user` 映射工作台 `user`。用户 ID 与 CSRF 派生算法保持兼容，既有私有模型记录仍按原所有者读取。
- 首次访问可能创建工作区用户，角色变化可能更新记录；不能通过伪造身份头对生产做“只读检查”。原生本地登录入口仅用于独立开发环境。
- 对文献调研与 `use_llm=true` 的目标查询按门户用户限制每 60 秒一次，限流 SQLite 保留在项目 `data/deepseek-rate-limit.db`。这不是所有模型供应商/插件接口的统一计费限流。
- 保留有上限的 SIMBAD 文献查询，最多 100 条，并保留目标别名及近十年筛选行为。
- 网关生成文件仍为 `/etc/nginx/researchtoolshub-gateways/generated.conf`，子路径处理使用 `/etc/nginx/snippets/researchtoolshub-fastapi-subpath.conf`。本次保持网关地址和配置，不手改生成文件。
- 前端资源 base 为 `/apps/stars/`，构建时 `VITE_API_BASE` 留空，API 由网关改写，不重复添加同一前缀。

## 路径修复与数据保留

- `backend/app/paths.py` 明确定义项目根目录，启动不再因为文件层级计算错误创建上级 `results/`；不需要旧 `/results`、`/data` 兼容挂载。
- 目录扫描在生成相对路径前解析文件和项目根目录的符号链接，修复 macOS `/var` 与 `/private/var` 的路径别名问题。文件读取仍检查允许根目录，没有放宽越界访问。
- 默认服务模型密钥位置从固定 `/app/DSAPI.key` 改为项目 `DSAPI.key`，生产单元还显式指定它；限流默认路径也改为项目目录。
- `warehouse/`、`results/`、`data/` 保持原位，现有 SQLite、共享科学数据、AI 历史、主密钥和模型密钥不重建。迁移前抽查的路径索引均为项目相对路径，没有要求把数据库中的路径改成新绝对地址。

目录库和对象文件不是可随意删除的缓存。主密钥仍为原 `warehouse/secrets/master.key`（0600），不读取或输出内容，不生成新主密钥替换现有密钥。业务备份需要覆盖一致性 SQLite、对象文件、旧报告和受控密钥；SQLite 使用 WAL，直接复制一个活动 `.sqlite` 文件不等于一致性备份。用户此次要求移除旧 Docker 框架备份，不等于要求删除业务数据或停止业务备份。

## 运维检查

```bash
systemctl show collectstarinfo.service -p ActiveState -p SubState -p User -p MainPID -p NRestarts
python3 /home/cang_tq/CollectStarInfo/scripts/check-health.py
ss -ltn '( sport = :8780 )'
```

`check-health.py` 不会把可能含连接信息的错误响应打印出来。排查日志时先筛选级别、时间和错误类别，再脱敏；不要输出完整环境变量、进程参数、用户数据、模型密钥或会话值。

## 2026-10-28 改造验收

- macOS 默认临时目录及 5 号机 Linux 隔离副本中，后端 **33/33**、前端 **8/8** 通过；生产子路径构建和临时端口原生试运行通过，覆盖健康、静态资源及未登录 401。生产切换结果将在完成后补齐。
- 运行环境已准备为 Python **3.12.16**、Node.js **22.23.4**；systemd 模板通过 5 号机 `systemd-analyze verify`。
- 补齐 npm 锁文件缺失的 `@emnapi/core`、`@emnapi/runtime` 两个可选依赖条目，已有包版本不变；Linux 严格安装不再需要绕过锁文件。
- 前端测试 8 项通过，生产子路径构建通过；光变页面最小化后 JS 约 5.01 MB（gzip 约 1.50 MB），仍有大资源包提示，未做性能优化。
- 真实付费模型调用、完整 SIMBAD/Gaia/MAST 检索下载、真实门户角色变更、备份恢复与可选 PostgreSQL/S3 没有作为此次部署验收的写入性测试执行。

迁移前检查记录中的 Docker 容器、`active (exited)` 和仓库外编排只属于历史部署，不是当前维护入口。切换完成后移除 CollectStarInfo 的旧容器、专用镜像、旧部署目录与其中的旧框架副本，不制作框架归档。其他服务或无关容器的管理不在本任务范围内。
