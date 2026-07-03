# Seeing the Whole Elephant: A Benchmark for Failure Attribution in LLM-based Multi-Agent Systems

## 基本信息

- **年份**: 2026
- **arXiv ID**: 2604.22708
- **作者**: Mengzhuo Chen, Junjie Wang, Fangwen Mu, Yawen Wang, Zhe Liu, Huanxiang Feng, Qing Wang

## 核心贡献

TraceElephant是一个用于LLM-based多Agent系统失败归因的基准测试。研究强调使用完整执行trace而非部分观察来进行失败归因。研究发现，与对Agent交互可见性有限的系统相比，完整的trace可将归因准确率提高高达76%。

## 核心方法

1. **完整执行Trace**: 收集多Agent系统的完整执行trace（而非部分观察）
2. **失败归因基准**: 建立标准化的失败归因评估基准
3. **对比实验**: 对比完整trace vs 部分观察的效果差异

## 关键发现

- 完整trace比部分观察提升76%的归因准确率
- 强调数据完整性对诊断效果的关键影响

## 与你的工作的关联

这篇论文验证了你的工作方向——完整的Agent行为日志对于诊断至关重要。你的系统收集的原始日志（包括工具调用、LLM API请求等）正是实现准确诊断的基础。

## 引用

```bibtex
@article{chen2026traceelephant,
  title={Seeing the Whole Elephant: A Benchmark for Failure Attribution in LLM-based Multi-Agent Systems},
  author={Chen, Mengzhuo and Wang, Junjie and Mu, Fangwen and Wang, Yawen and Liu, Zhe and Feng, Huanxiang and Wang, Qing},
  journal={arXiv preprint arXiv:2604.22708},
  year={2026}
}
```

## PDF链接

- 本地: [paper.pdf](paper.pdf)
- arXiv: https://arxiv.org/pdf/2604.22708
