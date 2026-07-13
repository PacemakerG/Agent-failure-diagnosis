# Agent 日志诊断系统改进方案

> 基于学术方法论的失败定位与根因分析改进计划

---

## 一、当前系统诊断

### 1.1 现有架构（core.py）

| 模块 | 功能 | 局限 |
|------|------|------|
| `extract_tool_events` | 工具 use/result 配对 | 孤立事件，无因果关系 |
| `build_phases` | 按 Skill 分阶段 | 阶段内无细粒度状态追踪 |
| `rule_findings` | 规则检测（耗时、错误、高频） | 只有"量"的检测，无"模式"深度分析 |
| `build_context` | 阶段耗时表、慢工具、subagent 摘要 | 信息平铺，无层次结构 |

### 1.2 核心问题

1. **工具调用孤立**：不知道工具 B 的输入是否依赖工具 A 的输出
2. **错误传播不可见**：工具 A 失败后，哪些工具 B、C、D 受其影响
3. **状态变更未追踪**：Edit 后是否 Verify，Bash 后是否 Check
4. **长程偏离未检测**：第 10 步的结果是否偏离第 1 步设定的目标

---

## 二、失败类型分类

### 2.1 显式失败（Explicit Failures）

**特征**：工具调用返回 `is_error=true`，错误信息明确

**示例**：
- Bash 命令返回非零退出码
- Edit 文件时路径不存在
- Agent 调用超时

**检测难度**：⭐ 容易（已有）

### 2.2 隐式失败（Implicit Failures）

**特征**：工具调用表面成功，但执行结果与期望不一致

**典型场景**：

| 场景 | 现象 | 后果 |
|------|------|------|
| **WorkState 遗漏更新** | Agent 完成任务但未在 WorkState.md 打勾 | 下游 Agent 未触发，任务流程断裂 |
| **任务声称完成但实际未做** | Agent 报告"已完成"，但产物缺失 | 中间产物缺失，后续步骤基于错误假设执行 |
| **状态读取错误** | Agent 读取 WorkState 时理解错误 | 执行了错误的任务分支 |
| **数据流断裂** | 工具 A 产出文件 X，工具 B 读取文件 Y（期望读X） | 基于过时/错误数据执行 |
| **静默跳过** | Agent 遇到异常后继续执行，未正确处理 | 部分逻辑未执行，结果不完整 |

**检测难度**：⭐⭐⭐⭐ 困难（需要语义理解）

---

## 三、改进方案概述

借鉴学术界 Agent 诊断方法论的五个核心改进：

| 改进项 | 借鉴论文 | 解决什么问题 |
|--------|----------|--------------|
| **工具依赖图构建** | AgentTrace (Causal Graph) | 识别工具间的数据依赖关系 |
| **错误传播分析** | TraceCoder (因果分析) | 定位显式错误如何在工具链中传播 |
| **状态一致性检测** | Process Mining + 自定义 | 检测 WorkState 等中心状态的一致性问题 |
| **任务完成验证** | 形式化验证思想 | 验证"声称完成" vs "实际证据" |
| **分层根因分析** | ErrorProbe (三阶段流水线) | 结构化诊断：症状→根因→修复 |

---

## 四、改进1：工具依赖图构建（显式+隐式依赖）

### 3.1 核心思想

通过内容匹配识别工具间的数据依赖。例如：
- `Read(file.py)` → `Edit(file.py)` : 编辑依赖读取的内容
- `Bash(grep "function_name")` → `Edit(file.py)` : 编辑依赖 grep 找到的函数名
- `Read(file.py)` → `Bash(grep "pattern" file.py)` : grep 依赖读取的文件路径

### 3.2 实现方案

