# SubAgent-Artifact 规格

## 职责

从 CLI 洗数结果目录（`{session_id}/*.md` 产物）或 `artifact_paths` 下载阶段产物到本地缓存目录。

## 主 Agent 传入参数

```json
{
  "artifacts": [
    { "type": "DOC_DESIGN",              "s3_url": "https://..." },
    { "type": "DOC_DESIGN_INTERFACE",   "s3_url": "https://..." },
    { "type": "DOC_PLAN",               "s3_url": "https://..." },
    { "type": "DOC_REQUIREMENT",        "s3_url": "https://..." },
    { "type": "DOC_ORIGINAL_REQUIREMENT","s3_url": "https://..." },
    { "type": "DOC_FEATURE_POINTS",     "s3_url": "https://..." },
    { "type": "DOC_BASELINE",           "s3_url": "https://..." },
    { "type": "DOC_DOMAIN_KNOWLEDGE",   "s3_url": "https://..." },
    { "type": "DOC_EVIDENCE",           "s3_url": "https://..." },
    { "type": "DOC_CONSTRAINT_CHECK",   "s3_url": "https://..." },
    { "type": "DOC_REPO_SCOPE",         "s3_url": "https://..." },
    { "type": "DOC_WORK_STATUS",        "s3_url": "https://..." },
    { "type": "DOC_CLARIFICATION_LOG",  "s3_url": "https://..." },
    { "type": "DOC_CLARIFICATION_SUMMARY","s3_url": "https://..." }
  ],
  "artifact_paths": {}
}
```

## 执行逻辑

数据源优先级：
1. CLI 洗数结果目录的 `.md` 产物（`${OUTPUT_DIR}/cli-washing/{session_id}/*.md`，拷贝到 `artifacts/` 目录）
2. `artifact_paths`（用户显式提供本地路径）

缺失产物记录到返回摘要的 `missing` 字段（不阻塞分析）。

## 输出文件（写入 `$OUTPUT_DIR/artifacts/`）

| 文件名 | 阶段 | 说明 |
|---|---|---|
| `design.md` | N4 技术方案 | 技术方案设计文档 |
| `design-interface.md` | N4 技术方案 | 接口设计文档 |
| `tasks.md` | N5 编码计划 | 编码计划/任务拆解 |
| `requirement.md` | N3 需求澄清 | 需求分析文档（用户故事 + AC） |
| `current-state.md` | N2 现状梳理 | 现状基线文档 |
| `original-requirement.md` | N1 项目初始化 | PRD 原始需求 |
| `feature-points.md` | N1 项目初始化 | 功能点拆解 |
| `domain-knowledge.md` | N1 项目初始化 | 领域知识文档 |
| `evidence.md` | N1 项目初始化 | 调研证据文档 |
| `constraint-check.md` | N4 技术方案 | 约束检查文档（架构约束、编码规范、中间件规范） |
| `repo.md` | N1 项目初始化 | 仓库范围识别 |
| `work_status.md` | N1 项目初始化 | 领域识别与工作状态 |
| `clarification-log.md` | N3 需求澄清 | 澄清交互日志 |
| `clarification-summary.md` | N3 需求澄清 | 澄清交互摘要 |
| `execution_trace.json` | 全链路 | 按阶段切分的执行轨迹摘要（从 CLI dag_*.json 生成） |

## execution_trace.json 生成

主 Agent 在 Phase 1 数据采集阶段，从 CLI 洗数产出的 `dag_*.json` 文件中提取摘要，生成 `execution_trace.json` 写入 `artifacts/` 目录。详见 `references/cli-schemas.md` 的「execution_trace.json 生成」章节。

## 返回摘要

```json
{
  "status": "success|partial",
  "artifact_map": {
    "design":                "$OUTPUT_DIR/artifacts/design.md",
    "design_interface":      "$OUTPUT_DIR/artifacts/design-interface.md",
    "tasks":                 "$OUTPUT_DIR/artifacts/tasks.md",
    "requirement":           "$OUTPUT_DIR/artifacts/requirement.md",
    "current_state":         "$OUTPUT_DIR/artifacts/current-state.md",
    "original_requirement":  "$OUTPUT_DIR/artifacts/original-requirement.md",
    "feature_points":        "$OUTPUT_DIR/artifacts/feature-points.md",
    "domain_knowledge":      "$OUTPUT_DIR/artifacts/domain-knowledge.md",
    "evidence":              "$OUTPUT_DIR/artifacts/evidence.md",
    "constraint_check":      "$OUTPUT_DIR/artifacts/constraint-check.md",
    "repo_scope":            "$OUTPUT_DIR/artifacts/repo.md",
    "work_status":           "$OUTPUT_DIR/artifacts/work_status.md",
    "clarification_log":     "$OUTPUT_DIR/artifacts/clarification-log.md",
    "clarification_summary": "$OUTPUT_DIR/artifacts/clarification-summary.md"
  },
  "missing": ["tasks", "domain_knowledge"]
}
```

## 约束

- 不存在的产物只记录为证据缺口，不阻塞 diff 分析
- `execution_trace.json` 由主 Agent 在数据采集阶段从 `dag_*.json` 生成（非 SubAgent 产出），写入 `artifacts/` 目录
- 元析流程自身的中间状态/报告文件（如 gate_test_analysis.md 等）不作为归因产物
