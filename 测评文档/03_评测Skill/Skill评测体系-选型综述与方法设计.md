# Skill 评测体系 — 选型综述与方法设计

> 源文档: <!-- 内部链接已脱敏 -->
> 拉取时间: 2026-07-13

> ℹ️ **摘要**
>
> 随着Agent Skill 数量超过 40 个、覆盖 PM→需求→设计→编码→测试→部署全链路,"如何评一个 Skill 写得好不好、用起来对不对"成为质量保障的核心问题。我们评的对象不是模型,而是 **Skill 这份被注入上下文的资产**。
>
> 本文给出一套评测体系：**先按 Anthropic 的两类划分（能力提升型 / 偏好编码型）确定评测重点——Agent以偏好编码型为主，核心是流程忠实度而非能力增量 ΔP**；方法上借鉴 skill-creator ，但**把它从"造 Skill 时在线评"改造成"用户真实跑完后、离线回放 CC 执行 trace "**；落地为 L1–L5 单向门控，重点建设 L1 静态准入与 L3 真实 trace 执行评判。

---

### 一、引言

#### 1.1 背景与挑战

Agent Skill 已超 40 个、覆盖研发全链路，质量保障面临五类痛点：评测标准难量化、Case 覆盖度不足、多 Skill 路由冲突难测、CLI 参数/工程正确性难测、评测链路长且根因定位难。

评测的对象需要先界定清楚：我们评的不是"模型"，而是"**Skill 这份被注入到上下文里的资产**"——一段写给 Agent 看的 SKILL.md，连同它的 references / scripts。同一个模型，给不给这份 Skill、写得好不好，结果天差地别；而且"读起来好看"不等于"好用"。

#### 1.2 关键前置问题：

#### 1.2.1 先分清 Skill 是哪一类

在打任何分之前，必须先回答一个更前置的问题：**这个 Skill 是哪一类？** Anthropic 在 skill-creator 里把 Skill 分两类，评测重点完全不同：

| 类型 | 定义 | 典型例子 | 评测重点 | 演进趋势 |
| --- | --- | --- | --- | --- |
| **Capability Uplift（能力提升型）** | 让 Agent 做到原来做不到或做不稳的事 | yx-java-hot-deploy、yx-onetest-gate | **有/无 Skill 的 pass rate 对比（ΔP）**；随模型能力提升可能不再必要，evals 会告诉你何时发生 | 随模型进步逐渐退出 |
| **Encoded Preference（偏好编码型）** | Agent 已能完成各步骤，但 Skill 按团队流程把它们串起来 | yx-plan、yx-subagent-driven-development | **流程忠实度（步骤遵循率）**；对照流程文档验证 | 长期稳定，只要流程不变 |

> **本文的核心命题（贯穿全文）：**
>
> 评一个 Skill，第一步不是打分，而是分清它是哪一类——**能力提升型看能力增量 ΔP，偏好编码型看流程忠实度**。Agent的 Skill 绝大多数是后者（"把 Agent 能做的事按Agent规范串起来"），所以我们评测的核心是 **"有没有忠实地按团队流程走完"**，而不是 **"带不带 Skill 谁的 pass rate 高"**。这一点必须先说清楚，否则会犯一个常见错误：用 ΔP（能力提升型的指标）去衡量一个偏好编码型 Skill——而对一个 Agent 本来就能做的流程，ΔP 往往趋近于 0，于是会误判"这个 Skill 没用"。真正该问的是它有没有把流程串对。

这个分类决定了后面所有设计：因为Agent以偏好编码型为主，我们的评测必须能精确回答"流程的每一步做了没有、做对没有"——这就要求拿到**真实的执行过程**，而不只是看最终结果对不对。

#### 1.2.2 **为什么是线上真实 trace，而不是自己造一批任务来跑？**

最自然的替代方案是仿照 benchmark：自己设计一组测试任务，在我们的机器上批量跑、再打分。我们没走这条路，理由有四条：

