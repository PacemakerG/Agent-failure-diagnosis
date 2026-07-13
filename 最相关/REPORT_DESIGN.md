# Agent 诊断报告设计规范

> 面向元析 Agent Teams 的结构化诊断报告

---

## 一、报告整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                     诊断报告                                  │
├─────────────────────────────────────────────────────────────┤
│ 1. 执行概览（一句话总结）                                      │
├─────────────────────────────────────────────────────────────┤
│ 2. 问题清单（分类列表）                                        │
│    ├─ 显式失败（工具报错）                                     │
│    ├─ 隐式失败（状态不一致）                                   │
│    └─ 流程异常（循环/超时）                                    │
├─────────────────────────────────────────────────────────────┤
│ 3. 问题详情（逐问题展开）                                      │
│    ├─ 问题描述                                                │
│    ├─ 归因分析（向前追溯）                                     │
│    │   ├─ 直接影响点                                          │
│    │   ├─ 间接影响链                                          │
│    │   └─ 根因定位                                            │
│    ├─ 证据链                                                  │
│    └─ 修复建议                                                │
├─────────────────────────────────────────────────────────────┤
│ 4. 时间线视图（可选）                                          │
│    └─ 问题点在时间轴上的位置                                   │
├─────────────────────────────────────────────────────────────┤
│ 5. 修复优先级                                                 │
└─────────────────────────────────────────────────────────────┘
```

---

## 二、问题分类体系

### 2.1 一级分类：按失败性质

| 分类 | 定义 | 典型场景 |
|------|------|----------|
| **显式失败** | 工具执行返回错误 | Bash 失败、Edit 失败、Agent 超时 |
| **隐式失败** | 工具成功但结果不符合预期 | 忘记更新 WorkState、虚假完成声明、数据流断裂 |
| **流程异常** | 流程执行偏离设计 | 循环次数超限、阶段阻塞、超时 |

### 2.2 二级分类：按影响范围

| 分类 | 定义 | 示例 |
|------|------|------|
| **单点问题** | 影响单个 Agent/工具 | coding-agent 的 Bash 命令失败 |
| **链式问题** | 影响下游依赖 | Read 失败导致后续 Edit 基于错误内容 |
| **全局问题** | 影响整个流程 | WorkState 未更新导致流程无法推进 |

### 2.3 三级分类：按根因类型

| 分类 | 根因 | 检测方法 |
|------|------|----------|
| **工具层** | 命令错误、参数错误、环境问题 | 工具返回值、错误信息 |
| **逻辑层** | 算法错误、理解偏差、幻觉 | 输入输出比对、行为-声明对比 |
| **流程层** | 状态更新遗漏、阶段跳过 | WorkState 变更检测、阶段完整性 |
| **协作层** | Agent 间信息传递失败 | 跨 Agent 数据依赖检测 |

---

## 三、归因分析设计（核心）

### 3.1 归因方向：向后影响 vs 向前追溯

```
向后影响（已有）          向前追溯（新增）
     │                        │
     ▼                        ▼
┌─────────┐              ┌─────────┐
│ 工具A失败 │              │ 工具C失败 │
└────┬────┘              └────┬────┘
     │                        │
     ▼                        ▼
┌─────────┐              ┌─────────┐
│ 影响工具B │              │ 归因工具B │
└────┬────┘              └────┬────┘
     │                        │
     ▼                        ▼
