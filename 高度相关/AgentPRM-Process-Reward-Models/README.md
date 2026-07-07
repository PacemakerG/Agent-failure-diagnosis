# AgentPRM: Process Reward Models for LLM Agents via Step-Wise Promise and Progress

## 基本信息

- **年份**: 2025
- **arXiv ID**: 2511.08325
- **作者**: Zhiheng Xi, Chenyang Liao, Guanyu Li, Yajie Yang, Wenxiang Chen, Zhihao Zhang, Binghai Wang, Senjie Jin, Yuhao Zhou, Jian Guan, Wei Wu, Tao Ji, Tao Gui, Qi Zhang, Xuanjing Huang
- **当前优先级**: P1 高度相关

## 核心贡献

AgentPRM 将 Agent 的过程评估从“每一步是否绝对正确”转成“每一步是否推动任务接近目标”。

这点很重要，因为 Agent 任务里的动作通常不是简单对错：

```text
读一个文件不一定错
改一个字段不一定错
跳过一个步骤也不一定马上错
```

真正要判断的是：

```text
这个动作有没有让任务更接近最终目标？
这个动作有没有让后续状态更可靠？
这个动作是不是在原地打转或偏离目标？
```

## 核心方法

1. **Agent Process Reward Model**: 为 Agent 每一步决策建模过程奖励。
2. **Promise and Progress**: 关注动作对目标的承诺和实际推进程度。
3. **序列依赖建模**: 不孤立评估单步动作，而是考虑前后决策关系。
4. **目标接近度评估**: 动作不按简单对错评估，而按对最终目标的贡献评估。
5. **用于 test-time compute 和 RL**: 可用于搜索、重排、训练和过程监督。

## 为什么对你的工作重要

你关心的隐性错误通常不是某一步“明显错了”，而是：

```text
每一步看起来都合理
但整体没有持续推进目标
中间某一步开始偏离
最终产物不理想
```

AgentPRM 给了一个很好的视角：

> 对每一步打“目标推进分”，而不是只看最终成功/失败。

## 可借鉴到 AgentLens 的设计

### 1. Step Progress Score

AgentLens 可以给每个 Step / Turn 生成过程评分：

```text
+1: 明确推进目标
 0: 中性动作，信息收集或上下文整理
-1: 偏离目标、无证据声明、跳过关键步骤、污染状态
```

### 2. Goal Drift 检测

如果后续步骤的 progress score 连续下降，可以标记：

```text
Goal Drift
```

例如：

```text
原目标：修复登录 bug
实际过程：大范围重构 UI、修改无关模块、没有验证登录流程
```

### 3. 和 Dataset Builder 衔接

AgentLens 未来可以从真实任务中导出：

```json
{
  "step": "run pytest",
  "progress_label": "positive",
  "reason": "验证修改是否满足任务目标"
}
```

这种数据可以服务后续 AgentPRM / reward model / RL 训练。

## 与 WorkState 隐性错误的关系

WorkState 少字段本身可以被看作一个负向过程信号：

```text
状态更新动作没有完成对后续流程必要的信息承诺
导致后续 Agent 无法正确推进目标
```

因此 AgentPRM 适合作为“过程质量评分”的理论参考，而不是直接的错误归因算法。

## 引用

```bibtex
@article{xi2025agentprm,
  title={AgentPRM: Process Reward Models for LLM Agents via Step-Wise Promise and Progress},
  author={Xi, Zhiheng and Liao, Chenyang and Li, Guanyu and Yang, Yajie and Chen, Wenxiang and Zhang, Zhihao and Wang, Binghai and Jin, Senjie and Zhou, Yuhao and Guan, Jian and Wu, Wei and Ji, Tao and Gui, Tao and Zhang, Qi and Huang, Xuanjing},
  journal={arXiv preprint arXiv:2511.08325},
  year={2025}
}
```

## PDF链接

- 本地: [paper.pdf](paper.pdf)
- arXiv: https://arxiv.org/pdf/2511.08325