1. **在线执行环境根本拿不到**。Skill 跑在用户自己的机器上，依赖用户本地的代码库、需求上下文、工程配置和凭证——这套环境我们无法复现，也无法像 skill-creator 那样在线注入故障。想自己跑，第一步就卡死。
2. **真实分布才暴露真问题**。合成任务只覆盖我们"想得到"的情况；而真实需求里的模糊措辞、边角 case、以及多个 Skill 在一条 session 里的真实串联组合，恰恰是我们坐在工位上想不出来的。AHE 的结论同样：真实场景才暴露真问题。
3. **样本是"白来的"且持续累积**。每一次用户真实执行都经 Stop hook 自动上传，不需要专门组织人力去跑测试集；规模和多样性随日常使用自然增长，跨用户、跨需求背景的横向样本天然就有。
4. **评的是"真实加载的那份规则"**。真实 trace 里保存了运行时实际加载的 `skill_{name}.md`，评判对照的就是用户当时真正用到的版本，而不是我们造测试时锚定的某个固定快照。

### 二、相关工作

#### 2.1 方法论与学术对标

| 来源 | 示例 | 它做了什么、怎么做的 | 在我们场景下的不足 |
| --- | --- | --- | --- |
| **skill-creator**<br>(Anthropic, 2026.03) | ![图片 (515x301)](<!-- 内部链接已脱敏 -->) | 官方"造 Skill 的 Skill"。先把 Skill 分两类（Capability Uplift / Encoded Preference）；<br>核心是一个**迭代改进循环**（创建→测试→量化评估→可视化审查）：每轮只改一个 SKILL.md，同时跑 with-skill + baseline 报 **Δ**；<br>断言由 **Grader Agent（AI）语义判定**通过/失败（不是结构化精确匹配），最后人工确认。 | 它是**造 Skill 时的在线评**：输入由它自己构造、故障可主动注入、trace 是它自己驱动跑出来的。<br>我们要评的是**用户在自己机器上真实跑完的 Skill**——拿不到那套在线环境，也无法在线注入故障。 |
| **SkillLearnBench**<br>(arXiv:2604.20087, CMU) | ![image.png (493x160)](<!-- 内部链接已脱敏 -->) | 持续技能学习 benchmark。20 个真实任务、**三级评测**（Skill Quality / Trajectory Quality / Task Success），Task Success 用确定性 verifier；<br>求解 agent 与 judge **跨模型**；b1–b4 对比证明**自反馈会递归漂移、外部反馈才真实改进**。 | 它是 **benchmark**，要预先造好金标准任务 + 确定性 verifier 才能跑。<br>我们评的是线上真实 trace、没有金标准，Task 这一级无法照搬确定性 verifier。 |
| **SkillLens**<br>(arXiv:2605.23899) | ![image.png (471x236)](<!-- 内部链接已脱敏 -->) | Skill 生命周期**实证研究**。测出无 rubric 时 LLM-judge 准确率仅 **46.4%**（低于随机）、加 3 维实证 rubric 升 **73.8%**；"看起来更好的 Skill 往往表现更差"**25% 是负迁移**；三个最高 better-rate 维度：可执行具体性 66.0% / 失败模式编码 65.5% / 反例黑名单 64.6%。 | 它给的是**实证结论**（哪些维度能预测质量），不是一套能跑的评测系统；<br>只覆盖静态编写质量，不回答执行过程对不对。 |
| **AHE**（Agentic Harness Engineering） | ![image.png (497x249)](<!-- 内部链接已脱敏 -->) | Agent 调试方法论。<br>指出 raw trace 可达数10M token本身不是高价值资产，构建分层流水线：保留原始trace、cleaner清洗去重、QA聚合 overview<br>本质是**渐进式披露**（默认读 overview、按需下钻、必要时回 raw 核实）；<br>Agent Debugger 证据驱动、finding 四要素可被下一轮**证伪**、同根因只记一次。 | 它的提炼服务于 **Evolver（自动改代码）** ；是自己构建的可观测系统harness |
| **darwin-skill** | ![图片 (551x232)](<!-- 内部链接已脱敏 -->) | 开源 skill 优化器。9 维 rubric（结构 59 + 效果 35 + meta 6），核心是**优化器循环**（评估→改进→实测→人审→保留/回滚）：<br>每轮只改一维（严格变好才 keep，否则 `git revert`）、效果维度靠在线 spawn 独立子 agent 跑 skill vs baseline。 | 它是"**边改边评的在线优化器**"，效果验证靠在线 spawn baseline。 |
| **Skill Judge** |  | 静态质量评判实践。核心公式 **`好 Skill = 专家级知识 − Claude 已知`**，每段标注 Expert / Activation / Redundant；120 分 8 维 A–F 评级；总结 **9 个失败模式**。 | 它是**纯静态质量评判**，完全不评执行——只回答"写得好不好"，不回答"跑起来对不对"。 |