```python
# dependency_graph.py

def build_dependency_graph(tool_events: list[dict]) -> dict:
    """
    识别工具间的数据依赖关系
    
    依赖类型：
    - file_dependency: 文件路径匹配
    - content_dependency: 内容片段匹配
    - temporal_dependency: 时序邻近（弱依赖）
    """
    dependencies = []
    
    for i, later in enumerate(tool_events):
        for earlier in tool_events[:i]:
            dep_type = infer_dependency_type(earlier, later)
            if dep_type:
                dependencies.append({
                    "from": earlier["tool_use_id"],
                    "to": later["tool_use_id"],
                    "type": dep_type,
                    "confidence": calculate_confidence(earlier, later, dep_type)
                })
    
    return {
        "nodes": [{"id": e["tool_use_id"], **e} for e in tool_events],
        "edges": dependencies
    }


def infer_dependency_type(earlier: dict, later: dict) -> str | None:
    """推断依赖类型"""
    earlier_output = earlier.get("content_summary", "")
    later_input = later.get("input_summary", "")
    
    # 1. 文件路径匹配
    if earlier.get("tool_name") == "Read":
        file_path = extract_file_path(earlier.get("input", {}))
        if file_path and file_path in later_input:
            return "file_dependency"
    
    # 2. 内容片段匹配（函数名、类名、变量名）
    key_fragments = extract_key_fragments(earlier_output)
    for fragment in key_fragments:
        if fragment in later_input:
            return "content_dependency"
    
    # 3. 时序邻近 + 工具类型关联（弱依赖）
    if is_temporally_close(earlier, later) and has_tool_type_relation(earlier, later):
        return "temporal_dependency"
    
    return None


def extract_key_fragments(content: str) -> list[str]:
    """从内容中提取关键片段用于依赖匹配"""
    fragments = []
    
    # 文件路径
    fragments.extend(re.findall(r'[\w/\-.]+\.(py|js|ts|java|go|rs|cpp|c|h)', content))
    
    # 函数名 (def function_name)
    fragments.extend(re.findall(r'def\s+(\w+)', content))
    
    # 类名 (class ClassName)
    fragments.extend(re.findall(r'class\s+(\w+)', content))
    
    # 特定输出标记
    if "Error" in content or "Exception" in content:
        fragments.append("error_occurred")
    
    return fragments
```

### 3.3 失败定位价值

1. **正向追踪**：当工具 X 失败，找出"哪些工具依赖 X 的结果"（受影响范围）
2. **反向追踪**：当最终结果错误，回溯"哪些工具链导致了这个结果"
3. **孤立检测**：识别"被调用但结果未被使用"的工具（可能的无用调用）

---

## 五、改进2：错误传播分析（显式失败）

### 4.1 核心思想

识别错误如何在工具链中传播：
- 工具 A 出错 → 工具 B 使用 A 的结果 → B 也出错（错误传播）
- 工具 A 出错 → 工具 C 没有使用 A 的结果 → C 正常（孤立错误）

### 4.2 实现方案

```python
def detect_error_propagation(tool_events: list[dict], 
                             dependencies: list[dict]) -> list[dict]:
    """
    检测错误传播链
    
    传播模式：
    - direct_propagation: 直接依赖导致错误传播
    - cascade_failure: 级联失败（多个依赖点依次失败）
    - independent_failure: 独立失败（非传播导致）
    """
    
    # 构建依赖图
    graph = build_graph(dependencies)
    
    error_events = [e for e in tool_events if e.get("is_error")]
    propagation_chains = []
    
    for error in error_events:
        # 向前追溯：这个错误影响了哪些后续工具？
        affected = find_affected_tools_bfs(graph, error, tool_events)
        
        if len(affected) >= 2:  # 影响了2个以上工具
            propagation_chains.append({
                "type": "error_propagation",
                "root_cause_tool": {
                    "id": error["tool_use_id"],
                    "name": error.get("tool_name"),
                    "error_summary": error.get("content_summary", "")[:200]
                },
                "affected_tools": [
                    {
                        "id": a["tool_use_id"],
                        "name": a.get("tool_name"),
                        "error_summary": a.get("content_summary", "")[:200]
                    }
                    for a in affected
                ],
                "chain_length": len(affected) + 1,
                "propagation_path": extract_propagation_path(graph, error, affected)
            })
    
    return propagation_chains


def find_affected_tools_bfs(graph: nx.DiGraph, 
                            root_error: dict,
                            tool_events: list[dict]) -> list[dict]:
    """BFS遍历找出所有受根因错误影响的工具"""
    root_id = root_error["tool_use_id"]
    affected = []
    
    # BFS遍历依赖图
    queue = [root_id]
    visited = {root_id}
    
    while queue:
        current = queue.pop(0)
        
        # 找出依赖 current 的所有工具
        for neighbor in graph.successors(current):
            if neighbor not in visited:
                visited.add(neighbor)
                neighbor_event = find_event_by_id(neighbor, tool_events)
                
                # 如果该工具也失败了，加入传播链
                if neighbor_event and neighbor_event.get("is_error"):
                    affected.append(neighbor_event)
                    queue.append(neighbor)
    
    return affected
```

### 4.3 规则层集成

```python
def rule_findings(phases, tool_events):
    findings = []
    
    # ... 现有规则 ...
    
    # 新增：错误传播检测
    dependencies = build_dependency_graph(tool_events)
    propagation_chains = detect_error_propagation(tool_events, dependencies)
    
    for chain in propagation_chains:
        root = chain["root_cause_tool"]
        affected_count = len(chain["affected_tools"])
        
        findings.append({
            "level": "high",
            "title": f"错误传播链：{root['name']}",
            "detail": f"根因工具失败导致 {affected_count} 个后续工具出错，链长度 {chain['chain_length']}",
            "chain": chain,
            "phase_id": find_phase_for_tool(root["id"], phases)
        })
    
    return findings
```

