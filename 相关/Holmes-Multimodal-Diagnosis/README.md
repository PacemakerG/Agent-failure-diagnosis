# Holmes: Multimodal Agentic Diagnosis for Mixed-Language Mobile Crashes at Industrial Scale

## 基本信息

- **年份**: 2026
- **arXiv ID**: 2606.21963
- **作者**: Jia Li, Wenyuan Ma, Ting Peng, Haibin Zheng, Yuetang Deng

## 核心贡献

该系统通过综合"多模态运行时信号——堆栈trace、日志和线程状态"来重建失败上下文，从而解决大规模应用中的移动崩溃诊断问题。它采用分层架构在数百万行代码中导航以识别缺陷。

## 核心方法

1. **多模态信号融合**: 综合堆栈trace、日志、线程状态等多种信号
2. **分层架构**: 在大型代码库中高效导航
3. **工业规模处理**: 处理实际生产环境的大规模数据
4. **Agentic诊断**: 使用Agent自主执行诊断任务

## 实验结果

在真实的微信崩溃数据上，Holmes实现了"87.6%的函数级故障定位准确率，并将平均调查时间减少98%以上（降至约77秒）"。

## 与你的工作的关联

Holmes的多模态诊断思想可以扩展你的工作——除了Agent行为日志，还可以考虑整合其他信号（如系统日志、性能指标）来进行更全面的诊断。

## 引用

```bibtex
@article{li2026holmes,
  title={Holmes: Multimodal Agentic Diagnosis for Mixed-Language Mobile Crashes at Industrial Scale},
  author={Li, Jia and Ma, Wenyuan and Peng, Ting and Zheng, Haibin and Deng, Yuetang},
  journal={arXiv preprint arXiv:2606.21963},
  year={2026}
}
```

## PDF链接

- 本地: [paper.pdf](paper.pdf)
- arXiv: https://arxiv.org/pdf/2606.21963