┌─────────┐              ┌─────────┐
│ 影响工具C │              │ 归因工具A │ ← 根因
└─────────┘              └─────────┘
```

### 3.2 归因分析模板

每个问题必须包含以下归因信息：

```yaml
problem:
  id: "P001"
  type: "显式失败"
  subtype: "Bash命令失败"
  location:
    agent: "coding-agent"
    phase: "coding_impl"
    tool_use_id: "tool_123"
    timestamp: "2026-07-09T10:30:00"
  
  # ========== 归因分析（核心）==========
  attribution:
    # 1. 直接影响（发生了什么）
    direct_effect:
      symptom: "pytest 命令返回 exit code 1"
      output_snippet: "FAILED test_example.py::test_func - AssertionError"
    
    # 2. 向后影响（影响了什么）
    downstream_impact:
      - type: "工具失败"
        affected: "deploy-agent 无法启动"
        reason: "测试失败导致构建中断"
      - type: "状态变更"
        affected: "work_status 标记为 failed"
        reason: "test_run 阶段失败"
    
    # 3. 向前追溯（为什么会这样）
    root_cause_trace:
      - level: 1
        type: "直接原因"
        description: "测试断言失败"
        evidence: "test_example.py line 42 assert a == b"
      
      - level: 2
        type: "间接原因"
        description: "修改代码时引入了错误"
        evidence: "coding-agent 在 Edit file.py 时修改了 test_func 依赖的逻辑"
        related_tool: "tool_118"  # Edit 操作
      
      - level: 3
        type: "根本原因"
        description: "缺乏修改后的验证"
        evidence: "Edit 后没有运行相关测试验证修改"
        related_pattern: "edit_verify_violation"
    
    # 4. 归因置信度
    confidence: 0.85
    confidence_reason: "基于工具依赖图和状态机模式检测"
  
  # ========== 证据链 ==========
  evidence_chain:
    - type: "工具调用记录"
      tool_use_id: "tool_123"
      content: "Bash(command='pytest')"
    - type: "错误输出"
      snippet: "FAILED test_example.py..."
    - type: "前置操作"
      tool_use_id: "tool_118"
      content: "Edit(file='example.py', ...)"
    - type: "模式违反"
      pattern: "edit_verify"
      description: "Edit 后 5 步内未执行测试"
  
  # ========== 修复建议 ==========
  remediation:
    immediate: "修复 example.py line 42 的断言失败"
    preventive: "在 Edit 后强制要求执行相关测试验证"
    automation: "添加 edit_verify 状态机检查规则"
```

---

## 四、报告模板设计

### 4.1 执行概览

```markdown
## 执行概览

本次流程共涉及 **5 个 Agent**，执行 **127 次工具调用**，
耗时 **45 分钟**，其中 **有效工作时间 32 分钟**，
发现 **3 个问题**（1 个显式，2 个隐式）。

**关键结论**：coding-agent 在实现阶段引入了测试失败的代码，
且未在修改后及时验证，导致进入测试-修复循环。
```

### 4.2 问题清单（分类视图）

```markdown
## 问题清单

### 显式失败（1）
| ID | 问题 | Agent | 阶段 | 严重程度 | 状态 |
|----|------|-------|------|----------|------|
| P001 | Bash: pytest 失败 | coding-agent | coding_impl | 🔴 High | 已定位 |

### 隐式失败（2）
| ID | 问题 | Agent | 阶段 | 严重程度 | 状态 |
|----|------|-------|------|----------|------|
| P002 | WorkState 未更新 | coding-agent | coding_finish | 🟡 Medium | 已定位 |
| P003 | 工具结果未被引用 | design-agent | design_tasks | 🟢 Low | 已定位 |

### 流程异常（0）
无
```

### 4.3 问题详情（单问题完整示例）

```markdown
## 问题详情

---

### P002: WorkState 状态遗漏更新

**基本信息**
- 问题类型：隐式失败 > 流程层
- 影响范围：全局（阻塞下游 Agent 触发）
- 发现时间：2026-07-09 10:45:00

#### 现象描述

coding-agent 声称已完成"接口契约实现"任务，
但未在 `work_status.md` 中标记对应任务为完成状态。

**Agent 原话**：
> "已完成接口契约实现，包括用户服务、订单服务的接口定义。"

**实际 WorkState**：
```yaml
# work_status.md (10:45:00 快照)
detailed_design:
  tasks:
    - name: "接口契约实现"
      status: "in_progress"  # ❌ 应为 completed
```

#### 归因分析

**直接影响**
- coding-agent 完成工作但未更新状态
- orchestrator 无法感知完成，未触发 deploy-agent

**向后影响链**
```
coding-agent 完成
    ↓
WorkState 未更新
    ↓
orchestrator 未收到完成信号
    ↓
deploy-agent 未触发
    ↓
流程阻塞 15 分钟（等待人工确认）
```

**向前追溯（根因定位）**

| 层级 | 原因类型 | 具体说明 | 证据 |
|------|----------|----------|------|
| 1 | 直接原因 | Agent 未执行 Edit(work_status.md) | 工具调用记录中无 WorkState 编辑 |
| 2 | 间接原因 | Agent 可能认为状态会自动更新 | 对话中未提及状态更新操作 |
| 3 | 根本原因 | 缺乏强制状态更新检查机制 | 流程设计未要求更新确认 |

