# Watson: A Cognitive Observability Framework for the Reasoning of LLM-Powered Agents

## 基本信息

- **年份**: 2024
- **arXiv ID**: 2411.03455
- **作者**: Benjamin Rombaut, Sogol Masoumzadeh, Kirill Vasilevski, Dayi Lin, Ahmed E. Hassan
- **当前优先级**: P1 高度相关，建议优先阅读第 12 篇

## 核心贡献

Watson 提出 **认知可观测性**：不仅观察 Agent 做了什么，还要观察和解释 Agent 为什么这么做。

它尝试在不修改 Agent 操作的情况下，通过提示归因等方法，回顾性地重建 Agent 的隐式推理 trace。

## 核心方法

1. **认知可观测性**: 观察 Agent 决策背后的隐式推理。
2. **提示归因**: 通过 prompt attribution 推断哪些上下文影响了输出。
3. **推理重建**: 从输出反向重建可能的推理过程。
4. **非侵入式设计**: 不要求修改 Agent 本身。

## 为什么对你的工作重要

隐性失败很多时候不是工具层错误，而是决策层偏差：

```text
Agent 为什么认为这个字段不用写？
Agent 为什么认为可以跳过测试？
Agent 为什么认为已经完成？
Agent 为什么没有打开关键文档？
```

这些问题只看 tool call 不够，需要看认知层信号。

## 可借鉴到 AgentLens 的设计

### 1. Reasoning Evidence

AgentLens 可以把模型请求中的 plan、analysis、summary、claim 抽出来，作为认知层事件：

```text
Agent planned to test
Agent later skipped test
Agent final response claimed test passed
```

这三者之间的矛盾就是诊断线索。

### 2. Decision Explanation

当发现某个异常状态更新时，系统可以追问：

```text
这个状态更新前，Agent 基于哪些上下文做了判断？
它是否引用了错误文件？
它是否忽略了用户约束？
它是否把默认值当成真实状态？
```

### 3. 和 Structured Logging 结合

Watson 对应认知层；AgentTrace Structured Logging 提供三层日志模型。两者结合后，AgentLens 可以从：

```text
做了什么
为什么这么做
当时上下文是什么
```

三个角度诊断隐性失败。

## 局限

认知重建天然有不确定性，不能完全当作事实证据。AgentLens 最好把它作为解释辅助，而不是唯一诊断依据。最终仍然要回到 trace、文件 diff、命令输出、WorkState 等可验证证据。

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
