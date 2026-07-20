# SubAgent-Intent 规格

## 职责

对 Hunk 列表执行三层 Change Intent 聚类（第零层 D-xx 设计项预聚类由主 Agent 预执行，第一层 GitNexus PDG 硬聚类 + 跨仓符号匹配由主 Agent 预执行，第二层 LLM diff 语义聚类由 SubAgent 执行），提取 before-side 并判定 diff_nature，输出 `change-intents.json`。聚类完成后由主 Agent 执行后置校验（`validate_subagent_output.py --mode intent`）和 evidence_type / structure_type 确定性推导。

## 派发时机

Phase 2a，与 SubAgent-AGCR 同时派发，互不依赖。

## 主 Agent 传入参数

```json
{
  "hunks": [
    {
      "hunk_id": "server-H001",
      "repo": "bizad_server",
      "file_path": "domain/service/Foo.java",
      "diff_content": "@@ -10,5 +10,8 @@\n-旧代码\n+新代码",
      "symbol_hint": "FooService",
      "symbol_type": "method",
      "enclosing_class": "FooService",
      "source_commits": [{"sha": "f6f87a5", "task_ref": "T12", "commit_message": "[FIX-1234] 修复满赠逻辑"}],
      "design_item_ref": "D-03",
      "design_cluster_id": "D-03",
      "excluded": false,
      "removed_lines": 3,
      "added_lines": 6
    }
  ],
  "design_cluster_path": "$OUTPUT_DIR/hunks/design-cluster-hints.json",
  "pre_cluster_path": "$OUTPUT_DIR/hunks/pre-cluster-hints.json",
  "output_file": "$OUTPUT_DIR/hunks/change-intents.json"
}
```

`design_cluster_id`（可选）：来自 Layer 0 输出。当 hunk 能通过 tasks.md 的 D-xx → file_path 映射匹配到某个设计项时，填入 D-xx 编号；匹配不到时不填或为 null。`design_cluster_path` 指向 Layer 0 输出的 `design-cluster-hints.json`。两者缺失时（如非 yx-plan 产出的项目），Layer 0 跳过，聚类退化为 Layer 1 + Layer 2 两层。

## Layer 0 — D-xx 设计项预聚类（主 Agent 执行，聚类前）

主 Agent 在执行 Layer 1 PDG 硬聚类前，先从 `tasks.md` 解析 D-xx 设计项 → 文件路径映射，为 hunk 打上 `design_cluster_id`。tasks.md 是 yx-plan Phase 15 的强制产物，每个任务包含 `覆盖: D-xx` 标注和 `Files:` 文件清单。

### 解析逻辑

从 tasks.md 文本中解析两层映射：

第一层：`任务 → D-xx`。从每个任务段的 `覆盖: D-xx` 行解析。一个任务可覆盖多个 D-xx（如 `覆盖: D-03、D-06、D-07`），此时该任务的 Files 下所有文件同时映射到这三个 D-xx。

第二层：`任务 → [file_path]`。从每个任务段的 `Files:` 块解析，每行 `Add:` / `Modify:` / `Delete:` 后提取文件路径。文件路径可能带仓库前缀（如 `bizad-benefit-exchange-server-domain/src/main/java/...`）或 worktree 注释（如 `Files（bizad_user_benefit_exchange_client worktree）:`）。

两层 join 后得到 `D-xx → [file_path]` 映射表。同时解析 tasks.md 末尾的覆盖矩阵（`| Design | D-xx ... | T-xx | Covered | ... |`）作为交叉校验。

### 匹配逻辑

将 `D-xx → [file_path]` 映射与 hunk-list.json 中的 hunk 按 file_path 做匹配，匹配策略分三级：

1. **精确匹配**：hunk 的 file_path 与 tasks.md 的 file_path 完全一致（去除仓库 worktree 前缀后比较）。
2. **前缀匹配**：当 tasks.md 的 file_path 出现 `...` 通配符时（如 `src/main/java/...（mvn generate 自动生成）`），取通配符前的目录前缀做 hunk file_path 的前缀匹配。适用于 thrift codegen 生成的 Java 存根文件。
3. **目录匹配**：hunk 的 file_path 所在目录与 tasks.md 中同一 D-xx 下其他已匹配文件的目录相同。适用于同目录下的关联文件（如同一 package 下的 DTO + Res + Service）。

