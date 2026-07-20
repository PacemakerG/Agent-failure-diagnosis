# yx-agcr-attribution 归因分析 Skill — 原理与执行过程详解

> 源文档: <!-- 内部链接已脱敏 -->
> 拉取时间: 2026-07-13

## yx-agcr-attribution 归因分析 Skill — 原理与执行过程详解

### 一、概述

`yx-agcr-attribution` 是Agent体系的**上线后代码采纳率归因分析 Skill**。其核心问题是：**AI 首轮生成的代码（one-shot）与最终上线代码之间存在差异，这些差异是什么原因造成的？**

分析链路：

```
one-shot commit → target-final commit 差异 diff
  → 语义 Hunk 切分
    → 逐层逆向归因（N6→N1）定位首因阶段
      → 阶段内精细分类 + 根因核验（R1-R5）
        → HTML 报告 + JSON 结构化结果
```

输出产物：`attribution-report.html`（面向人工阅读）+ `attribution-result.json`（面向系统消费）。

---

### 二、核心概念

#### 2.1 AGCR（AI Code Retention Rate）

AGCR = AI 首轮生成的代码中有多少被保留到最终上线版本，不含 RD 修改的部分。

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `agcr_value` | 外部观测（observability 系统） | 报告元信息展示用，不参与归因计算 |
| `calculated_agcr.raw` | SubAgent-AGCR 独立计算 | 基于 diff 行数，含全部改动 |
| `calculated_agcr.adjusted` | SubAgent-AGCR | 剔除 excluded hunk（格式化/自动生成等）后的值 |

计算公式：

```
AGCR_raw      = (AI新增行 - RD改写行) / AI新增行
AGCR_adjusted = (有效AI行 - 有效RD改写行) / 有效AI行
```

两个数字差 >5% 时，报告标注 `agcr_consistency=divergent` 并注明原因。

#### 2.2 三个关键 Commit

| 字段 | 含义 | 来源 |
| --- | --- | --- |
| `base_commit` | 拉分支时的代码基线 | `agcr_data_json.repos[].base_commit` |
| `one_shot_commit` | AI 首轮完整实现后的版本（= TDD commit） | `agcr_data_json.repos[].one_shot_commit` / `tdd_commit` |
| `target_final_commit` | 上线或最新版本 commit | 从 PR 链接/代码平台读取 |

**主分析 diff** 固定为远程 `one_shot_commit..target_final_commit`，禁止用本地 git 替代。

#### 2.3 Hunk（归因最小单元）

物理 Git diff hunk（`@@` 分隔）不直接使用，而是按语义边界重新切分：

```
Requirement
  └── FeatureChange（业务意图层）
        └── Commit（版本控制层）
              └── Hunk（归因分析层，最小单元）
```

**合并条件**：同一方法内同一意图的改动、跨文件但服务同一接口变更、逻辑修改 + 必要配套改动。

**拆分条件**：同一物理 hunk 内混杂多个不相关意图（如逻辑修复 + 风格调整）。

**排除条件**（excluded=true，不参与归因）：

- `whitespace`：纯格式/空白变更
- `auto_import`：import 自动整理
- `auto_generated`：protobuf stub 等自动生成代码 regenerate

#### 2.4 阶段映射（归因体系内部编号）

| 归因内部编号 | 报告展示名 | 对应 Skill |
| --- | --- | --- |
| N6 | N6 代码生成 | yx-subagent-driven-development |
| N5 | N5 编码计划 | yx-writing-plans |
| N4 | N4 技术方案 | yx-plan |
| N3 | N3 需求澄清 | yx-pm-analyze-requirement |
| N2 | N2 现状梳理 | yx-current-state-baseline |
| N1 | N1 项目初始化 | yx-repo-scope-bootstrap |

#### 2.5 归因体系（两层）

**第一层：首因阶段（Phase 2a 逆向归因）**

从 N6 代码表层逐层向上检查，定位问题在哪个阶段产物首先出现（`first_cause_stage`）。例如代码写错了，检查 tasks.md 指令是否正确 → 检查 design.md 设计项是否覆盖 → 检查 requirement.md 需求是否完整……

**第二层：阶段内精细分类（Phase 2b 正向归因）**

在确定首因阶段后，进一步定位：