#### 2.2 工程工具对标：DeepEval / Promptfoo（重点）

> 这两个工具的价值**不在端到端照搬，而在断言与打分的组件设计**。一个反直觉但关键的事实：两者都能把"预先生成好的输出"喂进去、只跑评判这一步（DeepEval 用端到端的 `evaluate()` 配合手工构造测试用例，Promptfoo 用 `echo` 数据源），所以**单轮输出打分可以直接借它们的组件**；但**两者原生的轨迹评测都绑定"自己在线驱动跑出来的执行记录"**——而轨迹、流程忠实度恰恰是我们最需要评的那一层。下面分别说清。

##### **DeepEval —— "LLM 界的 pytest"**

定位是开源的 LLM 评测框架，用法对标单元测试：写测试函数、写断言、跑命令，每个指标给 0–1 分并附理由，按阈值判通过 / 失败。核心数据结构是测试用例 `LLMTestCase`（输入、实际输出、期望输出、调用的工具、期望工具等字段）。三个最值得看的机制：

| **机制** | **怎么做** |
| --- | --- |
| **G-Eval** | 有论文支撑的 LLM 评判器。给"评分步骤"（比让它自由发挥更稳）加"不重叠分数带"（如 0–10 分各档语义不重叠，防止分数都挤在中间）；打分时按输出 token 的概率做归一化加权，降低评分偏置 |
| **DAG 决策树** | "确定性优先、LLM 兜底"。LLM 只在判定节点决定走哪条分支，最终分由确定的路径给出（叶子节点返回固定分，或交给内嵌的 G-Eval 兜底）。一句话概括：拆得越细，模型瞎编的空间越小 |
| **Agentic 指标** | 任务完成度（无需参考答案，从完整执行记录里抽"任务 + 结果"算对齐）、工具正确性（确定性比对：正确调用数 / 总数，可选顺序与精确匹配），另有计划遵循度、步骤效率、目标达成率等 |

**在我们场景的不足**：① 任务完成度、计划遵循度这类轨迹指标，输入的是 DeepEval **自己在线插桩跑出来的执行记录**，不是我们事后拿到的外部 CC 日志；官方没有"把外部已有的完整执行记录直接喂进轨迹指标"的入口。② 我们要评的是一条数十万至千万 token、多个 Skill 串联的真实会话，需要窗口切分、三态 Phase、分层提炼，它的测试用例模型不覆盖这些。③ 需要自行配置LLM provider接口，有一定的成本问题，难以接受

##### **Promptfoo —— 声明式 YAML 评测引擎**

开源的 LLM 测试与红队工具（已并入 OpenAI），理念是"测试驱动的 LLM 开发"。配置用一份 YAML：提示词、数据源、测试用例、公共默认项四块，断言可复用模板、可分组、每条带权重、测试级带阈值，**最终分是各条断言的加权平均**。断言分两类——**确定性**（包含、相等、正则、JSON 校验、自定义脚本等）和**模型辅助**（rubric 评分、事实性、分类器、择优等）；以 rubric 评分为例，评判器要返回分数与理由，分数过阈值才算通过。

<!-- 最小示例： -->
```YAML
providers: [echo]            # 不调模型，直接把传入的真实输出当作待评内容
tests:
  - vars: { logged_output: '...上传的真实产物...' }
    assert:
      - type: llm-rubric
        value: '产物是否覆盖了 SKILL.md 声明的关键要点'
        threshold: 0.8
      - type: contains
        value: 'release-checklist.md'
```

