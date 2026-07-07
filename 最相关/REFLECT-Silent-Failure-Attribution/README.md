# REFLECT: Intervention-Supported Error Attribution for Silent Failures in LLM Agent Traces

## 基本信息

- **年份**: 2026
- **arXiv ID**: 2606.09071
- **作者**: Xiaofeng Lin, Yingxu Wang, Tung Sum Thomas Kwok, Daniel Guo, Sahil Arun Nale, Charles Fleming, Guang Cheng
- **当前优先级**: P0 最相关

## 核心贡献

REFLECT 直接研究 **silent failure**：LLM Agent 的执行 trace 看起来已经完整跑完，没有明显工具错误、格式错误或运行时异常，但最终结果仍然错误。

它的核心不是简单判断哪一步可疑，而是通过 **干预验证** 来重新校准错误归因：

1. 先诊断一个候选错误步骤；
2. 针对该步骤构造诊断补丁；
3. 从原 trace 的前缀继续受控 replay；
4. 如果结果发生翻转，就把这个干预结果作为反事实证据；
5. 用反事实证据 refine 最终归因。

## 核心方法

1. **候选错误步骤定位**: 从完整 trace 中找出可能导致失败的步骤。
2. **诊断特定补丁**: 针对候选错误步骤生成局部修复或替代动作。
3. **受控 replay**: 从 trace 前缀继续执行，而不是完全重新跑任务。
4. **Outcome flip 证据**: 如果干预后结果从失败变成功，说明候选步骤很可能是真正关键错误点。
5. **归因修正**: 将干预结果反馈给最终错误归因，而不是只依赖 LLM judge 的一次判断。

## 为什么对你的工作重要

这篇论文非常贴近 AgentLens 后续要解决的问题：

```text
trace 正常完成
没有显性报错
最终产物不理想
需要定位哪个中间步骤悄悄偏离目标
```

它比传统 Root Cause Analysis 更适合 **隐性失败**。传统方法常常需要一个明确错误节点；REFLECT 面向的是“没有明显错误节点，但结果就是错”的场景。

## 可借鉴到 AgentLens 的设计

### 1. Silent Failure 诊断入口

AgentLens 可以新增一种诊断类型：

```text
Final outcome bad, but no explicit error.
```

不再要求 trace 中必须有 exception、test failure、compile error。

### 2. 候选关键步骤排序

先用规则或 LLM 找出候选偏差步骤：

- 没有证据支撑的完成声明
- 中间状态字段缺失
- 跳过验证阶段
- 关键文件未读取却声称已参考
- 计划与实际动作不一致

### 3. 局部 replay / 近似 replay

如果无法真正 replay Claude Code / Codex / OpenCode，可以先做离线近似：

```text
原始 trace 前缀 + 修改后的关键步骤 + 让模型判断后续是否会改变
```

短期可以作为诊断证据，中长期再接真正 replay。

## 局限

REFLECT 依赖 replay 或受控重放能力。真实 Coding Agent 的本地环境、文件状态、模型随机性都可能让 replay 成本很高。因此 AgentLens 短期更适合先借鉴它的 **干预验证思想**，不一定完整复现算法。

## 引用

```bibtex
@article{lin2026reflect,
  title={REFLECT: Intervention-Supported Error Attribution for Silent Failures in LLM Agent Traces},
  author={Lin, Xiaofeng and Wang, Yingxu and Kwok, Tung Sum Thomas and Guo, Daniel and Nale, Sahil Arun and Fleming, Charles and Cheng, Guang},
  journal={arXiv preprint arXiv:2606.09071},
  year={2026}
}
```

## PDF链接

- 本地: [paper.pdf](paper.pdf)
- arXiv: https://arxiv.org/pdf/2606.09071
