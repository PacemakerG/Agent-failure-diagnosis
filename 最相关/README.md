# 最相关论文导读

这个目录放的是最值得优先看的论文，但它们的作用不完全一样。

你现在真正关心的不是传统意义上的：

```text
程序报错 → 找哪一行代码错了
```

而是：

```text
Agent 看起来正常执行
  ↓
中间状态 / 流程 / 证据悄悄偏了
  ↓
最终产物不理想
```

所以读这些论文时，不要只问“它怎么找 bug”，而要问：

> **它能不能帮我发现正常 trace 里的隐性偏差？**

---

## 先读哪几篇

建议按这个顺序读。

| 顺序 | 论文 | 你要抓住的核心 |
|---|---|---|
| 1 | [REFLECT: Silent Failure Attribution](REFLECT-Silent-Failure-Attribution/) | trace 正常结束但结果错，怎么定位关键错误步骤 |
| 2 | [From Confident Closing to Silent Failure](False-Success-Silent-Failure/) | Agent 自信说完成了，但环境状态没完成，怎么识别 false success |
| 3 | [AgentRx: Diagnosing Agent Failures](AgentRx-Diagnosing-Agent-Failures/) | 把轨迹转成约束检查，发现 state / schema / protocol 违反 |
| 4 | [ErrorProbe: Self-Improving Diagnosis](ErrorProbe-Self-Improving-Diagnosis/) | 把失败变成可检测症状，再反向追踪和验证 |
| 5 | [AgentTrace: Causal Graph Tracing](AgentTrace-Causal-Graph-Tracing/) | 显性错误场景下，怎么用因果图做反向根因追踪 |
| 6 | [XAI for Coding Agent Failures](XAI-Coding-Agent-Failures/) | 怎么把 trace 解释成人能看懂的诊断报告 |

如果时间很少，只看前四篇。

---

## 每篇的内核方法

### 1. REFLECT：隐性失败归因

**核心问题：**

```text
没有工具报错
没有 JSON 解析失败
没有运行时异常
但最终答案就是错的
```

REFLECT 的关键思想是：

```text
先定位可疑步骤
  ↓
对这个步骤做干预修复
  ↓
从原轨迹前缀继续 replay
  ↓
如果最终结果变好，说明这个步骤更可能是关键错误点
```

对你的启发：

- 不能只看失败日志，因为隐性失败没有明显错误日志。
- 诊断要从“结果不好”反推“哪个中间步骤最早偏离”。
- 后期如果 AgentLens 有 replay / partial replay 能力，REFLECT 是最值得复现的方法之一。

你读的时候重点看：

```text
它怎么定义 silent failure？
它怎么生成候选错误步骤？
它怎么用干预结果反过来验证归因？
```

---

### 2. From Confident Closing to Silent Failure：False Success

**核心问题：**

```text
Agent 说：我已经完成了
但真实环境状态：并没有完成
```

这篇的核心不是传统错误归因，而是识别 **false success**。

它很适合支撑一个功能：

```text
Claim vs Evidence 检查
```

也就是：

```text
Agent 声称做了什么
  ↓
从 trace / command / file diff / test result / WorkState 里找证据
  ↓
没有证据，就标记为 unsupported claim / false success
```

对你的启发：

- Coding Agent 经常会“自信交付”，但没有真实证据。
- 不要相信最终回复，要看环境状态和执行证据。
- AgentLens 可以做一个非常实用的检查：**它说测了，真的跑测试了吗？它说改了，真的改到关键文件了吗？**

你读的时候重点看：

```text
false success 怎么定义？
作者如何比较 Agent 声称状态和真实环境状态？
为什么 LLM judge 容易被自信表述骗过？
```

---

### 3. AgentRx：轨迹约束诊断

**核心问题：**

```text
最终结果不对
但单步看起来都正常
怎么从执行轨迹里发现违反约束的步骤？
```

AgentRx 的核心思想是：

```text
从任务和轨迹中抽取约束
  ↓
逐步检查每个步骤是否违反约束
  ↓
输出可审计的违反证据
```