**归因路径可视化**
```
[Claim: 任务完成] 
     │
     ├──► [Expected: WorkState更新] 
     │          │
     │          └──► [Missing: 无Edit操作] ◄── 根因
     │
     └──► [Actual: 状态未变更]
                │
                └──► [Impact: 流程阻塞]
```

#### 证据链

1. **Agent 完成声明**（10:44:30）
   - 来源：coding-agent message
   - 内容："已完成接口契约实现"

2. **工具调用记录**（10:44:30 - 10:45:00）
   - 最后操作：Edit(file="user_service.py")
   - 缺失操作：无 Edit(file="work_status.md")

3. **WorkState 变更记录**
   - 最后一次更新：10:30:00（由 design-agent 更新）
   - coding-agent 阶段：无更新记录

#### 修复建议

**立即修复**
```bash
# 手动更新 WorkState
Edit work_status.md:
  - status: "in_progress"
  + status: "completed"
```

**预防措施**
1. 在 coding-agent prompt 中明确要求：
   > "完成任务后必须更新 work_status.md 对应任务状态"

2. 添加自动化检查：
   ```python
   # 在每个 Agent 执行后检查
   if agent_claims_completion and not workstate_updated:
       alert("状态更新缺失")
   ```

**自动化改进**
- 添加 `workstate_update` 状态机模式检测规则
- 在 Agent 执行后自动验证状态一致性

---
```

### 4.4 时间线视图

```markdown
## 时间线视图

```
10:30:00 ├─ design-agent 更新 WorkState（正常）
         │
10:35:00 ├─ coding-agent 开始执行
         │
10:44:30 ├─ coding-agent 声称完成 ⚠️
         │
10:45:00 ├─ 【问题】WorkState 未更新 🔴 P002
         │
10:45:00 ├─ orchestrator 等待状态更新（阻塞）
         │
11:00:00 ├─ 人工介入确认
         │
11:05:00 └─ deploy-agent 触发（延迟 20 分钟）
```

关键节点：
- 🔴 P002: WorkState 未更新
- 🟡 P003: 工具结果未被引用（设计阶段）
```

### 4.5 修复优先级

```markdown
## 修复优先级

### P0（立即处理）
1. **P002 - WorkState 状态遗漏**
   - 原因：阻塞流程推进
   - 动作：手动更新 WorkState，修改 Agent prompt

### P1（本周处理）
2. **P001 - 测试失败**
   - 原因：代码质量问题
   - 动作：修复断言失败，添加 Edit 后验证

### P2（后续优化）
3. **P003 - 工具结果未引用**
   - 原因：效率问题
   - 动作：检查设计阶段工具调用必要性
```

---

## 五、向前归因算法设计

### 5.1 归因搜索策略

```python
def forward_attribution(
    problem_event: dict,
    tool_events: list[dict],
    dependency_graph: nx.DiGraph,
    max_depth: int = 3
) -> list[dict]:
    """
    向前归因：从问题点向前搜索可能的根因
    
    搜索维度：
    1. 数据依赖：哪个工具的输出被问题工具使用？
    2. 时序关联：问题发生前 N 步内发生了什么？
    3. 状态变更：相关的状态文件如何变化？
    4. 模式违反：是否违反了期望的执行模式？
    """
    
    attribution_path = []
    current = problem_event
    
    for depth in range(1, max_depth + 1):
        causes = []
        
        # 维度1: 数据依赖归因
        data_deps = find_data_dependencies(current, dependency_graph)
        for dep in data_deps:
            if is_suspicious(dep):
                causes.append({
                    "level": depth,
                    "type": "data_dependency",
                    "cause_event": dep,
                    "reason": f"{dep['tool_name']} 的输出被当前工具使用"
                })
        
        # 维度2: 时序关联归因
        temporal_events = find_temporal_predecessors(
            current, tool_events, window=5
        )
        for event in temporal_events:
            if is_anomalous(event):
                causes.append({
                    "level": depth,
                    "type": "temporal_association",
                    "cause_event": event,
                    "reason": f"时序上邻近的异常事件"
                })
        
        # 维度3: 状态变更归因
        state_changes = find_related_state_changes(current)
        for change in state_changes:
            if is_unexpected(change):
                causes.append({
                    "level": depth,
                    "type": "state_change",
                    "cause_event": change,
                    "reason": f"状态变更与期望不符"
                })
        
        # 维度4: 模式违反归因
        violations = find_pattern_violations(current)
        for v in violations:
            causes.append({
                "level": depth,
                "type": "pattern_violation",
                "violation": v,
                "reason": f"违反期望模式: {v['pattern']}"
            })
        
        attribution_path.extend(causes)
        
        # 继续向下一层归因
        if causes:
            current = select_most_likely_cause(causes)
        else:
            break
    
    return attribution_path


