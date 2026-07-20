# Intent 归因输出格式

## 最终输出：intent-fragments/CI-xxx.json

SubAgent-RootCause 产出的最终归因结果，经 `normalize_hunks.py` 补充确定性推导字段后，写入 `intent-fragments/CI-xxx.json`。

```json
{
  "intent_id": "CI-001",
  "intent_label": "修改满赠权益兑换器接口签名并同步更新调用方",
  "diff_nature": "additive",
  "intent_descriptions": {
    "server-H001": "IFullGiftExchanger 原始接口签名缺少 activityNo 参数，人工补充该参数",
    "server-H002": "FullGiftExchangerImpl 原始实现未处理 activityNo 参数，人工补充处理逻辑",
    "server-H005": "Controller 原始调用处未传递 activityNo 参数，人工补充参数传递"
  },
  "before_code_summary": "AI 原始代码缺少 activityNo 参数的接口签名、实现和调用传递",
  "change_summary": "在接口、实现和调用处统一新增 activityNo 参数",
  "clustering_confidence": "high",
  "is_composite": false,
  "pdg_edges": [
    {"from": "server-H001", "to": "server-H002", "type": "interface_to_impl"},
    {"from": "server-H002", "to": "server-H005", "type": "impl_to_caller"}
  ],
  "hunk_ids": ["server-H001", "server-H002", "server-H005"],

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
      "upstream_snippet": "## D-07 满赠权益兑换\n参数: activityNos(String)..."
    },
    {
      "stage": "N4 技术方案",
      "artifact": "design.md",
      "finding": "D-07 设计项缺少 activityNo 参数的边界条件定义，为独立缺陷。requirement.md US-02 AC-1 要求按活动编号查询但 D-07 未设计该维度",
      "before_vs_artifact": "consistent",
      "artifact_snippet": "## D-07 满赠权益兑换\n参数: activityNos(String, 逗号分隔)\n返回: BenefitExchangeResult",
      "upstream_artifact": "requirement.md",
      "upstream_finding": "requirement.md US-02 AC-1 要求按活动编号查询，但 design.md D-07 未设计活动维度边界条件",
      "upstream_snippet": "### US-02 满赠进度查询\nAC-1: 用户输入活动编号查询..."
    },
    {
      "stage": "N3 需求澄清",
      "artifact": "requirement.md",
      "finding": "信号充足，US-02 AC-1 正确要求按活动编号维度查询",
      "before_vs_artifact": null,
      "artifact_snippet": "### US-02 满赠进度查询\nAC-1: 用户输入活动编号查询满赠进度",
      "upstream_artifact": null,
      "upstream_finding": null,
      "upstream_snippet": null
    }
  ],

  "downstream_propagation": "N5 编码计划：Task-003 步骤缺少 activityNo 边界处理 → 代码返工",
  "propagation_path": "N4 技术方案 设计遗漏（R3 模型推理）→ N5 编码计划 步骤覆盖不全 → 代码返工",
  "confidence": "high",
  "recommendation": "yx-plan 应在设计阶段增加边界条件检查清单，D-07 需补充 activityNo 不存在时的返回值定义",
  "knowledge_check": "domain-knowledge.md 无满赠进度查询的边界条件规范，但知识库存在活动维度查询通用规范",
  "artifact_manifestation": "design.md D-07 缺少 activityNo 不存在时的返回值定义",
  "root_cause_verdict": "设计遗漏 · 模型推理偏差",

  "funnel_trace": {
    "entry_node": 1,
    "entry_source": "defect_category: existence",
    "entry_mismatch": false,
    "all_missed": false
  },

  "surface_issue_type": "FUNC_LOGIC_ERROR",
  "evidence_type": "omission",
  "evidence_type_source": "derived",
  "evidence_type_derivation": "problem_type P4-3 → evidence_type_default: omission",
  "structure_type": "single",
  "structure_type_source": "derived",
  "structure_type_derivation": "R-S2: is_composite = false",

  "impact": {
    "abandonment_impact": 0.15,
    "agcr_impact": 0.12,
    "gap_impact": 0.28,
    "total_removed_lines": 18,
    "total_added_lines": 25
  }
}
```

## 字段来源分类

### SubAgent-Penetration 产出

| 字段 | 说明 |
|---|---|
| `first_cause_stage` | 首因层（N5/N4/N3/N2/N1） |
| `first_cause_nature` | 首因性质（product_defect / ai_deviation / prd_quality） |

### SubAgent-Typing 产出

| 字段 | 说明 |
|---|---|
| `problem_type` | P-code 格式（如 P4-3） |
| `problem_type_label` | 中文标签 |
| `funnel_trace` | 决策树导航轨迹 |

### SubAgent-RootCause 产出

| 字段 | 说明 |
|---|---|
| `root_cause` | R1-R5 |
| `root_cause_label` | 中文标签 |
| `root_cause_variant` | 根因子变体（如 R3） |
| `root_cause_evidence` | 根因判定证据文本 |
| `additional_tags` | 附加标签（如门禁漏检） |
| `direct_cause` | 直接原因描述 |
| `evidence_chain` | 完整证据链（合并三步证据） |
| `downstream_propagation` | 下游传导描述 |
| `propagation_path` | 传导路径 |
| `confidence` | 置信度（high / medium / low） |
| `recommendation` | 改进建议 |
| `knowledge_check` | 知识库检查结论 |
| `artifact_manifestation` | 产物表现 |
| `root_cause_verdict` | 根因判定结论 |

### SubAgent-Intent 产出（passthrough）

| 字段 | 说明 |
|---|---|
| `intent_id` | 意图 ID |
| `intent_label` | 意图标签 |
| `diff_nature` | diff 性质 |
| `intent_descriptions` | 各 hunk 的意图描述 |
| `before_code_summary` | AI 原始代码摘要 |
| `change_summary` | 变更摘要 |
| `clustering_confidence` | 聚类置信度 |
| `is_composite` | 是否复合意图 |
| `pdg_edges` | PDG 依赖边 |
| `hunk_ids` | hunk ID 列表 |

### 脚本确定性推导（详见 derivation-rules.md）

| 字段 | 推导脚本 | 来源 |
|---|---|---|
| `first_cause_skill` | normalize_hunks.py | first_cause_stage 映射 |
| `attribution_direction` | normalize_hunks.py | first_cause_nature 映射 |
| `surface_issue_type` | normalize_hunks.py | problem_type → SIT ID |
| `evidence_type` | normalize_hunks.py | problem_type → evidence_type_default |
| `structure_type` | normalize_hunks.py | is_composite |
| `impact` | calc_agcr.py + aggregate_stats.py | hunk-level 统计 |
