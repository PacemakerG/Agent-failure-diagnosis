# Where Did It All Go Wrong? A Hierarchical Look into Multi-Agent Error Attribution (ECHO)

## 基本信息

- **年份**: 2025
- **arXiv ID**: 2510.04886
- **作者**: Adi Banerjee, Anirudh Nair, Tarik Borogovac

## 核心贡献

ECHO是一种用于识别LLM多Agent系统失败的算法。该方法结合了"层次化上下文表示、基于客观分析的评估和共识投票"来提高准确性。该方法解决了现有调试技术的局限性，在微妙推理错误的情况下表现出改进的性能。

## 科技界方法

1. **层次化上下文表示**: 多层次地组织和表示Agent执行上下文
2. **客观分析评估**: 基于客观指标而非主观判断进行评估
3. **共识投票**: 多Agent投票机制聚合诊断结果
4. **细粒度归因**: 能够识别微妙的推理错误

## 与你的工作的关联

这篇论文与你的"阶段划分"概念高度契合。ECHO的层次化上下文表示可以直接借鉴到你的阶段类型标注（规划/执行/验证/修复）中。

## 引用

```bibtex
@article{banerjee2025echo,
  title={Where Did It All Go Wrong? A Hierarchical Look into Multi-Agent Error Attribution},
  author={Banerjee, Adi and Nair, Anirudh and Borogovac, Tarik},
  journal={arXiv preprint arXiv:2510.04886},
  year={2025}
}
```

## PDF链接

- 本地: [paper.pdf](paper.pdf)
- arXiv: https://arxiv.org/pdf/2510.04886