**在我们场景的不足**：① 它最"对口"的那组轨迹断言（工具是否调用、工具顺序、步数、目标是否达成、Skill 是否触发），读的是 **Promptfoo 这次 run 自己产生的执行链路记录**，不是外部上传的会话日志——轨迹层用不了，只能自己用脚本断言重写"工具顺序 / 步数 / Skill 是否触发"。② 它红队那套指标衡量的是"攻击成功率"，和"Skill 执行质量评分"语义不同，迁移价值有限。

> **共同结论**：两者的端到端入口都证明了"喂预生成输出、只跑评判"可行，所以**单轮输出打分可借它们的组件**；但**轨迹与流程忠实度的离线评测它们都做不了**——而那正是偏好编码型 Skill 的评测核心，只能我们自建（见 §3.5 Debugger）。具体借用了哪些组件见第三章。

#### 2.3 指导第三章方法的实证结论（小结）

第二章可提炼出 4 条直接指导第三章方法的结论：

1. **价值看类型，不看绝对分**：skill-creator 两类划分 + SkillLens 25% 负迁移 → 偏好编码型测流程忠实度、能力提升型测 ΔP，且都要防"用了反而更糟"。
2. **rubric 必须实证校准**：SkillLens 46.4%→73.8% → L1 三个最高权重维度取 better-rate 最高的三项。
3. **评结果不评步骤、语义判定不精确匹配**：skill-creator Grader Agent + Anthropic"评结果不评步骤" → L3 任务结果用 Rubric。
4. **三级评测是自然结构**：SkillLearnBench Skill/Trajectory/Task → 背书我们 L1/L3/L4 的分层。

---

### 三、我们的方法

整体做法分四步：**(3.1) 借鉴 skill-creator 的迭代改进循环作为骨架 →（3.2) 把它从"在线造时评"改造成"离线回放真实 trace"→（3.3) 用 L1–L5 分层做单向门控 →（3.4 / 3.5) L1 静态门控 + L3 执行层评判的具体落地**。

> **我们具体引用了第二章哪些工作的哪些方案**：
>
> | 我们的模块 | 引用的方案 | 我们怎么改造 |
> | --- | --- | --- |
> | **L1 静态门控**（§3.4） | darwin-skill 的**结构维度评分**（可执行具体性 / 失败模式编码 / 检查点等）+ **棘轮门控**；Skill Judge 的 **Knowledge Delta**（→Token 效率维度）+ **9 个失败模式**（→反模式扫描清单） | 只做准入门控、**不照搬其在线改写 / 在线实测**；效果验证整体下沉到 L3；9 维收敛成 8 维 |
> | **L3 执行过程**（§3.5） | skill-creator 的**迭代循环骨架** + **Grader Agent 语义判定**；SkillLearnBench 的**三级评测** / **外部反馈 + ratchet** / **跨模型评判**；AHE 的**分层提炼 + 渐进式披露** + **证据驱动 Debugger** | 从"在线造时评"改成"**离线回放真实 trace**"；单 Grader→**Observability + Debugger 两段式**；评真实 trace **不造合成任务**；任务结果用 **Rubric**；额外加**三态 Phase + 评测窗口约束** |
> | **工程组件**（贯穿 L1/L3） | DeepEval：**G-Eval**（evaluation_steps + 不重叠分数带 + logprob 归一化）、**DAG**"确定性优先 LLM 兜底"决策树、**Tool Correctness** 确定性比对；Promptfoo：**llm-rubric + threshold**、**weight / assert-set 加权聚合**、五类确定性断言（子集包含 / 排除 / 参数 / 时序 / 精确匹配） | **只搬组件、不引运行时**：两者的端到端入口（DeepEval end-to-end `evaluate()` + 手工 `LLMTestCase`、Promptfoo `echo` provider）证明"喂预生成输出只跑评判"可行，但其原生 trajectory / agent 轨迹指标都绑定**自驱 tracing**，离线评不了——轨迹层改由 §3.5 Debugger 自建 |

