# 确定性推导规则

以下字段不由 LLM 自标注，由 `normalize_hunks.py` / `aggregate_stats.py` 确定性推导。`*_source` 字段必须为 `"derived"`，`*_derivation` 字段记录命中的规则编号。

## evidence_type 推导规则（problem_type → evidence_type_default 映射）

**改造前**（已废弃）：R-E1~R-E6 关键词匹配，依赖 LLM finding 文本中的措辞（如"遗漏"、"逻辑错误"），脆弱且不可靠。

**改造后**：从 `config/problem-types.json` 的 `evidence_type_default` 字段确定性映射，不依赖 LLM 措辞。

推导逻辑（由 `normalize_hunks.py` 执行）：

```python
def derive_evidence_type(problem_type, first_cause_nature, root_cause):
    """从 problem_type 确定性推导 evidence_type，不依赖 LLM 措辞。"""
    # 特殊类型优先
    if first_cause_nature == "prd_quality" or problem_type == "P1-3":
        return "prd_quality"

    # 从 problem-types.json 读取 evidence_type_default
    pt_config = lookup_problem_type(problem_type)
    if pt_config and "evidence_type_default" in pt_config:
        return pt_config["evidence_type_default"]

    # R1 根因 + 知识缺失证据
    if root_cause == "R1" and has_knowledge_gap_evidence():
        return "knowledge_gap"

    return "other"
```

映射规则总览（完整值写入 `config/problem-types.json` 的 `evidence_type_default` 字段）：

| problem_type 语义 | evidence_type | 理由 |
|---|---|---|
| 遗漏类（P*-1, P*-6, P*-9, P*-10, P*-12） | `omission` | 完全缺失 |
| 覆盖不全类（P*-2） | `omission` | 部分缺失 |
| 逻辑错误/约束违反类（P*-3, P*-4, P*-7, P*-8, P*-11, P*-13, P4-14） | `logic_error` | 内容有误 |
| 选型错误/链路梳理错误（P4-1, P4-2） | `logic_error` | 方向有误 |
| 描述模糊类（P*-5） | `ambiguity` | 表述不清 |
| PRD 质量（P1-3） | `prd_quality` | 外部源头 |
| R1 根因 + 知识缺失 | `knowledge_gap` | 知识不足 |
| 其他 | `other` | 兜底 |

## structure_type 推导规则

| 规则 | 条件 | structure_type |
|---|---|---|
| R-S1 | is_composite = true | `composite` |
| R-S2 | 其他情况 | `single` |

## first_cause_skill 推导规则

从 `first_cause_stage` 固定映射，由 `normalize_hunks.py` 执行：

| first_cause_stage | first_cause_skill |
|---|---|
| N5 | `yx-code` |
| N4 | `yx-plan` |
| N3 | `yx-requirement` |
| N2 | `yx-state` |
| N1 | `yx-init` |

## attribution_direction 推导规则

从 `first_cause_nature` 固定映射，由 `normalize_hunks.py` 执行：

| first_cause_nature | attribution_direction |
|---|---|
| `product_defect` | `artifact_defect` |
| `ai_deviation` | `execution_deviation` |
| `prd_quality` | `artifact_defect` |

## surface_issue_type 推导规则

从 `problem_type` → SIT ID 映射，由 `normalize_hunks.py` 执行。映射表维护在 `config/problem-types.json` 的 `surface_issue_types` 定义中。SubAgent 不直接输出此字段。

## impact 字段推导

由 `calc_agcr.py` + `aggregate_stats.py` 确定性计算，SubAgent-RootCause 不产出此字段：

| 子字段 | 来源 |
|---|---|
| `abandonment_impact` | `calc_agcr.py` 从 hunk-level removed/added lines 汇聚 |
| `agcr_impact` | `calc_agcr.py` 计算 |
| `total_removed_lines` | `aggregate_stats.py` 从 hunk-list 统计 |
| `total_added_lines` | `aggregate_stats.py` 从 hunk-list 统计 |