匹配到 hunk 打上 `design_cluster_id`（D-xx 编号）。一个 hunk 可能匹配到多个 D-xx（如某文件同时被 D-03 和 D-06 覆盖），此时取覆盖矩阵中该文件出现次数最多的 D-xx；若无法区分，取编号较小的 D-xx 并在 `design_cluster_conflict` 字段中记录所有候选。

匹配不到的 hunk 标记为 `unmapped`，`design_cluster_id` 为 null。

### 输出

`design-cluster-hints.json` 结构：
```json
{
  "design_clusters": [
    {"design_cluster_id": "D-06", "hunk_ids": ["server-H001", "server-H017", "client-H003", "api-H001", "api-H002", "client-H001", "client-H002", "client-H004", "client-H005", "client-H006"], "task_refs": ["C1", "T9", "T14"]},
    {"design_cluster_id": "D-01", "hunk_ids": ["server-H007", "server-H011"], "task_refs": ["T1", "T11"]}
  ],
  "unmapped_hunks": ["server-H003", "server-H006"],
  "task_coverage": {
    "D-06": {"tasks": ["C1", "T9", "T14"], "files": ["etc/thrift/fullgift/service/IFullGiftService.thrift", "..."]},
    "D-01": {"tasks": ["T1", "T11"], "files": ["..."]}
  }
}
```

### 核心约束

Layer 0 只做合并增强，不做分裂。有映射的 hunk 打上 design_cluster_id，后续 Layer 1 和 Layer 2 倾向合并同一 design_cluster_id 的 hunk。没有映射的 hunk 正常往下走，不丢弃不惩罚。

`unmapped` 状态本身作为归因元数据保留，可用于 Step 1 渗透阶段辅助判断 `design_coverage`：全 unmapped 的 CI 更可能是 ai_deviation（AI 做了设计阶段未预期的改动），有映射且 `before_vs_artifact = "consistent"` 的 CI 更可能是 product_defect（AI 忠实实现了设计，问题在设计本身）。

### 信息维度说明

Layer 0 的 D-xx 映射来自 yx-plan 正向阶段的设计意图推导（Phase 3 Design Index: US/AC → 改动簇 → 需要改动的仓库/模块 → D-xx → 改动点 → 文件清单），不是代码结构分析。它覆盖了 PDG 的跨仓盲区和设计意图盲区——同一个设计决策（如"新建独立 Thrift 服务"）在不同仓库产生的文件变更（client IDL + server Gateway + api Controller）通过 D-xx 编号直接关联，无需代码依赖分析。

当 tasks.md 不存在时（非 yx-plan 产出的项目），Layer 0 跳过，聚类退化为 Layer 1 + Layer 2 两层。

## Layer 1 — GitNexus PDG 硬聚类 + 跨仓符号匹配（主 Agent 执行，聚类前）

主 Agent 在派发 SubAgent-Intent 前运行 `pre_cluster.py`，批量查询 GitNexus 获取 hunk 间 PDG 边，执行确定性硬聚类。pre_cluster.py 同时读取 Layer 0 输出的 `design-cluster-hints.json` 和 hunk-list.json 的 `symbol_hint` / `enclosing_class` 字段，执行跨仓符号匹配：

```bash
python3 "$SCRIPT_DIR/pre_cluster.py" \
  --hunk-list "$OUTPUT_DIR/hunks/hunk-list.json" \
  --design-cluster "$OUTPUT_DIR/hunks/design-cluster-hints.json" \
  --output "$OUTPUT_DIR/hunks/pre-cluster-hints.json"
```

