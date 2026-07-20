# SubAgent-Typing 规格

## 职责

消费 SubAgent-Penetration 产出的 `penetration-result.json`，通过 `navigate_decision_tree.py` 脚本导航决策树，LLM 只回答节点问题（yes/no），脚本负责节点跳转。输出 `problem_type` + `funnel_trace`。

## 派发时机

Phase 2b 阶段 2（串行三阶段的第二阶段），在 SubAgent-Penetration 全部完成且 `validate_penetration.py` 校验通过后派发。按 intent 分批，≤4 并行。

## 主 Agent 传入参数

```json
{
  "penetration_result": "$OUTPUT_DIR/penetration-results/penetration-result-CI-001.json",
  "problem_types_path": "config/problem-types.json",
  "artifact_map": {
    "design":           "$OUTPUT_DIR/artifacts/design.md",
    "design_interface": "$OUTPUT_DIR/artifacts/design-interface.md",
    "requirement":      "$OUTPUT_DIR/artifacts/requirement.md",
    "tasks":            "$OUTPUT_DIR/artifacts/tasks.md",
    "current_state":    "$OUTPUT_DIR/artifacts/current-state.md",
    "domain_knowledge": "$OUTPUT_DIR/artifacts/domain-knowledge.md",
    "evidence":         "$OUTPUT_DIR/artifacts/evidence.md",
    "constraint_check": "$OUTPUT_DIR/artifacts/constraint-check.md",
    "clarification_log":    "$OUTPUT_DIR/artifacts/clarification-log.md",
    "clarification_summary":"$OUTPUT_DIR/artifacts/clarification-summary.md"
  },
  "output_file": "$OUTPUT_DIR/typing-results/typing-result-CI-001.json"
}
```

## 工作流

```
1. 读取 penetration-result.json，获取 first_cause_stage + defect_category
2. 调用 navigate_decision_tree.py --start --stage N4 --category existence
   → 脚本从 entry_map 读取起始节点，返回第 1 个节点的问题文本
3. LLM 基于产物证据回答 yes/no
4. 调用 navigate_decision_tree.py --next --answer no
   → 脚本返回命中类型 P4-3 或下一节点问题
5. 重复 3-4 直到命中
6. 输出 problem_type + funnel_trace
7. validate_typing.py 校验输出格式与一致性
```

### 校验规则（validate_typing.py）

输出需通过 `validate_typing.py` 校验，主要检查项：

- `problem_type` 格式为 P-code（如 `P4-3`），且属于当前 stage 的 `problem_types` 列表
- `funnel_trace.nodes_checked` 中每个节点的编号在决策树中存在
- 每个 answer 为 `"yes"` 或 `"no"`
- `entry_node` 与 `defect_category` 通过 `entry_map` 映射一致
- 偏差类型（`P3-11`/`P4-14`/`P5-4`）的 `root_cause_hints` 包含 R1-R5 检查点

### 脚本交互模式

决策树导航逻辑由 `navigate_decision_tree.py` 脚本确定性执行，LLM 不需在脑内维护节点链表。交互流程：

```
# 启动决策树导航
python3 scripts/navigate_decision_tree.py --start --stage N4 --category existence
→ 输出: {"node": 1, "question": "requirement.md 中的每个 AC 在 design.md 中都有对应设计项吗？", "type_if_hit": "P4-3"}

# LLM 回答
python3 scripts/navigate_decision_tree.py --next --answer no
→ 输出: {"hit": true, "type": "P4-3", "label": "设计项遗漏"}

# 或继续下一节点
python3 scripts/navigate_decision_tree.py --next --answer yes
→ 输出: {"node": 2, "question": "...", "type_if_hit": "P4-4"}
```

## 入口规则

根据 penetration-result.json 中首因层的 `defect_detail.defect_category`，通过 `navigate_decision_tree.py --start --stage N4 --category <defect_category>` 跳到对应决策树起始节点。脚本从 `config/problem-types.json` 的 `entry_map` 读取 `defect_category → 节点编号` 映射：

