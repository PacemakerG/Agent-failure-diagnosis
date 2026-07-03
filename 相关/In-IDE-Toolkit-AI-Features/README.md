# In-IDE Toolkit for Developers of AI-Based Features

## 基本信息

- **年份**: 2026
- **arXiv ID**: 2605.14612
- **作者**: Yaroslav Sokolov, Yury Khudyakov, Lenar Sharipov, Andrei Gasparian, Parth Tiwary, Artem Trofimov

## 核心贡献

该论文解决了使用LLM构建AI功能时的测试和调试挑战。研究人员为JetBrains IDE开发了AI Toolkit插件，将trace和评估集成到开发工作流中。关键功能包括运行触发的trace捕获、分层检查、从trace创建数据集，以及类似单元测试的评估。

## 核心方法

1. **IDE原生可观测性**: 将trace和评估集成到开发环境
2. **运行触发trace捕获**: 自动捕获执行trace
3. **分层检查**: 层次化查看trace数据
4. **数据集创建**: 从trace自动生成评估数据集
5. **单元测试式评估**: 为AI功能提供类似传统单元测试的评估方式

## 核心洞察

研究识别了开发者的三个核心需求：
1. 使评估可重复
2. 实时暴露执行trace
3. 最小化设置开销

PyCharm的早期采用信号显示强烈的参与度和持续使用，表明"IDE原生可观测性降低了激活能量"。

## 与你的工作的关联

这篇论文对你的Web查看器开发有借鉴意义——提供一个集成的、低门槛的可观测性工具对于开发者采纳至关重要。

## 引用

```bibtex
@article{sokolov2026ide,
  title={In-IDE Toolkit for Developers of AI-Based Features},
  author={Sokolov, Yaroslav and Khudyakov, Yury and Sharipov, Lenar and Gasparian, Andrei and Tiwary, Parth and Trofimov, Artem},
  journal={arXiv preprint arXiv:2605.14612},
  year={2026}
}
```

## PDF链接

- 本地: [paper.pdf](paper.pdf)
- arXiv: https://arxiv.org/pdf/2605.14612
