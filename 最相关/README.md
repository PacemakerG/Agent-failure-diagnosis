# 最相关论文阅读指南

这个 README 只解释 **`最相关/` 目录下真实存在的 6 篇论文**。

注意：从方法价值上看，`PROTEA` 是全仓库 P0 第 1 篇，但它的物理目录目前在：

```text
../高度相关/PROTEA-Offline-Evaluation/
```

所以这里不把 PROTEA 算进 `最相关/` 目录数量，避免目录和 README 不一致。

---

## 这个目录里有哪 6 篇

| 顺序 | 论文 | 核心作用 | 阅读优先级 |
|---|---|---|---|
| 1 | [REFLECT: Silent Failure Attribution](REFLECT-Silent-Failure-Attribution/) | trace 正常结束但结果错，如何定位关键错误步骤 | 最高 |
| 2 | [From Confident Closing to Silent Failure](False-Success-Silent-Failure/) | Agent 自信说完成了，但环境状态没完成，如何识别 false success | 最高 |
| 3 | [AgentRx: Diagnosing Agent Failures](AgentRx-Diagnosing-Agent-Failures/) | 把轨迹转成约束检查，发现 state / schema / protocol 违反 | 最高 |
| 4 | [ErrorProbe: Self-Improving Diagnosis](ErrorProbe-Self-Improving-Diagnosis/) | 把失败变成可检测症状，再反向追踪和验证 | 高 |
| 5 | [AgentTrace: Causal Graph Tracing](AgentTrace-Causal-Graph-Tracing/) | 显性错误场景下，用因果图做反向根因追踪 | 中 |
| 6 | [XAI for Coding Agent Failures](XAI-Coding-Agent-Failures/) | 把 trace 解释成人能看懂的诊断报告 | 中 |

最短阅读路线：

```text
REFLECT
  ↓
False Success
  ↓
AgentRx
  ↓
ErrorProbe
```

如果要做产品展示，再读 XAI。

如果要做工具依赖图 / 显性错误归因，再读 AgentTrace。

---

## 先补一篇：PROTEA

虽然 PROTEA 不在这个目录下，但它是全仓库最值得优先读的论文：

- 路径：[../高度相关/PROTEA-Offline-Evaluation/](../高度相关/PROTEA-Offline-Evaluation/)
- 核心：**中间节点期望 + 中间输出评分**
- 价值：最贴近 WorkState 少字段、流程跳步、中间产物不满足阶段目标这类隐性失败。

建议实际阅读顺序是：

```text
0. PROTEA
1. REFLECT
2. False Success
3. AgentRx
4. ErrorProbe
5. AgentTrace
6. XAI
```

这里写成 `0`，就是为了明确：它很重要，但不属于 `最相关/` 目录内 6 篇。

---

## 1. REFLECT：silent failure 的关键步骤归因

路径：[`REFLECT-Silent-Failure-Attribution/`](REFLECT-Silent-Failure-Attribution/)

### 内核方法

REFLECT 研究的是：

```text
trace 正常完成
没有工具崩溃
没有明显异常
但最终结果是错的
```

核心链路：

```text
定位候选错误步骤
    ↓
对某一步做干预修复
    ↓
从 trace 前缀继续执行 / replay
    ↓
如果结果变好，说明这一步更可能是关键错误点
```

### 对 AgentLens 的意义

它回答的是：

```text
一整条 Agent 轨迹都跑完了，哪个中间步骤才是导致结果变差的关键点？
```

可迁移功能：

```text
Critical Step Attribution
Step Impact Score
What-if Replay / 局部重跑验证
```

### 阅读重点

重点看：

1. 它怎么定义 silent failure。
2. 它怎么生成候选错误步骤。
3. 它怎么用 intervention 验证归因。
4. 它对 replay 能力有什么依赖。

如果短期做不了 replay，也可以先借鉴它的 **候选关键步骤排序**。

---

## 2. From Confident Closing to Silent Failure：Claim vs Evidence

路径：[`False-Success-Silent-Failure/`](False-Success-Silent-Failure/)

### 内核方法

这篇关注 false success：

```text
Agent 自信地说“我完成了”
但环境状态证明它没完成
```

核心不是看有没有报错，而是比较：

```text
Agent 的完成声明
    vs
真实环境状态 / 文件变化 / 命令证据
```

### 对 AgentLens 的意义

这篇可以直接变成一个功能：

```text
Claim vs Evidence Checker
```

例子：

```text
Agent 说：我已经测试过了
证据检查：没有 test command / 没有测试输出
结论：unsupported claim
```

```text
Agent 说：我已经更新了状态字段
证据检查：WorkState diff 中没有该字段
结论：false success risk
```

### 阅读重点

重点看：

1. false success 怎么定义。
2. 它如何比较 Agent 声明和环境状态。
3. 为什么 LLM judge 容易被“自信语气”误导。
4. 为什么只看最终回答不够。

这篇适合作为 AgentLens 的 **验收检查层**。

---

## 3. AgentRx：约束合成与逐步验证