#### 3.1 方法论骨架：skill-creator 的迭代改进循环

skill-creator 给出了一套**可迭代、有对照、能量化**的评测范式——一个**迭代改进循环**：

```Plain Text
       ┌─────────────────────────────────────────────┐
       │                                             │
       ▼                                             │
 ① 创建 Create ──→ ② 测试 Test ──→ ③ 量化评估 Measure ──→ ④ 可视化审查 Review
 写/改 SKILL.md     跑测试用例        Grader Agent 判定      eval-viewer 看结果
 (单一可编辑资产)   with-skill +      断言通过/失败          + 人工确认
                   baseline 对照      报告 Δ                 (人在回路)
```

四阶段关键点：

1. **创建（Create）**：每轮只改**一个** SKILL.md（单一可编辑资产），便于归因。
2. **测试（Test）**：同时跑 **with-skill + baseline** 两个 subagent，为算 Δ 做准备。
3. **量化评估（Measure）**：编写**断言**验证输出，**断言由 Grader Agent（AI）理解并判断通过/失败**——本质是 *AI 读取输出 → 理解断言 → 判断通过/失败*，**不是结构化精确匹配**；同时报告 pass_rate / token / 时间的 **Δ**。
4. **可视化审查（Review）**：eval-viewer 可视化结果，**最后由人工确认**改动是否保留。

#### 3.2 关键改造：从"在线造时评"到"离线回放真实 trace"

skill-creator 是**"造 Skill 的时候在线评"**：输入由它自己构造（可控）、故障可主动注入、trace 是它自己驱动跑出来的。而我们要评的是**用户在自己机器上真实跑完的 Skill**：

> **我们的核心改造：不构造合成用例，直接用 CC 的真实执行 trace 做离线回放评测。**
>
> 用户每次真实执行 Skill，CC session JSONL 通过 `yx-skill-timing` 的 Stop hook 自动上传 S3；我们事后拉下来、清洗成可导航 trace 目录，再对照 Skill 当时实际加载的规则做评判。

这个根本区别决定了一系列改造：

| skill-creator（在线造时评） | 我们（离线回放真实 trace） | 为什么必须改 |
| --- | --- | --- |
| 合成测试用例，自己构造输入 | 直接用真实 CC session trace | 拿不到用户机器执行环境，也无法在线注入；**真实场景才暴露真问题**（AHE） |
| Grader Agent 在线读输出即时判断 | **Observability Agent + Debugger Agent 两段式离线判断** | SKILL.md 篇幅长（yx-plan 1000+ 行），每 session 重解析既慢又没复用；拆两段做**预计算复用** |
| 断言写在 eval 配置里 | 断言基准 = **运行时 ****`skill_{name}.md`**（从 trace 提取，非磁盘当前版本） | 评的必须是 Skill **执行时实际加载**的规则 |
| 一次评一个改动、看单次结果 | 多 session 横向对比看稳定性 | 真实样本天然多样，稳定性靠"同 Skill 跨 session 得分分布"体现 |
| eval-viewer 在线看 | findings JSON + HTML 报告（phase rail + 问题树） | 离线批量产出，需可下钻、可归档 |
| 最后人工确认 | findings **可被下一轮证伪** + HTML 供人审 | 保留"人在回路"，但下沉为**证据驱动**的可证伪 finding |

> **Grader Agent 的灵魂被完整继承**：*断言由 AI 理解语义判定，而非精确匹配*。这正是 L3"**任务结果 / 步骤输出用 Rubric LLM-judge，不用固定预期输出**"的来源——Agent 常找到设计者没预想的有效路径，精确匹配会把正确实现误判成错误。

#### 3.3 分层落地：L1–L5 单向门控

类比测试金字塔，遵循**单向因果依赖**：定义→触发→执行→输出→体验，**下层未通过时上层缺陷无法可靠归因**。

