# SubAgent-RootCause 规格

## 职责

消费 SubAgent-Typing 产出的 `typing-result.json` 中的 `problem_type` + `root_cause_hints`，加载 `problem-types.json` 中该类型的 root_cause_variants，逐条核验 R1-R5。输出最终归因结果 `intent-fragments/CI-xxx.json`。

## 派发时机

Phase 2b 阶段 3（串行三阶段的第三阶段），在 SubAgent-Typing 全部完成且 `validate_typing.py` 校验通过后派发。按 intent 分批，≤4 并行。

## 主 Agent 传入参数

```json
{
  "typing_result": "$OUTPUT_DIR/typing-results/typing-result-CI-001.json",
  "penetration_result": "$OUTPUT_DIR/penetration-results/penetration-result-CI-001.json",
  "change_intents": "$OUTPUT_DIR/hunks/change-intents.json",
  "problem_types_path": "config/problem-types.json",
  "artifact_map": {
    "design":           "$OUTPUT_DIR/artifacts/design.md",
    "design_interface": "$OUTPUT_DIR/artifacts/design-interface.md",
    "requirement":      "$OUTPUT_DIR/artifacts/requirement.md",
    "tasks":            "$OUTPUT_DIR/artifacts/tasks.md",
    "current_state":    "$OUTPUT_DIR/artifacts/current-state.md",
    "original_requirement": "$OUTPUT_DIR/artifacts/original-requirement.md",
    "feature_points":   "$OUTPUT_DIR/artifacts/feature-points.md",
    "domain_knowledge": "$OUTPUT_DIR/artifacts/domain-knowledge.md",
    "evidence":         "$OUTPUT_DIR/artifacts/evidence.md",
    "constraint_check": "$OUTPUT_DIR/artifacts/constraint-check.md",
    "repo_scope":       "$OUTPUT_DIR/artifacts/repo.md",
    "work_status":      "$OUTPUT_DIR/artifacts/work_status.md",
    "clarification_log":    "$OUTPUT_DIR/artifacts/clarification-log.md",
    "clarification_summary":"$OUTPUT_DIR/artifacts/clarification-summary.md"
  },
  "execution_trace": "$OUTPUT_DIR/artifacts/execution_trace.json",
  "output_file": "$OUTPUT_DIR/intent-fragments/CI-001.json"
}
```

## 首因阶段 → execution_trace 阶段映射

`execution_trace.json` 的 `stages` 字段按 phase_name 组织各阶段执行轨迹（skill_invocation / knowledge_retrieval / write / reasoning 事件）。根据 `penetration_result.first_cause_stage` 确定需要读取的 trace 阶段：

| first_cause_stage | 关联产物 | trace 阶段（phase_name 模糊匹配） | 重点检查事件 |
|---|---|---|---|
| N5 编码计划 | tasks.md | `coding_plan` / `coding_planning` | write_events（tasks.md 写入）、reasoning_events（步骤展开推理） |
| N4 技术方案 | design.md, design-interface.md, constraint-check.md | `tech_design` / `design` / `constraint` | knowledge_retrieval（知识库 Read/Grep）、write_events（产物写入）、reasoning_events（设计推理） |
| N3 需求澄清 | requirement.md | `requirement` / `clarification` | knowledge_retrieval、reasoning_events（AC 推导） |
| N2 现状梳理 | current-state.md, domain-knowledge.md, constraint-check.md | `current_state` / `domain_knowledge` / `constraint` | knowledge_retrieval（知识库检索）、write_events（知识加载到产物） |
| N1 项目初始化 | repo.md, work_status.md, original-requirement.md, feature-points.md | `scope_bootstrap` | knowledge_retrieval、write_events |

**匹配策略**：phase_name 可能因 CLI SDK 版本不同而有差异。如果上表中的名称未精确匹配，按以下策略查找：
1. 读取 `execution_trace.json` 的 `stages` 字段，列出所有 phase_name
2. 用关键词模糊匹配（如 `first_cause_stage = "N4"` 时，匹配包含 `design` 或 `tech` 的 phase_name）
3. 也可通过 `skill_events` 中的 skill_name 反查（如 skill_name 含 `yx-plan` → N4 阶段，含 `yx-code` → N5 阶段）
4. 定位到阶段后，重点读取该阶段的 `timeline` 中的 `knowledge_retrieval`（R1b 召回检查）和 `write_events`（R2 执行损耗对比）事件

## 根因核验流程

根据 problem_type 加载其 root_cause_variants（从 problem-types.json），结合 typing_evidence_detail 中的 `root_cause_hints`（直接定位检查目标）和 `defective_items_from_penetration`（已定位的缺陷项），逐条核验每个根因的 evidence_hint：

