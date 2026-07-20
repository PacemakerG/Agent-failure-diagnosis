# SubAgent-Penetration 规格

## 职责

对每个 Change Intent 的 before-side（AI 原始代码）和 after-side（人工修正后代码），从 N5 向 N1 逐层穿透，定位首因层（first_cause_stage）及其性质（first_cause_nature）。

## 派发时机

Phase 2b 阶段 1（串行三阶段的第一阶段），在 SubAgent-Intent 完成聚类且后置校验通过后派发。按 intent 分批，≤4 并行。

## 主 Agent 传入参数

```json
{
  "intent": {
    "intent_id": "CI-001",
    "intent_label": "修改满赠权益兑换器接口签名并同步更新调用方",
    "diff_nature": "additive",
    "intent_descriptions": {
      "server-H001": "IFullGiftExchanger 原始接口签名缺少 activityNo 参数，人工补充该参数",
      "server-H002": "FullGiftExchangerImpl 原始实现未处理 activityNo 参数，人工补充处理逻辑",
      "server-H005": "Controller 原始调用处未传递 activityNo 参数，人工补充参数传递"
    },
    "hunk_ids": ["server-H001", "server-H002", "server-H005"],
    "hunks": [
      {
        "hunk_id": "server-H001",
        "file_path": "domain/service/IFullGiftExchanger.java",
        "symbol_hint": "exchange",
        "symbol_type": "method",
        "enclosing_class": "IFullGiftExchanger",
        "diff_content": "@@ -10,5 +10,8 @@\n-BenefitExchangeResult exchange(String activityNos);\n+BenefitExchangeResult exchange(String activityNos, String activityNo);",
        "before_code": "BenefitExchangeResult exchange(String activityNos);",
        "after_code": "BenefitExchangeResult exchange(String activityNos, String activityNo);",
        "change_summary": "在 exchange 方法签名中新增 activityNo 参数",
        "diff_nature": "additive",
        "source_commits": [{"sha": "f6f87a5", "task_ref": "T12"}],
        "design_item_ref": "D-07",
        "removed_lines": 1,
        "added_lines": 1
      }
    ]
  },
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
  "artifact_structure_report": "$OUTPUT_DIR/artifact-structure-report.json",
  "problem_types_path": "config/problem-types.json",
  "output_file": "$OUTPUT_DIR/penetration-results/penetration-result-CI-001.json"
}
```

## 核心原则

**产物缺陷优先于 AI 执行偏差**。每层先检查产物是否正确（维度 A），再检查 AI 是否遵循产物（维度 B）。原因：如果产物本身有缺陷，AI 无论是否遵循产物都会出问题，根因方向应指向产物缺陷并继续向上游穿透；只有产物正确时，AI 偏离才是根因。

**硬门禁（Hard Gate）**：`before_vs_artifact` 是判定首因性质的决定性信号，违反此约束的归因结果将被 validate_penetration.py 拒绝（exit code 1）。当 `before_vs_artifact = "consistent"`（AI 代码忠实遵循了产物）时，维度 B 通过，首因性质**不可能**为 `ai_deviation`——此时 after-side 与 before-side 的差异必定源于产物本身的缺陷（维度 A 不通过），应判定为 `product_defect` 并继续穿透。维度 A 检查不能仅停留在产物是否覆盖了 AC 的字面要求，还必须验证产物使用的业务机制（如调用的接口、计算逻辑、数据流向）是否正确——设计项可能覆盖了 AC 但用了错误的机制，这种情况下产物仍然有缺陷。

N5/N4 层为 code ↔ artifact 对比（before-side 和 after-side 直接参与），N3-N1 层为 artifact ↔ artifact 对比（产物间传导检查，before-side 不直接参与，但 after-side 仍参与维度 A 的产物缺陷判定）。

## 维度 A 脚本化模式（§5.7）

主 Agent 在派发 Penetration subagent 前执行 `check_artifact_structure.py`，产出 `artifact-structure-report.json`。SubAgent 逐层检查改为"先读脚本结果，再做语义检查"模式：

**维度 A 检查流程（优化后）**：