---

## 六、改进3：隐式失败检测（核心新增）

### 6.1 核心思想

**问题本质**：Agent 执行了动作但未正确更新状态，或声称完成但实际未产生预期效果。

**检测策略**：
1. **WorkState 一致性检查**：期望状态 vs 实际状态
2. **任务完成验证**：声称产出 vs 实际产物
3. **数据流完整性**：中间产物是否生成且被正确使用
4. **行为-声明一致性**：Agent 说做了什么 vs 实际做了什么

### 6.2 WorkState 状态一致性检测

针对中心状态文档（如 WorkState.md）的模式：

```python
# implicit_failure_detection.py

def detect_workstate_inconsistency(
    tool_events: list[dict],
    main_entries: list[dict]
) -> list[dict]:
    """
    检测 WorkState 状态不一致问题
    
    模式：
    1. Agent 声称完成某任务（在对话中）但未更新 WorkState
    2. Agent 更新了 WorkState 但对应任务实际上未完成
    3. Agent 读取 WorkState 后执行了与当前状态不匹配的任务
    """
    inconsistencies = []
    
    # 1. 提取所有 WorkState 相关事件
    workstate_reads = extract_workstate_reads(tool_events)   # Read(WorkState.md)
    workstate_edits = extract_workstate_edits(tool_events)   # Edit(WorkState.md)
    
    # 2. 解析 WorkState 内容变化
    state_transitions = parse_state_transitions(workstate_edits)
    
    # 3. 检测"声称完成但未更新"模式
    for agent_completion in find_agent_completion_claims(main_entries):
        task_id = agent_completion["task_id"]
        completion_time = agent_completion["timestamp"]
        
        # 检查后续是否有对应的 WorkState 更新
        subsequent_updates = [
            e for e in workstate_edits 
            if e["started_at"] > completion_time
            and task_id in e.get("content_summary", "")
        ]
        
        if not subsequent_updates:
            inconsistencies.append({
                "type": "completion_without_state_update",
                "severity": "high",
                "task_id": task_id,
                "agent_id": agent_completion["agent_id"],
                "description": f"Agent 声称完成任务 {task_id} 但未更新 WorkState",
                "consequence": "下游 Agent 可能未触发，导致任务流程断裂",
                "evidence": {
                    "completion_claim": agent_completion["message"],
                    "expected_state_change": f"应在 WorkState 中标记 {task_id} 为完成",
                    "actual_state_change": "未检测到 WorkState 更新"
                }
            })
    
    # 4. 检测"更新了状态但未实际完成"模式
    for state_update in state_transitions:
        task_id = state_update["task_id"]
        new_status = state_update["new_status"]  # "done", "completed", "✓"
        
        if new_status in ["done", "completed", "✓", "x"]:
            # 反向检查该任务是否有实际执行证据
            execution_evidence = find_task_execution_evidence(
                tool_events, task_id, before_time=state_update["timestamp"]
            )
            
            if not execution_evidence:
                inconsistencies.append({
                    "type": "state_update_without_execution",
                    "severity": "medium",
                    "task_id": task_id,
                    "description": f"WorkState 标记 {task_id} 为完成，但未找到实际执行证据",
                    "consequence": "可能产生虚假进度，后续步骤基于未完成的假设",
                    "evidence": {
                        "state_change": state_update["diff"],
                        "expected_evidence": f"应有对应 {task_id} 的执行记录",
                        "actual_evidence": "未找到相关工具调用"
                    }
                })
    
    return inconsistencies


def parse_state_transitions(workstate_edits: list[dict]) -> list[dict]:
    """解析 WorkState.md 的编辑历史，提取状态变更"""
    transitions = []
    
    for edit in workstate_edits:
        # 解析 diff，识别哪些任务状态发生了变化
        diff = edit.get("content_summary", "")
        
        # 模式1: - [ ] Task A → + [x] Task A
        completed_tasks = re.findall(r'\-\s*\[\s*\]\s*(.+?)\s*\n\+\s*\[[xX✓]\]\s*\1', diff)
        for task in completed_tasks:
            transitions.append({
                "task_id": task.strip(),
                "old_status": "pending",
                "new_status": "done",
                "timestamp": edit.get("started_at"),
                "agent_id": edit.get("agent_id"),
                "diff": diff[:500]
            })
        
        # 模式2: 识别新增的任务项
        new_tasks = re.findall(r'\+\s*\[\s*\]\s*(.+)', diff)
        for task in new_tasks:
            transitions.append({
                "task_id": task.strip(),
                "old_status": None,
                "new_status": "added",
                "timestamp": edit.get("started_at"),
                "agent_id": edit.get("agent_id")
            })
    
    return transitions


def find_agent_completion_claims(main_entries: list[dict]) -> list[dict]:
    """从对话中提取 Agent 声称完成任务的声明"""
    claims = []
    
    for entry in main_entries:
        if entry.get("type") != "assistant":
            continue
        
        content = entry.get("content", "")
        
        # 匹配完成声明的模式
        completion_patterns = [
            r'已完成\s*[任务]?\s*[:：]\s*(.+?)(?:\n|$)',
            r'任务\s*(.+?)\s*已?完成',
            r'完成\s*[了]?\s*(.+?)(?:任务)?',
            r'done[:：]\s*(.+?)(?:\n|$)',
            r'completed[:：]\s*(.+?)(?:\n|$)',
        ]
        
        for pattern in completion_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            for match in matches:
                claims.append({
                    "task_id": match.strip(),
                    "timestamp": entry.get("timestamp"),
                    "agent_id": entry.get("agent_id", "main"),
                    "message": content[:200]
                })
    
    return claims
```