1. **R1a 源头缺失**：检查 `root_cause_hints.knowledge_artifact`（如 domain-knowledge.md）和知识库中是否存在完成该步骤所需的领域知识。如果知识库中无相关记录 → R1a 命中。
   - evidence_hint: 检查对应 knowledge/domain-knowledge/external-entry-index.md 是否有记录
   - **知识库分类映射**：根据 problem_type 的 R1 变体中 `knowledge_base_category` 字段（或 attribution_stages 的 `knowledge_base_categories`），定位到知识库的具体分类进行检查：
     - 架构约束/编码规范/日志规范/防御性编码/稳定性规范 → 检查 `not-to` 分类
     - 实现模式/最佳实践/工具方法抽取模式/任务拆解惯例 → 检查 `how-to` 分类
     - 技术选型决策依据 → 检查 `complex-clarification` 分类
     - 评审门禁/检查清单 → 检查 `spec` 分类
     - 系统边界/术语/主链路 → 检查 `overview` 分类
   - 如果对应分类中无相关记录 → R1a 命中；在 `root_cause_evidence` 中注明"知识库 {分类} 分类缺少 {问题类型} 相关条目"

2. **R1b 传递损耗**：检查知识库中有记录，但 `root_cause_hints.knowledge_artifact` 或上游产物中未引用该知识。如果知识存在但未被加载到产物中 → R1b 命中。
   - evidence_hint: 若有记录，读取 `execution_trace.json` 中首因阶段对应 trace 的 `knowledge_retrieval` 事件，检查是否检索了对应知识库分类条目（参见「首因阶段 → execution_trace 阶段映射」）
   - **知识库分类映射**：检查对应知识库分类中的条目是否被加载到 domain-knowledge.md / constraint-check.md：
     - 如 `not-to` 分类有日志规范条目，但 constraint-check.md 未收录 → R1b 命中（传递损耗）
     - 如 `how-to` 分类有代码复用模式条目，但 design.md/constraint-check.md 未引用 → R1b 命中
   - 在 `root_cause_evidence` 中注明"知识库 {分类} 分类有 {条目} 但未加载到 {产物}"

3. **R2 执行损耗**：检查 `root_cause_hints.upstream_artifact`（如 requirement.md）中有该信息，但在当前阶段产物的写入/合并过程中丢失。
   - evidence_hint: 读取 `execution_trace.json` 中首因阶段对应 trace 的 `reasoning_events` 和 `write_events`，对比中间推理结果与最终写入产出物内容（参见「首因阶段 → execution_trace 阶段映射」）

4. **R3 模型推理**：知识和信息都充分且已加载到上下文，但模型推理产生偏差。使用 `defective_items_from_penetration` 中的缺陷项与 `evidence_detail.after_side_evidence` 对比模型输出与人工修正。
   - evidence_hint: 逐条对比输入产出物（如 design.md D-xx）与输出产出物（如 tasks.md 覆盖矩阵），检查一致性

5. **R4 门禁漏检**：检查 `root_cause_hints.gate_artifact`（如 design-review.md）是否应该拦截该问题但未拦截。
   - evidence_hint: 复查各阶段 gate 文件各检查项及判定结论
   - Gate 文件对应：N5=plan-review.md, N4=design-review.md, N3=requirement-gate.md, N2=baseline-gate.md

6. **R5 澄清交互不充分**（仅 P3/P4）：检查 `root_cause_hints.clarification_artifacts`（如 clarification-log.md 和 clarification-summary.md），模型是否在澄清环节就关键问题提问。
   - evidence_hint: 检查 clarification-log.md 或澄清记录中是否有针对该问题点的提问与回答

如果多个根因同时命中，取证据链最直接的根因。

## 特殊处理

### 偏差类型（P3-11/P4-14/P5-4）完整根因核验

偏差类型不再跳过根因核验。SubAgent-RootCause 对偏差类型执行完整的 R1-R5 根因检查链路，与产物缺陷类型一致。偏差类型的根因可能是：
- **R1a/R1b**：根据修改类型映射到知识库分类检查——
  - 日志规范缺失 → 检查 `not-to` 分类是否有日志规范条目
  - 工具方法抽取模式缺失 → 检查 `how-to` 分类是否有代码复用模式
  - 架构约束违反 → 检查 `not-to` 分类是否有架构约束条目
  - 编码规范偏离 → 检查 `not-to` 分类是否有编码规范条目
  - 若对应分类无记录 → R1a 命中；若有记录但未加载到 constraint-check.md → R1b 命中
- **R2**：上游产物（requirement.md/design.md/tasks.md）中有该约束，但在当前阶段产物的写入/合并过程中丢失
- **R3**：知识和信息都充分且已加载到上下文，但模型推理产生偏离（偏离了产物中的约束）
- **R4**：门禁应该拦截该偏离但未拦截
- **R5**：澄清环节是否就该约束提问