硬聚类规则：
1. 同一 `design_cluster_id` 的 hunk → must_merge（Layer 0 设计项映射是最强的合并信号——D-xx 映射来自 yx-plan 正向阶段的设计意图推导，直接表示这些 hunk 服务于同一设计决策）
2. 跨仓符号匹配 → likely_merge（候选同组，交由 Layer 2 LLM 判断）。匹配条件（满足任一）：
   - 条件 a：不同 repo 的 hunk 的 `symbol_hint` 完全相同且不为通用方法名（排除 `toString`、`equals`、`hashCode`、`getValue`、`setValue` 等）
   - 条件 b：不同 repo 的 hunk 的 `enclosing_class` 完全相同（如 client 仓和 server 仓都有 `IFullGiftService` 相关 hunk）
   - 条件 c：同 repo 不同文件的 hunk 的 `symbol_hint` 相同且 `enclosing_class` 存在继承/实现关系（如 `IFullGiftAppService` 接口和 `FullGiftAppService` 实现类的 `queryFullGiftUserStatus`）
   > 跨仓符号匹配用 likely_merge 而非 must_merge，因为相同符号名不必然意味着同一设计意图——可能是巧合命名或同一接口的不同版本变更。但如果这些 hunk 同时有相同的 `design_cluster_id`，则规则 1 优先，直接 must_merge。
3. PDG 强依赖边（接口↔实现、方法↔调用方）→ must_merge（确定性归为同一 cluster）
4. ast_hunk_split.py merge_suggestions（同文件同方法）→ must_merge
5. PDG 弱依赖边（共享变量、同模块引用）→ likely_merge（候选同组，交由 Layer 2 LLM 判断）
6. excluded = true 的 hunk → 不参与聚类

**PDG 已知盲区**（Layer 0 和跨仓符号匹配的补充依据）：
- **跨仓 PDG 断链**：PDG 按单仓代码图构建，无法追踪跨仓 jar 依赖符号。server 仓 `implements IFullGiftService.Iface` 中的 `IFullGiftService` 来自 client 仓的 Maven jar 依赖，PDG 解析为外部符号，不产生跨仓边。
- **thrift/IDL codegen 关系不可见**：PDG 不理解 thrift-maven-plugin 的 `.thrift` → `.java` 生成关系。`FullGiftUserStatusDTO.thrift` 和自动生成的 `FullGiftUserStatusDTO.java` 在 PDG 看来是无关联文件。
- **thrift include 结构不可见**：PDG 不解析 `.thrift` 文件的 include 链。`IFullGiftService.thrift` include `FullGiftUserStatusRes.thrift`，后者又 include `FullGiftUserStatusDTO.thrift`——三个 .thrift 文件在 PDG 看来是三个孤岛。
- **schema 协同变更不可见**：字段删除（如移除 triggerPoint）在 Interface → Impl → Mapper → MyBatis XML 四层的投影是协同变更，PDG 只能看到 call chain 上的结构依赖，看不到数据字段级别的协同删除关系。

**设计原则**：Layer 0 补充设计意图维度（D-xx 映射覆盖跨仓、codegen、schema 协同等 PDG 盲区），Layer 1 补充代码结构维度（PDG 边 + 跨仓符号匹配）。两个维度有交集（call chain 上的协同变更两者都能抓到），但不重叠部分恰好互补。task_ref 和 design_item_ref 不作为硬聚类依据，仅作为 Layer 2 的可选 bonus signal。

输出 `pre-cluster-hints.json` 结构：
```json
{
  "must_merge": [
    ["server-H001", "server-H002"],
    ["client-H001", "client-H002", "client-H004"]
  ],
  "likely_merge": [
    ["server-H001", "server-H017"],
    ["server-H001", "client-H006"]
  ],
  "pdg_edges": [
    {"from": "server-H001", "to": "server-H002", "type": "interface_to_impl", "strength": "strong"},
    {"from": "server-H001", "to": "server-H003", "type": "shared_variable", "strength": "weak"}
  ],
  "cross_repo_symbol_edges": [
    {"from": "server-H017", "to": "client-H006", "match": "symbol_hint", "value": "queryFullGiftUserStatus", "strength": "likely"},
    {"from": "server-H001", "to": "server-H017", "match": "enclosing_class_inheritance", "value": "IFullGiftAppService→FullGiftAppService", "strength": "likely"}
  ],
  "design_cluster_edges": [
    {"design_cluster_id": "D-06", "hunk_ids": ["server-H001", "server-H017", "client-H003", "api-H001", "api-H002", "client-H001", "client-H002", "client-H004", "client-H005", "client-H006"], "method": "layer0_design_cluster"}
  ],
  "resolved_intents": [
    {"intent_id": "CI-001", "hunk_ids": ["server-H001", "server-H002"], "method": "pdg_hard_merge"},
    {"intent_id": "CI-002", "hunk_ids": ["client-H001", "client-H002", "client-H004", "client-H005", "client-H006", "server-H017", "api-H001", "api-H002"], "method": "layer0_design_cluster"}
  ],
  "unclustered": ["server-H003", "server-H004", "server-H005"]
}
```