### 6.3 任务完成验证（声称 vs 实际）

```python
def verify_task_completion(
    task_id: str,
    completion_claim: dict,
    tool_events: list[dict]
) -> dict:
    """
    验证任务声称完成 vs 实际产物
    
    检查维度：
    1. 文件产物：声称生成的文件是否真实存在
    2. 代码变更：声称的修改是否在代码中体现
    3. 测试执行：声称的测试是否实际运行
    4. 副作用：是否有其他预期的副作用发生
    """
    
    verification = {
        "task_id": task_id,
        "claimed_by": completion_claim["agent_id"],
        "verification_results": []
    }
    
    # 1. 检查文件产物
    claimed_files = extract_claimed_files(completion_claim["message"])
    for file_path in claimed_files:
        # 查找是否有 Write/Edit 操作实际创建了该文件
        file_creation = find_file_creation_event(tool_events, file_path, 
                                                  before_time=completion_claim["timestamp"])
        if not file_creation:
            verification["verification_results"].append({
                "check_type": "file_product",
                "claimed": f"生成文件 {file_path}",
                "actual": "未找到文件创建/编辑记录",
                "status": "FAILED",
                "severity": "high"
            })
    
    # 2. 检查测试执行
    if "test" in completion_claim["message"].lower():
        test_execution = find_test_execution(tool_events, before_time=completion_claim["timestamp"])
        if not test_execution:
            verification["verification_results"].append({
                "check_type": "test_execution",
                "claimed": "执行测试",
                "actual": "未找到测试执行记录",
                "status": "FAILED",
                "severity": "high"
            })
    
    # 3. 总结验证结果
    failed_checks = [r for r in verification["verification_results"] if r["status"] == "FAILED"]
    verification["overall_status"] = "VERIFIED" if not failed_checks else "SUSPICIOUS"
    verification["failed_check_count"] = len(failed_checks)
    
    return verification
```

### 6.4 数据流完整性检测

```python
def detect_dataflow_breaks(tool_events: list[dict]) -> list[dict]:
    """
    检测数据流断裂：工具 A 声称产出 X，但工具 B 未使用 X 或使用了错误的 Y
    
    典型问题：
    1. 工具产出文件但未被后续读取
    2. 工具读取了错误的文件版本
    3. 中间产物生成后未被传递到下游
    """
    breaks = []
    
    # 1. 识别所有文件产出事件
    file_productions = extract_file_productions(tool_events)
    
    # 2. 检查每个产出是否被后续使用
    for production in file_productions:
        file_path = production["file_path"]
        producer_time = production["timestamp"]
        
        # 查找后续是否有工具读取该文件
        subsequent_reads = [
            e for e in tool_events
            if e.get("tool_name") == "Read"
            and file_path in e.get("input_summary", "")
            and e.get("started_at") > producer_time
        ]
        
        if not subsequent_reads:
            # 检查是否有其他工具间接使用该文件（如 Bash 命令中引用）
            indirect_uses = find_indirect_file_uses(tool_events, file_path, after_time=producer_time)
            
            if not indirect_uses:
                breaks.append({
                    "type": "orphan_product",
                    "severity": "medium",
                    "file_path": file_path,
                    "produced_by": production["tool_use_id"],
                    "produced_at": producer_time,
                    "description": f"文件 {file_path} 生成后未被任何工具使用",
                    "consequence": "可能是多余的产物，或下游工具使用了错误的数据源",
                    "suggestion": "检查下游工具是否应使用该文件，或确认该文件是否真的需要生成"
                })
    
    # 3. 检测"期望使用但未使用"的模式
    expected_consumptions = infer_expected_consumptions(tool_events)
    for expected in expected_consumptions:
        actual_consumption = find_actual_consumption(expected, tool_events)
        if not actual_consumption:
            breaks.append({
                "type": "expected_consumption_missing",
                "severity": "high",
                "expected_file": expected["file_path"],
                "expected_consumer": expected["consumer_tool"],
                "description": f"期望 {expected['consumer_tool']} 使用 {expected['file_path']}，但实际未使用",
                "consequence": "工具可能基于过时或错误的数据执行",
            })
    
    return breaks
```