```Plain Text
        ┌────────────────────────────────────┐
        │  L5 体验层（北极星）  pass@k / pass^k │   端到端任务成功率
        ├────────────────────────────────────┤
        │  L4 输出层           幻觉率 / 安全性  │   最终产出物质量
        ├────────────────────────────────────┤
        │  L3 执行层           工具链 / 分支覆盖 │   ← 偏好编码型的主战场
        ├────────────────────────────────────┤
        │  L2 触发层           Precision/Recall │   路由准确率（多 Skill 冲突）
        ├────────────────────────────────────┤
        │  L1 元数据层         静态扫描（低成本）│   编写质量准入门控
        └────────────────────────────────────┘
```

> **探索期只看两个指标**：Skill 早期频繁迭代，做大规模精细化评测会"刚评完就失效"。建议探索期以 **L1 快速评测 + 北极星（pass@k）** 为牵引，出现问题再下钻。
>
> 结合 §1.2 结论：Agent以偏好编码型为主，**L3 执行层是主战场**（流程忠实度在这里测）。L2 有选型方向暂未落地详设；L4/L5 暂不纳入本轮。

#### 3.4 L1 静态门控：低成本拦截编写质量

**目标**：在花算力跑动态评测之前先用静态检查拦掉编写质量问题。L1 是**布尔准入门控**，不是打分排名——参数都讲不清的 Skill 跑 L3 只产不可信结论、浪费算力。

L1 分两层加权合并：

```Plain Text
SKILL.md 目录
   ├─→ 自动化脚本检查（eval-skill.py）：结构 / 触发描述 / 安全扫描 / 脚本质量 / 文档规范（Pass/Fail，P0 失败强制阻断）
   └─→ LLM Rubric 评估（8 维，每维 1–10 分 × 权重）→ 综合得分 = Σ(维度分 × 权重) / 10，阈值 ≥ 70
```

**8 个维度的权重实证校准**（依据见 §4 D2）：

| 维度 | 权重 | 实证依据 |
| --- | --- | --- |
| **可执行具体性** | 17 | SkillLens Actionable Specificity，better-rate 66.0% |
| **工作流清晰度** | 12 | — |
| **失败模式编码** | 12 | SkillLens Failure Mechanism Encoding，better-rate 65.5% |
| 反例与黑名单 | 5 | SkillLens High-Risk Action Blacklist，better-rate 64.6% |
| Token 效率 / Frontmatter / 检查点 / 资源整合度 | 5/7/6/4 | 工程完整性补充（Token 效率取 Skill Judge 的 Knowledge Delta） |

**可评测性专项（进入 L3 的门控）**：L1 通过后再查 5 项（参数格式 / 参数联动 / 执行顺序 / 环境依赖 / 失败可归因性），**≥3 项"可推理"才进入 L3**。

> **L1 准出**：自动化检查全通过 AND 综合得分 ≥70 AND 无维度 ≤2 分 AND 可评测性 ≥3 项可推理 → 进入 L3。
> **迭代门控（ratchet）**：改进后综合得分必须**严格高于**改进前，平局不接受。

#### 3.5 L3 执行层：对真实 trace 做证据驱动评判（核心）

L3 回答三层问题：**①功能正确性**（做对了吗）→ **②过程质量**（过程合理吗）→ **③容错纠错**（能恢复吗）。

**离线管道**（`yx-l3-eval`）：

```Plain Text
用户真实执行 Skill
   │  CC session JSONL 上传 S3（yx-skill-timing Stop hook）
   ▼
┌──────────────────── yx-l3-eval 离线管道 ────────────────────┐
│ ① 拉取 & 预过滤   claudeLogList 拉时间窗内 session，只留含目标 Skill 的 │
│ ② 清洗落库       parse_session.py → parsed/ 目录                       │
│ ③ Observability  每 session 一次（≤10 tool calls）：只读运行时         │
│    Agent          skill_{name}.md → 产出 skill_spec.md（结构化规格）    │
│ ④ Debugger       每 session 一个独立 sub-agent（并发）：对照 skill_spec │
│    Agent          + 下钻 messages.jsonl → 6 维负分制 + 证据驱动 findings │
│ ⑤ 落库 & 报告    skill-eval API + generate_report.py → HTML            │
└────────────────────────────────────────────────────────────┘
```

