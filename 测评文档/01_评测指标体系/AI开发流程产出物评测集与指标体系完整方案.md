# Agent AI 开发流程产出物评测集与指标体系完整方案

> 源文档: <!-- 内部链接已脱敏 -->
> 拉取时间: 2026-07-13

[toc]

### 1. 方案定位

本文是「产出物评测指标体系」与「评测集构造方案」的完整方案。指标体系回答“各阶段产出物怎么评、评哪些指标、如何算分”；评测集方案回答“如何把指标落成可复用、可回归、可自动化执行的 Case、Oracle、Grader 与报告”。

本方案重点覆盖Agent AI 开发流程中的六个关键阶段：N1 需求入口提取、N2 作用域初始化、N3 现状基线、N4 需求澄清、N6 技术方案、N7 编码计划。

核心目标：

- 将各阶段产出物质量从主观判断转为可度量指标。
- 将历史返工、Review 问题、线上缺陷转化为可回归样本。
- 支持模型、Prompt、Skill、流程编排变更前后的质量对比。
- 沉淀正负样本经验,反哺 Guardrail、Checklist 和 Workflow Memory。

### 2. 整体框架

#### 2.1 Agent评测体系全流程图

核心思路：每个开发阶段（N1-N2-N3-N4-N6-N7）均由对应 Skill 驱动执行，每个阶段都会经过 Skill 评测（静态检查 + 执行层评测），之后每个阶段的产出物都会经过产出物评测（结构合规 + 内容质量）。

![流程图](<!-- 内部链接已脱敏 -->)

其中skill的评测方案详见 [<!-- 内部链接已脱敏 -->](<!-- 内部链接已脱敏 -->)

#### 2.2 产出物评测框架

```Mermaid
flowchart LR
  subgraph FLOW["Agent开发流程（本方案覆盖阶段）"]
    N1["N1 需求入口提取<br/>km_links / fsd_url / group_info"]
    N2["N2 作用域初始化<br/>active_repos / primary_repo / branch / work_status.md"]
    N3["N3 现状基线<br/>current-state.md / evidence.md / baseline-gate.md"]
    N4["N4 需求澄清<br/>requirement.md / prototype.md / clarification-log.md"]
    N6["N6 技术方案<br/>design.md / design-interface.md / design-review.md"]
    N7["N7 编码计划<br/>tasks.md / 覆盖矩阵 / DAG"]
    N1 --> N2 --> N3 --> N4 --> N6 --> N7
  end

  subgraph EVAL["评测集构造资产"]
    IB["Input Bundle<br/>原始输入 + 上游产物 + 代码快照"]
    EB["Expected Behavior<br/>must_cover / must_not_include / expected_*"]
    OG["Oracle / Grader<br/>exact / rule / traceability / evidence / LLM judge / human"]
    MT["Metadata<br/>阶段 / 业务域 / 复杂度 / 失败模式"]
    RR["Run Record<br/>模型版本 / Skill版本 / 得分 / block-warn / 成本"]
    IB --> EB --> OG --> MT --> RR
  end

  N1 -. "N1 Case" .-> IB
  N2 -. "N2 Case" .-> IB
  N3 -. "N3 Case" .-> IB
  N4 -. "N4 Case" .-> IB
  N6 -. "N6 Case" .-> IB
  N7 -. "N7 Case" .-> IB

  OG --> RP["评测报告<br/>阶段分 / 失败样本 / 回归对比 / 修复建议"]
  RP --> MEM["经验沉淀<br/>Golden Set / Hard Set / Shadow Set / Guardrail"]
  MEM -. "回流为后续需求参考样本与门禁规则" .-> N1
```

### 3. 业界参考方法