def is_suspicious(event: dict) -> bool:
    """判断事件是否可疑（可能是根因）"""
    return any([
        event.get("is_error"),
        event.get("duration_ms", 0) > 60000,  # 耗时过长
        "error" in event.get("content_summary", "").lower(),
        event.get("tool_name") == "Read" and "not found" in event.get("content_summary", "").lower()
    ])


def is_anomalous(event: dict) -> bool:
    """判断事件是否异常"""
    # 基于历史统计判断
    return event.get("is_error") or event.get("unusual_pattern", False)
```

### 5.2 归因置信度计算

```python
def calculate_attribution_confidence(
    attribution_path: list[dict],
    evidence_chain: list[dict]
) -> float:
    """
    计算归因结果的置信度
    
    因素：
    - 证据充分性：有多少直接证据支持
    - 路径一致性：归因路径是否逻辑自洽
    - 模式匹配度：是否符合已知失败模式
    """
    
    # 1. 证据充分性 (0-0.4)
    evidence_score = min(len(evidence_chain) * 0.1, 0.4)
    
    # 2. 路径一致性 (0-0.3)
    path_coherence = calculate_path_coherence(attribution_path)
    
    # 3. 模式匹配度 (0-0.3)
    pattern_match = max(
        (a.get("pattern_match_score", 0) for a in attribution_path),
        default=0
    )
    
    return evidence_score + path_coherence + pattern_match
```

---

## 六、报告生成流程

```python
def generate_diagnosis_report(
    session_data: dict,
    work_status_data: dict,
    flow_context: dict
) -> dict:
    """生成结构化诊断报告"""
    
    report = {
        "metadata": {
            "session_id": session_data["session_id"],
            "generated_at": datetime.now().isoformat(),
            "agent_count": len(session_data["agents"]),
            "tool_event_count": len(session_data["tool_events"])
        },
        
        "summary": generate_summary(session_data),
        
        "problems": {
            "explicit": [],   # 显式失败
            "implicit": [],   # 隐式失败
            "flow": []        # 流程异常
        },
        
        "timeline": generate_timeline_view(session_data),
        
        "priorities": []
    }
    
    # 1. 检测所有问题
    all_problems = detect_all_problems(session_data, work_status_data)
    
    # 2. 对每个问题进行归因分析
    for problem in all_problems:
        # 归因分析
        problem["attribution"] = forward_attribution(
            problem["event"],
            session_data["tool_events"],
            session_data["dependency_graph"]
        )
        
        # 证据链构建
        problem["evidence_chain"] = build_evidence_chain(problem)
        
        # 分类放入报告
        category = classify_problem(problem)
        report["problems"][category].append(problem)
    
    # 3. 计算修复优先级
    report["priorities"] = calculate_remediation_priority(
        report["problems"]
    )
    
    return report
```

---

## 七、总结

### 报告核心设计原则

| 原则 | 说明 |
|------|------|
| **分类清晰** | 显式/隐式/流程，一级二级三级分类 |
| **归因向前** | 从问题点向前追溯，定位根因 |
| **证据可验证** | 每个结论都有工具调用记录支持 |
| **修复可执行** | 立即/预防/自动化三层建议 |
| **优先级明确** | P0/P1/P2 分级，指导处理顺序 |

### 与元析整合的关键点

1. **WorkState 解析**：解析 `work_status.md` 的状态变更
2. **Agent 识别**：识别不同 Agent 的 session 片段
3. **Hook 触发**：在 orchestrator 关键点触发诊断
4. **报告反馈**：诊断结果写入 `diagnosis_report.md`

---

*文档版本: 1.0*
*创建日期: 2026-07-09*