> **设计要点 ⓪ · 清洗落库是分层提炼，不是简单存储**（借鉴 AHE）
> 一次 rollout 的 raw trace 可达数十万~10M token，包含每次 LLM 调用、tool call、middleware hook、sub-agent；一轮评测常有数百条 trace。**raw trace 本身不是高价值资产**——原封不动扔给下游，上下文预算全烧在读 trace 上，评判的空间所剩无几。所以 `parse_session.py` 在 raw trace 之上构造一条**分层提炼流水线**，产出 `parsed/` 目录：
>
> | 文件 | 层级 | 作用 |
> | --- | --- | --- |
> | `overview.md` | 概览层（~10K token） | Skill 时间线、AskUserQuestion 次数、工具报错、compaction 等关键信号——**Debugger 默认先读这层** |
> | `skill_{name}.md` | 规格源 | 运行时实际加载的 SKILL.md（非磁盘版本），供 Observability Agent 提炼 `skill_spec.md` |
> | `messages.jsonl` | 明细层（不截断） | 逐条消息，支持 `Read(offset, limit)` + `grep` **按需下钻** |
> | `skill_invocations.json` | 索引层 | Skill 调用时间线，界定评测窗口边界 |
> | `subagents/*.jsonl` | 明细层 | 各 sub-agent 消息 |
>
> 分层的本质是**渐进式披露**：Debugger 默认读 overview + skill_spec，按需下钻 messages.jsonl，必要时回 `raw_s3_url` 核实结论是否可信——让 10M 级轨迹变成**可并发、可消费、可审计**的观测资产。

**为什么两段式**（对 skill-creator 单个 Grader Agent 的关键改造）：SKILL.md 太长、Debugger tool-call 预算有限，每 session 重解析既慢又不可复用。Observability Agent 先把运行时 SKILL.md 沉淀成 `skill_spec.md`，Debugger 从"理解原文 + 找证据"降级为"对照规格 + 找证据"——**N 个 session 共享一次 SKILL.md 解析**的预计算复用。

剩下三个关键设计：

> **设计要点 ① · 三态 Phase 模型**
> 每个 Phase 是否"可锚定"取决于有没有可在 trace 检测到的**外部 I/O 签名动作**（Skill 调用 / AskUserQuestion / 写文件 / S3 上传）：
>
> 1. `executed`：可锚定**且**找到签名动作 → range 可信。
> 2. `skipped`：可锚定**但** trace 里确实没做 → **有效问题信号**。
> 3. `unanchorable`：纯内部推理、无外部信号 → range=null，**不代表跳过**。

> **设计要点 ② · 评测窗口约束**（修串联 Skill 互相污染）
> session 是 `skill1 → … → skilln` 串联。窗口 `[win_start, win_end)`：`win_start`=本 skill 调用点，`win_end`=下一个**平级 skill**调用点。
>
> 1. **helper sub-skill**（执行完返回本 skill，如 yx-knowledge-learn）→ **留窗口内**。
> 2. **handoff skill**（控制权不返回，如 yx-plan 末尾的 yx-writing-plans）→ 是**关闭窗口的边界**，绝不能当 sub-skill，否则吞掉下游 skill 的执行（已知 bug）。

> **设计要点 ③ · 任务结果用 Rubric 而非固定预期输出**
> 继承 Grader Agent + Anthropic"评结果不评步骤"：Agent 常找到设计者没预想的有效路径，固定预期会误判正确实现。

**6 维度负分制**：初始 100 分逐项扣，**单次执行 ≥80 通过**。

| 维度 | 扣分规则 | 判定方式 |
| --- | --- | --- |
| **任务结果** | −100（一票否决） | Rubric LLM-judge |
| **步骤遵循性** | 每步偏离 −10 | 五类确定性断言（子集包含 / 排除 / 参数 / 时序 / 精确匹配） |
| **步骤输出** | 每项缺失 −10 | Rubric 要点核查，基准从运行时 SKILL.md「产物目录」动态读取 |
| **工具调用** | 每项 −10 | 排除 + 子集包含断言 + Rubric 解读正确性 |
| **效率** | 超预算 ×1.5 起，每多 5 步 −10 | 步骤预算按 Skill 类型 + 历史 P90 校准 |
| **容错** | 每个未恢复故障 −20 | 外部故障恢复 + 自我纠错 |

