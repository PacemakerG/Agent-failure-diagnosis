# Reflexion: Language Agents with Verbal Reinforcement Learning

## 基本信息

- **年份**: 2023
- **arXiv ID**: 2303.11366
- **作者**: Noah Shinn, Federico Cassano, Edward Berman, Ashwin Gopinath, Karthik Narasimhan, Shunyu Yao

## 核心贡献

该论文引入了一个框架，使语言模型能够通过语言自我修正而非权重更新来充当自适应Agent。关键创新涉及Agent"口头反思任务反馈信号，然后将自己的反思文本保存在情景记忆缓冲区中"以增强后续性能。

## 科技界方法

1. **语言自我反思**: Agent用语言形式反思自己的行为
2. **情景记忆**: 存储反思结果供未来使用
3. **口头强化学习**: 不更新模型权重，通过自然语言反馈改进
4. **迭代改进**: 多次迭代反思逐步提升性能

## 实验结果

- 在HumanEval编码任务上达到91%准确率，超过GPT-4的80%
- 适用于顺序决策、编程和推理任务等多种领域

## 与你的工作的关联

Reflexion的"反思策略"对你的LLM诊断层有借鉴意义：在Prompt中引入反思步骤（"检查你的分析是否与原始数据一致"）可以提高诊断准确性。

## 引用

```bibtex
@article{shinn2023reflexion,
  title={Reflexion: Language Agents with Verbal Reinforcement Learning},
  author={Shinn, Noah and Cassano, Federico and Berman, Edward and Gopinath, Ashwin and Narasimhan, Karthik and Yao, Shunyu},
  journal={arXiv preprint arXiv:2303.11366},
  year={2023}
}
```

## PDF链接

- 本地: [paper.pdf](paper.pdf)
- arXiv: https://arxiv.org/pdf/2303.11366
