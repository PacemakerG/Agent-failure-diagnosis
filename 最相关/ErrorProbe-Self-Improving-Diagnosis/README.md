# Towards Self-Improving Error Diagnosis in Multi-Agent Systems (ErrorProbe)

## 基本信息

- **年份**: 2026
- **arXiv ID**: 2604.17658
- **作者**: Jiazheng Li, Emine Yilmaz, Bei Chen, Dieu-Thu Le

## 核心贡献

ErrorProbe是一个用于识别LLM-based多Agent系统中哪个Agent导致失败并精确定位错误来源的框架。它使用"三阶段流水线：(1) 将MAS失败分类可操作化以检测局部异常，(2) 执行症状驱动的反向追踪以剪枝无关上下文，(3) 使用专门的Multi-Agent团队"。系统构建经过验证的记忆，无需专家注释。

## 科技界方法

1. **失败分类可操作化**: 将抽象的失败类型转化为可检测的具体症状
2. **症状驱动的反向追踪**: 从症状出发反向追溯错误来源
3. **上下文剪枝**: 去除无关上下文，聚焦关键信息
4. **多Agent验证团队**: 使用专门的Agent团队验证诊断结果
5. **经验记忆**: 无需专家注释的自我改进机制

## 与你的工作的关联

ErrorProbe的三阶段流水线对你的诊断系统架构有直接参考价值：规则检测（症状识别）→ 反向追踪（根因分析）→ 验证（确认诊断）。

## 引用

```bibtex
@article{li2026errorprobe,
  title={Towards Self-Improving Error Diagnosis in Multi-Agent Systems},
  author={Li, Jiazheng and Yilmaz, Emine and Chen, Bei and Le, Dieu-Thu},
  journal={arXiv preprint arXiv:2604.17658},
  year={2026}
}
```

## PDF链接

- 本地: [paper.pdf](paper.pdf)
- arXiv: https://arxiv.org/pdf/2604.17658
