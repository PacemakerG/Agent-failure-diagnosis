# Empowering Autonomous Debugging Agents with Efficient Dynamic Analysis

## 基本信息

- **年份**: 2026
- **arXiv ID**: 2604.24212
- **作者**: Jiahong Xiang, Xiaoyang Xu, Xiaopan Chu, Hongliang Tian, Yuqun Zhang
- **发表场所**: ACM FSE 2026

## 核心贡献

该研究提出了Agent-centric Debugging Interface (ADI)，旨在增强自主Agent的程序修复能力。ADI不依赖传统的逐行调试器交互，而是实现"使用Frame Lifetime Trace技术的函数级交互范式"。

## 科技界方法

1. **函数级交互**: 传统的逐行调试 vs 函数级抽象
2. **Frame Lifetime Trace**: 捕获函数生命周期的trace技术
3. **Agent-centric设计**: 专为自主Agent设计的调试接口
4. **动态分析**: 运行时收集程序行为数据

## 实验结果

- 在SWE-bench上，基本Agent解决了63.8%的任务，每任务成本1.28美元
- 集成到现有系统后，提供"6.2%到18.5%的一致增益"

## 与你的工作的关联

这篇论文的函数级trace思想对你的工具有启发——与其记录每一行代码执行，不如在工具调用/函数层面进行trace，这样更高效且信息密度更高。

## 引用

```bibtex
@article{xiang2026autonomous,
  title={Empowering Autonomous Debugging Agents with Efficient Dynamic Analysis},
  author={Xiang, Jiahong and Xu, Xiaoyang and Chu, Xiaopan and Tian, Hongliang and Zhang, Yuqun},
  journal={Proceedings of the ACM SIGSOFT International Symposium on Foundations of Software Engineering (FSE)},
  year={2026}
}
```

## PDF链接

- 本地: [paper.pdf](paper.pdf)
- arXiv: https://arxiv.org/pdf/2604.24212
