# DoVer: Intervention-Driven Auto Debugging for LLM Multi-Agent Systems

## 基本信息

- **年份**: 2025
- **arXiv ID**: 2512.06749
- **作者**: Ming Ma, Jue Zhang, Fangkai Yang, Yu Kang, Qingwei Lin, Saravan Rajmohan, Dongmei Zhang

## 核心贡献

DoVer是一个通过针对性干预来验证失败假设的框架。与仅关注归因准确性不同，它衡量"系统是否解决了失败或在任务成功方面取得了可量化的进展"。该框架在多个数据集和Agent框架上将成功率恢复提高了18-28%。

## 科技界方法

1. **假设生成**: 基于观察生成失败假设
2. **主动干预验证**: 通过针对性干预验证假设（而非被动观察）
3. **效果评估**: 衡量干预后的实际改进效果
4. **闭环调试**: 从验证结果学习并迭代

## 实验结果

- 在多个数据集上实现18-28%的成功率恢复
- 验证30-60%的失败假设

## 与你的工作的关联

这篇论文的主动验证思想对你的诊断系统有启发：不仅仅是识别问题，还要验证修复建议的有效性。这对于从"诊断"向"自动修复"演进有借鉴意义。

## 引用

```bibtex
@article{ma2025dover,
  title={DoVer: Intervention-Driven Auto Debugging for LLM Multi-Agent Systems},
  author={Ma, Ming and Zhang, Jue and Yang, Fangkai and Kang, Yu and Lin, Qingwei and Rajmohan, Saravan and Zhang, Dongmei},
  journal={arXiv preprint arXiv:2512.06749},
  year={2025}
}
```

## PDF链接

- 本地: [paper.pdf](paper.pdf)
- arXiv: https://arxiv.org/pdf/2512.06749