这对 WorkState / schema / protocol 问题很有用。

例如你的场景：

```json
{
  "design_done": true,
  "test_required": true,
  "review_required": true
}
```

某个 Agent 少写了字段：

```json
{
  "design_done": true
}
```

这不是异常，但它违反了状态协议。

对你的启发：

- 把“隐性错误”转成“约束违反”。
- 约束可以来自任务要求、流程协议、WorkState schema、团队规范。
- 最终产物差，不一定先找代码 bug，而是先找哪个步骤破坏了约束。

你读的时候重点看：

```text
约束是怎么生成的？
它怎么逐步检查轨迹？
它输出的 evidence log 长什么样？
```

---

### 4. ErrorProbe：症状驱动反向追踪

**核心问题：**

```text
多 Agent 系统失败后，怎么定位是哪个 Agent / 哪个步骤导致的？
```

ErrorProbe 的核心结构可以抽象成：

```text
失败类型
  ↓
可检测症状
  ↓
反向追踪
  ↓
多 Agent 验证
  ↓
经验记忆
```

它最适合作为 AgentLens 诊断系统的框架骨架。

你可以把隐性失败先变成症状：

```text
状态字段缺失
计划阶段缺失
测试声明无证据
后续 Agent 使用默认分支
文件 diff 没覆盖需求点
```

然后再做反向追踪。

对你的启发：

- 诊断不能上来就问“根因是什么”，要先把失败拆成可检测症状。
- 同一种症状可以积累成经验记忆，后续自动复用。
- 这篇适合指导系统架构，而不是只复现某一个算法。

你读的时候重点看：

```text
它如何把失败类型 operationalize？
它的反向追踪如何剪枝上下文？
它的经验记忆怎么积累？
```

---

### 5. AgentTrace：因果图反向追踪

**核心问题：**

```text
有明显错误节点时，怎么沿着工具调用依赖链找根因？
```

它的核心方法是：

```text
执行日志
  ↓
重建工具调用因果图
  ↓
从最终错误节点反向追踪
  ↓
排序根因候选
```

这篇适合显性错误：

```text
测试失败
命令报错
工具调用失败
文件不存在
接口返回异常
```

但对你的隐性失败问题，它不是第一优先级，因为隐性失败通常没有明确的 error node。

对你的启发：

- 因果图仍然有价值，可以用来表示依赖关系。
- 但不能只依赖 error node，要增加 state node、claim node、evidence node、artifact node。

你读的时候重点看：

```text
它怎么构建依赖图？
它用哪些信号排序根因？
哪些部分可以迁移到 AgentLens 的 trace graph？
```

---

### 6. XAI for Coding Agent Failures：诊断报告展示层

**核心问题：**

```text
原始 trace 太长，用户看不懂
怎么转成可解释的诊断报告？
```

它的核心方法是：

```text
原始执行轨迹
  ↓
失败分类 / 自动注释
  ↓
结构化事件
  ↓
可视化流程 + 自然语言解释
```

这篇不是最核心的诊断算法，但对产品化很有用。

对你的启发：

- AgentLens 最终不能只输出一堆日志。
- 要输出“哪个步骤可疑、为什么可疑、证据是什么、建议怎么改”。
- 它适合做 failure report 页面和自然语言总结。

你读的时候重点看：

```text
它怎么把 trace 变成结构化解释？
它的失败分类法怎么设计？
它的可视化报告怎么组织？
```

---

## 这几篇怎么组合成你的方案

你可以把它们组合成一个完整诊断链路：

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

---

## 最短阅读路线

如果只想快速形成方案，按这个读：

```text
False Success
  ↓
AgentRx
  ↓
ErrorProbe
  ↓
REFLECT
```

读完这四篇，你基本就能回答：

```text
怎么发现 Agent 明明没报错但其实没完成？
怎么检查中间状态是否违背协议？
怎么把隐性错误转成可检测症状？
怎么定位最关键的偏差步骤？
```

如果要做产品展示，再读：

```text
XAI for Coding Agent Failures
```

如果要做工具调用依赖图，再读：

```text
AgentTrace Causal Graph
```
