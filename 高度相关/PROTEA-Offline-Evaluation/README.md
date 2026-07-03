# PROTEA: Offline Evaluation and Iterative Refinement for Multi-Agent LLM Workflows

## 基本信息

- **年份**: 2026
- **arXiv ID**: 2605.18032
- **作者**: Kazuki Kawamura, Satoshi Waki, Kei Tateno

## 核心贡献

PROTEA为调试多Agent LLM工作流提供"离线、测试驱动的多Agent工作流改进统一接口"。它使用可配置的评分标准评估中间输出，并在工作流图上可视化瓶颈。该工具从最终答案生成节点级期望，并实现有针对性的提示修订和自动重新评估。

## 核心方法

1. **离线评估**: 无需生产环境即可评估工作流
2. **测试驱动改进**: 类似单元测试的工作流验证
3. **中间输出评分**: 对中间步骤进行质量评估
4. **工作流图可视化**: 在工作流图上叠加状态以识别瓶颈
5. **节点级期望生成**: 从最终答案推导中间节点的期望输出

## 实验结果

- 文档检查准确率从64.3%提升到83.9%
- 推荐指标显著改善

## 与你的工作的关联

PROTEA的"离线评估"概念对你的场景很有价值——可以在不重新执行Agent的情况下，基于已有日志进行诊断和改进建议验证。

## 引用

```bibtex
@article{kawamura2026protea,
  title={PROTEA: Offline Evaluation and Iterative Refinement for Multi-Agent LLM Workflows},
  author={Kawamura, Kazuki and Waki, Satoshi and Tateno, Kei},
  journal={arXiv preprint arXiv:2605.18032},
  year={2026}
}
```

## PDF链接

- 本地: [paper.pdf](paper.pdf)
- arXiv: https://arxiv.org/pdf/2605.18032
