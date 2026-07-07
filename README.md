# Agent Behavioral Diagnosis — 论文调研库

本仓库收录 **Agent 行为偏差诊断 / 隐性失败诊断** 相关论文。核心关注：Agent 看起来正常执行，但中间状态、流程、证据或目标推进已经悄悄偏离，最终导致交付结果不理想。

## 目录结构

```text
.
├── 最相关/          # 目录内 7 篇；核心必读，先看该目录 README
├── 高度相关/        # 方法可借鉴：层次归因、干预验证、结构化日志、过程奖励
├── 相关/            # 背景参考：产品形态、传统调试、可解释报告、自反思机制
└── scripts/          # 辅助脚本
```

每篇论文目录通常包含：

- `README.md`：中文解读笔记
- `paper.pdf`：论文原文

建议先读：[最相关/README.md](最相关/README.md)

---

## 推荐阅读顺序

### P0：核心必读

| 排名 | 论文 | 年份 | 为什么最相关 |
|------|------|------|--------------|
| 1 | [PROTEA: Offline Evaluation](最相关/PROTEA-Offline-Evaluation/) | 2026 | 中间节点期望 + 中间输出评分，最适合发现 WorkState 少字段、流程跳步 |
| 2 | [REFLECT: Silent Failure Attribution](最相关/REFLECT-Silent-Failure-Attribution/) | 2026 | 直接研究 silent failure：trace 正常完成但结果错误，定位关键错误步骤 |
| 3 | [From Confident Closing to Silent Failure](最相关/False-Success-Silent-Failure/) | 2026 | 研究 false success：Agent 自信声称完成，但环境状态证明没有完成 |
| 4 | [AgentRx: Diagnosing Agent Failures](最相关/AgentRx-Diagnosing-Agent-Failures/) | 2026 | 从执行轨迹合成约束，逐步检查 schema / state / protocol 违反 |
| 5 | [ErrorProbe: Self-Improving Diagnosis](最相关/ErrorProbe-Self-Improving-Diagnosis/) | 2026 | 症状识别、反向追踪、多 Agent 验证、经验记忆，适合作为诊断系统主架构 |

### P1：方法可借鉴

| 排名 | 论文 | 年份 | 可借鉴点 |
|------|------|------|----------|
| 6 | [TrajAD: Trajectory Anomaly Detection](高度相关/TrajAD-Trajectory-Anomaly-Detection/) | 2026 | 把 Agent 过程诊断定义成轨迹异常检测 |
| 7 | [AgentTrace: Structured Logging](相关/AgentTrace-Structured-Logging/) | 2026 | 三层日志模型：操作层 / 认知层 / 上下文层 |
| 8 | [ECHO: Hierarchical Error Attribution](高度相关/ECHO-Hierarchical-Error-Attribution/) | 2025 | 层次化上下文表示，适合 Session → Task → Stage → Step 的分层诊断 |
| 9 | [AgentPRM: Process Reward Models](高度相关/AgentPRM-Process-Reward-Models/) | 2025 | 每一步按“是否推进目标”评分 |
| 10 | [DoVer: Intervention-Driven Debugging](高度相关/DoVer-Intervention-Driven-Debugging/) | 2025 | 主动干预验证失败假设 |
| 11 | [Zero-Replay Debugging](高度相关/Zero-Replay-Debugging/) | 2026 | 不重放执行，只从日志中预测高影响事件 |
| 12 | [Watson: Cognitive Observability](高度相关/Watson-Cognitive-Observability/) | 2024 | 分析 Agent 为什么这么做 |

### P2：背景参考

| 排名 | 论文 | 年份 | 价值 |
|------|------|------|------|
| 13 | [TraceElephant: Failure Attribution](高度相关/TraceElephant-Failure-Attribution/) | 2026 | 支撑完整 trace 对失败归因的重要性 |
| 14 | [XAI for Coding Agent Failures](最相关/XAI-Coding-Agent-Failures/) | 2026 | 把 trace 转成可视化流程和自然语言报告 |
| 15 | [In-IDE Toolkit for AI Features](相关/In-IDE-Toolkit-AI-Features/) | 2026 | 借鉴产品形态：低门槛 trace 捕获、评估集、单元测试式评估 |
| 16 | [AgentTrace: Causal Graph Tracing](最相关/AgentTrace-Causal-Graph-Tracing/) | 2026 | 显性错误的因果图反向追踪 |
| 17 | [TraceCoder: Trace-Driven Debugging](高度相关/TraceCoder-Trace-Driven-Debugging/) | 2026 | 传统代码运行时调试 |
| 18 | [Autonomous Debugging: Dynamic Analysis](相关/Autonomous-Debugging-Dynamic-Analysis/) | 2026 | 函数级动态 trace |
| 19 | [Reflexion: Verbal Reinforcement Learning](相关/Reflexion-Self-Reflective-Agents/) | 2023 | 自反思机制背景论文 |

---

## 对 AgentLens / CCWhat 的启发

后续不应只做 `error log -> root cause`，更应围绕：

- Intermediate Output Scoring：评估每个阶段产物是否满足节点级期望
- Claim vs Evidence：检查 Agent 声称完成的事情是否真的有 trace / 命令 / diff 证据
- WorkState / Schema Conformance：检查中间状态是否缺字段、字段是否被错误更新
- Workflow Conformance：对比期望流程和真实执行路径，发现缺失阶段、跳步、顺序错误
- Critical Step Attribution：定位最早开始偏离目标的步骤