| 方法 | 核心思想 | 启发 |
| --- | --- | --- |
| [OpenAI Evals：业务工作流私有评测集](https://github.com/openai/evals) | OpenAI Evals 的核心思想是将业务场景转化为结构化 eval：数据样本、任务定义、grader、报告结果分离管理。它适合参考的点是：<br>- 评测样本与评分逻辑分离。<br>- 支持私有业务数据作为 eval，不要求公开。<br>- 每个 eval 可以配置不同 grader，例如 exact match、model-graded、custom logic。<br>- 适合做版本回归，比较不同模型或不同系统版本。 | 每个阶段都应有独立 eval，例如 `n4_requirement_eval`、`n6_design_eval`、`n7_tasks_eval`，但最终统一汇总成全链路报告。 |
| [HELM：场景 × 指标的多维评测](https://github.com/stanford-crfm/helm) | HELM 强调用统一格式组织场景和指标，不只评准确率，也评鲁棒性、效率、安全等多维指标。它适合参考的点是：<br>- 先定义 scenario，再定义 metric。<br>- 同一场景下可以有多个指标，避免单一分数掩盖问题。<br>- 保留 prompts、responses 和中间结果，便于复盘。<br>- 通过标准化运行配置保证可复现。 | 每个阶段就是一个 scenario，每个阶段都有结构合规、事实准确、追溯证据、下游可用性等 metric |
| [MT-Bench / LLM-as-Judge：开放式产出的语义评审](https://github.com/lm-sys/FastChat/tree/main/fastchat/llm_judge) | MT-Bench 使用强模型作为 judge 评估开放式回答，并通过人工标注校准 judge 的可靠性。它适合参考的点是：<br>- 对没有唯一标准答案的开放式产出，可以用 rubric 评分。<br>- 评分时要求 judge 给出理由，而不是只给分数。<br>- 可以使用单答案评分，也可以使用 pairwise 对比。<br>- 需要抽样人工标注，监控 judge 与人工的一致性。 | N3/N4/N6/N7 的内容质量不能只靠规则评测，需要 LLM-as-Judge + 人工校准；尤其是 PRD 忠实度、设计推导链完整度、任务指令可执行度等指标 |
| [SWE-bench：真实开发任务 + 执行型 Oracle](https://github.com/swe-bench/SWE-bench) | SWE-bench 将真实 GitHub issue 和代码仓库固定到特定 commit，要求模型生成 patch，再用测试验证是否解决问题。它适合参考的点是：<br>- 样本来自真实软件工程任务，而不是人工编造题目。<br>- 每条样本固定代码版本，保证可复现。<br>- 使用执行结果作为最终 oracle，减少纯主观判断。<br>- 样本包含 issue、repo、commit、patch、test 等完整上下文。 | N8/N9 以后可以使用编译、单测、集成测试作为强 oracle；N1~N7 虽然多是文档产物，也应尽量让评测结果能被下游执行结果反证。 |
| [RAGAS](https://docs.ragas.io/) / [FActScore](https://arxiv.org/abs/2305.14251)：证据约束与事实拆解 | RAGAS 关注 RAG 系统的 faithfulness、answer relevance、context precision/recall。FActScore 将长文本拆成 atomic facts，再逐条验证事实是否有支撑。 | N3 现状基线和 N6 技术方案里有大量事实性判断，不能只看语言流畅度，应拆成可验证事实，逐条检查是否能回链到 PRD、KM、代码、DB、配置或接口文档 |

### 4. 评测集总体设计

#### 4.1 五类资产

| 资产 | 说明 | 示例 |
| --- | --- | --- |
| Input Bundle | 运行阶段所需输入 | 原始需求、FSD/KM 链接、上游产物、代码 commit |
| Expected Behavior | 标准期望行为 | 必须识别某仓库、必须覆盖某 AC、不得提前写方案 |
| Oracle / Grader | 判定依据与评分器 | exact match、规则校验、证据回链、LLM judge、人工评审 |
| Metadata | 样本标签 | 阶段、业务域、复杂度、是否跨仓、失败模式 |
| Run Record | 运行记录 | 模型版本、Prompt 版本、Skill 版本、得分、失败原因、成本 |

Oracle 是“什么算对”的判定依据，Grader 是“如何执行评分”的打分器。

#### 4.2 评测集分层

| 分层 | 用途 | 样本来源 | 是否门禁 |
| --- | --- | --- | --- |
| Golden Set | 稳定回归，版本升级必跑 | 历史高质量需求、人工精标样本 | 是 |
| Hard Set | 复现系统短板 | 返工案例、PR Review 问题、线上缺陷 | 是，低频运行 |
| Shadow Set | 观察真实分布 | 近期真实需求抽样，弱标注或半自动标注 | 否，先观测 |

#### 4.3 Case Schema

```Json
{
  "case_id": "YX-EVAL-N4-0001",
  "title": "营销活动互斥规则需求澄清",
  "stage": "N4_REQUIREMENT",
  "domain": "marketing",
  "difficulty": "medium",
  "source": {
    "fsd_url": "https://...",
    "km_links": ["<!-- 内部链接已脱敏 -->"],
    "repo_commits": {"repo-a": "abc123"}
  },
  "input_bundle": {
    "raw_requirement": "path/or/text",
    "upstream_artifacts": {
      "current_state": "current-state.md",
      "evidence": "evidence.md"
    },
    "constraints": ["不得提前生成技术方案"]
  },
  "expected": {
    "must_cover": ["AC-01", "异常场景：重复提交"],
    "must_not_include": ["未经确认的技术实现", "虚构业务规则"],
    "golden_artifact": "gold/requirement.md"
  },
  "graders": ["schema_checker", "traceability_checker", "llm_judge_rubric"],
  "thresholds": {"pass": 75, "excellent": 90},
  "failure_modes": ["P1_REQUIREMENT_MISUNDERSTANDING", "P6_CONTEXT_GAP"]
}
```

### 5. 总体评分模型

阶段质量分：

```Text
阶段质量分 = 结构合规分 × 25% + 内容质量分 × 40% + 追溯证据分 × 20% + 下游可用性分 × 15%
```

全链路权重建议：

```Text
全链路质量分 = N1 5% + N2 8% + N3 15% + N4 22% + N6 30% + N7 20%
```

等级与动作：

| 等级 | 分值 | 动作 |
| --- | --- | --- |
| 优秀 | ≥90 | 入正样本库，必要时作为 Golden Artifact |
| 通过 | 75-89 | 正常流转 |
| 需改进 | 60-74 | warn，建议修正 |
| 不合格 | <60 | block，修正后重评 |
| 关键指标为 0 | 任意分 | 强制 block |

### 6. 分阶段评测指标与样本构造

#### 6.1 N1 需求入口提取评测

##### 6.1.1 产出物与样本构造

产出物：`km_links[]`、`fsd_url`、`group_info`、原始输入记录与提取证据。

| 内容 | 说明 |
| --- | --- |
| 输入 | 用户原始输入，可能包含 FSD、KM、纯文本需求、多个链接、短链、anchor 链接、无效链接 |
| 标注 | `expected_fsd_url`、`expected_km_links`、`expected_link_types`、`invalid_links`、`raw_evidence_span` |
| Oracle | 链接集合标准答案、链接类型标准答案、原文 evidence span |
| Grader | URL exact checker、link type checker、accessibility checker、evidence span checker |

##### 6.1.2 指标

| 维度 | 指标 | 评测方式 | 计算规则 | 门禁建议 |
| --- | --- | --- | --- | --- |
| 结构合规 | 必填字段完整率 | Schema 检查 | `非空必填字段数 / 必填字段总数` | <100 warn |
| 内容准确 | FSD 提取准确率 | exact match | `正确 fsd_url 数 / 应提取 fsd_url 数` | 明确存在但未提取 block |
| 内容准确 | KM 链接召回率 | 集合匹配 | `正确提取 KM 链接数 / 应提取 KM 链接数` | <80 block |
| 内容准确 | KM 链接精确率 | 集合匹配 | `正确提取 KM 链接数 / 实际提取 KM 链接数` | <80 warn |
| 内容准确 | 链接类型分类准确率 | 标准答案比对 | `分类正确链接数 / 正确提取链接数` | <80 warn |
| 追溯证据 | 原文回链率 | span 匹配 | `有原文证据字段数 / 提取字段总数` | <90 warn |
| 下游可用 | N2 启动成功率 | 下游运行验证 | `N2 可基于 N1 输出启动 ? 100 : 0` | 0 block |

阶段评分：

```Text
N1 分 = 字段完整率×15% + 链接召回率×30% + 链接精确率×20% + 类型分类准确率×15% + 原文回链率×10% + N2启动成功率×10%
```

#### 6.2 N2 作用域初始化评测

##### 6.2.1 产出物与样本构造

产出物：`active_repos[]`、`primary_repo`、feature branch、worktree、`work_status.md`。

| 内容 | 说明 |
| --- | --- |
| 输入 | N1 输出、原始需求、KM 文档、历史需求仓库线索、代码搜索线索 |
| 标注 | `expected_primary_repo`、`expected_active_repos`、`optional_repos`、`forbidden_repos`、`repo_selection_evidence` |
| Oracle | 仓库集合标准答案、主仓标准答案、仓库选择证据 |
| Grader | repo set checker、primary repo checker、evidence checker、worktree checker |

##### 6.2.2 指标

| 维度 | 指标 | 评测方式 | 计算规则 | 门禁建议 |
| --- | --- | --- | --- | --- |
| 结构合规 | `work_status.md` 字段完整率 | Schema 检查 | `已填写字段数 / 必填字段数` | <100 warn |
| 结构合规 | 分支/worktree 创建成功率 | Git/文件检查 | `成功创建项数 / 预期创建项数` | <100 block |
| 内容准确 | 主仓命中率 | exact match | `primary_repo == expected_primary_repo ? 100 : 0` | 0 block |
| 内容准确 | 仓库召回率 | 集合匹配 | `正确识别仓库数 / 应识别仓库数` | 核心仓漏掉 block |
| 内容准确 | 仓库精确率 | 集合匹配 | `正确识别仓库数 / 实际识别仓库数` | <70 warn |
| 内容准确 | 无关仓误召率 | 集合匹配，反向指标 | `误召仓库数 / active_repos 总数` | > 30 warn |
| 追溯证据 | 仓库选择证据覆盖率 | 证据检查 | `有证据仓库数 / active_repos 总数` | <90 warn |
| 下游可用 | N3 扫描可执行率 | 下游运行验证 | `可执行扫描仓库数 / active_repos 总数` | <100 block |

阶段评分：

```Text
N2 分 = work_status完整率×10% + 分支worktree成功率×15% + 主仓命中×20% + 仓库召回率×25% + 仓库精确率×10% + 仓库证据覆盖率×10% + N3扫描可执行率×10%
```

#### 6.3 N3 现状基线评测

##### 6.3.1 产出物与样本构造

产出物：`current-state.md`、`evidence.md`、`baseline-gate.md`，可选中间产物包括 `feature-points.md`、`scan-plan.md`、scan 片段等。

| 内容 | 说明 |
| --- | --- |
| 输入 | 原始 PRD、KM 背景资料、N1/N2 输出、active_repos 固定 commit |
| 标注 | `expected_entries`、`expected_current_capabilities`、`expected_gaps`、`expected_non_gaps`、`required_evidence`、`forbidden_solution_terms` |
| Oracle | 入口标准答案、关键能力标准事实、代码/KM 证据、禁止方案词 |
| Grader | structure checker、entry coverage checker、evidence backlink checker、atomic fact checker、solution leakage checker、LLM judge |

##### 6.3.2 指标

| 维度 | 指标 | 评测方式 | 计算规则 | 门禁建议 |
| --- | --- | --- | --- | --- |
| 结构合规 | 产物文件齐全率 | 文件检查 | `存在且非空文件数 / 预期文件数` | 核心文件缺失 block |
| 结构合规 | 章节完整率 | Markdown 标题匹配 | `命中章节数 / 模板章节总数` | <100 warn |
| 结构合规 | 表格/枚举合规率 | 模板列和值域校验 | `合规项数 / 总项数` | <90 warn |
| 边界合规 | 禁止方案性表述命中数 | 关键词扫描 | 0次=100；1-2次=60；≥3次=0 | ≥3 block |
| 内容准确 | 入口识别召回率 | 对照 expected_entries | `命中入口数 / 应识别入口数` | 核心入口漏识别 block |
| 内容准确 | 入口行为描述准确率 | 读代码与证据比对 | `(一致数 + 部分一致数×0.5) / 入口总数` | <85 warn |
| 内容准确 | 能力缺口准确率 | 代码搜索反证 | `真实缺口数 / 声明缺口总数` | 关键误判 block |
| 内容准确 | 需求 GAP 有效率 | Agent 评审 | `有效 GAP 数 / GAP 总数` | <80 warn |
| 追溯证据 | 入口证据回链率 | current-state ↔ evidence 对齐 | `有 evidence 支撑入口数 / 入口总数` | 核心入口无证据 block |
| 追溯证据 | 事实支持率 | atomic fact 验证 | `有代码/KM支撑事实数 / 事实总数` | <85 warn |
| 下游可用 | 澄清路由覆盖率 | 待确认项路由检查 | `已路由待确认项数 / 待确认项总数` | <90 warn |
| 下游可用 | N4 引用率 | 下游反向统计 | `被 N4 引用关键现状项数 / N3关键现状项总数` | 观测指标 |

阶段评分：

```Text
N3 分 = 结构合规分×25% + 内容准确分×40% + 证据回链分×25% + 下游路由分×10%
结构合规分 = 文件齐全率×40% + 章节完整率×35% + 表格枚举合规率×25%
内容准确分 = 入口召回率×25% + 行为描述准确率×30% + 能力缺口准确率×30% + GAP有效率×15%
证据回链分 = 入口证据回链率×50% + 事实支持率×50%
```

#### 6.4 N4 需求澄清评测

##### 6.4.1 产出物与样本构造

产出物：`requirement.md`、`prototype.md`、`clarification-log.md`、`clarification-summary.md`、`requirement-gate.md`。

| 内容 | 说明 |
| --- | --- |
| 输入 | 原始 PRD、prototype、N3 current-state/evidence、PM/RD/QA 澄清记录 |
| 标注 | `expected_user_stories`、`expected_acceptance_criteria`、`must_clarify_questions`、`expected_business_rules`、`forbidden_requirements`、`expected_current_state_links` |
| Oracle | 原始需求点、AC 标准集合、澄清问题标准结论、禁止扩写项 |
| Grader | requirement schema checker、PRD coverage checker、clarification closure checker、testability checker、current-state mapping checker、LLM judge |

##### 6.4.2 指标

| 维度 | 指标 | 评测方式 | 计算规则 | 门禁建议 |
| --- | --- | --- | --- | --- |
| 结构合规 | 文件齐备率 | 文件检查 | `存在且非空文件数 / 预期文件数` | 核心文件缺失 block |
| 结构合规 | 章节完整率 | 标题匹配 | `命中章节数 / 模板章节总数` | <100 warn |
| 结构合规 | 用户故事编号合规率 | 正则检查 | `US-XX格式故事数 / 故事总数` | <100 warn |
| 结构合规 | 故事必填字段覆盖率 | 字段检查 | `字段完整故事数 / 故事总数` | <95 warn |
| 内容准确 | PRD 忠实度 | LLM/Human rubric | 1-5分换算百分制 | <4/5 block |
| 内容质量 | 用户故事自包含度 | 抽样评审 | 1-5分换算百分制 | <4/5 warn |
| 内容质量 | AC 可测试率 | QA/Agent 评审 | `可直接转测试用例AC数 / AC总数` | <80 block |
| 内容质量 | 业务规则无歧义率 | 模糊词 + 语义评审 | `无歧义规则数 / 规则总数` | <85 warn |
| 追溯证据 | PRD→Story 覆盖率 | 覆盖矩阵 | `被故事覆盖原始需求点数 / 原始需求点总数` | 核心需求遗漏 block |
| 追溯证据 | Story→现状映射准确率 | 对照 N3 | `正确关联N3现状故事数 / 故事总数` | <85 warn |
| 闭环质量 | must_clarify 闭环率 | 澄清记录检查 | `有明确结论问题数 / must_clarify问题总数` | <100 block |
| 下游可用 | N6 输入可用率 | 下游反向统计 | `可被设计承接故事数 / 故事总数` | 观测指标 |

阶段评分：

```Text
N4 分 = 结构合规分×20% + 内容质量分×45% + 追溯证据分×20% + 澄清闭环分×15%
内容质量分 = PRD忠实度×35% + 用户故事自包含度×20% + AC可测试率×25% + 业务规则无歧义率×20%
追溯证据分 = PRD→Story覆盖率×60% + Story→现状映射准确率×40%
```

#### 6.5 N6 技术方案评测

##### 6.5.1 产出物与样本构造

产出物：`design.md`、`design-interface.md`、`design-review.md`、`release-checklist.md`。存在跨仓、跨包、接口协议变化时，`design-interface.md` 必须产出。

| 内容 | 说明 |
| --- | --- |
| 输入 | requirement.md、prototype.md、current-state.md、evidence.md、knowledge.md、代码固定 commit |
| 标注 | `expected_design_items`、`expected_high_risk_topics`、`expected_contracts`、`expected_constraints`、`forbidden_designs`、`required_evidence` |
| Oracle | US/AC 到 D-xx 的标准覆盖、高危场景清单、接口契约标准、规范约束 |
| Grader | design schema checker、requirement-to-design checker、high-risk checklist checker、contract checker、evidence checker、LLM judge |

##### 6.5.2 指标

| 维度 | 指标 | 评测方式 | 计算规则 | 门禁建议 |
| --- | --- | --- | --- | --- |
| 结构合规 | 文件齐备率 | 文件与条件产物检查 | `实际合规文件数 / 预期文件数` | 必备文件缺失 block |
| 结构合规 | D-xx 编号规范率 | 正则检查 | `规范D-xx数 / 设计项总数` | <100 warn |
| 结构合规 | 章节完整率 | 模板匹配 | `命中章节数 / 预期章节数` | <100 warn |
| 内容质量 | requirement→design 覆盖率 | 覆盖矩阵 | `被D-xx覆盖US/AC数 / US/AC总数` | 核心AC遗漏 block |
| 内容质量 | 推导链完整度 | LLM/Human rubric | 问题拆解→方案选择→设计决策→实现约束，1-5分 | <4/5 warn |
| 内容质量 | 架构决策依据充分度 | 证据检查 + 评审 | `有明确依据决策数 / 关键决策总数` | <85 warn |
| 内容质量 | 高危场景覆盖率 | Checklist | `已处理高危项数 / 适用高危项总数` | 关键高危项缺失 block |
| 内容质量 | 可实现性评分 | 代码落点与依赖检查 | 1-5分换算百分制 | <4/5 warn |
| 追溯证据 | 设计证据支撑率 | 对照 N3/N5/代码/KM | `有来源支撑设计项数 / 设计项总数` | <85 warn |
| 追溯证据 | 接口契约覆盖率 | 跨边界调用检查 | `已定义契约跨边界调用数 / 跨边界调用总数` | 缺核心契约 block |
| 质检闭环 | design-review 问题闭环率 | Review 状态检查 | `已修复问题数 / review问题总数` | BLOCKED 未闭环 block |
| 下游可用 | design→task 可分解率 | N7 反向统计 | `可清晰拆分D-xx数 / D-xx总数` | 观测指标 |

高危场景清单至少包括：事务边界、幂等、并发、兼容性、灰度、回滚、降级、监控告警、数据订正、缓存一致性、异步时序、配置变更。

阶段评分：

```Text
N6 分 = 结构合规分×20% + 内容质量分×45% + 追溯证据分×20% + 质检闭环分×15%
内容质量分 = requirement→design覆盖率×25% + 推导链完整度×25% + 架构决策依据充分度×15% + 高危场景覆盖率×25% + 可实现性评分×10%
追溯证据分 = 设计证据支撑率×50% + 接口契约覆盖率×50%
```

#### 6.6 N7 编码计划评测

##### 6.6.1 产出物与样本构造

产出物：`tasks.md`、接口契约任务 C-xx、覆盖矩阵、任务依赖 DAG。

| 内容 | 说明 |
| --- | --- |
| 输入 | design.md、design-interface.md、design-review.md、代码固定 commit、任务模板、测试规范 |
| 标注 | `expected_task_coverage`、`expected_contract_tasks`、`expected_dependencies`、`expected_files`、`expected_test_strategy`、`forbidden_task_patterns` |
| Oracle | D-xx 到 Task 的标准覆盖、关键依赖、文件范围、测试策略 |
| Grader | task schema checker、design-to-task checker、DAG checker、anchor checker、instruction judge、test strategy checker |

##### 6.6.2 指标

| 维度 | 指标 | 评测方式 | 计算规则 | 门禁建议 |
| --- | --- | --- | --- | --- |
| 结构合规 | 任务格式合规率 | 正则检查 | `格式合规任务数 / 任务总数` | <100 warn |
| 结构合规 | 必填字段覆盖率 | 字段检查 | `6字段齐全任务数 / 任务总数` | <95 warn |
| 结构合规 | A/B 分类明确率 | 规则检查 | `明确分类任务数 / 任务总数` | <100 warn |
| 内容质量 | design→task 覆盖率 | 覆盖矩阵 | `被任务覆盖非豁免D-xx数 / 非豁免D-xx总数` | 未覆盖核心D-xx block |
| 内容质量 | D-xx 映射正确率 | 语义评审 | `正确承接设计意图任务数 / 抽检任务数` | <85 warn |
| 内容质量 | 任务粒度合理度 | Agent/人工评审 | 1-5分换算百分制 | <4/5 warn |
| 内容质量 | Instruction 可执行度 | Agent/人工评审 | 1-5分换算百分制 | <4/5 warn |
| 追溯证据 | Context 锚点可定位率 | 代码路径/类/方法检查 | `可定位锚点数 / 锚点总数` | <80 block |
| 执行正确 | Depends on 有效率 | DAG 校验 | 引用存在且无环；有环直接0分 | 有环 block |
| 执行正确 | Verified by 合规率 | 测试命令/验证方式检查 | `验证方式合规任务数 / 任务总数` | 核心A类无测试 block |
| 下游可用 | 并行批次可执行率 | DAG 分批模拟 | `可无冲突并行任务数 / 可并行任务总数` | 观测指标 |

阶段评分：

```Text
N7 分 = 结构合规分×20% + 内容质量分×40% + 执行正确分×25% + 下游可用分×15%
内容质量分 = design→task覆盖率×30% + D-xx映射正确率×20% + 任务粒度合理度×25% + Instruction可执行度×25%
执行正确分 = Context锚点可定位率×35% + Depends on有效率×35% + Verified by合规率×30%
```

### 7. Grader 体系

| Grader 类型 | 适用阶段 | 说明 |
| --- | --- | --- |
| Exact Grader | N1/N2 | 链接、repo 集合、主仓命中 |
| Rule Grader | N3/N4/N6/N7 | 文件、章节、编号、字段、DAG、关键词 |
| Traceability Grader | N3/N4/N6/N7 | PRD→US、US→D-xx、D-xx→Task、现状→需求 |
| Evidence Grader | N3/N6 | 事实和设计决策是否有代码/KM/配置支撑 |
| LLM Judge | N3/N4/N6/N7 | 开放式语义质量评分 |
| Human Review | Golden/Hard Set | 高风险样本校准和争议仲裁 |
| Execution Grader | 后续 N8/N9 | 编译、单测、集成测试、覆盖率反证 |

LLM Judge 要求：

- 必须基于给定输入和证据评分，不能使用常识补业务事实。
- 每个评分项必须输出分数、理由、证据引用和修复建议。
- N4/N6/N7 建议使用双 judge：一个正向评分，一个专门找漏洞。
- Golden Set 定期人工抽检，校准 judge 与人工一致性。

### 8. 目录结构

```Text
yuanxi-evalset/
  README.md
  versions/
    v0.1_seed/
    v0.2_regression/
    v0.3_hard_cases/
  cases/
    N1_intake/
    N2_scope/
    N3_current_state/
    N4_requirement/
    N6_design/
    N7_tasks/
  rubrics/
    n3_current_state_rubric_v1.md
    n4_requirement_rubric_v1.md
    n6_design_rubric_v1.md
    n7_tasks_rubric_v1.md
  graders/
    exact_checkers/
    schema_checkers/
    traceability_checkers/
    evidence_checkers/
    llm_judge_prompts/
  goldens/
    artifacts/
    labels/
  reports/
    baseline/
    runs/
```

| 目录 | 含义 |
| --- | --- |
| `versions/` | 评测集版本快照，记录哪些 case 参与本版本 |
| `cases/` | 各阶段评测样本输入与期望行为 |
| `rubrics/` | 什么叫好的评分标准 |
| `graders/` | 如何执行评分的规则、脚本或 Prompt |
| `goldens/` | 人工确认的标准答案、金牌产物和标签 |
| `reports/` | 每次评测运行结果、回归对比和失败明细 |

### 9. 初始样本规模

建议 v0.1 建设 60 条种子样本：

| 阶段 | 样本数 | 重点覆盖 |
| --- | --- | --- |
| N1 | 10 | 混合链接、无效链接、anchor 链接、纯文本需求 |
| N2 | 10 | 单仓、多仓、Provider/Consumer、误召仓 |
| N3 | 10 | 入口漏扫、能力缺口误判、证据不足、方案泄漏 |
| N4 | 10 | PRD 误解、AC 不可测、must_clarify 未闭环、故事不自包含 |
| N6 | 10 | 高危场景遗漏、接口契约缺失、推导链断裂、越界设计 |
| N7 | 10 | D-xx 未覆盖、任务过粗、DAG 错误、Context 不可定位 |

### 10. 评测报告

每次运行输出三类报告：

- 总览报告：评测集版本、系统版本、总分、阶段分、通过率、block 数、回归数、成本。
- 阶段报告：样本通过率、核心指标均值、P50、P90、最低分、Top 失败样本、高频失败模式。
- Case 详情报告：输入摘要、产出物路径、grader 明细分、block/warn 项、证据引用、差异和修复建议。

### 11. 建设节奏

#### 11.1 第一阶段：种子集建设，1~2 周

- 从历史需求中挑选 30 条普通样本、20 条失败样本、10 条高质量样本。
- 完成 N1/N2 exact 标注。
- 完成 N3/N4/N6/N7 人工弱标注和第一版 rubric。
- 建立基础报告格式。
- 先以 warn 模式运行，不做强阻断。

#### 11.2 第二阶段：评分器稳定，3~4 周

- 固化 schema/rule/traceability grader。
- 对 N4/N6/N7 的 LLM judge 做人工一致性校准。
- 将高置信规则升级为 block。
- 对历史系统版本跑回放，建立 baseline。

#### 11.3 第三阶段：闭环运营，5~8 周

- 每次模型、Prompt、Skill、流程改动前后跑 Golden Set。
- 每周跑 Hard Set，检查历史失败模式是否回归。
- 每月从真实需求抽样补充 Shadow Set。
- 将连续 3 次命中的失败模式固化为 Guardrail。
- 将高分样本沉淀为正样本经验库，供后续需求注入。

### 12. 成功标准

| 指标 | 目标 |
| --- | --- |
| Golden Set 稳定性 | 同一系统版本重复运行分差不超过 3 分 |
| 人工一致性 | N4/N6/N7 LLM judge 与人工结论一致率 ≥80% |
| 历史问题复现率 | Hard Set 中历史失败模式复现率 ≥70% |
| 退化发现率 | Prompt/Skill 变更导致的质量退化能被评测集捕获 |
| 规则沉淀率 | 每月至少沉淀 3 条稳定 Guardrail 或 Checklist |
| 经验转化率 | 高分样本中至少 30% 可转化为可复用经验 |

### 13. 推荐落地优先级

1. 先做 N4、N6、N7，因为它们最直接影响后续 AI Coding 成败。
2. 同步补 N1、N2 的 exact 评测，成本低、收益稳定。
3. N3 不只做章节检查，要以证据回链和事实拆解为核心。
4. 第一版评测集先跑 warn 模式，校准 2~3 周后再升级 block。
5. 每个阶段都保留正样本和负样本，避免评测集只会发现坏产物，却不知道好产物长什么样。

> Oracle、Grader：Oracle 是评测的“答案依据”，Grader 是执行评分的“打分器”
