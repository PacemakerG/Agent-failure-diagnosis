# AgentRx: Diagnosing AI Agent Failures from Execution Trajectories

## 基本信息

- **年份**: 2026
- **arXiv ID**: 2602.02475
- **作者**: Shraddha Barke, Arnav Goyal, Alind Khare, Avaljot Singh, Suman Nath, Chetan Bansal
- **当前优先级**: P0 最相关

## 核心贡献

AgentRx 关注如何从完整执行轨迹中诊断 AI Agent 失败。它的核心价值在于：

> 不只是看最终结果，而是把执行轨迹转成一组可检查的约束，然后逐步验证这些约束在哪里被违反。

论文构建了一个失败轨迹 benchmark，并为每条失败轨迹标注：

- critical failure step
- failure category
- supporting evidence

同时提出 AGENTRX 框架，通过约束合成、逐步验证和证据日志来定位关键失败步骤。

## 核心方法

1. **失败轨迹标注**: 人工标注失败 Agent run 中的关键失败步骤和失败类型。
2. **约束合成**: 从任务目标、执行上下文和轨迹中合成应该满足的约束。
3. **逐步约束验证**: 沿着 trace 检查每一步是否违反约束。
4. **证据日志**: 输出可审计的 constraint violation log。
5. **关键步骤定位**: 基于违反证据定位 critical failure step 和失败类型。

## 为什么对你的工作重要

这篇论文非常适合你说的 WorkState / 状态协议问题。

你的典型问题是：

```text
某个 Agent 少写了 WorkState 字段
↓
后续 Agent 基于缺失字段走了默认分支
↓
流程没有报错
↓
最终产物质量差
```

这正适合用 AgentRx 的思想来做：

```text
应该满足的状态约束
↓
每一步状态更新是否满足约束
↓
哪个步骤第一次违反约束
↓
该步骤是否导致后续流程偏离
```

## 可借鉴到 AgentLens 的设计

### 1. WorkState 约束检查

为每个阶段定义应满足的状态约束：

```json
{
  "after_design_stage": [
    "design_doc_exists",
    "requirements_mapped",
    "test_plan_required"
  ],
  "after_implementation_stage": [
    "files_modified",
    "test_command_recorded",
    "verification_status_updated"
  ]
}
```

然后在 trace 中检查：

```text
实际状态是否满足这些约束？
哪个字段缺失？
哪个字段值被错误覆盖？
哪个步骤之后状态开始不一致？
```

### 2. Constraint Violation Log

AgentLens 可以生成类似：

```text
Step 17: Planner claimed design completed
Expected: workstate.design.confirmed = true
Observed: field missing
Evidence: no write_state event, no design summary artifact
Impact: Executor skipped design validation branch
```

这比简单说“失败原因可能是 Planner”更有说服力。

### 3. 从“诊断结论”变成“证据链”

AgentLens 的诊断报告不应该只是自然语言猜测，而应该包含：

```text
结论
↓
违反的约束
↓
对应 trace 证据
↓
后续影响路径
```

## 局限

AgentRx 需要先定义或合成约束。对于开放式 Coding 任务，约束不一定天然存在。因此 AgentLens 可以先从工程规则开始：

- 是否读了必要文件
- 是否产生了必要 diff
- 是否执行了验证命令
- 是否更新了关键状态字段
- 是否存在 claim-evidence 对齐

## 引用

```bibtex
@article{barke2026agentrx,
  title={AgentRx: Diagnosing AI Agent Failures from Execution Trajectories},
  author={Barke, Shraddha and Goyal, Arnav and Khare, Alind and Singh, Avaljot and Nath, Suman and Bansal, Chetan},
  journal={arXiv preprint arXiv:2602.02475},
  year={2026}
}
```

## PDF链接

- 本地: [paper.pdf](paper.pdf)
- arXiv: https://arxiv.org/pdf/2602.02475
