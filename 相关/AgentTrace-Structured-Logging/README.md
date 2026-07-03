# AgentTrace: A Structured Logging Framework for Agent System Observability

## 基本信息

- **年份**: 2026
- **arXiv ID**: 2602.10133
- **作者**: Adam AlSayyad, Kelvin Yuxiang Huang, Richik Pal
- **发表场所**: AAAI 2026 Workshop LaMAS

## 核心贡献

该论文通过引入动态可观测性框架来解决LLM驱动的自主Agent的安全挑战。AgentTrace"在运行时以最小开销检测Agent，捕获跨越三个层面的丰富结构化日志流：操作层面、认知层面和上下文层面"。研究人员认为这种方法实现了"更可靠的Agent部署、细粒度风险分析和知情的信任校准"。

## 核心方法

1. **三层日志模型**:
   - **操作层面 (Operational)**: Agent的外部行为、工具调用
   - **认知层面 (Cognitive)**: Agent的内部推理、决策过程
   - **上下文层面 (Contextual)**: 执行环境的上下文信息

2. **运行时检测**: 在Agent运行时动态检测，最小化开销
3. **结构化日志**: 标准化的日志格式便于分析
4. **安全与可审计**: 支持风险分析和信任校准

## 与你的工作的关联

这篇论文的三层日志模型（操作/认知/上下文）为你的日志收集和分析提供了结构化的参考框架。你的当前工作主要集中在操作层面，可以考虑扩展。

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
