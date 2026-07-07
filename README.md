# Agent Behavioral Diagnosis — 论文调研库

本仓库收录 **Agent 行为偏差诊断 / 隐性失败诊断** 相关论文。

重点不再只是：

```text
程序报错 → 找根因
```

而是更真实、更难发现的问题：

- Agent 声称完成，但环境状态没有完成
- trace 看起来正常，但最终结果是错的
- 中间 WorkState / schema / 协议字段缺失
- 某个 Agent 少更新了状态，导致后续步骤被跳过
- 编译、测试、工具调用都通过，但产物质量不达标

核心问题：

> **Agent 为什么在“看起来正常执行”的情况下，悄悄偏离目标？**

---

## 目录结构

```text
.
├── 最相关/          # 核心必读与早期高相关论文；先看该目录 README
├── 高度相关/        # 方法可借鉴：层次归因、干预验证、结构化日志、过程奖励
├── 相关/            # 背景参考：产品形态、传统调试、可解释报告、自反思机制
└── scripts/          # 辅助脚本
```

每篇论文目录通常包含：

- `README.md` — 中文解读笔记
- `paper.pdf` — 论文原文

建议先读：

- [最相关/README.md](最相关/README.md)

它会解释核心论文的内核方法、阅读顺序，以及哪些论文适合直接迁移到 AgentLens / CCWhat。

---

## 推荐阅读顺序

### P0：核心必读

这组最贴近 **silent failure、false success、state deviation、workflow conformance**。

| 排名 | 论文 | 年份 | 为什么最相关 |
|------|------|------|--------------|
| 1 | [PROTEA: Offline Evaluation](高度相关/PROTEA-Offline-Evaluation/) | 2026 | 对中间节点输出评分，从最终答案反推节点级期望，最适合发现 WorkState 少字段、流程跳步 |
| 2 | [REFLECT: Silent Failure Attribution](最相关/REFLECT-Silent-Failure-Attribution/) | 2026 | 直接研究 silent failure：trace 正常完成但结果错误，通过干预验证定位关键错误步骤 |
| 3 | [From Confident Closing to Silent Failure](最相关/False-Success-Silent-Failure/) | 2026 | 研究 false success：Agent 自信声称完成，但环境状态证明没有完成 |
| 4 | [AgentRx: Diagnosing Agent Failures](最相关/AgentRx-Diagnosing-Agent-Failures/) | 2026 | 从执行轨迹合成约束，逐步检查约束违反，适合 schema / state / protocol 诊断 |
| 5 | [ErrorProbe: Self-Improving Diagnosis](最相关/ErrorProbe-Self-Improving-Diagnosis/) | 2026 | “症状识别 → 反向追踪 → 多 Agent 验证 → 经验记忆”的诊断框架很适合作为系统主架构 |

---

### P1：方法可借鉴

这组适合作为具体模块的方法来源。

| 排名 | 论文 | 年份 | 可借鉴点 |
|------|------|------|----------|
| 6 | [TrajAD: Trajectory Anomaly Detection](高度相关/TrajAD-Trajectory-Anomaly-Detection/) | 2026 | 把 Agent 过程诊断定义成轨迹异常检测，目标是定位异常步骤 |
| 7 | [AgentTrace: Structured Logging](相关/AgentTrace-Structured-Logging/) | 2026 | 三层日志模型：操作层 / 认知层 / 上下文层，可指导 AgentLens 采集什么 |
| 8 | [ECHO: Hierarchical Error Attribution](高度相关/ECHO-Hierarchical-Error-Attribution/) | 2025 | 层次化上下文表示，适合 Session → Task → Stage → Step 的分层诊断 |
| 9 | [AgentPRM: Process Reward Models](高度相关/AgentPRM-Process-Reward-Models/) | 2025 | 每一步按“是否推进目标”评分，适合发现目标漂移和无效动作 |
| 10 | [DoVer: Intervention-Driven Debugging](高度相关/DoVer-Intervention-Driven-Debugging/) | 2025 | 通过主动干预验证失败假设，适合从诊断走向自动修复 |
| 11 | [Zero-Replay Debugging](高度相关/Zero-Replay-Debugging/) | 2026 | 不重放执行，只从日志中预测高影响事件，适合真实 Agent 日志诊断 |
| 12 | [Watson: Cognitive Observability](高度相关/Watson-Cognitive-Observability/) | 2024 | 分析 Agent 为什么这么做，适合解释隐式推理偏差 |

