# AgentTrace: A Structured Logging Framework for Agent System Observability

## 基本信息

- **年份**: 2026
- **arXiv ID**: 2602.10133
- **作者**: Adam AlSayyad, Kelvin Yuxiang Huang, Richik Pal
- **发表场所**: AAAI 2026 Workshop LaMAS
- **当前优先级**: P1 高度相关，建议优先阅读第 7 篇

## 核心贡献

该论文提出一个动态可观测性框架，用于在运行时捕获 LLM Agent 的结构化日志。

最值得借鉴的是它的三层日志模型：

1. **操作层面 Operational**: Agent 的外部行为、工具调用、命令执行、文件读写。
2. **认知层面 Cognitive**: Agent 的推理、决策、计划、解释。
3. **上下文层面 Contextual**: 当前任务、环境、状态、角色、约束、输入上下文。

## 为什么对你的工作重要

AgentLens 当前强在操作层：

```text
工具调用
命令执行
文件变更
模型请求响应
```

但要诊断隐性失败，还必须补上下文层：

```text
当前阶段
当前 WorkState
当前 Agent 角色
当前任务完成标准
当前 schema / protocol 约束
```

否则你只能看到“Agent 做了什么”，但很难判断“它该不该这么做”。

## 可借鉴到 AgentLens 的设计

### 1. 三层事件模型

AgentLens 的 trace 可以升级成：

```text
Operational Event
- tool call
- command
- file diff
- request/response

Cognitive Event
- plan
- assumption
- decision
- claim
- self-evaluation

Contextual Event
- goal
- stage
- workstate
- role
- protocol constraint
```

### 2. 隐性失败需要上下文层

例如 WorkState 少字段：

```text
只有操作层：看到 Agent 写了某个 JSON
加入上下文层：知道这个阶段必须写 test_required 字段
```

只有后者才能判断这是隐性错误。

### 3. 和 Claim vs Evidence 结合

Agent 声称完成属于 cognitive event；真实命令、文件 diff、状态更新属于 operational/contextual evidence。两者对不上，就是 false success 风险。

## 局限

这篇论文主要回答“应该采集什么”，不是直接回答“怎么归因”。诊断算法仍然需要结合 PROTEA、AgentRx、ErrorProbe、TrajAD 等方法。

## 引用

```bibtex
@article{alsayyad2026agenttrace,
  title={AgentTrace: A Structured Logging Framework for Agent System Observability},
  author={AlSayyad, Adam and Huang, Kelvin Yuxiang and Pal, Richik},
  journal={AAAI 2026 Workshop on Language Models for Agentic Systems (LaMAS)},
  year={2026}
}
```

## PDF链接

- 本地: [paper.pdf](paper.pdf)
- arXiv: https://arxiv.org/pdf/2602.10133
