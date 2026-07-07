# Knowledge-Based Zero-Replay Debugging of Multi-Agent LLM Traces

## 基本信息

- **年份**: 2026
- **arXiv ID**: 2606.14805
- **作者**: Dong Ho Kang, Hyeonjeong Cha, Daein Weon
- **当前优先级**: P1 高度相关，建议优先阅读第 11 篇

## 核心贡献

这篇论文研究的问题是：

> 如果不能实际重放 Agent 执行，能不能只根据已有 trace 预测哪些事件是高影响事件？

它将 trace 编译成结构化事件知识图，并使用预测模型识别关键分支点。

## 核心方法

1. **事件知识图**: 将 trace 编译为结构化事件图。
2. **零重放预测**: 不实际 replay，也预测高影响事件。
3. **BranchPoint-Latent**: 用预测器识别关键分支点。
4. **反事实效果预测**: 估计某个事件对最终结果的影响。

## 为什么对你的工作重要

真实 Coding Agent 诊断经常没法完整重放：

```text
本地文件状态变了
模型输出不可复现
外部工具状态变了
网络/API结果变了
用户环境不可控
```

所以 AgentLens 很可能长期都需要一个能力：

```text
不能 replay，也要从已有日志中推断关键偏差点。
```

Zero-Replay Debugging 正好对应这个需求。

## 可借鉴到 AgentLens 的设计

### 1. Event Knowledge Graph

把 AgentLens 的 trace 转成事件图：

```text
User Goal
↓
Plan Claim
↓
Tool Call
↓
File Diff
↓
WorkState Update
↓
Final Claim
```

每个节点保存：

```text
时间
类型
输入输出
依赖关系
证据强度
是否满足约束
```

### 2. Branch Point 检测

重点寻找：

```text
状态字段第一次缺失的位置
流程第一次跳过的位置
目标第一次偏移的位置
无证据 claim 第一次出现的位置
```

### 3. 低成本诊断

即使没有 replay，也能先输出：

```text
High-impact suspected event
Supporting evidence
Possible downstream impact
```

## 局限

它仍然需要高质量结构化事件表示。对于 AgentLens 来说，前置条件是先把 Session / Task / Step / Tool / State Change 结构化做好。

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
