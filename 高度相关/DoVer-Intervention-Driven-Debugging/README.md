# DoVer: Intervention-Driven Auto Debugging for LLM Multi-Agent Systems

## 基本信息

- **年份**: 2025
- **arXiv ID**: 2512.06749
- **作者**: Ming Ma, Jue Zhang, Fangkai Yang, Yu Kang, Qingwei Lin, Saravan Rajmohan, Dongmei Zhang
- **当前优先级**: P1 高度相关，建议优先阅读第 10 篇

## 核心贡献

DoVer 的核心思想是：

> 诊断不能只停留在“猜测失败原因”，还要通过有针对性的干预来验证这个假设是否真的能改善任务结果。

它关注的不只是归因是否看起来合理，而是干预后系统是否真的更接近成功。

## 核心方法

1. **假设生成**: 根据观察到的失败现象生成失败假设。
2. **主动干预验证**: 对可疑位置进行定向干预，而不是被动观察 trace。
3. **效果评估**: 判断干预后任务是否成功，或是否有可量化进展。
4. **闭环调试**: 根据干预结果继续修正诊断和修复策略。

## 为什么对你的工作重要

对 AgentLens 来说，短期重点是诊断：

```text
发现问题
定位证据
解释影响路径
```

但中长期一定会走向：

```text
诊断
↓
提出修复建议
↓
验证建议是否有效
↓
沉淀经验
```

DoVer 正好是从“诊断系统”走向“自动修复闭环”的参考。

## 可借鉴到 AgentLens 的设计

### 1. Diagnosis Hypothesis

例如系统发现：

```text
WorkState.test_required 缺失导致验证阶段跳过
```

可以生成假设：

```text
如果 Planner 在设计阶段写入 test_required=true，Executor 应该不会跳过验证阶段。
```

### 2. Intervention Plan

干预方式可以是：

```text
补充状态字段
修改 prompt
强制验证阶段执行
回滚到某个 Step 前重新执行
```

### 3. Validation Result

诊断报告应该区分：

```text
未验证猜测
已被证据支持
已被干预验证
```

这会显著提升诊断可信度。

## 局限

DoVer 依赖重新执行或局部干预。对 Claude Code / Codex / OpenCode 真实日志来说，短期可能很难完整 replay。AgentLens 可以先实现“建议级干预”，后续再接入可重放实验环境。

## 引用

```bibtex
@article{ma2025dover,
  title={DoVer: Intervention-Driven Auto Debugging for LLM Multi-Agent Systems},
  author={Ma, Ming and Zhang, Jue and Yang, Fangkai and Kang, Yu and Lin, Qingwei and Rajmohan, Saravan and Zhang, Dongmei},
  journal={arXiv preprint arXiv:2512.06749},
  year={2025}
}
```

## PDF链接

- 本地: [paper.pdf](paper.pdf)
- arXiv: https://arxiv.org/pdf/2512.06749