- **问题类型**（`intra_stage_type`）：该阶段产物出了什么具体问题，如「设计项遗漏」「接口规格错误」
- **根因子类型**（`intra_stage_sub_type`）：R1～R5 根因核验

#### 2.6 根因分类（R1-R5）

| 编码 | 名称 | 判断标准 |
| --- | --- | --- |
| R1a | 知识建设缺口 | `domain-knowledge.md` 无该主题相关记录 |
| R1b | 知识利用缺口 | `domain-knowledge.md` 有记录但阶段产物未体现 |
| R2 | 执行损耗 | 推理结论正确，但写入产物时发生信息失真或丢失。**必须有 trace 证据支持**（trace_by_stage.json 中存在正确中间结论）；无 trace 时禁止定 R2，改定 R3 |
| R3 | 模型推理 | 知识有记录、产物已体现，但推理结论本身有逻辑错误 |
| R4 | 门禁漏检 | 应被已有质量门禁拦截但未拦截 |
| R5 | 澄清交互不充分 | 应在澄清阶段向 PM/RD 提问但未提问（N2、N6 不适用 R5） |

**R1→R3 消去链**（R3 的前置条件必须全满足）：

1. knowledge.md **有**相关记录
2. 阶段产物**体现**了该知识
3. 推理结论**有逻辑错误**

阶段内证据必须按三段式（有 trace 时扩展为四段式）写明：

```
[知识核验] domain-knowledge.md {有/无} {主题} 相关记录：{具体位置}。
[体现情况] {产物} {体现/未体现} 该知识：{具体内容}。
[根因判定] 因此定 {R1a/R1b/R3/R2/R4/R5}：{推理过程}。
[Trace核验]（有 trace 时必须写）本阶段 trace_snippet 中 {有/无} 关于该约束的正确中间结论：{关键片段或"无"说明}。
```

---

### 三、系统架构

```
主 Agent（编排）
  ├── Phase 1
  │     ├── SubAgent-Artifact × 1   （下载阶段产物 + 可选 trace 下载）
  │     └── SubAgent-Diff × N repos （远程 commit 校验 + diff 生成）
  │
  ├── Phase 2a（等 Phase 1 全部完成后）
  │     ├── SubAgent-Split × N repos   （Hunk 语义切分）
  │     ├── SubAgent-AGCR × 1          （采纳率独立计算，与 2b 并行）
  │     └── SubAgent-Hunk × N FC       （逐层逆向归因，每 FC 1 个，≤3 个并行）
  │
  ├── Phase 2b（等 Phase 2a SubAgent-Hunk 全部完成后）
  │     └── SubAgent-IntraStage × N stages  （阶段内精细分类，每阶段 1 个，≤4 个并行）
  │
  └── Phase 3（等 Phase 2b + SubAgent-AGCR 全部完成后）
        └── 汇聚统计 → HTML + JSON → S3Plus → DB 写入
```

**全局并发约束**：同时运行 SubAgent ≤ 4 个（SubAgent-AGCR 占 1 额度）。

---

### 四、执行流程详解

#### Phase 1：初始化与数据收集

##### Step 1：读取显式输入

用户传入 `req_id` 或 `fsd_url`（必需），可选：

4. `commits_file`：回放/调试模式覆盖 commit（不能替代常规模式的 agcr_data_json）
5. `artifact_paths`：回放模式覆盖产物路径
6. `output_dir`、`run_id`、`agcr_value`

##### Step 2：读取 Observability 数据（触发 Gate 1）

通过 HTTP GET 接口读取结构化数据：

```bash
# 产物数据
curl -s "${BASE_URL}/stage-artifact?run_id={run_id}&requirement_id={req_id}&page_size=200"

# Commit 数据
curl -s "${BASE_URL}/stage-commit?run_id={run_id}&requirement_id={req_id}&page_size=200"
```

**Gate 1 校验项**：

1. `artifacts[]` 和 `commits[]` 均不为空
2. 每个 repo 有 `branchName` 且有 PR 链接
3. 每个 repo 都能解析出 `base_commit` / `one_shot_commit`
4. N1 遗漏仓库检测（非阻塞，标记 `n1_scope_miss: true`）

##### SubAgent-Artifact 并发执行

从 `s3Url` 下载各阶段产物到本地缓存：