### 6.5 行为-声明一致性检测

```python
def detect_behavior_declaration_mismatch(
    main_entries: list[dict],
    tool_events: list[dict]
) -> list[dict]:
    """
    检测 Agent 声称的行为与实际执行的行为不一致
    
    典型场景：
    1. Agent 说"我检查了测试状态"，但实际没有运行测试命令
    2. Agent 说"我修复了 bug"，但实际 Edit 的是不相关的文件
    3. Agent 说"我验证了结果"，但实际没有执行验证操作
    """
    mismatches = []
    
    # 1. 提取所有行为声明
    behavior_claims = extract_behavior_claims(main_entries)
    
    for claim in behavior_claims:
        claim_time = claim["timestamp"]
        claimed_action = claim["action_type"]
        claimed_target = claim["target"]
        
        # 2. 在声称时间前后查找实际执行的工具调用
        nearby_events = [
            e for e in tool_events
            if abs(time_diff(e.get("started_at"), claim_time)) < 60  # 前后60秒内
        ]
        
        # 3. 验证声称的行为是否有实际证据
        verified = verify_claim_against_events(claim, nearby_events)
        
        if not verified:
            mismatches.append({
                "type": "behavior_declaration_mismatch",
                "severity": "high",
                "agent_id": claim["agent_id"],
                "claimed_action": claimed_action,
                "claimed_target": claimed_target,
                "claim_text": claim["text"][:200],
                "description": f"Agent 声称'{claimed_action} {claimed_target}'，但未找到对应的执行记录",
                "consequence": "可能是幻觉导致的虚假进度报告，后续步骤基于错误假设",
                "evidence_gap": {
                    "expected_tool": infer_expected_tool(claimed_action),
                    "expected_target": claimed_target,
                    "actual_nearby_tools": [e.get("tool_name") for e in nearby_events[:5]]
                }
            })
    
    return mismatches


def extract_behavior_claims(entries: list[dict]) -> list[dict]:
    """提取 Agent 的行为声明"""
    claims = []
    
    behavior_patterns = {
        "check": [r'我?检查了?\s*(.+?)(?:\n|$)', r'check(?:ed)?\s*(.+?)(?:\n|$)'],
        "fix": [r'我?修复了?\s*(.+?)(?:\n|$)', r'fix(?:ed)?\s*(.+?)(?:\n|$)', r'解决了?\s*(.+)'],
        "verify": [r'我?验证(?:了)?\s*(.+?)(?:\n|$)', r'verify(?:ied)?\s*(.+?)(?:\n|$)'],
        "run": [r'我?运行(?:了)?\s*(.+?)(?:\n|$)', r'执行(?:了)?\s*(.+?)(?:\n|$)', r'run\s*(.+?)(?:\n|$)'],
        "create": [r'我?创建(?:了)?\s*(.+?)(?:\n|$)', r'生成(?:了)?\s*(.+?)(?:\n|$)'],
    }
    
    for entry in entries:
        content = entry.get("content", "")
        for action_type, patterns in behavior_patterns.items():
            for pattern in patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                for match in matches:
                    claims.append({
                        "action_type": action_type,
                        "target": match.strip(),
                        "text": content,
                        "timestamp": entry.get("timestamp"),
                        "agent_id": entry.get("agent_id", "main")
                    })
    
    return claims
```

### 6.6 规则层集成

```python
def rule_findings_implicit_failures(
    phases: list[dict],
    tool_events: list[dict],
    main_entries: list[dict]
) -> list[dict]:
    """检测隐式失败（核心新增）"""
    findings = []
    
    # 1. WorkState 一致性检测
    workstate_issues = detect_workstate_inconsistency(tool_events, main_entries)
    for issue in workstate_issues:
        findings.append({
            "level": issue["severity"],
            "title": f"WorkState 不一致：{issue['type']}",
            "detail": issue["description"],
            "phase_id": issue.get("phase_id"),
            "evidence": issue.get("evidence"),
            "consequence": issue.get("consequence"),
            "type": "implicit_failure"
        })
    
    # 2. 数据流断裂检测
    dataflow_breaks = detect_dataflow_breaks(tool_events)
    for break_info in dataflow_breaks:
        findings.append({
            "level": break_info["severity"],
            "title": f"数据流断裂：{break_info['type']}",
            "detail": break_info["description"],
            "file_path": break_info.get("file_path"),
            "suggestion": break_info.get("suggestion"),
            "type": "implicit_failure"
        })
    
    # 3. 行为-声明不一致检测
    mismatches = detect_behavior_declaration_mismatch(main_entries, tool_events)
    for mismatch in mismatches:
        findings.append({
            "level": mismatch["severity"],
            "title": f"行为与声明不符：{mismatch['claimed_action']}",
            "detail": mismatch["description"],
            "agent_id": mismatch["agent_id"],
            "evidence_gap": mismatch.get("evidence_gap"),
            "type": "implicit_failure"
        })
    
    return findings
```

