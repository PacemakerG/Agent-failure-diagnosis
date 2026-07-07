# TrajAD: Trajectory Anomaly Detection for Trustworthy LLM Agents

## 基本信息

- **年份**: 2026
- **arXiv ID**: 2602.06443
- **作者**: Yibing Liu, Chong Zhang, Zhongyi Han, Hansong Liu, Yong Wang, Yang Yu, Xiaoyan Wang, Yilong Yin
- **当前优先级**: P1 高度相关

## 核心贡献

TrajAD 将 LLM Agent 的可靠性问题定义为 **Trajectory Anomaly Detection**：不是只看输入输出是否安全，也不是只看最终答案是否正确，而是审计中间执行过程是否出现异常。

它强调：

> 诊断 Agent 不能只判断“有没有失败”，还要定位“哪一步开始异常”。

这和 AgentLens 的目标高度一致：从 Session / Task / Step 级 trace 中定位异常过程。

## 核心方法

1. **轨迹异常检测定义**: 将 Agent 执行过程视为一条 trajectory，目标是检测并定位异常步骤。
2. **TrajBench**: 通过 perturb-and-complete 策略构造带过程异常的数据集。
3. **过程监督**: 不只监督最终结果，而是给中间步骤提供细粒度监督。
4. **专用 verifier**: 训练专门的异常检测 verifier，而不是直接依赖通用 LLM zero-shot 判断。
5. **异常定位**: 重点是定位异常发生的步骤，为 rollback-and-retry 提供基础。

## 为什么对你的工作重要

你关心的问题不是：

```text
程序有没有报错？
```

而是：

```text
执行路径有没有偏？
哪个中间步骤开始不对？
哪个状态更新导致后续流程跳过？
```

这正是 TrajAD 的问题设定。

## 可借鉴到 AgentLens 的设计

### 1. Trace Anomaly Score

给每个 Step / Turn 打一个异常分：

```text
是否缺少预期动作？
是否跳过关键阶段？
是否出现无效动作？
是否和上一步目标不连续？
是否产生异常状态迁移？
```

### 2. Perturbation Dataset

AgentLens 可以从真实 trace 构造训练/评测数据：

```text
正常 trace
↓
人为删除一个关键 read/test/state-update 步骤
↓
得到异常 trace
↓
训练模型定位异常点
```

这对 Dataset Builder 很有价值。

### 3. Rollback-and-Retry 基础

一旦能定位异常步骤，后续就可以做：

```text
回滚到异常步骤前
重新规划
重新执行
对比结果
```

## 与 WorkState 隐性错误的关系

WorkState 少字段本质上是一种 trajectory anomaly：

```text
状态应该从 S1 → S2
实际变成 S1 → S2'
S2' 没有报错，但缺少关键字段
后续路径从正常分支进入错误分支
```

TrajAD 可以作为这类问题的过程异常检测参考。

## 引用

```bibtex
@article{liu2026trajAD,
  title={TrajAD: Trajectory Anomaly Detection for Trustworthy LLM Agents},
  author={Liu, Yibing and Zhang, Chong and Han, Zhongyi and Liu, Hansong and Wang, Yong and Yu, Yang and Wang, Xiaoyan and Yin, Yilong},
  journal={arXiv preprint arXiv:2602.06443},
  year={2026}
}
```

## PDF链接

- 本地: [paper.pdf](paper.pdf)
- arXiv: https://arxiv.org/pdf/2602.06443