| artifactType | 对应阶段 | 产物文件 |
| --- | --- | --- |
| `DOC_DESIGN` | N4 技术方案 | design.md, design-interface.md, constraint-check.md |
| `DOC_PLAN` | N5 编码计划 | tasks.md |
| `DOC_REQUIREMENT` | N3 需求澄清 | requirement.md, clarification-log.md |
| `DOC_BASELINE` | N2 现状梳理 | current-state.md, feature-points.md |

缺失产物记录为 evidence_gap，不阻塞分析。

**Step 4.5（可选）：下载并解析 Session JSONL（ai-trace）**

条件：`agcr_data_json` 或 `latest_data_json` 中存在 `session_id` 字段。

```bash
python3 {skill_dir}/scripts/extract_stage_trace.py \
  --session-id {session_id} \
  --run-id {run_id} \
  --output /tmp/agcr-{run_id}/artifacts/trace_by_stage.json \
  --env test
```

结果：

5. **成功**：`artifact_map["trace"]` 写入 `trace_by_stage.json`（按阶段切分，每阶段含 `trace_snippet`）
6. **失败 / 无 JSONL / 无 session_id**：`artifact_map["trace"] = null`，**不阻塞**后续步骤

Session JSONL 不在 `artifacts[]` 中，通过 `yuanxi_claude_log_split`（阶段边界）+ `yuanxi_claude_log_upload`（S3 URL）独立链路读取，用于 SubAgent-IntraStage 区分 R2/R3。

##### SubAgent-Diff 并发执行（每 repo 1 个）

执行 Gate 2（commit 存在性）+ Gate 3（分支归属与顺序），再生成 diff：

```
one_shot_commit..target_final_commit  →  {repo}-one-shot-to-target-final.diff
base_commit..one_shot_commit          →  {repo}-base-to-one-shot.diff
base_commit..target_final_commit      →  {repo}-base-to-target-final.diff（辅助，失败不阻塞）
```

---

#### Phase 2a：Hunk 切分与逆向归因

##### Step 5：语义 Hunk 切分（SubAgent-Split × N repos）

| 子步骤 | 执行者 | 内容 |
| --- | --- | --- |
| 5.1 收集 diff 与 commit 链 | SubAgent-Split | 读取 diff 文件和 commit-chain.json |
| 5.2 排除条件过滤 | SubAgent-Split | 标记 whitespace/auto_import/auto_generated |
| 5.3 物理 hunk 拆分 | SubAgent-Split | 按混杂意图拆分 |
| 5.4 跨 hunk/跨文件合并 | SubAgent-Split | 同意图合并为语义 Hunk |
| 5.5 识别 symbol_hint | SubAgent-Split | 类名/方法名 |
| 5.6 关联 source_commits | SubAgent-Split | 行号交叉比对 |
| 5.7 FeatureChange 分组 | **主 Agent** | 跨 repo 按业务意图分组，分配 FC-xxx ID |

##### Step 6：采纳率计算（SubAgent-AGCR，与 SubAgent-Hunk 并行）

```python
AGCR_raw      = (ai_lines - reworked) / ai_lines
AGCR_adjusted = (effective_ai_lines - effective_reworked) / effective_ai_lines
```

##### Step 7+8：逐 hunk 逆向归因（SubAgent-Hunk × N FC）

从 N6 代码生成开始，向上逐层检查，每层必须写检查记录（不允许跳层）。**evidence_chain 完整性约束（强制）**：定责 N3，则 evidence_chain 必须包含 N6、N5、N4、N3 共 4 层记录，产物缺失层也不能跳过。

---

#### Phase 2b：阶段内精细分类（SubAgent-IntraStage）

Phase 2a SubAgent-Hunk 全部完成后，主 Agent 按 `first_cause_stage` 分组，每个活跃阶段派发 1 个 SubAgent-IntraStage（≤ 4 并行，N1 不参与）。

##### 执行流程（每 hunk）

**Step 3**：按以下顺序逐一核验根因（R1a→R1b→R3→R2→R4→R5），第一个命中即停止：