**用户干预扫描**：从 trace 捞真实用户消息分三类加权——**纠偏型（权重 15，"不对/重做/方向错了"）必产 ≥1 条 finding**，是步骤遵循性问题的强证据。

**证据驱动四要素**（可被下一轮证伪，同一根因只记一次）：

```JSON
{
  "dimension": "step_compliance",
  "deduction": -10,
  "failure_evidence": "message #163: SubAgent A（yx-knowledge-learn）从未被派发",
  "root_cause": "skill_defect — SKILL.md Phase 2 未要求 SubAgent A 完成前的强制检查点",
  "targeted_fix": "Phase 2 末尾增加：SubAgent A 返回 knowledge.md 路径后才允许进入 Phase 3",
  "predicted_impact": "修复后知识层不被跳过；简单需求可走 fast-channel 豁免"
}
```

`root_cause` category：`skill_defect` / `data_issue` / `env_permission` / `model_randomness`。

> **L3 准出**：eval_score ≥ 80 AND veto = 0 → 通过。

---

### 四、设计决策与依据（为什么这么做）

第三章讲了"怎么做"，这一章逐条说明"为什么"——**尽量来自实证（论文 / benchmark / 官方实现），而非设计者直觉**。

| # | 决策 | 依据 |
| --- | --- | --- |
| **D1** | **先分类，再决定评什么**（能力提升型看 ΔP，偏好编码型看流程忠实度） | skill-creator 两类划分。Agent以偏好编码型为主，用 ΔP 会误判"没用"（Agent 本就会做，ΔP≈0），真正该测流程忠实度 |
| **D2** | **rubric 维度权重必须实证校准** | SkillLens：无 rubric 时 LLM-judge 仅 **46.4%**（低于随机），加 3 维实证 rubric 升 **73.8%**；最高权重维度直接取 better-rate 最高的三项 |
| **D3** | **L1 是布尔门控，不是打分排名** | 参数都讲不清的 Skill 跑 L3 只产不可信结论、浪费算力 |
| **D4** | **任务结果用 Rubric，不用固定预期输出**（继承 Grader Agent） | skill-creator Grader Agent 本就是"AI 读输出→理解断言→判通过/失败"；Anthropic"评结果不评步骤"——Agent 有等效路径，精确匹配会误判 |
| **D5** | **评真实 trace，不造合成用例** | AHE Agent Debugger；真实场景才暴露真问题；离线场景拿不到在线注入 |
| **D6** | **Observability / Debugger 两段式** | SKILL.md 篇幅长，每 session 重解析既慢又没复用；拆两段做预计算复用 |
| **D7** | **三态 Phase 模型** | 修旧版把纯内部推理 Phase 误判成 skipped 的 bug |
| **D8** | **评测窗口约束** | 修串联 Skill 消息互相污染（yx-writing-plans 误标进 yx-plan）；handoff 当 sub-skill 会吞掉下游执行 |
| **D9** | **外部反馈 + ratchet 回退** | SkillLearnBench：自反馈递归漂移，外部反馈才真实改进；darwin-skill 棘轮，改进必须严格高于改进前 |
| **D10** | **防负迁移** | SkillLens：**25% 是负迁移**；强制 baseline 对照才能发现"用了反而更糟" |
| **D11** | **DeepEval / Promptfoo 搬思路不引依赖** | 在线插桩 / 自驱 trace 假设，与事后回放真实 session 冲突 |
| **D12** | **trace 分层提炼 + 渐进式披露**（parse_session.py） | AHE：raw trace 数十万~10M token、本身不是高价值资产，原封不动扔给下游会烧光上下文预算；分层成 overview/明细/raw 三档，默认读概览、按需下钻、必要时回 raw 核实，让大规模轨迹可并发可消费可审计 |

---

*仅供内部使用，未经授权切勿外传*
*最后更新：2026-06-24*