路径：[`AgentRx-Diagnosing-Agent-Failures/`](AgentRx-Diagnosing-Agent-Failures/)

### 内核方法

AgentRx 的核心是：

```text
从任务和轨迹中合成约束
    ↓
逐步检查每一步是否违反约束
    ↓
生成可审计的 violation log
    ↓
定位关键失败步骤和失败类型
```

它把“隐性错误”转成了“约束违反”。

### 对 AgentLens 的意义

这篇非常适合 WorkState / schema / protocol 诊断。

例如可以定义：

```json
{
  "required_state_fields": ["design_done", "test_required", "verification_result"]
}
```

然后检查：

```text
Step 12 更新了 WorkState
但缺少 test_required
后续 Step 18 因字段缺失跳过 verification
```

对应功能：

```text
WorkState Conformance Checker
Schema Violation Detector
Protocol Violation Log
```

### 阅读重点

重点看：

1. 它怎么从轨迹里合成 constraints。
2. 它怎么逐步检查 constraints。
3. 它怎么生成 evidence / validation log。
4. 它怎么把约束违反映射到 critical failure step。

这篇适合作为 AgentLens 的 **规则诊断引擎**。

---

## 4. ErrorProbe：症状识别、反向追踪、验证

路径：[`ErrorProbe-Self-Improving-Diagnosis/`](ErrorProbe-Self-Improving-Diagnosis/)

### 内核方法

ErrorProbe 的核心流水线是：

```text
失败类型 → 可检测症状
    ↓
症状驱动的反向追踪
    ↓
上下文剪枝
    ↓
多 Agent 验证诊断结果
    ↓
沉淀经验记忆
```

### 对 AgentLens 的意义

它适合作为诊断系统主架构：

```text
Symptom Detector
    ↓
Trace Backward Analyzer
    ↓
Evidence Collector
    ↓
Diagnosis Validator
    ↓
Diagnosis Memory
```

隐性失败也可以先定义成症状：

```text
状态字段缺失
Agent 声称完成但无证据
计划阶段完成但没有后续验证
关键文件没有被读取或修改
后续 Agent 使用默认分支继续执行
```

### 阅读重点

重点看：

1. 它如何把失败分类变成可操作症状。
2. 它如何反向追踪。
3. 它如何剪枝无关上下文。
4. 它如何用多 Agent 验证诊断。
5. 它如何积累诊断经验。

这篇适合用来设计 AgentLens 的 **诊断流水线**。

---

## 5. AgentTrace: Causal Graph Tracing：显性错误因果图

路径：[`AgentTrace-Causal-Graph-Tracing/`](AgentTrace-Causal-Graph-Tracing/)

### 内核方法

AgentTrace 的核心是：

```text
执行日志
    ↓
重建工具调用因果图
    ↓
从最终错误节点反向追踪
    ↓
排序根因候选
```

### 对 AgentLens 的意义

它更适合显性错误：

```text
测试失败
命令报错
工具调用失败
文件不存在
接口返回异常
```

但对隐性失败，它不是第一优先级，因为隐性失败通常没有明确的 error node。

可迁移点：

```text
Trace Graph
Tool Dependency Graph
Backward Attribution
```

但要扩展成：

```text
State Node
Claim Node
Evidence Node
Artifact Node
```

### 阅读重点

重点看：

1. 它怎么构建依赖图。
2. 它用哪些信号排序根因。
3. 哪些部分可以迁移到 AgentLens 的 trace graph。

---

## 6. XAI for Coding Agent Failures：诊断报告展示层

路径：[`XAI-Coding-Agent-Failures/`](XAI-Coding-Agent-Failures/)

### 内核方法

这篇解决的是：

```text
原始 trace 太长，用户看不懂
怎么转成可解释的诊断报告？
```

核心方法：

```text
原始执行轨迹
    ↓
失败分类 / 自动注释
    ↓
结构化事件
    ↓
可视化流程 + 自然语言解释
```

### 对 AgentLens 的意义

它适合做报告展示，不是核心诊断算法。

AgentLens 最终不能只输出一堆日志，而应该输出：

```text
哪个步骤可疑
为什么可疑
证据是什么
建议怎么改
```

### 阅读重点

重点看：

1. 它怎么把 trace 变成结构化解释。
2. 它的失败分类法怎么设计。
3. 它的可视化报告怎么组织。

---

## 这 6 篇怎么组合成 AgentLens 的方案

```text
1. False Success
   先判断 Agent 是不是真的完成了

2. AgentRx
   检查轨迹中有没有 state / schema / protocol 约束违反

3. ErrorProbe
   把发现的问题变成症状，再反向追踪原因

4. REFLECT
   如果可以重放，用干预验证关键错误步骤

5. AgentTrace
   对显性错误，用因果图补充依赖追踪

6. XAI
   把诊断结果做成用户能看懂的报告
```

对应到 AgentLens，可以拆成 5 个模块：

```text
Claim vs Evidence Checker
WorkState / Schema Conformance Checker
Trajectory Symptom Detector
Critical Step Attribution
Diagnosis Report Generator
```