```
① knowledge.md 无相关记录 → R1a（知识建设缺口）
② knowledge.md 有记录但产物未体现 → R1b（知识利用缺口）
③ 知识有记录、产物已体现，但推理结论有逻辑错误 → R3（模型推理）
   有 trace 时：确认 trace 中无正确中间结论 + 产物结论有误；
   无 trace 时：同样定 R3，在 [根因判定] 末尾注明"无 trace 证据，基于产物推断 R3"
④ 推理正确但写入产物时信息失真/丢失 → R2（执行损耗）
   必须有 trace 支持：trace_snippet 中存在关于该约束的正确中间结论，但产物未体现；
   无 trace 时禁止定 R2，改定 R3 并注明"无 trace 证据，无法确认推理阶段正确性，定 R3"
⑤ 应被质量门禁拦截但未拦截 → R4（门禁漏检）
⑥ 应在澄清阶段提问但未提问 → R5（澄清交互不充分，N2/N6 不适用）
```

**Step 4**：写 `intra_stage_evidence`（三段式，有 trace 时扩展为四段式）：

```
[知识核验] domain-knowledge.md {有/无} {主题} 相关记录：{具体位置}。
[体现情况] {产物} {体现/未体现} 该知识：{具体内容}。
[根因判定] 因此定 {R1a/R1b/R3/R2/R4/R5}：{推理过程}。
[Trace核验]（有 trace 时必须写）本阶段 trace_snippet 中 {有/无} 关于该约束的正确中间结论：
  {引用关键片段（≤100字）或"无"说明}。→ 用于区分 R2/R3。
```

##### N1 项目初始化特殊处理

N1 不派发 SubAgent-IntraStage，由 SubAgent-Hunk 直接判定：

| 问题类型 | 说明 | 根因 |
| --- | --- | --- |
| P1-1 领域识别错误 | 涉及错误领域的仓库/模块 | R1a |
| P1-2 领域仓库范围错误 | 领域正确但仓库范围配置有误（代码结构.md 问题） | R1a / R1b / R3 |
| P1-3 PRD原始功能遗漏/有误 | 外部输入缺陷，PRD 原文缺少该功能描述 | 无（terminal） |

##### N1 遗漏仓库特殊处理

若某仓库在项目初始化时未纳入 N1 范围（`n1_scope_miss: true`），其所有 hunk 由**主 Agent 直接预填**（不派发 SubAgent-Hunk / SubAgent-IntraStage），归因为 **P1-2 领域仓库范围错误**。

主 Agent 执行轻量级根因核验：

1. 在知识库中查找 `代码结构.md`，检索是否有该 repo 的仓库记录；
2. 若 `代码结构.md` 不存在，兜底检查 `work_status.md` 和 `repo.md`；
3. 根据检索结果判定根因：

| 检索结果 | sub_type | root_cause |
| --- | --- | --- |
| 无任何记录（含兜底文件也无） | P1-2a | R1a 知识建设缺口 |
| 有记录但 N1 范围未纳入 | P1-2a | R1b 知识利用缺口 |
| 有记录且被纳入讨论但最终推理排除 | P1-2b | R3 模型推理 |

---

#### Phase 3：汇聚与输出

##### Step 10：生成 HTML 报告

报告共 12 节：§1 基本信息 / §2 代码版本 / §3 计算采纳率 / §4 Diff 概览 / §5 问题分布 / §6 功能调整与归因明细 / §7 排除 Hunk 汇总 / §8 首因层分布 / §9 传导链路 / §10 改进建议 / §11 证据缺口 / §12 产物读取情况（含 Session JSONL trace 行）。

---

### 五、HARD-GATE 门禁

| Gate | 说明 | 是否阻塞 |
| --- | --- | --- |
| Gate 1 | 数据完整性（artifacts/commits/base/one_shot commit 均可解析） | 阻塞 |
| Gate 2 | commit 存在性（远程 repo 可查到三个 commit） | 阻塞 |
| Gate 3 | 分支归属与顺序（base→one_shot→final 线性可达） | 阻塞 |
| Gate 4 | diff 为空时不归因（100% 采纳，直接输出） | 终止归因 |

---

### 六、配置文件

