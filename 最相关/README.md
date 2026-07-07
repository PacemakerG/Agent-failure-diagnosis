# 最相关论文阅读指南

这个 README 是整个仓库最重要的入口。它回答两个问题：

1. **最相关的论文到底在解决什么内核问题？**
2. **你应该按什么顺序读，才能服务于 AgentLens / CCWhat 的隐性失败诊断？**

这里的“最相关”不是传统意义上的“代码报错定位”，而是更贴近真实 Coding Agent 场景的：

```text
Agent 看起来正常执行
  ↓
中间状态 / 流程 / 证据悄悄偏了
  ↓
最终产物不理想
```

也就是：**没有明显报错，但系统已经偏离目标。**

---

## 一句话阅读顺序

先读这 5 篇：

```text
1. PROTEA
2. REFLECT
3. From Confident Closing to Silent Failure
4. AgentRx
5. ErrorProbe
```

再读这 2 篇作为补充：

```text
6. AgentTrace: Causal Graph Tracing
7. XAI for Coding Agent Failures
```

说明：`PROTEA` 当前物理目录在 [`../高度相关/PROTEA-Offline-Evaluation/`](../高度相关/PROTEA-Offline-Evaluation/)，但方法价值已经是 P0 第一篇。为了不重复存 PDF，这里直接链接原目录。

---

## 核心论文总览

| 顺序 | 论文 | 核心方法 | 对 AgentLens 的意义 |
|---|---|---|---|
| 1 | [PROTEA](../高度相关/PROTEA-Offline-Evaluation/) | 中间节点期望 + 中间输出评分 | 判断 WorkState / 中间产物是否满足阶段目标 |
| 2 | [REFLECT](REFLECT-Silent-Failure-Attribution/) | silent failure 的干预式归因 | 找到正常 trace 中导致结果变差的关键步骤 |
| 3 | [False Success](False-Success-Silent-Failure/) | Claim vs Environment State | 检查 Agent 声称完成是否有真实证据 |
| 4 | [AgentRx](AgentRx-Diagnosing-Agent-Failures/) | 约束合成 + 逐步验证 | 检查 schema / state / protocol 是否被违反 |
| 5 | [ErrorProbe](ErrorProbe-Self-Improving-Diagnosis/) | 症状识别 + 反向追踪 + 验证 | 作为诊断系统主架构 |
| 6 | [AgentTrace](AgentTrace-Causal-Graph-Tracing/) | 因果图反向追踪 | 处理显性错误和工具依赖图 |
| 7 | [XAI](XAI-Coding-Agent-Failures/) | trace 解释与报告生成 | 做 Viewer / Report 展示层 |

---

## 1. PROTEA：中间节点期望与评分

路径：[`../高度相关/PROTEA-Offline-Evaluation/`](../高度相关/PROTEA-Offline-Evaluation/)

### 内核方法

PROTEA 的核心不是最终答案评估，而是：

```text
目标 / 最终答案
    ↓
反推每个中间节点应该产出什么
    ↓
检查真实中间输出是否满足期望
    ↓
找到 workflow 中的瓶颈节点
```

它真正重要的是两个思想：

```text
Node-Level Expectation
Intermediate Output Scoring
```

也就是：每个阶段都应该有“应产出内容”，并且可以被单独打分。

### 为什么最重要

你关心的隐性问题通常长这样：

```text
某个 Agent 少写了 WorkState 字段
        ↓
后续 Agent 基于错误状态继续执行
        ↓
流程没有报错
        ↓
最终产物交付不理想
```

这个问题不是传统 bug，而是 **中间节点没有满足阶段期望**。

### 怎么迁移到 AgentLens

可以做成：

```text
Task Goal
  ↓
Stage Expectation
  ↓
WorkState / Artifact / Command Evidence
  ↓
Intermediate Score
  ↓
First Deviation Step
```

具体功能：