偏差类型的 `root_cause_hints.deviation_type_hints`（由 SubAgent-Typing 输出）提供 R1-R5 各检查点的具体产物路径。**前提条件**：偏差类型的 `before_vs_artifact` 必须为 `"inconsistent"`（经 SubAgent-Penetration 硬门禁验证 AI 确实偏离了产物）。

### P1-3（PRD 质量问题）无根因

PRD 遗漏属于外部源头问题，不适用 R1-R5，root_cause = null。

### R4 门禁漏检作为附加标签

R4 通常是伴随性根因。如果首因根因是 R1/R2/R3/R5，但同时发现门禁应该拦截但未拦截，则 R4 记入 `additional_tags` 而非作为主根因。只有当问题本身无法归因到 R1/R2/R3/R5 时，才将 R4 作为主根因。

### confidence 字段继承规则

`confidence` 字段**必须**从 `change-intents.json` 中该 intent_id 对应的 `cluster_confidence` 字段继承，不得自行默认填写 `medium`。

继承流程：
1. 读取传入参数 `change_intents` 指向的 `change-intents.json` 文件
2. 在 `change_intents` 数组中找到与当前 `intent_id` 匹配的条目
3. 取其 `cluster_confidence` 值（`high`/`medium`/`low`），直接写入输出的 `confidence` 字段
4. 如果 `change-intents.json` 中找不到匹配的 `intent_id`，回退为 `low` 并在 `root_cause_evidence` 中说明原因

**禁止行为**：不读取 `change-intents.json` 而统一写 `confidence: "medium"`，这会导致报告中所有意图的置信度都显示为"中"，丢失聚类阶段的高/低置信度区分。

## 输出格式：intent-fragments/CI-xxx.json

合并 Penetration 的穿透证据和 Typing 的类型证据，形成最终归因结果。

**注意**：`problem_type` 字段必须沿用 SubAgent-Typing 输出的 P-code（如 `P4-3`），严禁在此步骤替换为 SIT ID。`surface_issue_type` 字段不在本输出中——它由下游 `normalize_hunks.py` 从 `problem_type` 自动推导。

```json
{
  "intent_id": "CI-001",
  "first_cause_stage": "N4 技术方案",
  "first_cause_skill": "yx-plan",
  "first_cause_nature": "product_defect",
  "problem_type": "P4-3",
  "problem_type_label": "设计项遗漏",
  "root_cause": "R3",
  "root_cause_label": "模型推理",
  "root_cause_variant": "R3",
  "root_cause_evidence": "domain-knowledge.md 无满赠进度查询的边界条件规范，但 requirement.md US-02 AC-1 明确要求按活动编号查询，知识库中存在活动维度查询的通用规范。模型在设计 D-07 时未从 AC-1 推理出需要 activityNo 参数边界条件，属于推理偏差而非知识缺失",
  "additional_tags": ["门禁漏检"],
  "direct_cause": "AI 原始代码缺少 activityNo 参数的接口签名设计和实现",
  "attribution_direction": "artifact_defect",
  "evidence_chain": [
    {
      "stage": "N5 编码计划",
      "artifact": "tasks.md",
      "finding": "Task-003 覆盖该文件，步骤齐全但缺少 activityNo 参数处理。tasks.md 正确映射了 design.md D-07 的不完整设计，缺陷由 N4 传导",
      "before_vs_artifact": "consistent",
      "artifact_snippet": "### T-003: FullGiftExchanger\nInstruction:\n1. 实现 exchange 方法...",
      "upstream_artifact": "design.md",
      "upstream_finding": "D-07 行为契约缺少 activityNo 参数边界条件，tasks.md 正确映射了不完整的设计",
      "upstream_snippet": "## D-07 满赠权益兑换\n参数: activityNos(String)...",
      "dependency_path": "D-07 设计缺陷 (缺少 activityNo 边界条件) → tasks.md Task-003 步骤未覆盖该参数 → AI 代码忠实实现 (before-side 缺少 activityNo)"
    },
    {
      "stage": "N4 技术方案",
      "artifact": "design.md",
      "finding": "D-07 设计项缺少 activityNo 参数的边界条件定义（如活动不存在时的返回值），为独立缺陷。requirement.md US-02 AC-1 要求按活动编号查询但 D-07 未设计该维度",
      "before_vs_artifact": "consistent",
      "artifact_snippet": "## D-07 满赠权益兑换\n参数: activityNos(String, 逗号分隔)\n返回: BenefitExchangeResult",
      "upstream_artifact": "requirement.md",
      "upstream_finding": "requirement.md US-02 AC-1 要求按活动编号查询，但 design.md D-07 未设计活动维度边界条件",
      "upstream_snippet": "### US-02 满赠进度查询\nAC-1: 用户输入活动编号查询...",
      "dependency_path": "requirement.md US-02 AC-1 (活动编号查询要求) → design.md D-07 行为契约 (缺少 activityNo 边界条件) → §2.2 链路图子流程 (兑换流程缺少活动不存在分支) → design-interface.md 接口定义 (缺少 activityNo 参数) → tasks.md 接口契约段 (缺少 activityNo 参数) → AI 代码忠实实现"
    },
    {
      "stage": "N3 需求澄清",
      "artifact": "requirement.md",
      "finding": "信号充足，US-02 AC-1 正确要求按活动编号维度查询",
      "before_vs_artifact": null,
      "artifact_snippet": "### US-02 满赠进度查询\nAC-1: 用户输入活动编号查询满赠进度",
      "upstream_artifact": null,
      "upstream_finding": null,
      "upstream_snippet": null,
      "dependency_path": null
    }
  ],
  "downstream_propagation": "N5 编码计划：Task-003 步骤缺少 activityNo 边界处理 → 代码返工",
  "propagation_path": "N4 技术方案 设计遗漏（R3 模型推理）→ N5 编码计划 步骤覆盖不全 → 代码返工",
  "confidence": "high",
  "confidence_source": "从 change-intents.json 中该 intent_id 的 cluster_confidence 字段继承。禁止默认写 medium——必须读取 change-intents.json 并继承 cluster_confidence 值。",
  "recommendation": "yx-plan 应在设计阶段增加边界条件检查清单，D-07 需补充 activityNo 不存在时的返回值定义",
  "knowledge_check": "domain-knowledge.md 无满赠进度查询的边界条件规范，但知识库存在活动维度查询通用规范",
  "artifact_manifestation": "design.md D-07 缺少 activityNo 不存在时的返回值定义",
  "root_cause_verdict": "设计遗漏 · 模型推理偏差",
  "impact": {
    "abandonment_impact": 0.15,
    "agcr_impact": 0.12,
    "total_removed_lines": 18,
    "total_added_lines": 25
  }
}
```