### 6.7 为什么能检测隐蔽问题

| 隐蔽问题 | 检测方法 | 原理 |
|----------|----------|------|
| WorkState 忘记打勾 | `completion_without_state_update` | 对比 Agent 完成声明 vs WorkState 编辑记录 |
| 虚假完成声明 | `state_update_without_execution` | 对比 WorkState 状态 vs 实际执行证据 |
| 中间产物缺失 | `orphan_product` | 检查文件产出后是否有消费方 |
| 使用了错误数据源 | `expected_consumption_missing` | 推断期望的数据流 vs 实际数据流 |
| 声称检查但未执行 | `behavior_declaration_mismatch` | 对比行为声明 vs 实际工具调用 |

---

## 七、改进5：状态机模式检测（原有）

### 5.1 核心思想

定义期望的状态转换模式，检测缺失的环节。常见模式：

| 模式 | 触发条件 | 期望后续 | 违反含义 |
|------|----------|----------|----------|
| edit_verify | Edit 成功 | 5步内应有测试/验证 | 编辑后未验证 |
| read_understand | Read 长文件(>500字符) | 3步内应有行动 | 读取后未理解 |
| bash_error_retry | Bash 失败 | 1步内应调整参数 | 盲目重试 |
| plan_execute | 有明确计划 | 执行应与计划一致 | 执行偏离计划 |

### 5.2 实现方案

```python
# state_machine_patterns.py

STATE_MACHINE_PATTERNS = {
    "edit_verify": {
        "trigger": {
            "tool_name": "Edit",
            "is_error": False
        },
        "expected_follow_up": {
            "within_steps": 5,
            "condition": lambda e: (
                e.get("tool_name") == "Bash" and 
                any(kw in e.get("input_summary", "").lower() 
                    for kw in ["test", "verify", "check", "run", "pytest"])
            )
        },
        "violation_label": "编辑后未验证",
        "severity": "high",
        "rationale": "Edit 后没有验证可能导致错误代码被忽略"
    },
    
    "read_understand": {
        "trigger": {
            "tool_name": "Read",
            "is_error": False,
            "content_length_check": lambda content: len(content) > 500
        },
        "expected_follow_up": {
            "within_steps": 3,
            "condition": lambda e: e.get("tool_name") in ["Bash", "Edit", "Agent"]
        },
        "violation_label": "读取长文件后未行动",
        "severity": "medium",
        "rationale": "读取长内容后没有后续行动，可能未充分理解内容"
    },
    
    "bash_error_retry": {
        "trigger": {
            "tool_name": "Bash",
            "is_error": True
        },
        "expected_follow_up": {
            "within_steps": 1,
            "condition": lambda e: (
                e.get("tool_name") == "Bash" and 
                not is_same_command(e.get("input_summary", ""), trigger_input)
            )
        },
        "violation_label": "Bash失败后未调整直接重试",
        "severity": "medium",
        "rationale": "相同命令重复执行可能陷入死循环"
    },
    
    "tool_result_usage": {
        "trigger": {
            "tool_name": ["Read", "Bash", "Agent"],
            "is_error": False
        },
        "expected_follow_up": {
            "within_steps": 5,
            "condition": lambda e: (
                # 后续工具输入中包含触发工具输出的关键片段
                uses_previous_result(e, trigger_output)
            )
        },
        "violation_label": "工具结果未被引用",
        "severity": "low",
        "rationale": "工具调用结果未被后续使用，可能是多余调用"
    }
}


def detect_state_machine_violations(tool_events: list[dict]) -> list[dict]:
    """检测状态机模式违反"""
    violations = []
    
    for i, event in enumerate(tool_events):
        for pattern_name, pattern in STATE_MACHINE_PATTERNS.items():
            if matches_trigger(event, pattern["trigger"]):
                # 检查期望的 follow-up 是否在范围内发生
                found = False
                search_end = min(i + 1 + pattern["expected_follow_up"]["within_steps"], 
                                len(tool_events))
                
                for j in range(i + 1, search_end):
                    if pattern["expected_follow_up"]["condition"](tool_events[j]):
                        found = True
                        break
                
                if not found:
                    violations.append({
                        "pattern": pattern_name,
                        "label": pattern["violation_label"],
                        "severity": pattern["severity"],
                        "rationale": pattern["rationale"],
                        "trigger_tool": {
                            "id": event["tool_use_id"],
                            "name": event.get("tool_name"),
                            "at": event.get("started_at")
                        },
                        "expected": f"在{pattern['expected_follow_up']['within_steps']}步内应有特定行动",
                        "phase_id": event.get("phase_id")
                    })
    
    return violations
```