1. **结构性检查（脚本已完成，直接读取结果）**：读取 `artifact-structure-report.json` 中该层的检查结果。pass 的项无需再检查；fail 的项记录为结构性缺陷证据，直接判定维度 A 不通过；skip 的项（范围界定失败）由 LLM 在步骤 2 中自行检查
2. **语义检查（LLM 执行）**：对 §5.5 列出的语义检查项 + skip 项进行判断。如果结构性检查全部 pass，但语义检查发现缺陷 → 维度 A 不通过
3. **综合**：结构性 fail 或语义 fail → 维度 A 不通过；全部 pass → 维度 A 通过

**维度 B 检查流程**：不变，仍由 LLM 执行 before-side ↔ artifact 对比。

脚本检查范围限定在 intent 关联的产物模块（D-xx / Task / US-xx），不做全量产物诊断。当范围界定失败时，脚本优雅降级为 skip，不阻塞归因流程。

## Hunk 改动性质预分类

在逐层穿透前，先对 intent 内每个 hunk 的实际 diff 内容进行改动性质分类。改动性质决定该 hunk 是否需要穿透到上游产物层检查产物缺陷，还是可以在 N5 直接归因。

**关键原则**：穿透检查的目标是 hunk 的**改动内容**，而非 hunk 涉及的**文件/模块**。即使 hunk 修改的文件在设计阶段有对应 D-xx，如果 hunk 本身的改动是纯编码细节（如补一个 import），也不应因为 D-xx 存在就穿透到 N4 检查 D-xx 是否完整——import 缺失与设计项完整性无关。

| 改动性质 | 判定条件 | 穿透策略 |
|---|---|---|
| `coding_detail` | import 语句增减、格式调整、命名修正、注释补充、trivial 语法修复——改动不涉及功能逻辑、接口签名或架构约束 | **不穿透上游**：N5 直接判定。检查 constraint-check.md 是否有编码规范 C 项（如 import 顺序、命名约定）；有 C 且 AI 未遵守 → P5-4 执行偏差；无 C → P5-4 R3 模型推理（纯编码错误） |
| `functional_logic` | 业务逻辑、算法实现、条件分支、数据流向修改 | 正常穿透（N5→N4→N3→N2→N1） |
| `non_func_standard` | 日志、监控、异常处理、防御性代码、幂等保护、代码复用/工具方法抽取 | C 引用链穿透（N5→N4→N2，参见各层非功能性检查） |
| `interface_signature` | 接口签名、参数定义、返回类型、DTO 字段修改 | 正常穿透，重点检查 design-interface.md → design.md |
| `structural_refactor` | 代码结构重构（抽取方法、合并逻辑、移动代码位置）不改变功能语义 | C 引用链穿透，KB 分类映射到 how-to |

当 intent 包含多个 hunk 且改动性质不一致时，按「最重改动性质优先」确定 intent 级穿透策略：`functional_logic` > `interface_signature` > `non_func_standard`/`structural_refactor` > `coding_detail`。但 `coding_detail` 性质的 hunk 独立归因到 N5，即使 intent 级首因为更上游层，该 hunk 的归因结果仍独立记录在 `hunk_level_overrides` 中，不被上游产物缺陷裹挟。

## 逐层检查逻辑

### Check-1 (N5 编码计划): before-side ↔ tasks.md + after-side ↔ tasks.md

**维度 A — 产物是否正确**（优先检查）：

**改动性质守卫（coding_detail）**：如果 hunk 改动性质为 `coding_detail`（import、格式、命名等纯编码细节），跳过维度 A 的产物完整性检查（编码细节不属于 tasks.md 职责范围），直接执行编码规范检查：
1. 检查 constraint-check.md 是否有对应的编码规范 C 项（如 import 顺序规范、命名约定等）
2. 如果有 C 项且 before-side 未遵守 → 维度 B 不通过，判定为 P5-4 执行偏差，穿透终止
3. 如果没有 C 项 → 判定为 P5-4（R3 模型推理，纯编码错误），穿透终止。**不继续穿透到 N4**——纯编码细节不是 design.md / requirement.md 应覆盖的范围，穿透上游不会产生有意义的归因

