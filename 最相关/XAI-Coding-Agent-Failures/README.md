# XAI for Coding Agent Failures: Transforming Raw Execution Traces into Actionable Insights

## 基本信息

- **年份**: 2026
- **arXiv ID**: 2603.05941
- **作者**: Arun Joshi
- **当前优先级**: P2 相关，适合报告展示和解释层

## 核心贡献

该研究提出一个可解释 AI 框架，目标是把原始 Agent 执行 trace 转化为结构化、可理解、可行动的解释。

它的核心组件包括：

1. **领域特定失败分类法**
2. **自动注释系统**
3. **混合解释生成器**
4. **可视化流程 + 自然语言洞察**

## 核心价值

这篇论文最适合回答：

```text
诊断结果怎么展示给用户？
如何把复杂 trace 变成可读报告？
如何让用户更快理解失败原因？
```

它对 AgentLens 的 **Analysis Report / Diagnostics UI / 可视化解释** 很有价值。

## 为什么不是当前核心算法

这篇论文更偏“解释层”和“报告层”，不是专门解决：

```text
WorkState 少字段
流程跳步
Agent 声称完成但无证据
trace 正常完成但结果错误
```

所以它不应该作为隐性失败诊断的第一梯队，而应该放在诊断结果展示阶段。

## 可借鉴到 AgentLens 的设计

### 1. Trace Annotation

对 trace 自动标注：

```text
关键工具调用
关键文件修改
无证据声明
状态字段变更
验证缺失
疑似目标漂移
```

### 2. Hybrid Explanation

诊断报告不要只有文字，也要包含结构化流程：

```text
Step 12: Planner claimed test plan complete
Step 13: WorkState missing test_required
Step 18: Executor skipped verification
Step 24: Final answer claimed completed
```

### 3. 用户可行动建议

报告应该给出：

```text
问题是什么
证据在哪里
影响路径是什么
建议怎么修
```

## 和其他论文的关系

推荐组合：

```text
PROTEA / AgentRx / ErrorProbe 负责发现问题
XAI 负责把问题讲清楚
```

## 引用

```bibtex
@article{joshi2026xai,
  title={XAI for Coding Agent Failures: Transforming Raw Execution Traces into Actionable Insights},
  author={Joshi, Arun},
  journal={arXiv preprint arXiv:2603.05941},
  year={2026}
}
```

## PDF链接

- 本地: [paper.pdf](paper.pdf)
- arXiv: https://arxiv.org/pdf/2603.05941