已被 must_merge 确定性分组的 hunk 直接归为同一 intent，不进入 Layer 2。unclustered 中的 hunk 进入 Layer 2 LLM 语义聚类。

## Layer 2 — LLM Diff 语义聚类（SubAgent-Intent 执行）

对 Layer 1 未确定性分组的 hunk，启动 LLM 语义聚类。采用 rationale-driven 两步法（借鉴 Atomizer），而非直接让 LLM 输出聚类结果。

### LLM 输入

- hunk 的 diff_content（主信号）
- hunk 的 symbol_hint、enclosing_class
- source_commits 的 commit_message 关键词（辅助输入，提供意图先验）
- Layer 1 的 likely_merge 建议和 pdg_edges
- task_ref / design_item_ref（可选 bonus signal，存在时提升置信度，缺失时不影响聚类）

### Step 1：before-side 提取 + diff_nature 判定 + intent_description 生成

对每个非 excluded hunk 执行三个子步骤：

#### 1a：before-side 提取

从 diff_content 中提取 AI 原始代码和人工修正后代码：
- `before_code`：diff 中 `-` 行（去掉前缀 `-`）拼接，代表 AI 原始代码片段
- `after_code`：diff 中 `+` 行（去掉前缀 `+`）拼接，代表人工修正后代码片段
- `change_summary`：before → after 的变化摘要（1-2 句话，描述人工做了什么修正）

#### 1b：diff_nature 判定

基于 before-code 和 after-code 的对比，判定修改性质：

| diff_nature | 判定信号 | 含义 |
|---|---|---|
| `corrective` | after 修改了 before 中的条件/逻辑/计算公式，且修改方向是修正错误 | 人工修正了 AI 代码中的逻辑错误 |
| `additive` | after 在 before 基础上新增了代码块（新增分支/方法/处理逻辑），before 无对应实现 | 人工补充了 AI 遗漏的功能 |
| `subtractive` | after 删除了 before 中的代码块，且未替换为其他实现 | 人工删除了 AI 不应生成的代码 |
| `refining` | after 重命名/调整格式/提取方法/内联变量，功能行为不变 | 人工重构优化 AI 代码（非功能变更） |

> 判定约束：必须基于 before-code 和 after-code 的实际代码对比，禁止仅凭 commit_message 判定。commit_message 可作为辅助参考但不凌驾于代码对比之上。

#### 1c：intent_description 生成

**方向变化**：intent_description 描述 AI 原始代码（before-side）的缺陷，而非人工修改动作。

格式模板：`{symbol} 原始代码{问题描述}，人工{修正方向}`

示例：
- `FullGiftExchanger.checkGift 原始代码满减互斥判断使用 OR 条件导致满赠与满减可同时触发，人工修正为 AND 条件`
- `BenefitController 原始代码缺少满赠进度查询接口，人工补充按活动编号批量查询接口`
- `OrderService.createOrder 原始代码包含未要求的日志埋点逻辑，人工删除多余代码`

生成约束：
- 必须基于 before-code 和 after-code 的实际代码变化，禁止臆测
- 问题描述使用 before-side 的视角（"缺少"/"使用了错误的"/"包含多余的"）
- 修正方向简洁描述人工做了什么（"修正为"/"补充了"/"删除了"）
- commit_message 关键词提供意图先验：如含"修复"+"满赠"可辅助识别为 corrective；含"新增"可辅助识别为 additive