对于非 `coding_detail` 的 hunk，先读取 `artifact-structure-report.json` 的 N5 结构性检查结果（task_dxx_mapping: Task→D-xx 映射完整性 / interface_field_consistency: tasks.md 接口字段与 design-interface.md 一致性），再做以下语义检查：
- after-side 体现的修改是否在 tasks.md 中有对应的 Task 或 Instruction 步骤；如果没有，该修改是否属于 tasks.md 应覆盖的范围（功能拆解、步骤覆盖）
- design.md 的每个 D-xx 是否在 tasks.md 中有对应 Task
- Task 的 Instruction 步骤是否完整覆盖 D-xx 的行为契约
- Task 的 Context/Files/Constraint Ref 是否正确
- **非功能性规范检查**：当 after-side 体现的修改属于非功能性标准（日志、工具方法抽取、编码规范、防御性代码等），检查 Task 是否引用了 constraint-check.md 中对应类别的 C 项。如果 Task 引用了 C 但 before-side 没遵守 → 转维度 B 检查（执行偏差）；如果 Task 未引用 C → 不判定为 N5 产物缺陷（编码规范不在 tasks.md 职责范围），继续穿透到 N4 检查 constraint-check.md

**维度 B — AI 是否遵循编码计划**：before-side 是否按 tasks.md 中的 Task 指令和步骤实现？检查：
- before-side 对应的文件是否在 tasks.md 的 Task Files 字段中有对应 Task
- before-side 的代码逻辑是否按 Task 的 Instruction 步骤实现
- before-side 的接口骨架是否与 tasks.md 接口契约段一致

判定（先 A 后 B）：

1. **A 不通过**（after-side 体现了 tasks.md 缺失的内容，即 tasks.md 偏离 design.md）→ 产物缺陷（problem_nature = "product_defect"），继续穿透到 N4
2. **A 通过**（产物无缺陷）→ 检查 B：
   - B 不通过（before-side 偏离 tasks.md）→ AI 执行偏差（problem_nature = "ai_deviation"），N5 为首因层，穿透终止
   - B 通过（before-side 遵循 tasks.md）→ N5 管辖维度无问题，但 tasks.md 仅覆盖功能维度，代码修改可能涉及架构约束、技术选型等 design.md / constraint-check.md 管辖维度，继续穿透到 N4

### Check-2 (N4 技术方案): before-side ↔ design.md + after-side ↔ design.md

**维度 A — 产物是否正确**（优先检查）：先读取 `artifact-structure-report.json` 的 N4 结构性检查结果（D-xx→US-xx 映射 / ○复用标注交叉验证 / DEC-xx 引用完整性），再做以下语义检查：
- after-side 体现的修改是否在 design.md 中有对应的设计项（D-xx）或决策项（DEC-xx），或在 constraint-check.md 中有对应的约束项；如果没有，该修改是否属于 N4 应覆盖的范围（行为契约、边界条件、技术选型、架构约束、编码规范）
- design.md 的每个设计项是否覆盖了 requirement.md 的用户故事和 AC
- **重要**：每个 D-xx 的 `**对应用户故事**：US-xx` 字段明确标注了该设计项对应的用户故事。在构建 evidence_chain 的 `upstream_snippet` 时，**必须**从该字段提取 US-xx 编号，并在 requirement.md 中找到对应的用户故事原文作为 upstream_snippet。禁止使用 design.md 未标注的其他 US-xx。
- D-xx 的逻辑是否与 AC 的 Given/When/Then 一致
- **§2.1 系统边界图正确性**：design.md §2.1 系统边界图是否与 current-state.md §1 系统结构描述一致（组件名、外部依赖、服务边界）
- **§2.1 ○复用标注交叉验证**：design.md §2.1 标注为 ○复用 的组件，在 after-side 是否被修改？如果被修改 → 标注有误，应为 △修改（人类修改了复用组件说明产物标注错误）
- **§2.2 核心业务链路正确性**：design.md §2.2 核心业务链路图（Mermaid）是否与 requirement.md §2.4 核心操作流和 §2.5 状态机一致（关键节点、分支、步骤顺序）
- DEC-xx 选型是否基于正确的 current-state.md 系统能力和知识库，且与 requirement.md §2.2 In Scope / §2.4 核心操作流 / §2.5 状态机约束一致
- **current-state.md 过时交叉验证**：design.md §2.1 系统边界图和 DEC-xx 选型引用的 current-state.md 描述，是否与实际代码库一致？如果不一致 → current-state.md 过时，向上穿透到 N2
- constraint-check.md 中的架构约束、编码规范、中间件规范是否完整且与设计项一致
- **非功能性 C 引用链检查**（关键新增）：当 after-side 体现的修改属于非功能性标准（日志规范、工具方法抽取、编码规范、架构约束等），按以下顺序检查：
  1. 检查相关 D-xx 是否引用了 constraint-check.md 中对应类别的 C 项。如果 D-xx 引用了 C 且 before-side 没遵守 → 维度 B 不通过，判定为 P4-14 执行偏差，穿透终止
  2. 如果 D-xx 未引用 C → 检查 constraint-check.md 中是否存在对应 C 项。如果 C 存在但 D-xx 未引用 → N4 产物缺陷（design 阶段生成时未关联约束），继续穿透 N2。根因可能是 R2（中间推理已识别但写入时丢失引用）或 R3（模型未识别约束与设计项的关联）
  3. 如果 constraint-check.md 中不存在对应 C 项 → constraint-check.md 缺少该约束条目，继续穿透 N2

