# Towards Self-Improving Error Diagnosis in Multi-Agent Systems (ErrorProbe)

## 基本信息

- **年份**: 2026
- **arXiv ID**: 2604.17658
- **作者**: Jiazheng Li, Emine Yilmaz, Bei Chen, Dieu-Thu Le
- **当前优先级**: P0 最相关，建议优先阅读第 5 篇

## 核心贡献

ErrorProbe 是一个用于识别 LLM-based 多 Agent 系统中哪个 Agent 导致失败、并精确定位错误来源的框架。

它最值得借鉴的是完整诊断流水线：

```text
症状识别
↓
反向追踪
↓
上下文剪枝
↓
多 Agent 验证
↓
经验记忆
```

相比只做因果图反向追踪，ErrorProbe 更适合作为 AgentLens 诊断系统的整体架构参考。

## 核心方法

1. **失败分类可操作化**: 将抽象失败类型转化为可以检测的具体症状。
2. **症状驱动的反向追踪**: 从症状出发，向前追溯可能来源。
3. **上下文剪枝**: 去除无关 trace，聚焦关键上下文。
4. **多 Agent 验证团队**: 用专门 Agent 验证诊断结论。
5. **经验记忆**: 保存被验证过的诊断经验，无需专家持续标注。

## 为什么对你的工作重要

你关心的隐性问题不一定有 exception：

```text
状态字段缺失
流程跳过
Agent 声称完成但没有证据
最终产物不理想
```

ErrorProbe 的“失败分类可操作化”可以直接改造成：

```text
把隐性失败定义成可检测症状
```

例如：

| 隐性失败类型 | 可检测症状 |
|---|---|
| WorkState 字段缺失 | 应有字段不存在，或字段值未更新 |
| 流程跳步 | 期望阶段没有对应 Step / Tool Evidence |
| Claim 无证据 | Agent 声称完成，但 trace 中没有文件/命令/状态证据 |
| 目标漂移 | 后续动作与初始任务目标弱相关 |
| 验证缺失 | 代码修改后没有测试或检查命令 |

## 可借鉴到 AgentLens 的设计

### 1. Symptom Detectors

先做规则化症状检测，而不是直接让 LLM 猜根因：

```text
missing_state_field
missing_verification_step
unsupported_completion_claim
workflow_stage_skipped
goal_drift
```

### 2. Backward Trace

从症状反向追：

```text
Verification skipped
↑
WorkState.test_required missing
↑
Planner did not write test_required
↑
Planner summary claimed test plan complete
```

### 3. Verification Agents

诊断结论可以交给多个 verifier：

- State Verifier
- Workflow Verifier
- Claim-Evidence Verifier
- Artifact Verifier

最终输出一个带证据的诊断报告。

## 局限

ErrorProbe 仍然以“失败发生后诊断”为主。对于完全没有显性失败、只是产物质量低的场景，需要额外结合 PROTEA、REFLECT、False Success、AgentRx 这几类论文。

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