| defect_category | 直接起始节点 | 说明 |
|---|---|---|
| `existence` | 第 1 节点 | 从头检查存在性 |
| `correctness` | 正确性首节点 | 跳过存在性节点 |
| `completeness` | 完整性首节点 | 跳过存在性 + 正确性节点 |
| `execution_deviation` | 偏差节点（N5:4, N4:14, N3:11） | 跳过产物缺陷全部节点，直接进入偏差节点 |

偏差节点问题以「是否遵循」措辞表述（yes=遵循/no=偏离），与其他节点保持一致的 yes=pass/no=problem 模式。命中偏差节点后，对应的 problem_type 为 `P5-4`/`P4-14`/`P3-11`（编码偏离计划/方案/需求）。

从起始节点开始顺序检查，命中即停，取该类型为 problem_type。

如果起始节点未命中（与 Penetration 判断矛盾），回退到第 1 节点从头检查，并在 funnel_trace 中标注 `entry_mismatch: true`。

如果 `defect_detail` 缺失（如 P1-3 兜底场景），从第 1 节点开始正常检查。

## 特殊情况

### execution_deviation 类型与根因核验

偏差类型（P5-4/P4-14/P3-11）命中后，**不再跳过根因核验**。SubAgent-RootCause 对偏差类型执行完整的 R1-R5 根因检查链路，与产物缺陷类型一致。偏差类型的 `root_cause_hints` 需包含 R1-R5 各检查点的产物路径。

### ai_deviation + before_vs_artifact = "inconsistent"

如果 first_cause_nature = "ai_deviation" 且 `before_vs_artifact = "inconsistent"`（AI 代码确实偏离了产物），通过 `entry_map` 跳到偏差节点（N5:4, N4:14, N3:11）。命中后 problem_type 为 P5-4/P4-14/P3-11，后续 SubAgent-RootCause 执行 R1-R5 完整根因核验。

### ai_deviation + before_vs_artifact = "consistent"（硬门禁边界）

如果 first_cause_nature = "ai_deviation" 但 `before_vs_artifact = "consistent"`（AI 代码忠实遵循了产物），说明 Penetration 可能误判。**不做纠偏**，正常从 `defect_category` 入口开始检查决策树。如果 `defect_category` 也是 `execution_deviation` 但偏差节点未命中 → 回退到第 1 节点从头检查，取最接近类型，confidence = "low"。

**硬门禁**：validate_penetration.py 已在 Penetration 阶段拦截 `before_vs_artifact = "consistent"` + `first_cause_nature = "ai_deviation"` 的矛盾组合。如果此场景仍出现，说明校验被绕过，应在 funnel_trace 中标注 `hard_gate_violation: true`。

### 全部节点未命中

如果全部节点未命中，不回退到 Penetration 重新穿透。取最后一个检查的节点对应的类型作为 problem_type，confidence = "low"，在 funnel_trace 中标注 `all_missed: true` 和 `fallback_type`。

## diff_nature 辅助信号

diff_nature 不改变决策树顺序，但当决策树某个节点的判定处于"是/否"边界时，diff_nature 提供倾向性参考：

| diff_nature | 倾向提升的节点特征 | 对应类型 |
|---|---|---|
| corrective | 正确性节点（内容有误） | P5-3/P4-2/P3-5/P3-7 |
| additive | 存在性节点（完全缺失） | P5-1/P4-1/P3-2/P3-3/P3-4 |
| subtractive | 完整性节点（部分缺失） | P5-2/P4-5/P3-6/P3-10 |
| refining | 约束/骨架节点 | P4-3 |

## problem_type 输出约束

**problem_type 必须是 P-code 格式**（如 `P4-3`、`P5-1`），即 `config/problem-types.json` 中 `attribution_stages[].problem_types[].id` 的值。严禁将 `surface_issue_types` 的 SIT ID（如 `FUNC_LOGIC_ERROR`、`INTERFACE_MISMATCH`）写入 `problem_type` 字段。