输出到 `change-intents.json` 的 `hunks[].intent_descriptions[]` 字段。

### Step 2：基于 intent_description + diff_nature + commit_message 关键词聚类

将所有 hunk 的 intent_description 和 diff_nature 作为聚类输入，按语义相似度分组：

聚类规则：
1. intent_description 描述的 AI 代码缺陷相同（同一业务逻辑的不同表现）→ 同一 Change Intent
1.5. 同一 `design_cluster_id` 的 hunk → 优先归入同一 Change Intent（Layer 0 design_cluster_id 是强合并信号，优先级高于 likely_merge 和 commit_message 关键词）
2. diff_nature 相同 + intent_description 的业务意图相同 → 同一 Change Intent
3. intent_description 的修正方向互补（如"缺少接口"+"缺少调用方"服务于同一功能） → 同一 Change Intent
4. Layer 1 的 likely_merge 建议（含跨仓符号匹配边） → 优先归入同一 Change Intent
5. commit_message 关键词一致（如多个 hunk 的 commit message 都含"满赠"+"修复"） → 倾向归入同一 Change Intent
6. 同一 design_item_ref 的 hunk（如存在） → 倾向归入同一 Change Intent
7. 跨 repo 的 hunk 仅当满足以下条件之一才合并：
   - 条件 a：有相同的 `design_cluster_id`（Layer 0 已通过设计意图建立跨仓关联）
   - 条件 b：有 Layer 1 跨仓符号匹配 likely_merge 边 + commit_message 关键词一致 + intent_description 语义一致
   > 放宽原因：PDG 无法追踪跨仓依赖，但 Layer 0 的 design_cluster_id 和 Layer 1 的跨仓符号匹配已提供跨仓关联证据，不应仅因跨 repo 就拒绝合并。
8. diff_nature = refining 的 hunk 单独成组，不与 corrective/additive 混合。**例外**：同一 `design_cluster_id` 内的 refining hunk 可与 corrective/additive 合并——同一设计项内的重构和修正是同一设计决策的不同侧面，拆分反而丢失设计意图完整性

聚类输出：
```json
{
  "change_intents": [
    {
      "intent_id": "CI-002",
      "intent_description": "FullGiftExchanger 原始代码满减互斥判断逻辑错误，使用 OR 条件导致满赠与满减可同时触发",
      "diff_nature": "corrective",
      "hunk_ids": ["server-H003", "server-H004"],
      "is_composite": false,
      "cluster_confidence": "high|medium|low",
      "cluster_method": "llm_rationale",
      "clustering_inputs": {
        "commit_message_keywords": ["修复", "满赠", "互斥"],
        "pdg_hints": ["likely_merge:server-H003,server-H004"],
        "bonus_signals": {"task_ref": "T12", "design_item_ref": "D-03"}
      }
    }
  ]
}
```

cluster_confidence 判定：
- `high`：intent_description 高度一致 + diff_nature 一致 + commit_message 关键词一致 + 有 PDG likely_merge 边
- `medium`：intent_description 语义一致 + diff_nature 一致，但缺少 commit_message 或 PDG 边辅助
- `low`：仅基于文件 proximity 聚类，intent_description 语义模糊

## 后置校验 + evidence_type / structure_type 推导（主 Agent 执行，聚类后）

### 后置校验（validate_subagent_output.py --mode intent）

不新建独立的 `validate_clusters.py`，聚类后置校验统一由 `validate_subagent_output.py` 的 `--mode intent` 完成（该脚本同时承担 SubAgent-Intent 输出的全字段硬校验与本节的 9 项跨 CI/hunk 交叉校验）：

```bash
python3 "$SCRIPT_DIR/validate_subagent_output.py" \
  --mode intent \
  --change-intents "$OUTPUT_DIR/hunks/change-intents.json" \
  --hunk-list "$OUTPUT_DIR/hunks/hunk-list.json" \
  --pre-cluster "$OUTPUT_DIR/hunks/pre-cluster-hints.json" \
  --output "$OUTPUT_DIR/hunks/cluster-validation.json"
```