```text
阶段产物评分
WorkState 字段完整性检查
关键文件修改覆盖检查
验证步骤是否真实执行
```

### 阅读重点

重点看：

1. 它如何定义 workflow 节点。
2. 它如何生成节点级期望。
3. 它如何给中间输出打分。
4. 它如何定位 workflow bottleneck。

不要只看实验指标，重点看 **中间节点评估思想**。

---

## 2. REFLECT：silent failure 的关键步骤归因

路径：[`REFLECT-Silent-Failure-Attribution/`](REFLECT-Silent-Failure-Attribution/)

### 内核方法

REFLECT 研究的是：

```text
trace 正常完成
没有工具崩溃
没有明显异常
但最终结果是错的
```

它的核心链路是：

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

对应功能：

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

## 3. From Confident Closing to Silent Failure：Claim vs Evidence

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

## 4. AgentRx：约束合成与逐步验证

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

## 5. ErrorProbe：症状识别、反向追踪、验证

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

## 6. AgentTrace: Causal Graph Tracing：显性错误的因果图

路径：[`AgentTrace-Causal-Graph-Tracing/`](AgentTrace-Causal-Graph-Tracing/)

### 内核方法

AgentTrace 的核心是：

```text
执行日志
    ↓
工具调用因果图
    ↓
从最终错误节点反向追踪
    ↓
定位根因节点
```

### 对 AgentLens 的意义

它适合处理显性失败：

```text
工具调用失败
命令报错
测试失败
编译失败
明确异常节点
```

但它对 silent failure 不够直接，因为 silent failure 往往没有明确错误节点。

### 阅读重点

只需要重点看：

1. 因果图怎么建。
2. 节点依赖怎么表示。
3. 如何从终点反向找根因。

它更适合作为 **工具依赖图 / error propagation graph** 的补充模块。

---

## 7. XAI for Coding Agent Failures：诊断报告展示层

路径：[`XAI-Coding-Agent-Failures/`](XAI-Coding-Agent-Failures/)

### 内核方法

XAI 的核心是：

```text
原始 execution trace
    ↓
自动注释关键事件
    ↓
生成结构化解释
    ↓
可视化流程 + 自然语言洞察
```

### 对 AgentLens 的意义

它不负责发现隐性错误本身，更适合做：

```text
诊断报告
可视化流程
用户可读解释
修复建议展示
```

### 阅读重点

重点看：

1. 它怎么把 raw trace 转成结构化事件。
2. 它怎么生成可解释报告。
3. 它的 UI / 报告表达方式。

这篇适合 AgentLens 的 **Viewer / Report 页面**。

---

## 最终组合方案

这几篇不是互相替代，而是各管一层：

| 层次 | 论文 | 作用 |
|---|---|---|
| 中间节点评估 | PROTEA | 判断每个阶段产物是否满足期望 |
| 关键步骤归因 | REFLECT | 定位 silent failure 的关键错误步骤 |
| 完成声明校验 | False Success | 检查 Agent 声称完成是否有证据 |
| 状态/协议约束检查 | AgentRx | 检查 WorkState、schema、流程约束是否被违反 |
| 诊断流水线 | ErrorProbe | 把症状识别、反向追踪、验证组织成系统 |
| 显性错误因果图 | AgentTrace | 对报错、测试失败、工具失败做反向追踪 |
| 报告展示 | XAI | 把诊断结果变成用户看得懂的解释 |

最适合 AgentLens 的组合是：

```text
PROTEA 的节点期望
+ AgentRx 的约束检查
+ False Success 的证据校验
+ ErrorProbe 的诊断流水线
+ REFLECT 的关键步骤归因
+ XAI 的报告展示
```

最终目标不是只回答：

```text
哪里报错了？
```

而是回答：

```text
Agent 从哪一步开始看似正常、实际偏离？
这个偏离有什么证据？
它如何影响后续流程？
用户应该优先修哪一个环节？
```
