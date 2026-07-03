# Knowledge-Based Zero-Replay Debugging of Multi-Agent LLM Traces

## 基本信息

- **年份**: 2026
- **arXiv ID**: 2606.14805
- **作者**: Dong Ho Kang, Hyeonjeong Cha, Daein Weon

## 核心贡献

该论文通过提出一种基于知识的方法来解决多Agent LLM系统中的调试挑战。与使用昂贵的反事实重放来评估事件不同，作者将问题框定为预测重放oracle会在不实际执行重放操作的情况下识别哪些事件为高影响事件。他们将trace编译成结构化事件知识图，并使用名为BranchPoint-Latent的梯度提升预测器。

## 核心方法

1. **事件知识图**: 将trace编译为结构化的知识图表示
2. **零重放预测**: 无需实际重放即可预测高影响事件
3. **BranchPoint-Latent**: 梯度提升预测器识别关键分支点
4. **反事实效果预测**: 预测事件对结果的因果影响

## 实验结果

在37个trace家族上测试，该方法在新的家族上实现了Branch Recall@5从0.73到0.93的提升，且无需重放成本。

## 与你的工作的关联

这篇论文的"零重放"思想对你的场景很重要——你不能重放Cloud Agent的执行，只能从日志中诊断。事件知识图的构建方法值得借鉴。

## 引用

```bibtex
@article{kang2026zeroreplay,
  title={Knowledge-Based Zero-Replay Debugging of Multi-Agent LLM Traces},
  author={Kang, Dong Ho and Cha, Hyeonjeong and Weon, Daein},
  journal={arXiv preprint arXiv:2606.14805},
  year={2026}
}
```

## PDF链接

- 本地: [paper.pdf](paper.pdf)
- arXiv: https://arxiv.org/pdf/2606.14805