| 文件 | 作用 |
| --- | --- |
| `config/problem-types.json` | 代码表象分类枚举（surface_issue_types）定义，15 种类型，执行前必须读取，不硬编码 |
| `config/attribution-rules.md` | 逆向归因决策树（辅助表 A/B/C），SubAgent-Hunk 执行归因前必须读取 |
| `config/intra-stage-types.json` | 阶段内问题类型注册表，37 种类型（N6×3 + N5×3 + N4×13 + N3×10 + N2×8） |
| `config/intra-stage-rules.md` | 阶段内精细分类规则（R1-R5 核验流程、四段式证据格式、各阶段检查侧重） |
| `scripts/extract_stage_trace.py` | Session JSONL 按阶段切分脚本，可选执行；查 yuanxi_claude_log_split + yuanxi_claude_log_upload，输出 trace_by_stage.json 供 SubAgent-IntraStage 区分 R2/R3 |
| `templates/attribution-report.html` | HTML 报告模板（内联 CSS，无外部依赖） |
| `templates/PLACEHOLDERS.md` | 所有占位符的填充规则（执行 Step 10 前必须读取） |

---

### 七、代码表层问题类型（surface_issue_types）

`surface_issue_type` 是 Phase 2a SubAgent-Hunk 在完成逐层逆向归因时对代码 diff **表层现象**的分类标签。它描述的是「这段代码改了什么」，与 `first_cause_stage`（哪个阶段是根因）相互独立，两者共同构成归因的完整画像。

枚举值来自 `config/problem-types.json`，共 **15 种**，分 7 组。报告中只展示中文 label，不展示英文 ID。

#### 功能类（3 种）

| 枚举 ID | 中文标签 | 典型场景 |
| --- | --- | --- |
| `FUNC_MISSING` | 功能缺失 | 该实现的逻辑未实现：遗漏功能分支、遗漏 AC 覆盖点、遗漏边界值处理、某个完整功能块未生成 |
| `FUNC_EXTRA` | 功能多余 | 实现了不该实现的逻辑：超出需求范围、被删除需求的残留实现、不必要的中间状态处理 |
| `FUNC_LOGIC_ERROR` | 功能逻辑错误 | 功能已实现但逻辑有误：条件判断取反、边界值 off-by-one、参数顺序颠倒、算法实现与规格不符 |

**使用提示**：检查 tasks.md → design.md 确认是否有对应设计依据；对照设计项检查实现逻辑是否一致。

#### 兼容性类（2 种）

| 枚举 ID | 中文标签 | 典型场景 |
| --- | --- | --- |
| `BEHAVIOR_CONFLICT` | 与现有行为冲突 | AI 代码主动破坏了既有流程、全局状态或接口行为：覆盖已有全局配置、改变既有方法返回格式、破坏接口向后兼容性 |
| `COMPAT_MISSING` | 兼容性处理缺失 | 新代码对新数据/新流程自身正确，但未处理新老共存的过渡期：存量数据字段为 null 未兜底、老接口版本未保留、枚举扩展无 default 分支 |

**使用提示**：两者区别在于「是否主动破坏」—— BEHAVIOR_CONFLICT 是已有功能被破坏（合并即有问题），COMPAT_MISSING 是灰度/切量时才触发的新老共存问题。检查 current-state.md 是否记录了现有行为，design.md 是否有兼容方案。

#### 接口/数据类（2 种）

| 枚举 ID | 中文标签 | 典型场景 |
| --- | --- | --- |
| `INTERFACE_MISMATCH` | 接口签名/参数不对 | 方法签名、请求/响应 DTO 字段、Thrift IDL 与实际调用方或服务端定义不匹配，参数类型/顺序/返回值结构有误 |
| `DATA_MODEL_ERROR` | 数据模型/字段有误 | 字段类型、枚举值、表结构、存储 key 格式与设计不符，或使用了错误的数据库表/缓存结构 |

**使用提示**：检查 design-interface.md 接口定义是否正确传递到 tasks.md；对照 design.md 数据模型章节检查字段 DO/DTO 映射。

#### 规范类（3 种）

| 枚举 ID | 中文标签 | 典型场景 |
| --- | --- | --- |
| `ARCH_VIOLATION` | 架构/分层违反 | 跨层调用（Controller 直接操作 DAO）、错误的模块间依赖、使用了不应直接访问的内部接口或包 |
| `MIDDLEWARE_MISUSE` | 中间件使用不当 | MQ 消费/发送方式、缓存读写策略、配置中心用法、分布式锁使用与团队规范不符，或未遵循框架约定的使用姿势 |
| `CODING_STYLE` | 编码风格/命名不规范 | 命名约定（变量/方法/类名）、注释格式、代码组织结构与团队规范不符；包含 RD 明确标注为个人偏好的风格调整 |

