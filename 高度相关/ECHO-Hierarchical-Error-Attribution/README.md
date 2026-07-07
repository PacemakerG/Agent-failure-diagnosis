# Where Did It All Go Wrong? A Hierarchical Look into Multi-Agent Error Attribution (ECHO)

## 基本信息

- **年份**: 2025
- **arXiv ID**: 2510.04886
- **作者**: Adi Banerjee, Anirudh Nair, Tarik Borogovac
- **当前优先级**: P1 高度相关，建议优先阅读第 8 篇

## 核心贡献

ECHO 用于识别 LLM 多 Agent 系统失败中的责任位置。它的核心是：

1. **层次化上下文表示**
2. **基于客观分析的评估**
3. **共识投票**
4. **细粒度错误归因**

相比只看单个工具调用，它更强调把多 Agent 运行过程拆成多个层级来理解。

## 为什么对你的工作重要

你现在的 AgentLens 已经天然有层次结构：

```text
Session
  ↓
Task
  ↓
Conversation / Stage
  ↓
Step / Turn
  ↓
Tool Event / State Change
```

隐性失败往往不是单步错误，而是某个层级上的语义偏差：

```text
Task 目标没错
某个 Stage 缺失
某个 Step 少写状态
后续 Tool Event 都正常执行
最终结果偏了
```

ECHO 的层次化归因思想适合用来组织诊断报告。

## 可借鉴到 AgentLens 的设计

### 1. 分层诊断

不要直接问“哪个工具调用错了”，而是逐层判断：

```text
Task 是否完成目标？
Stage 是否完整？
Step 是否推进目标？
State Change 是否满足协议？
Tool Evidence 是否支撑 Agent claim？
```

### 2. 多视角投票

可以设计多个 verifier：

- Workflow Verifier
- State Verifier
- Claim-Evidence Verifier
- Artifact Verifier
- Goal-Progress Verifier

最后聚合成诊断结论。

### 3. 微妙错误识别

ECHO 提到对微妙推理错误更友好，这适合 AgentLens 后续处理：

```text
Agent 的推理听起来合理，但状态更新不完整
Agent 的结论看似可信，但没有真实证据
```

## 局限

ECHO 更偏归因框架，不直接解决 WorkState schema 检查。实际落地时应结合 AgentRx 的约束检查和 PROTEA 的中间节点评分。

## 引用

```bibtex
@article{banerjee2025echo,
  title={Where Did It All Go Wrong? A Hierarchical Look into Multi-Agent Error Attribution},
  author={Banerjee, Adi and Nair, Anirudh and Borogovac, Tarik},
  journal={arXiv preprint arXiv:2510.04886},
  year={2025}
}
```

## PDF链接

- 本地: [paper.pdf](paper.pdf)
- arXiv: https://arxiv.org/pdf/2510.04886
