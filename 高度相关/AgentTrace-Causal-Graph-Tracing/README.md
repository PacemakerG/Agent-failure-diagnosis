# AgentTrace: Causal Graph Tracing for Root Cause Analysis in Deployed Multi-Agent Systems

## 基本信息

- **年份**: 2026
- **arXiv ID**: 2603.14688
- **作者**: Zhaohui Geoffrey Wang

## 核心贡献

AgentTrace是一个轻量级的因果追踪框架，用于部署后多Agent工作流的失败诊断。该框架从执行日志中重建因果图，并从错误反向追踪以识别根因，使用可解释的信号实现高准确度和亚秒级延迟，且在调试过程中不需要LLM推理。

## 核心方法

1. **因果图重建**: 从执行日志中重建工具调用之间的因果关系
2. **反向追踪算法**: 从最终错误节点反向追溯到根因
3. **结构和位置信号**: 使用可解释的信号（而非LLM）进行根因排序
4. **轻量级部署**: 无需重放，直接分析已部署系统的日志

## 与你的工作的关联

这篇论文直接解决"工具依赖图 + 错误传播链"问题，与你的P3改进计划中的"工具依赖图"高度吻合。论文中的因果图构建方法可以直接借鉴。

## 引用

```bibtex
@article{wang2026agenttrace,
  title={AgentTrace: Causal Graph Tracing for Root Cause Analysis in Deployed Multi-Agent Systems},
  author={Wang, Zhaohui Geoffrey},
  journal={arXiv preprint arXiv:2603.14688},
  year={2026}
}
```

## PDF链接

- 本地: [paper.pdf](paper.pdf)
- arXiv: https://arxiv.org/pdf/2603.14688