---

### P2：背景参考

这组有价值，但更偏传统调试、工具展示或产品形态。

| 排名 | 论文 | 年份 | 价值 |
|------|------|------|------|
| 13 | [TraceElephant: Failure Attribution](高度相关/TraceElephant-Failure-Attribution/) | 2026 | 证明完整 trace 对失败归因很重要，可支撑 AgentLens 的数据采集价值 |
| 14 | [XAI for Coding Agent Failures](最相关/XAI-Coding-Agent-Failures/) | 2026 | 适合报告展示：把 trace 转成可视化流程和自然语言洞察 |
| 15 | [In-IDE Toolkit for AI Features](相关/In-IDE-Toolkit-AI-Features/) | 2026 | 借鉴产品形态：低门槛 trace 捕获、评估集、类似单元测试的评估 |
| 16 | [AgentTrace: Causal Graph Tracing](最相关/AgentTrace-Causal-Graph-Tracing/) | 2026 | 适合显性错误的因果图反向追踪，但对 silent failure 不够直接 |
| 17 | [TraceCoder: Trace-Driven Debugging](高度相关/TraceCoder-Trace-Driven-Debugging/) | 2026 | 更偏代码运行时调试，对传统编译/测试失败有价值 |
| 18 | [Autonomous Debugging: Dynamic Analysis](相关/Autonomous-Debugging-Dynamic-Analysis/) | 2026 | 函数级动态 trace，对程序调试有价值 |
| 19 | [Reflexion: Verbal Reinforcement Learning](相关/Reflexion-Self-Reflective-Agents/) | 2023 | 自反思机制背景论文，可作为诊断记忆/经验库的早期参考 |

---

## 研究主题映射

### 1. 隐性失败 / False Success

- REFLECT
- From Confident Closing to Silent Failure
- PROTEA
- AgentRx

核心问题：

```text
Agent 看起来完成了，但真实环境状态没有完成。
Trace 没有报错，但最终结果不满足目标。
```

---

### 2. 状态偏差 / Schema & WorkState Diagnosis

- PROTEA
- AgentRx
- ErrorProbe
- TrajAD

核心问题：

```text
中间状态字段缺失。
协议字段没有更新。
后续 Agent 基于错误状态继续执行。
流程没有报错，但结果逐渐偏离。
```

---

### 3. 过程异常 / Trajectory Anomaly

- TrajAD
- AgentPRM
- ECHO
- Watson

核心问题：

```text
每一步单看都合理，但整体路径不合理。
Agent 没有明显失败，但过程没有持续推进目标。
```

---

### 4. 根因归因 / Failure Attribution

- ErrorProbe
- AgentRx
- Zero-Replay Debugging
- AgentTrace: Causal Graph
- TraceElephant

核心问题：

```text
最终结果不好时，哪个中间步骤最可能是关键偏差点？
```

---

### 5. 可观测性 / Trace Infrastructure

- AgentTrace: Structured Logging
- TraceElephant
- In-IDE Toolkit
- XAI for Coding Agent Failures

核心问题：

```text
为了诊断隐性失败，AgentLens 到底应该记录什么？
如何把原始 trace 转成用户能看懂的诊断报告？
```

---

## 对 AgentLens / CCWhat 的启发

当前路线不应该只做：

```text
error log → root cause
```

更应该做：

```text
Goal
  ↓
Plan
  ↓
State Transition
  ↓
Tool / File / Command Evidence
  ↓
Intermediate Output Score
  ↓
Final Outcome
```

建议后续功能优先级：

1. **Claim vs Evidence 检查**  
   Agent 声称“已读文档 / 已测试 / 已完成”，系统从 trace、命令、文件 diff 中找证据。

2. **WorkState / Schema Conformance 检查**  
   检查中间状态是否缺字段、字段是否被错误更新、是否触发错误分支。

3. **Workflow Conformance 检查**  
   对比期望流程和真实执行路径，发现缺失阶段、跳步、顺序错误。

4. **Intermediate Output Scoring**  
   不只评估最终答案，也评估每个阶段产物是否满足节点级期望。

5. **Critical Step Attribution**  
   当最终产物不理想时，定位最早开始偏离目标的步骤。
