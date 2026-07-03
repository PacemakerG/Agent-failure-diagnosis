# Watson: A Cognitive Observability Framework for the Reasoning of LLM-Powered Agents

## 基本信息

- **年份**: 2024
- **arXiv ID**: 2411.03455
- **作者**: Benjamin Rombaut, Sogol Masoumzadeh, Kirill Vasilevski, Dayi Lin, Ahmed E. Hassan

## 核心贡献

该论文引入了认知可观测性——检查Agent选择背后隐式推理的能力。Watson作为一个通用框架，在不修改Agent操作的情况下检查快思考LLM Agent中的推理。它使用提示归因方法回顾性地重建推理trace。

## 核心方法

1. **认知可观测性**: 观察和解释Agent的隐式推理过程
2. **提示归因**: 通过提示工程回顾性推断推理trace
3. **推理重建**: 从输出反向重建推理过程
4. **非侵入式设计**: 无需修改Agent即可观察

## 实验验证

在MMLU基准测试和AutoCodeRover、OpenHands等Agent上，在SWE-bench-lite上进行测试。框架"呈现可行动的推理洞察并支持有针对性的干预"，提高系统的透明度和可靠性。

## 与你的工作的关联

Watson的"认知可观测性"概念对你的诊断系统很有价值——不仅要观察Agent做了什么，还要理解它为什么这么做的推理过程。这对于分析LLM的决策错误很关键。

## 引用

```bibtex
@article{rombaut2024watson,
  title={Watson: A Cognitive Observability Framework for the Reasoning of LLM-Powered Agents},
  author={Rombaut, Benjamin and Masoumzadeh, Sogol and Vasilevski, Kirill and Lin, Dayi and Hassan, Ahmed E.},
  journal={arXiv preprint arXiv:2411.03455},
  year={2024}
}
```

## PDF链接

- 本地: [paper.pdf](paper.pdf)
- arXiv: https://arxiv.org/pdf/2411.03455