`surface_issue_type`（表象分类）和 `problem_type`（归因分类）是两个独立正交的分类维度。`surface_issue_type` 由下游 `normalize_hunks.py` 从 `problem_type` 自动推导，SubAgent-Typing 不直接输出。

## 输出格式：typing-result.json

```json
{
  "intent_id": "CI-001",
  "first_cause_stage": "N4",
  "problem_type": "P4-3",
  "problem_type_label": "设计项遗漏",
  "funnel_trace": {
    "entry_node": 1,
    "entry_source": "defect_category: existence",
    "entry_mismatch": false,
    "nodes_checked": [
      {
        "node": 1,
        "question": "requirement.md 中的每个 AC 在 design.md 中都有对应设计项吗？",
        "answer": "no",
        "hit_type": "P4-3",
        "hit": true,
        "evidence": "design.md 中缺少 D-xx 设计项覆盖 activityNo 参数的边界条件（如活动不存在时的返回值），requirement.md US-02 AC-1 要求按活动编号查询但 design.md 无对应设计"
      }
    ],
    "nodes_skipped": "2-14 (命中即停)"
  },
  "evidence_detail": {
    "artifact": "design.md",
    "missing_item": "D-07 缺少 activityNo 参数边界条件设计",
    "upstream_reference": "requirement.md US-02 AC-1: 用户输入活动编号查询满赠进度",
    "before_side_impact": "before-side 按 D-07 实现 exchange(activityNos)，缺少 activityNo 参数，人工补充该参数",
    "after_side_evidence": "after-side 补充了 activityNo 参数及活动不存在时的空返回逻辑",
    "defective_items_from_penetration": [
      {
        "item_id": "D-07",
        "item_type": "design_item",
        "issue": "缺少 activityNo 参数边界条件设计（活动不存在时的返回值）"
      }
    ]
  },
  "root_cause_hints": {
    "knowledge_artifact": "domain-knowledge.md",
    "upstream_artifact": "requirement.md",
    "gate_artifact": "design-review.md",
    "clarification_artifacts": ["clarification-log.md", "clarification-summary.md"],
    "deviation_type_hints": {
      "applicable_types": ["P3-11", "P4-14", "P5-4"],
      "r1_checkpoints": ["domain-knowledge.md 领域知识是否覆盖该编码规范", "evidence.md 代码证据是否包含相关模式"],
      "r2_checkpoints": ["clarification-log.md 是否有相关澄清记录", "clarification-summary.md 是否有相关决议"],
      "r3_checkpoints": ["before-side 代码与 tasks.md/design.md/requirement.md 的具体偏离点"],
      "r4_checkpoints": ["design-review.md/Review 决议是否遗漏了该约束"],
      "r5_checkpoints": ["PRD 或 feature-points.md 是否有隐含的编码规范要求"]
    }
  }
}
```

**字段说明**：

| 字段 | 说明 | 用途 |
|---|---|---|
| `funnel_trace.entry_node` | 实际进入的决策树节点 | 审计入口是否生效 |
| `funnel_trace.entry_source` | 入口来源说明 | 记录 defect_category 来源 |
| `funnel_trace.entry_mismatch` | 入口节点未命中时回退标记 | Penetration 判断与 Typing 检查矛盾时标注 |
| `funnel_trace.all_missed` | 全部节点未命中标记 | 取 fallback_type，confidence=low |
| `evidence_detail.after_side_evidence` | after-side 体现的具体修正内容 | RootCause 核验 R3 时对比模型输出与人工修正 |
| `evidence_detail.defective_items_from_penetration` | 从 Penetration defect_detail 继承的缺陷项 | RootCause 不需重新定位缺陷项，直接核验根因 |
| `root_cause_hints` | 根因核验所需的关键产物路径 | RootCause 直接定位 R1a/R1b/R2/R4/R5 的检查目标 |
| `root_cause_hints.deviation_type_hints` | 偏差类型（P3-11/P4-14/P5-4）的 R1-R5 检查点 | 偏差类型不再跳过根因核验，RootCause 按 R1-R5 逐项检查 |