**使用提示**：三者均需检查 constraint-check.md + knowledge.md 是否有对应规范记录，以及是否传递到 tasks.md 指令中。

#### 健壮性类（2 种）

| 枚举 ID | 中文标签 | 典型场景 |
| --- | --- | --- |
| `DEFENSIVE_MISSING` | 防御性代码缺失 | 缺少 null check、参数合法性校验、异常捕获与处理、幂等保护、超时控制等防御性代码 |
| `TRANSACTION_ISSUE` | 事务/一致性问题 | 事务边界设置错误（粒度过大/过小）、跨服务操作缺少一致性保障、补偿逻辑缺失、本地消息表/TCC 等一致性方案未实现 |

#### 稳定性/上线类（2 种）

| 枚举 ID | 中文标签 | 典型场景 |
| --- | --- | --- |
| `ROLLOUT_MISSING` | 上线方案缺失 | 缺少灰度开关、降级逻辑、回滚方案、历史数据迁移脚本或上线前置条件检查 |
| `PERFORMANCE_ISSUE` | 性能问题 | N+1 查询、循环内大量 RPC 调用、大批量无分页处理、锁粒度过粗、缺少必要索引使用、不合理的全量扫描 |

#### 兜底（1 种）

| 枚举 ID | 中文标签 | 使用条件 |
| --- | --- | --- |
| `OTHER` | 其他问题 | 不属于以上任何类别时使用。**必须同时填写**：① `other_reason`（与最近似类别的差异说明）；② `proposed_new_type`（`{label, reason}`，潜在新类别建议供后续演进）。禁止在能归入以上类别时使用 OTHER |

#### 选型决策树

```
该 diff 改了什么？
  ├── 该有的功能没做 / 做了不该做的 / 做错了          → 功能类（MISSING / EXTRA / LOGIC_ERROR）
  ├── 破坏了已有功能 / 灰度期新老数据未兼容            → 兼容性类（CONFLICT / COMPAT_MISSING）
  ├── 接口 DTO / IDL 字段不对 / 数据表字段有误          → 接口/数据类（INTERFACE / DATA_MODEL）
  ├── 分层违反 / 中间件用错 / 命名风格不合规            → 规范类（ARCH / MIDDLEWARE / STYLE）
  ├── 缺少 null check / 事务边界问题                   → 健壮性类（DEFENSIVE / TRANSACTION）
  ├── 没有灰度开关 / 有性能瓶颈                        → 稳定性类（ROLLOUT / PERFORMANCE）
  └── 以上均不符合                                     → OTHER（必须填 other_reason + proposed_new_type）
```

---

### 八、阶段内问题类型（intra_stage_types）汇总

#### N6 代码生成（3 种）

| ID | 问题类型 |
| --- | --- |
| P6N6-1 | 任务指令未遵守（tasks.md 有指令但代码未按指令实现） |
| P6N6-2 | 代码生成遗漏（tasks.md 有任务但实现缺失） |
| P6N6-3 | 代码生成超出任务范围 |

#### N5 编码计划（3 种）

| ID | 问题类型 |
| --- | --- |
| P5N5-1 | 设计项未转化为任务（design.md 有设计项但 tasks.md 未覆盖） |
| P5N5-2 | 任务步骤不完整（缺少关键实现步骤） |
| P5N5-3 | 约束条件未传递（design.md 约束在 tasks.md 未体现） |

#### N4 技术方案（13 种，含代表性示例）

| ID | 问题类型 |
| --- | --- |
| P4-1 | 设计缺失（功能完全未设计） |
| P4-2 | 设计错误（逻辑/流程/算法方向错误） |
| P4-3 | 设计项遗漏（局部细节遗漏） |
| P4-4 | 接口规格遗漏/错误 |
| P4-5 | 架构约束未体现 |
| P4-6 | 数据模型遗漏 |
| P4-7 | 边界条件/异常场景未设计 |
| P4-8 | 稳定性约束遗漏 |
| … | 共 13 种 |

#### N3 需求澄清（10 种）