**维度 B — AI 是否遵循技术方案**：before-side 是否按 design.md 中的设计项（D-xx）和 constraint-check.md 中的约束实现？检查：
- 接口签名、参数定义是否与 D-xx 行为契约一致
- 数据模型、计算逻辑是否与 D-xx 伪代码一致
- 技术选型是否与 DEC-xx 决策一致
- 接口定义是否与 design-interface.md 一致
- 代码是否遵循 constraint-check.md 中的架构分层、编码规范、中间件使用约束

判定（先 A 后 B）：A 不通过 → 产物缺陷，继续穿透到 N3；A 通过 + B 不通过 → AI 执行偏差，N4 为首因层，穿透终止；A 通过 + B 通过 → 继续穿透到 N3。

**关键约束**：当 `before_vs_artifact = "consistent"`（AI 代码忠实遵循了 design.md）时，维度 B 通过，**不可能**判定为 AI 执行偏差。此时 after-side 与 before-side 的差异必定源于 design.md 本身的缺陷（维度 A 不通过）——例如 design.md 使用了错误的业务机制，AI 忠实实现了这个错误的设计，人工修正了实现方式。这种情况应判定为产物缺陷，按维度 A 不通过处理，继续向上游穿透。维度 A 检查不仅要验证设计项是否覆盖了 AC，还必须验证设计项使用的业务机制是否与 requirement.md AC、current-state.md 和领域知识一致。

### Check-3 (N3 需求澄清): design.md ↔ requirement.md

此层为产物间对比（before-side 不直接参与，但 after-side 仍参与维度 A 判定）：

**维度 A — 需求是否正确**：先读取 `artifact-structure-report.json` 的 N3 结构性检查结果（US→current-state.md 章节存在性 / AC 场景与 In Scope 文本匹配），再做以下语义检查：
- after-side 体现的修改是否反映了 requirement.md 的 AC 遗漏、错误或不完整；如果 AC 正确但人工仍修改了代码，该修改是否属于 requirement.md 应覆盖的范围
- AC 是否与 original-requirement.md 和 feature-points.md 一致
- 用户故事和 AC 是否基于正确的 current-state.md 和知识库
- **范围界定正确性（N3-a）**：In/Out Scope 划分是否与 current-state.md 能力缺口一致（逐条比对 current-state.md §3 差异澄清点与 requirement.md In/Out Scope）
- **操作流完整性（N3-b）**：核心操作流（§2.4 Mermaid 流程图）是否覆盖所有 In Scope 场景及关键分支（异常/超时/回滚/降级）
- **状态机一致性（N3-c）**：状态机（§2.5 Mermaid）是否与操作流（§2.4）的语义对应（状态转换触发条件与操作流步骤一致）
- **AC 与范围操作流一致性（N3-d）**：AC 场景描述是否在 §2.2 In Scope 列表中有对应，且与 §2.4 操作流步骤匹配
- **Review 决议约束有效性（N3-e）**：RD-xx（Review 决议）是否在 design.md 中有设计响应，QA-xx（测试要求）是否有测试覆盖
- **映射表准确性（N3-f）**：§6 映射表中 US-xx 引用的 current-state.md 章节是否存在且准确

**维度 B — 技术方案是否正确反映需求**：design.md 的设计项是否正确映射了 requirement.md？检查：
- design.md 的设计项是否覆盖了 requirement.md 的所有用户故事和 AC
- 设计项的逻辑是否与 AC 一致