### 5.3 长程幻觉检测

```python
def detect_goal_divergence(phases: list[dict], 
                           tool_events: list[dict],
                           threshold: float = 0.3) -> list[dict]:
    """
    检测执行是否偏离初始目标（长程幻觉）
    
    方法：
    1. 提取第一阶段的目标/需求描述
    2. 比较后续阶段的工具调用是否与目标相关
    3. 如果相关性低于阈值，标记为偏离
    """
    if not phases:
        return []
    
    # 提取初始目标
    initial_goal = extract_goal_from_first_phase(phases[0])
    
    divergences = []
    for i, phase in enumerate(phases[1:], 1):
        phase_tools = phase.get("dominant_tools", [])
        relevance = calculate_goal_relevance(phase_tools, initial_goal)
        
        if relevance < threshold:
            divergences.append({
                "type": "goal_divergence",
                "phase_id": phase.get("phase_id"),
                "phase_name": phase.get("name"),
                "relevance_score": relevance,
                "expected_focus": initial_goal,
                "actual_focus": phase.get("dominant_tools"),
                "rationale": f"阶段工具调用与初始目标相关性过低 ({relevance:.2f})"
            })
    
    return divergences
```

---

## 八、改进6：分层根因分析

### 6.1 核心思想

借鉴 ErrorProbe 三阶段流水线：
1. **Stage 1: 症状确认**（基于规则 findings）
2. **Stage 2: 根因推断**（基于依赖图和传播分析）
3. **Stage 3: 修复建议**（基于状态机模式）

### 6.2 Prompt 策略改进

```markdown
# 分层诊断 Prompt 模板

## Stage 1: 症状确认

基于以下规则检测到的可疑点，确认并列出所有需要深入分析的具体工具调用：

{{findings}}

输出要求：
- 列出每个可疑点的 tool_use_id
- 确认现象描述
- 标记可疑程度（high/medium/low）

## Stage 2: 根因推断

对以下可疑点进行根因分析：

{{stage1_output}}

分析维度：
1. **错误传播分析**：如果涉及错误，是否是其他错误传播导致？
   - 查看错误传播链：{{error_propagation_chains}}
   
2. **依赖关系分析**：工具调用的输入是否正确？
   - 查看工具依赖图：{{dependency_graph}}
   
3. **状态机分析**：是否符合期望的执行模式？
   - 查看状态机违反：{{state_machine_violations}}

输出要求（每个根因）：
- 根因类型：错误传播 / 依赖错误 / 状态机违反 / 独立错误
- 根因位置：具体的 tool_use_id 或 phase_id
- 推断依据：基于上述哪个分析维度

## Stage 3: 修复建议

基于 Stage 2 的根因分析，给出具体可执行的修复建议：

输出要求（每个建议）：
- 对应根因：引用 Stage 2 的根因编号
- 修复动作：具体的代码/配置/流程修改建议
- 预期效果：修复后应该观察到什么变化
- 验证方法：如何确认修复成功

## 优化优先级

综合所有根因的 severity 和影响范围，给出处理优先级排序。
```

### 6.3 代码实现

```python
def hierarchical_diagnosis(context: str, 
                          findings: list[dict],
                          dependency_graph: dict,
                          error_chains: list[dict],
                          state_violations: list[dict]) -> dict:
    """分层诊断主函数"""
    
    # Stage 1: 症状确认（可以用规则直接完成，不需要LLM）
    stage1_output = findings
    
    # Stage 2: 根因推断（调用LLM）
    stage2_prompt = build_stage2_prompt(
        stage1_output, 
        dependency_graph, 
        error_chains,
        state_violations
    )
    root_causes = call_llm(stage2_prompt)
    
    # Stage 3: 修复建议（调用LLM）
    stage3_prompt = build_stage3_prompt(root_causes)
    recommendations = call_llm(stage3_prompt)
    
    return {
        "symptoms": stage1_output,
        "root_causes": root_causes,
        "recommendations": recommendations,
        "priorities": calculate_priorities(root_causes)
    }
```

