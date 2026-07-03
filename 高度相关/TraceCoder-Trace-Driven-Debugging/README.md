# TraceCoder: A Trace-Driven Multi-Agent Framework for Automated Debugging of LLM-Generated Code

## 基本信息

- **年份**: 2026
- **arXiv ID**: 2602.06875
- **作者**: Jiangping Huang, Wenguang Ye, Weisong Sun, Jian Zhang, Mingyue Zhang, Yang Liu

## 核心贡献

TraceCoder是一个协作框架，模拟人类专家的"观察-分析-修复"过程。系统通过诊断探针检测代码以捕获执行trace，执行因果分析以识别根因，并包含历史经验教训学习机制以防止重复错误。Rollback机制确保每次修复迭代都向正确性改进。

## 科技界方法

1. **诊断探针**: 在代码中插入探针以捕获细粒度运行时trace
2. **因果分析**: 分析trace以识别错误根因
3. **历史经验教训学习机制**: 从过去的调试经验中学习，避免重复错误
4. **Rollback机制**: 确保每次修复都是改进
5. **多Agent协作**: 模拟人类专家的协作调试过程

## 实验结果

在代码生成任务中，相比基线方法实现了高达34.43%的Pass@1准确率相对提升。

## 与你的工作的关联

该论文的因果分析和历史学习机制对你的诊断系统有借鉴意义，特别是如何将原始trace转化为可行动的洞察。

## 引用

```bibtex
@article{huang2026tracecoder,
  title={TraceCoder: A Trace-Driven Multi-Agent Framework for Automated Debugging of LLM-Generated Code},
  author={Huang, Jiangping and Ye, Wenguang and Sun, Weisong and Zhang, Jian and Zhang, Mingyue and Liu, Yang},
  journal={arXiv preprint arXiv:2602.06875},
  year={2026}
}
```

## PDF链接

- 本地: [paper.pdf](paper.pdf)
- arXiv: https://arxiv.org/pdf/2602.06875