判定（先 A 后 B）：A 不通过 → 需求缺陷，继续穿透到 N2；A 通过 + B 不通过 → design.md 映射偏差（归因到 N4 传导），N4 为首因层；A 通过 + B 通过 → 继续穿透到 N2。

### Check-4 (N2 现状梳理): requirement.md ↔ current-state.md + domain-knowledge.md + evidence.md

**维度 A — 现状梳理是否正确**：after-side 体现的修改是否指向 current-state.md / domain-knowledge.md / evidence.md 的缺陷？检查：
- after-side 体现的修改是否反映了现状梳理的遗漏（如入口覆盖缺失、GAP 未识别、领域知识缺失）
- **系统结构准确性（N2-a）**：current-state.md §1 系统结构描述（组件名、服务边界、调用关系）是否与实际代码库一致——如果不一致，说明现状梳理阶段未准确识别系统结构
- **组件描述准确性（N2-b）**：current-state.md §1 组件描述（职责、接口、行为）是否与实际代码库一致——如果不一致，说明现状描述有误
- **外部依赖时效性（N2-c）**：current-state.md §1 外部依赖描述（依赖的服务、接口版本）是否过时——如果实际依赖已变更但 current-state.md 未更新，说明现状梳理阶段未捕获最新依赖
- **交叉验证**：N4 维度 A 的 current-state.md 过时交叉验证结果与此处 N2 检查结果交叉引用——如果 N4 已发现 current-state.md 描述与实际不一致，此处确认根因为 N2 现状梳理缺陷
- current-state.md 的入口覆盖、核心流程记录、影响范围评估是否完整
- evidence.md 的代码证据是否准确
- domain-knowledge.md 的领域知识是否完整
- **知识库分类检查**（关键新增）：当 N4 穿透报告 constraint-check.md 缺少某类约束 C 时，检查 domain-knowledge.md 中是否收录了对应知识库分类条目。根据修改类型映射到知识库分类：
  - 日志规范/架构约束/编码规范/防御性编码 → 检查 not-to 分类
  - 实现模式/最佳实践/工具方法抽取模式/任务拆解惯例 → 检查 how-to 分类
  - 技术选型决策依据 → 检查 complex-clarification 分类
  - 评审门禁/检查清单 → 检查 spec 分类
  - 系统边界/术语/主链路 → 检查 overview 分类
- 如 domain-knowledge.md 中对应分类有该条目但未被加载到 constraint-check.md → R1b 命中（传递损耗），N2 为首因层
- 如 domain-knowledge.md 中对应分类无该条目 → R1a 命中（源头缺失），继续穿透到 N1

**维度 B — 需求是否基于正确现状**：检查：
- requirement.md 的用户故事和 AC 是否考虑了 current-state.md 中的 GAP、能力边界
- 是否引用了 domain-knowledge.md 中的领域知识
- AC 是否与 evidence.md 的代码证据一致

判定（先 A 后 B）：A 不通过 → 现状梳理缺陷，继续穿透到 N1；A 通过 + B 不通过 → 需求未基于现状（归因到 N3 传导），N3 为首因层；A 通过 + B 通过 → 继续穿透到 N1。

### Check-5 (N1 项目初始化): current-state.md ↔ repo.md + work_status.md + original-requirement.md + feature-points.md

**维度 A — PRD 原始功能是否完整**：after-side 体现的修改是否指向 N1 产物的缺陷？检查：
- after-side 体现的修改是否反映了 PRD 功能点遗漏、仓库范围缺失或领域识别错误
- original-requirement.md 和 feature-points.md 是否遗漏了 PRD 中的功能点
- repo.md 的仓库范围是否覆盖了需求涉及的所有模块
- work_status.md 的领域识别是否正确

**维度 B — 知识和范围是否被下游正确使用**：检查：
- current-state.md 是否基于 repo.md 的仓库范围
- domain-knowledge.md 是否覆盖了 work_status.md 识别的领域

判定（先 A 后 B）：A 不通过 → N1 产物缺陷，首因层为 N1；A 通过 + B 不通过 → 知识未被使用（归因到 N2 传导），N2 为首因层；A 通过 + B 通过 → 全链路产物均无问题，触发 Check-6 兜底。

### Check-6 (兜底): 全链路无缺口