---

## 九、实施路线图

### Phase 1: 依赖图基础设施（1-2周）

**新增文件**：`dependency_graph.py`
- `build_dependency_graph()` - 构建工具依赖图
- `find_error_propagation_chain()` - 错误传播链识别
- `find_root_cause()` - 反向根因追踪

**修改文件**：`core.py`
- 在 `build_report_data()` 中集成依赖图构建
- 在 `rule_findings()` 中添加传播检测规则

### Phase 2: 隐式失败检测（1-2周）【核心新增】

**新增文件**：`implicit_failure_detection.py`
- `detect_workstate_inconsistency()` - WorkState 一致性检测
- `detect_dataflow_breaks()` - 数据流断裂检测
- `detect_behavior_declaration_mismatch()` - 行为-声明一致性检测
- `verify_task_completion()` - 任务完成验证

**修改文件**：`core.py`
- 在 `rule_findings()` 中添加隐式失败检测调用
- 新增 `findings` 类型标记（`explicit_failure` vs `implicit_failure`）

### Phase 3: 状态机检测（1周）

**新增文件**：`state_machine_patterns.py`
- `STATE_MACHINE_PATTERNS` - 模式定义
- `detect_state_machine_violations()` - 违反检测
- `detect_goal_divergence()` - 目标偏离检测

**修改文件**：`core.py`
- 在 `rule_findings()` 中添加状态机检测

### Phase 4: 诊断增强（1周）

**修改文件**：`diagnosis_prompt.md`
- 改为分层诊断结构
- 注入依赖图、传播链、隐式失败证据、状态机违反信息
- 区分显式失败（工具报错）和隐式失败（状态不一致）的分析策略

**修改文件**：`pipeline.py`
- 实现 `hierarchical_diagnosis()` 调用逻辑

### Phase 5: 可视化增强（可选，1-2周）

**前端增强**：`report_template.html`
- 甘特图上叠加依赖箭头
- 错误传播链高亮显示
- 状态机违反点标记

---

## 十、优先级建议

| 优先级 | 改进项 | 影响 | 工作量 | 建议顺序 |
|--------|--------|------|--------|----------|
| P0 | 依赖图构建 | 高 | 中 | 第1周 |
| P0 | 错误传播分析 | 高 | 中 | 第1-2周 |
| **P0** | **隐式失败检测** | **高** | **中** | **第2-3周** |
| P1 | 状态机模式检测 | 中 | 中 | 第3-4周 |
| P1 | 分层诊断Prompt | 中 | 低 | 第4周 |
| P2 | 目标偏离检测 | 中 | 高 | 后续迭代 |
| P2 | 可视化增强 | 低 | 高 | 后续迭代 |

---

## 十一、预期效果

实施以上改进后，诊断系统应能回答：

| 问题类型 | 当前能力 | 改进后能力 |
|----------|----------|------------|
| **显式失败** ||
| 哪个工具失败了？ | ✅ 已有 | ✅ 已有 |
| 错误如何传播？ | ❌ 无 | ✅ 传播链追踪 |
| **隐式失败** ||
| WorkState 是否漏更新？ | ❌ 无 | ✅ WorkState 一致性检测 |
| Agent 声称完成是否真的做了？ | ❌ 无 | ✅ 任务完成验证 |
| 中间产物是否被正确使用？ | ❌ 无 | ✅ 数据流完整性检测 |
| Agent 说检查是否真的检查了？ | ❌ 无 | ✅ 行为-声明一致性检测 |
| **通用能力** ||
| 根因在哪里？ | ⚠️ LLM推断 | ✅ 依赖图+传播分析定位 |
| 哪个环节缺失？ | ❌ 无 | ✅ 状态机违反检测 |
| 是否偏离目标？ | ❌ 无 | ✅ 长程偏离检测 |
| 根因在哪里？ | ⚠️ LLM推断 | ✅ 依赖图+传播分析定位 |
| 哪个环节缺失？ | ❌ 无 | ✅ 状态机违反检测 |
| 是否偏离目标？ | ❌ 无 | ✅ 长程偏离检测 |

---

## 十二、参考文献

1. **AgentTrace**: Causal Graph Tracing for Root Cause Analysis - 依赖图构建方法
2. **TraceCoder**: Trace-Driven Multi-Agent Debugging - 因果分析和历史学习
3. **ErrorProbe**: Self-Improving Error Diagnosis - 三阶段诊断流水线
4. **ECHO**: Hierarchical Error Attribution - 层次化上下文分析
5. **XAI for Coding Agent Failures** - 可视化解释生成

---

*文档版本: 1.0*
*创建日期: 2026-07-03*
*适用场景: Cloud Agent 日志事后诊断*