| ID | 问题类型 |
| --- | --- |
| P3-1 | 用户故事遗漏 |
| P3-2 | AC 不完整 |
| P3-3 | 非功能需求遗漏 |
| P3-4 | 需求理解偏差 |
| P3-5 | 澄清结论错误 |
| … | 共 10 种 |

#### N2 现状梳理（8 种）

| ID | 问题类型 |
| --- | --- |
| P2-1 | 仓库范围遗漏 |
| P2-2 | 入口路径识别错误 |
| P2-3 | GAP 分析不完整 |
| … | 共 8 种 |

每种问题类型下有 4～5 个根因子类型（a=R1a, b=R3, c=R2, d=R4, e=R5）。N2 和 N6 没有 e（不适用 R5）。R2（c 后缀）在无 trace 时禁止使用，改定 R3（b 后缀）并注明原因。

---

### 九、Hunk 完整 Schema

```json
{
  "hunk_id": "repo-a-H001",
  "repo": "repo-a",
  "file": "src/.../OrderService.java",
  "old_start": 100, "old_lines": 10,
  "new_start": 102, "new_lines": 12,
  "symbol_hint": "OrderService.createOrder",
  "change_summary": "修改意图一句话描述",
  "surface_issue_type": "FUNC_LOGIC_ERROR",
  "surface_issue_type_source": "enum（始终为 enum，OTHER 也是枚举值）",
  "other_reason": null,
  "proposed_new_type": null,
  "confidence": "high|medium|low",
  "source_commits": ["abc1234"],
  "commit_message": "feat: add validation",
  "task_ref": "Task-005",
  "feature_change_id": "FC-001",
  "excluded": false,
  "exclude_reason": null,

  "_phase2a": "SubAgent-Hunk 填充",
  "first_cause_stage": "N4 技术方案",
  "first_cause_skill": "yx-plan",
  "evidence_chain": [
    {"stage": "N6 代码生成", "artifact": "tasks.md", "finding": "..."},
    {"stage": "N5 编码计划", "artifact": "design.md", "finding": "..."},
    {"stage": "N4 技术方案", "artifact": "requirement.md", "finding": "..."}
  ],
  "evidence_missing_stages": [],
  "direct_cause": "代码层看到的直接问题",
  "recommendation": "改进建议",
  "propagation_path": "N4技术方案 设计项遗漏（P4-3b R3）→ N5未识别 → N6代码缺失",

  "_phase2b": "SubAgent-IntraStage 填充",
  "intra_stage_type": "P4-3",
  "intra_stage_type_label": "设计项遗漏",
  "intra_stage_sub_type": "P4-3b",
  "intra_stage_root_cause": "R3 模型推理",
  "intra_stage_evidence": "[知识核验]... [体现情况]... [根因判定]..."
}
```

---

### 十、常见问题与约束

#### 不允许的操作

1. 本地 `git log` / `git diff` / `git fetch`：所有代码数据必须来自远程代码平台
2. 用 `agcr_data_json.latest_commit` 代替 `target_final_commit`：两者语义不同
3. 跳层归因：evidence_chain 必须包含 N6 到 first_cause_stage 的每一层
4. 跳过 `[知识核验]` 段直接判定 R3：必须先验证 knowledge.md 有记录且产物体现
5. 无 trace 证据时定 R2：R2 必须有 trace_by_stage.json 的正向证据支持
6. 在能归入已有 14 种 surface_issue_type 时选 OTHER：OTHER 是严格兜底，不是懒人选项

#### SubAgent 并发上限

1. 全局同时运行 SubAgent ≤ 4 个
2. SubAgent-AGCR 占 1 额度，SubAgent-Hunk 最多 3 个并行
3. SubAgent-IntraStage 最多 4 个并行（无 AGCR 竞争）
4. FC 数量 > 3 时分轮处理，不等待失败 FC 重试

#### 失败降级策略

1. SubAgent-Hunk 失败：该 FC 所有 hunk 标记 `confidence: low`，`attribution_failed: true`，继续其他 FC
2. SubAgent-IntraStage 失败：对该阶段所有 hunk 补填 null，不阻塞 Phase 3
3. DB 写入失败：不影响 S3 上传，不视为整体失败
4. 产物缺失：记录 evidence_gap，`confidence` 降级，继续上溯归因
5. trace 下载失败：`artifact_map["trace"] = null`，R2 自动禁用（改 R3），不阻塞归因流程