如果 Check-1 到 Check-5 均未发现产物缺陷和 AI 执行偏差，但人工确实修改了代码，判定为 P1-3（PRD 原始功能遗漏/有误），归因为 PRD 质量问题（problem_nature = "prd_quality"）。

## 穿透终止规则

单路径逐层检查，无需维护双状态：

- 维度 A 不通过 → 当前层为缺陷层（problem_nature = "product_defect"），继续穿透上一层
- 维度 A 通过 + B 不通过 → 当前层为首因层，穿透终止（N5/N4: AI 执行偏差；N3-N1: 映射偏差，下游层为首因）
- 维度 A 通过 + B 通过 → 当前层无问题，继续穿透上一层
- N1 A 通过 + B 通过 → Check-6 兜底（P1-3 PRD 质量问题）

穿透终止时，首因层 = 最上游有独立缺陷的层。传导层（A 不通过但缺陷由上游传导导致）只是中间节点，标记 problem_nature = "upstream_propagation"，不作为首因层。

## defect_category 判定规则

首因层在 `defect_detail` 中携带 `defect_category` 字段，供 SubAgent-Typing 直接进入正确的决策树起始节点：

| 条件 | defect_category |
|---|---|
| 维度 A 不通过 + after-side 体现的内容在产物中完全缺失 | `existence` |
| 维度 A 不通过 + after-side 体现的内容在产物中存在但有误 | `correctness` |
| 维度 A 不通过 + after-side 体现的内容在产物中部分覆盖 | `completeness` |
| 维度 B 不通过（产物正确但 AI 未遵循，且 before_vs_artifact = "inconsistent"）| `execution_deviation` |

**硬门禁**：当 `before_vs_artifact = "consistent"` 时，维度 B 通过，`defect_category` **不得**为 `execution_deviation`。validate_penetration.py 将拒绝违反此约束的结果。

非首因层不传递 `defect_detail`。

## 输出格式：penetration-result.json

```json
{
  "intent_id": "CI-001",
  "first_cause_stage": "N4",
  "first_cause_nature": "product_defect",
  "first_cause_rationale": "N5 产物缺陷由 N4 传导（tasks.md 正确映射了 design.md 的不完整设计），N3 信号充足（requirement.md AC-02 正确要求按活动维度查询），N4 为缺陷源头",
  "penetration_chain": [
    {
      "layer": "N5",
      "artifact": "tasks.md",
      "has_problem": true,
      "problem_nature": "upstream_propagation",
      "finding": "Task-003 覆盖该文件，步骤齐全但缺少 activityNo 参数处理。tasks.md 正确映射了 design.md D-07 的不完整设计，缺陷由 N4 传导",
      "before_vs_artifact": "consistent",
      "artifact_snippet": "T-003 Instruction: 实现 exchange 方法，参数 activityNos(String)",
      "upstream_artifact": "design.md",
      "upstream_finding": "D-07 行为契约缺少 activityNo 参数边界条件",
      "upstream_snippet": "## D-07 满赠权益兑换\n参数: activityNos(String)..."
    },
    {
      "layer": "N4",
      "artifact": "design.md",
      "has_problem": true,
      "problem_nature": "product_defect",
      "finding": "D-07 设计项缺少 activityNo 参数的边界条件定义，before-side 按 D-07 实现但人工补充了该参数。design.md D-07 与 requirement.md US-02 AC-1 不一致",
      "before_vs_artifact": "consistent",
      "artifact_snippet": "D-07: exchange(activityNos) ← US-02 AC-1: 用户输入活动编号查询",
      "upstream_artifact": "requirement.md",
      "upstream_finding": "US-02 AC-1 要求按活动编号查询，但 D-07 未设计该维度",
      "upstream_snippet": "### US-02 满赠进度查询\nAC-1: 用户输入活动编号查询...",
      "defect_detail": {
        "failed_dimension": "A",
        "defect_category": "existence",
        "defective_items": [
          {
            "item_id": "D-07",
            "item_type": "design_item",
            "issue": "缺少 activityNo 参数边界条件设计（活动不存在时的返回值）",
            "after_side_evidence": "after-side 补充了 activityNo 参数及活动不存在时的空返回逻辑"
          }
        ],
        "upstream_reference": "requirement.md US-02 AC-1: 用户输入活动编号查询满赠进度"
      }
    },
    {
      "layer": "N3",
      "artifact": "requirement.md",
      "has_problem": false,
      "finding": "信号充足，requirement.md US-02 AC-1 正确要求按活动编号维度查询",
      "artifact_snippet": "US-02 AC-1: 用户输入活动编号查询满赠进度",
      "upstream_artifact": null,
      "upstream_finding": null,
      "upstream_snippet": null
    }
  ],
  "checked_layers": ["N5", "N4", "N3"],
  "termination_reason": "N3 信号充足，穿透终止，首因层 = N4"
}
```