校验结果中规格化的顶层 `warnings[]` / `auto_fixes[]` 会同时写回 `change-intents.json` 的 `validation` 字段（见下方输出文件示例），并完整保留在 `--output` 指定的报告文件中，供人工/主 Agent 定位问题细节。

校验项：
1. **symbol_hint 矛盾检测**：同一 Change Intent 内 hunk 的 symbol_hint 完全不同且无 PDG 边 → warning
2. **文件重叠检测**：两个 intent 包含同一文件同一行范围 → 冲突
3. **commit 链时序检测**：不同 commit message 表达不同功能但聚到一起 → warning
4. **规模合理性检测**：intent > 8 hunk 或跨 > 4 文件 → 过度聚合 warning
5. **D-xx 映射一致性**：intent 中 hunk 映射到 > 2 个不同 `design_cluster_id` 且无 PDG 强依赖边 → 建议拆分（`design_cluster_id` 存在时才检查。阈值从 3 降为 2：一个 Change Intent 对应 2 个以上设计项已需警惕，除非有 PDG 强依赖证明代码结构上确实不可分割）
6. **intent_description 语义矛盾检测**：同一 intent 内的 intent_description 语义方向不一致 → warning
7. **diff_nature 混合检测**：同一 intent 内包含不同 diff_nature 的 hunk → warning（corrective + additive 可容忍，refining 与其他混合需拆分。**例外**：同一 `design_cluster_id` 内的 refining + corrective/additive 混合不触发 warning——同一设计项内的重构和修正属于同一设计决策的不同侧面）
8. **commit_message 与 diff 一致性检测**：commit_message 表达的意图与 intent_description 描述的 AI 代码缺陷方向不一致 → warning
9. **跨仓 design_cluster 一致性检测**：跨 repo 的 hunk 有相同的 `design_cluster_id` 但未被分到同一 Change Intent → warning（Layer 0 已通过设计意图建立跨仓关联，未合并可能意味着 Layer 2 聚类遗漏了设计意图信号。如果确实应该分开，需在 clustering_inputs 中标注分离原因）

校验结果写入 `cluster-validation.json`，包含 `warnings[]` 和 `auto_fixes[]`（自动修正建议）。

### evidence_type / structure_type 确定性推导（主 Agent 执行）

**重要**：evidence_type 和 structure_type 不由 LLM 自标注，避免循环推理。由主 Agent 在归因完成后基于 evidence_chain 和归因字段确定性推导。详见 SKILL.md §6.3。

**evidence_type 推导规则**（按优先级从高到低）：

| 规则 | 条件 | evidence_type |
|---|---|---|
| R-E1 | evidence_chain 中首因层 finding 含"逻辑错误"或"约束违反" | `logic_error` |
| R-E2 | evidence_chain 中首因层 finding 含"遗漏"或"缺失" | `omission` |
| R-E3 | evidence_chain 中首因层 finding 含"表达模糊"或"表述不清" | `ambiguity` |
| R-E4 | first_cause_nature = `prd_quality` 或 problem_type = P1-3 | `prd_quality` |
| R-E5 | evidence_chain 中首因层 upstream_finding 含"知识库缺失" | `knowledge_gap` |
| R-E6 | 以上均不匹配 | `other` |

**structure_type 推导规则**：

| 规则 | 条件 | structure_type |
|---|---|---|
| R-S1 | is_composite = true | `composite` |
| R-S2 | 其他情况 | `single` |

输出字段：
- `evidence_type`：推导值
- `evidence_type_source`：固定为 `"derived"`
- `evidence_type_derivation`：命中的规则编号 + 触发条件摘要
- `structure_type`：推导值
- `structure_type_source`：固定为 `"derived"`
- `structure_type_derivation`：命中的规则编号 + 触发条件摘要

## 输出文件

`$OUTPUT_DIR/hunks/change-intents.json`：

