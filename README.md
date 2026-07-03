# Agent Failure Diagnosis — 论文调研库

本仓库收录了 **Agent 失败诊断** 领域的相关论文，聚焦于多 Agent 系统的可观测性、根因分析与自动调试。论文按与研究方向的相关程度分为三个层级，每篇论文附有结构化的中文解读笔记（核心贡献、核心方法、与研究工作的关联）和原始 PDF。

---

## 目录结构

```
.
├── 最相关/          # 与研究方向直接对齐的核心论文（3 篇）
├── 高度相关/        # 方法或问题域高度重叠的论文（10 篇）
└── 相关/            # 提供背景参考或间接借鉴的论文（5 篇）
```

每个子目录对应一篇论文，包含：
- `README.md` — 中文解读笔记（基本信息 / 核心贡献 / 核心方法 / 与研究工作的关联 / BibTeX）
- `paper.pdf` — 论文原文

---

## 最相关（3 篇）

直接解决 Agent 失败诊断的核心问题，方法可直接借鉴。

| 论文 | 年份 | 核心贡献 |
|------|------|----------|
| [AgentTrace: Causal Graph Tracing](最相关/AgentTrace-Causal-Graph-Tracing/) | 2026 | 从执行日志重建因果图，反向追踪根因，亚秒级延迟，无需 LLM 推理 |
| [ErrorProbe: Self-Improving Diagnosis](最相关/ErrorProbe-Self-Improving-Diagnosis/) | 2026 | 三阶段流水线（症状识别 → 反向追踪 → 多 Agent 验证），自动构建经验记忆 |
| [XAI for Coding Agent Failures](最相关/XAI-Coding-Agent-Failures/) | 2026 | 用可解释 AI 方法分析编码 Agent 失败模式，定位关键决策节点 |

---

## 高度相关（10 篇）

与诊断、追踪或 Agent 调试在方法或问题域上高度重叠。

| 论文 | 年份 | 核心贡献 |
|------|------|----------|
| [AgentTrace: Causal Graph Tracing](高度相关/AgentTrace-Causal-Graph-Tracing/) | 2026 | 因果图追踪（与最相关版本互补） |
| [DoVer: Intervention-Driven Debugging](高度相关/DoVer-Intervention-Driven-Debugging/) | 2026 | 通过主动干预验证 Agent 行为，定位失败根因 |
| [ECHO: Hierarchical Error Attribution](高度相关/ECHO-Hierarchical-Error-Attribution/) | 2026 | 层次化错误归因，将系统级失败分解到具体 Agent |
| [ErrorProbe: Self-Improving Diagnosis](高度相关/ErrorProbe-Self-Improving-Diagnosis/) | 2026 | 自我改进诊断框架 |
| [PROTEA: Offline Evaluation](高度相关/PROTEA-Offline-Evaluation/) | 2026 | 离线评估框架，无需在线执行即可分析 Agent 行为 |
| [TraceCoder: Trace-Driven Debugging](高度相关/TraceCoder-Trace-Driven-Debugging/) | 2026 | 基于执行 trace 引导 LLM 进行代码调试 |
| [TraceElephant: Failure Attribution](高度相关/TraceElephant-Failure-Attribution/) | 2026 | 大规模 trace 数据中的失败归因方法 |
| [Watson: Cognitive Observability](高度相关/Watson-Cognitive-Observability/) | 2026 | 认知层面的可观测性，捕获 Agent 内部推理过程 |
| [XAI for Coding Agent Failures](高度相关/XAI-Coding-Agent-Failures/) | 2026 | 可解释 AI 方法分析失败 |
| [Zero-Replay Debugging](高度相关/Zero-Replay-Debugging/) | 2026 | 无需重放执行即可定位 Agent 失败的调试方法 |

---

## 相关（5 篇）

提供方法背景或间接借鉴，覆盖可观测性框架、动态分析、IDE 工具链等。

| 论文 | 年份 | 核心贡献 |
|------|------|----------|
| [AgentTrace: Structured Logging](相关/AgentTrace-Structured-Logging/) | 2026 | 三层结构化日志框架（操作 / 认知 / 上下文），AAAI 2026 |
| [Autonomous Debugging: Dynamic Analysis](相关/Autonomous-Debugging-Dynamic-Analysis/) | 2026 | Agent-centric 调试接口，函数级 trace，ACM FSE 2026 |
| [Holmes: Multimodal Diagnosis](相关/Holmes-Multimodal-Diagnosis/) | 2026 | 多模态信号融合诊断移动崩溃，微信生产环境验证 |
| [In-IDE Toolkit for AI Features](相关/In-IDE-Toolkit-AI-Features/) | 2026 | JetBrains IDE 内嵌 trace 与评估工具链 |
| [Reflexion: Verbal Reinforcement Learning](相关/Reflexion-Self-Reflective-Agents/) | 2023 | 语言 Agent 的自我反思机制，HumanEval 达 91% |

---

## 研究主题分布

- **根因分析**: AgentTrace (Causal Graph)、ECHO、TraceElephant、Zero-Replay
- **执行追踪**: TraceCoder、AgentTrace (Structured Logging)、Autonomous Debugging
- **多 Agent 诊断**: ErrorProbe、DoVer、Watson
- **可解释性**: XAI for Coding Agents、Reflexion
- **工程工具**: Holmes、In-IDE Toolkit、PROTEA
