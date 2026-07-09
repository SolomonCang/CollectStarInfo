---
description: "Use when implementing, extending, or refactoring this astronomy target-search project; generating target reports; integrating SIMBAD/Gaia/MAST/JWST/HST data; or improving source-information completeness for each target."
name: "Astronomy Target Search Guidelines"
applyTo: ["src/**/*.py", "run_agent.py", "README.md"]
---
# 目标源信息搜寻指令

适用于“按目标名称或目标列表批量检索恒星/天体信息并生成结构化报告”的任务。
本指令为当前仓库内的默认规范，强度为“优先遵循（允许例外）”。

## 当前项目已实现能力
- 支持单目标或多目标批量运行，可通过命令行直接传入目标名，或从 TXT/CSV 文件读取目标列表。
- 支持通过 `config.yaml`、命令行参数和 `.env` 协调运行配置，包括输出目录、输出格式、是否启用 LLM、Gaia 锥搜半径、MAST 区域检索半径等。
- 可查询 SIMBAD 基本信息，包括主名、坐标、光谱型、标识符列表，以及与目标关联的参考文献。
- 可从 SIMBAD 标识符中提取 Gaia source id，并优先复用 SIMBAD 已带出的 Gaia 相关字段；当信息不完整时，再回退到 Gaia DR3 做 source id 查询或坐标锥搜。
- 可输出 Gaia 关键参数，包括 source id、G 星等、视差、视差误差，以及基于视差计算的距离与距离误差。
- 可从目标标识符中提取 TIC、EPIC、KIC，并通过 MAST 统计目标附近的任务覆盖情况。
- 可汇总 TESS、K2、Kepler、JWST、HST 在目标邻域内的观测计数，并尽可能给出时间覆盖信息（如 Sector、Campaign、Quarter、起止时间）。
- 可对 JWST/HST 先按目标名检查，再在目标坐标附近做区域回退查询，降低因命名不一致导致的漏检。
- 可基于 SIMBAD 参考文献构建文献工作流，对关键词、标题、摘要做分层分析，并按 `obj_freq` 阈值筛选更相关的参考文献。
- 可从参考文献中自动归纳观测类型与研究主题，形成 literature_workflow 结构化结果，而不依赖 LLM 也能产出这部分内容。
- 可在配置了 DeepSeek API 时生成多源汇总摘要；未配置或显式禁用 LLM 时，仍可完成数据库检索与结构化输出。
- 可为每个目标增量保存 JSON、Markdown、TXT 报告，当前输出为逐目标文件，例如 `results/<target>.json` 与 `results/<target>.md`。
- 具备模块级容错能力：SIMBAD、Gaia、MAST、文献分析、LLM 总结中的单模块失败会记录到 notes，不应阻断同一目标后续步骤或其他目标处理。

## 当前范围边界
- 当前项目的“研究进展”主要来自 SIMBAD 参考文献及其关键词、标题、摘要的规则化归纳，不等同于人工精读全文后的综述。
- 当前距离估计采用视差的一阶反演与误差传播，属于轻量级估算，不应表述为高精度贝叶斯距离结果。
- 当前 MAST 统计以任务覆盖和观测条目计数为主，不直接下载原始观测数据，也不执行光变曲线或谱数据分析。

## 默认输出语言
- 报告与总结默认使用中文。
- 若用户在单次任务中明确要求英文或双语，以用户即时要求为准。

## 目标覆盖范围
- 对每个目标，优先覆盖以下信息层级：基本信息、观测数据、研究进展、进阶观测信息。
- 基本信息：标准名称、别名、坐标、光谱型、亮度/视星等。
- 观测数据：Gaia 参数（如视差、距离估计）、任务归档观测计数（TESS/K2/Kepler/JWST/HST）。
- 研究进展：与目标直接相关的已发表研究主题、关键结论或热点方向。
- 进阶观测信息：可用任务数据覆盖情况、后续观测可行性与数据缺口。

## 数据源与优先级
- 首选权威数据库并保持一致口径：SIMBAD -> Gaia DR3 -> MAST。
- 当主路径失败时，使用坐标邻域查询作为回退，不应直接中断整条目标处理流程。
- 不同来源字段含义可能不同，输出时标注字段来源，避免混用造成误导。

## 输出与可追溯性
- JSON 与 Markdown 报告结构应稳定，字段命名保持向后兼容。
- 结论必须可追溯到查询结果；不确定项应明确标注为“未知”或“待确认”。
- 缺失数据要给出原因（未检索到、接口失败、字段为空），不要静默省略。

## 工程实现约束
- 新增逻辑优先复用现有客户端层（`simbad_client`、`gaia_client`、`mast_client`、`deepseek_client`）。
- 批处理场景下保证单目标失败不影响其他目标输出。
- 优先改进可观测性：关键分支记录简洁日志，便于定位来源失败或字段缺失。

## 质量门槛
- 在修改检索逻辑时，至少验证：单目标输入可运行、目标列表输入可运行、`--no-llm` 路径可运行并输出有效结构化结果。
