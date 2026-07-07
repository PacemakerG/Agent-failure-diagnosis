# PROTEA: Offline Evaluation and Iterative Refinement for Multi-Agent LLM Workflows

## 基本信息

- **年份**: 2026
- **arXiv ID**: 2605.18032
- **作者**: Kazuki Kawamura, Satoshi Waki, Kei Tateno
- **当前优先级**: P0 最相关，建议优先阅读第 1 篇

## 核心贡献

PROTEA 为多 Agent LLM 工作流提供离线评估和迭代改进框架。它最重要的点不是“最终结果错了以后找报错”，而是：

> **对中间节点输出进行评分，并从最终答案反推节点级期望。**

这非常适合诊断隐性失败：流程没有报错，代码也能跑，但某个中间状态或中间产物已经偏离预期，最终导致产物质量下降。

## 核心方法

1. **离线评估**: 不一定重新执行 Agent，也能基于已有 trace / workflow 数据进行分析。
2. **测试驱动改进**: 类似单元测试一样为多 Agent workflow 建立评估标准。
3. **中间输出评分**: 不只看最终答案，而是评估每个节点产物质量。
4. **工作流图可视化**: 在 workflow graph 上叠加评分和瓶颈信息。
5. **节点级期望生成**: 从最终答案或目标反推每个中间节点应该产出什么。
6. **提示修订与重评估**: 根据节点问题定位后进行有针对性的 prompt / workflow 改进。

## 为什么对你的工作最重要

你关心的问题是：

```text
某个 Agent 少写了 WorkState 字段
↓
后续 Agent 仍然正常执行
↓
流程没有报错
↓
最终产物交付不理想
```

这不是传统编译错误，也不是工具调用异常，而是 **中间节点输出不满足期望**。

PROTEA 的思想可以直接迁移成：

```text
Task 目标
↓
阶段级期望
↓
WorkState / Artifact / Tool Evidence 检查
↓
中间节点评分
↓
定位第一个不满足期望的步骤
```

## 可借鉴到 AgentLens 的设计

### 1. Intermediate Output Scoring

对每个阶段产物打分：

```text
需求理解是否完整？
设计是否覆盖关键约束？
WorkState 是否包含必要字段？
代码修改是否覆盖目标文件？
验证命令是否真实执行？
```

### 2. Node-Level Expectation

为每个阶段生成“应该产出什么”：

```json
{
  "planning": ["明确目标", "列出关键文件", "定义验证方式"],
  "implementation": ["修改目标文件", "更新状态字段", "保留 diff 证据"],
  "verification": ["执行测试", "记录结果", "失败时回到修复"]
}
```

### 3. Workflow Bottleneck View

在 AgentLens Viewer 中可以展示：

```text
Plan ✅
Design ⚠️ WorkState missing field: test_required
Implementation ✅
Verification ❌ skipped because test_required missing
```

## 局限

PROTEA 更偏离线评估和 workflow 改进，不是完整的实时监控系统。AgentLens 可以先借鉴它的节点期望和中间产物评分，不一定完全复现其全部迭代框架。

## 引用

```bibtex
@article{kawamura2026protea,
  title={PROTEA: Offline Evaluation and Iterative Refinement for Multi-Agent LLM Workflows},
  author={Kawamura, Kazuki and Waki, Satoshi and Tateno, Kei},
  journal={arXiv preprint arXiv:2605.18032},
  year={2026}
}
```

## PDF链接

- 本地: [paper.pdf](paper.pdf)
- arXiv: https://arxiv.org/pdf/2605.18032