**字段说明**：

| 字段 | 说明 | 取值 |
|---|---|---|
| `first_cause_stage` | 首因层 | `"N5"` / `"N4"` / `"N3"` / `"N2"` / `"N1"` |
| `first_cause_nature` | 首因性质 | `"product_defect"` / `"ai_deviation"` / `"prd_quality"` |
| `penetration_chain[].problem_nature` | 该层问题性质 | `"product_defect"` / `"ai_deviation"` / `"upstream_propagation"` |
| `penetration_chain[].before_vs_artifact` | before-side ↔ artifact 对比结论 | `"consistent"` / `"inconsistent"` / `null`（N3-N1 层） |
| `penetration_chain[].artifact` | 该层检查的产物名称 | 如 `"tasks.md"`、`"design.md"` |
| `penetration_chain[].artifact_snippet` | 产物证据片段 | 关键证据文本 |
| `penetration_chain[].upstream_artifact` | 上游产物名称（传导链路） | 如 `"design.md"`，信号充足层为 `null` |
| `penetration_chain[].upstream_finding` | 上游产物缺陷描述 | 传导层指向首因层产物，信号充足层为 `null` |
| `penetration_chain[].upstream_snippet` | 上游产物证据片段 | 关键证据文本，信号充足层为 `null` |
| `defect_detail.failed_dimension` | 首因层哪个维度失败 | `"A"`（产物缺陷）或 `"B"`（AI 执行偏差） |
| `defect_detail.defect_category` | 缺陷类别，映射到决策树起始节点 | `"existence"` / `"correctness"` / `"completeness"` / `"execution_deviation"` |
| `defect_detail.defective_items` | 具体缺陷项列表 | 每项含 `item_id`、`item_type`、`issue`、`after_side_evidence` |
| `defect_detail.upstream_reference` | 上游产物中对应的正确信息 | 如 "requirement.md US-02 AC-1: ..." |

## 边界情况处理

### 产物缺失

当某个阶段产物文件不存在时：
- N5 tasks.md 缺失 → 无法执行 Check-1，标记为 P5-1（任务遗漏），problem_nature = "product_defect"，直接判 N5 为首因层
- N4 design.md 缺失 → 无法执行 Check-2，标记为 P4-3（设计项遗漏），直接判 N4 为首因层
- N3-N1 产物缺失 → 记录为产物缺失信号，继续向上穿透

### before-side 无法提取

当 diff 中 `-` 行为空（纯新增代码，无删除行）时：
- diff_nature = additive，before-side 为空
- 归因方向：检查产物是否要求了该功能/逻辑，如果产物有要求但 before-side 为空 → AI 执行偏差（遗漏实现）
- 如果产物中也没有该要求 → 检查上游产物是否有对应需求

### 多 hunk intent 内归因不一致

当同一 intent 内多个 hunk 的归因结果不一致时：
- 取影响最大的 hunk（removed_lines 最多）的归因结果作为 intent 级归因
- 其他 hunk 的归因差异记录在 `hunk_level_overrides` 字段中
- 如果 hunk 间归因差异跨阶段（如 H001 首因 N4，H002 首因 N5），取最上游的首因层作为 intent 级首因
- **`coding_detail` hunk 独立归因保护**：改动性质为 `coding_detail` 的 hunk（import、格式、命名等）独立归因到 N5（ai_deviation），即使 intent 级首因被其他 hunk 拉到更上游层（如 N4 产物缺陷），该 hunk 的归因结果仍独立记录在 `hunk_level_overrides` 中，标注 `first_cause_stage: "N5"`、`first_cause_nature: "ai_deviation"`、`reason: "coding_detail hunk 独立归因，不随 intent 级上游缺陷裹挟"`