```json
{
  "change_intents": [
    {
      "intent_id": "CI-001",
      "intent_description": "IFullGiftExchanger 接口签名缺少 activityNo 参数，人工补充参数并同步更新调用方",
      "diff_nature": "additive",
      "hunk_ids": ["server-H001", "server-H002"],
      "is_composite": false,
      "cluster_confidence": "high",
      "cluster_method": "pdg_hard_merge",
      "pdg_edges": [
        {"from": "server-H001", "to": "server-H002", "type": "interface_to_impl"}
      ]
    },
    {
      "intent_id": "CI-002",
      "intent_description": "FullGiftExchanger.checkGift 原始代码满减互斥判断使用 OR 条件导致满赠与满减可同时触发，人工修正为 AND 条件",
      "diff_nature": "corrective",
      "hunk_ids": ["server-H003", "server-H004"],
      "is_composite": false,
      "cluster_confidence": "high",
      "cluster_method": "llm_rationale",
      "clustering_inputs": {
        "commit_message_keywords": ["修复", "满赠"],
        "pdg_hints": [],
        "bonus_signals": {"task_ref": null, "design_item_ref": null}
      },
      "evidence_type": "omission",
      "evidence_type_source": "derived",
      "evidence_type_derivation": "R-E2: 首因层 finding 含\"缺少\"",
      "structure_type": "single",
      "structure_type_source": "derived",
      "structure_type_derivation": "R-S2: is_composite = false"
    }
  ],
  "hunks": [
    {
      "hunk_id": "server-H001",
      "intent_descriptions": [
        "IFullGiftExchanger 接口原始签名缺少 activityNo 参数，人工补充该参数"
      ],
      "diff_nature": "additive",
      "before_code": "public interface IFullGiftExchanger {\n    void exchange(GiftContext ctx);\n}",
      "after_code": "public interface IFullGiftExchanger {\n    void exchange(GiftContext ctx, String activityNo);\n}",
      "change_summary": "在 exchange 方法签名中新增 activityNo 参数",
      "is_composite": false
    }
  ],
  "validation": {
    "warnings": [],
    "auto_fixes": []
  }
}
```

## 返回摘要

```json
{
  "status": "success",
  "change_intent_count": 5,
  "pdg_resolved_count": 2,
  "llm_clustered_count": 3,
  "low_confidence_count": 0,
  "diff_nature_breakdown": {
    "corrective": 3,
    "additive": 1,
    "subtractive": 0,
    "refining": 1
  },
  "output_file": "$OUTPUT_DIR/hunks/change-intents.json"
}
```

## 约束

1. intent_description 必须基于 before-code 和 after-code 的实际代码变化，描述 AI 原始代码的缺陷，禁止臆测
2. diff_nature 必须基于 before-code 和 after-code 的代码对比判定，commit_message 仅作辅助参考
3. commit_message 关键词作为 LLM 聚类辅助输入，与 intent_description 联合提供意图先验
4. task_ref 和 design_item_ref 是可选 bonus signal，缺失时不影响聚类流程
5. evidence_type 和 structure_type 不由 SubAgent-Intent 产出，由主 Agent 在归因完成后确定性推导
6. excluded hunk 不参与聚类
7. Layer 1 已确定性分组（must_merge，含 design_cluster must_merge、PDG 强依赖 must_merge、同文件同方法 must_merge）的 hunk 不进入 Layer 2 LLM 聚类
8. diff_nature = refining 的 hunk 仍参与聚类，但单独成组不与其他 diff_nature 混合。例外：同一 `design_cluster_id` 内的 refining hunk 可与 corrective/additive 合并
9. 聚类为三层结构：Layer 0（D-xx 设计项预聚类）→ Layer 1（PDG 硬聚类 + 跨仓符号匹配）→ Layer 2（LLM 语义聚类）。Layer 0 跳过时退化为两层
10. `design_cluster_id` 在 Layer 1 作为 must_merge 信号，在 Layer 2 作为优先合并信号，在后置校验中作为跨仓一致性检查依据。三层均使用同一字段，语义一致
11. Layer 0 只做合并增强不做分裂，`unmapped` hunk 不受惩罚，正常进入 Layer 1 和 Layer 2
