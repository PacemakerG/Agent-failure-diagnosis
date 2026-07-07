# AgentTrace: Causal Graph Tracing for Root Cause Analysis in Deployed Multi-Agent Systems

## 基本信息

- **年份**: 2026
- **arXiv ID**: 2603.14688
- **作者**: Zhaohui Geoffrey Wang
- **当前优先级**: P2 相关，适合显性错误根因追踪

## 核心贡献

AgentTrace 是一个轻量级因果追踪框架，用于部署后多 Agent 工作流的失败诊断。它从执行日志中重建因果图，并从最终错误节点反向追踪根因。

它的优势是：

- 不需要 LLM 推理即可排序根因；
- 利用结构和位置信号进行高效诊断；
- 适合有明确错误节点的场景；
- 可作为工具依赖图和错误传播链的参考。

## 核心方法

1. **因果图重建**: 从执行日志中重建工具调用之间的因果关系。
2. **反向追踪算法**: 从最终错误节点反向追溯到根因。
3. **结构和位置信号**: 使用可解释信号，而非 LLM，进行根因排序。
4. **轻量级部署**: 无需重放，直接分析已部署系统日志。

## 为什么不是当前最优先

这篇论文对传统失败诊断很有价值，但它更适合：

```text
工具调用失败
测试失败
编译失败
异常节点明确
最终错误节点清楚
```

而你现在更关心的是：

```text
流程正常跑完
没有显性错误节点
中间状态字段缺失
后续流程悄悄跳过
最终产物不理想
```

这种 silent failure 通常没有明确的“最终错误节点”，所以单纯的因果图反向追踪不够。

## 可借鉴到 AgentLens 的设计

### 1. 工具依赖图

AgentLens 仍然可以借鉴它的图结构：

```text
read file
↓
edit file
↓
run test
↓
update state
↓
final response
```

### 2. 影响路径展示

当检测到一个隐性症状后，例如 `WorkState.test_required missing`，可以沿依赖图展示影响路径：

```text
Planner missing state field
↓
Executor skipped verification branch
↓
Final answer claimed completed without test evidence
```

### 3. 和 AgentRx / ErrorProbe 结合

更适合的组合是：

```text
AgentRx / ErrorProbe 发现症状
↓
AgentTrace Causal Graph 展示传播路径
```

## 局限

AgentTrace 偏向“从显性错误节点出发反向追踪”。对于没有 exception、没有 test failure、没有失败 API 的场景，需要额外引入 PROTEA、REFLECT、False Success、AgentRx 等方法。

## 引用

```bibtex
@article{wang2026agenttrace,
  title={AgentTrace: Causal Graph Tracing for Root Cause Analysis in Deployed Multi-Agent Systems},
  author={Wang, Zhaohui Geoffrey},
  journal={arXiv preprint arXiv:2603.14688},
  year={2026}
}
```

## PDF链接

- 本地: [paper.pdf](paper.pdf)
- arXiv: https://arxiv.org/pdf/2603.14688