## evidence_chain 构建规则

**格式统一约束**：evidence_chain 中每个条目必须包含以下标准字段：`stage`、`artifact`、`finding`、`before_vs_artifact`、`upstream_artifact`、`upstream_finding`、`upstream_snippet`、`dependency_path`。禁止使用 `doc`/`section`/`snippet`/`relevance` 等非标准字段名。

**各层构建规则**：
- **首因层**：完整字段。dependency_path 标注缺陷源头到下游的完整传导路径，格式为 `缺陷源 (描述) → 下游1 (描述) → 下游2 (描述) → ...`。传导路径沿固定依赖链展开，如 `DEC-xx 选型偏差 → 级联 D-xx 设计失效 → §2.2 链路图子流程错误 → design-interface.md 接口定义同步 → tasks.md 接口契约段同步 → AI 代码忠实实现`。当首因层为 N4 且涉及 design.md 时，dependency_path 必须包含 design.md §2.2 链路图节点引用
- **传导层**（首因层到 N5 之间的层）：传导描述（finding 说明缺陷如何从首因层传导到此层，upstream_finding 指向首因层产物）。dependency_path 标注本层在传导链中的位置，格式为 `上游缺陷源 (描述) → 本层产物 (传导方式) → 下游 (描述)`
- **信号充足层**（穿透终止层）：仅一行确认（finding = "信号充足"），upstream 字段为 null，dependency_path 为 null
- `before_vs_artifact` 在 N5/N4 层必填（记录 before-side ↔ artifact 和 after-side ↔ artifact 的对比结论），N3-N1 层为 null（N3-N1 为 artifact↔artifact 对比，before-side 不直接参与）

**upstream_snippet 完整性约束**（硬约束）：当 `upstream_artifact` 不为 null 时，`upstream_snippet` 必须包含 upstream_artifact 中的具体文本片段（至少一行），禁止为 null 或空字符串。传导层的 upstream_snippet 应包含首因层产物中导致传导的具体条目文本。信号充足层的 upstream 字段全部为 null。下游 `validate_subagent_output.py` 会校验此约束。

**D-xx → US-xx 映射一致性**：当首因层为 N4 且 artifact 为 design.md 时，必须从 D-xx 的 `**对应用户故事**：US-xx` 字段提取用户故事编号，在 requirement.md 中找到对应原文作为 `upstream_snippet`。禁止引用 design.md 中 D-xx 未标注的其他 US-xx。下游 `validate_subagent_output.py --design-md` 会交叉校验此一致性。

**偏差类型 evidence_chain 特殊规则**：偏差类型（P3-11/P4-14/P5-4）的首因层 evidence_chain 中，`before_vs_artifact` 必须为 `"inconsistent"`，`dependency_path` 的终端节点应标注 `AI 代码偏离产物约束 (描述偏离的具体约束)`，而非 `AI 代码忠实实现`。
