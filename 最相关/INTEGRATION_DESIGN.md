# 元析 Agent Teams + 诊断系统整合设计方案

> 将 deep-ai-analysis 诊断能力集成到元析 Agent Teams 流程中

---

## 一、现状分析

### 1.1 元析 Agent Teams 架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    orchestrator-agent (Lead)                     │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │ pm-agent │→│design-agent│→│coding-agent│→│deploy-agent│      │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘        │
│                                               ↓                  │
│                                        ┌──────────────┐         │
│                                        │integration-test│        │
│                                        │    -agent      │        │
│                                        └──────────────┘         │
└─────────────────────────────────────────────────────────────────┘
                              ↓
                    ┌──────────────────┐
                    │   work_status.md  │ ← 中心状态文件
                    └──────────────────┘
```

**关键特征**：
- 使用 `work_status.md` 作为中心状态协调
- 循环处理：编码 ↔ 部署 ↔ 测试 三角循环
- 错误路由：根据错误模式决定回退到哪个阶段

### 1.2 deep-ai-analysis 诊断能力

```
┌──────────────────────────────────────────────────────────────┐
│                    deep-ai-analysis                          │
├──────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │  日志采集     │  │  规则检测     │  │  LLM 诊断     │       │
│  │  (recorder)  │→ │  (findings)  │→ │  (diagnosis) │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
│         ↑                                                    │
│    ┌─────────────────┐                                       │
│    │  Claude Code    │                                       │
│    │  session.jsonl  │                                       │
│    └─────────────────┘                                       │
└──────────────────────────────────────────────────────────────┘
```

**当前局限**：
- 仅支持单 Session 分析
- 不感知 Agent Teams 的协作模式
- 不识别 work_status.md 状态流转

---

## 二、整合目标

### 2.1 核心目标

让诊断系统能够分析元析 Agent Teams 的**多 Agent 协作过程**，定位：

| 问题类型 | 示例 | 检测方法 |
|----------|------|----------|
| **显式工具失败** | Bash 命令返回错误码 | 已有能力 |
| **WorkState 状态遗漏** | coding-agent 完成但未更新 work_status | 隐式失败检测 |
| **阶段循环异常** | 编码-部署-测试循环超过2次 | 流程模式检测 |
| **Agent 间状态不一致** | pm-agent 标记完成但 design-agent 未触发 | 跨 Agent 依赖检测 |
| **长程任务偏离** | 最终实现与需求不符 | 目标偏离检测 |

### 2.2 整合方式

采用 **Hook 注入** 方式，在元析流程关键点触发诊断：

```
元析 Agent Teams 流程
       │
       ▼
┌──────────────┐     ┌──────────────────┐
│   Hook 点    │────▶│ 诊断分析触发     │
└──────────────┘     └──────────────────┘
       │                      │
       │                      ▼
       │              ┌──────────────┐
       │              │ 实时/事后诊断 │
       │              │ 报告生成      │
       │              └──────────────┘
       │                      │
       ▼                      ▼
┌──────────────┐     ┌──────────────────┐
│ 流程继续/回退 │◄────│ 诊断结果反馈     │
└──────────────┘     └──────────────────┘
```

---

## 三、具体实施方案

### 方案A：实时诊断（推荐）

在每个 Agent 执行完成后，实时分析并决定是否继续。

#### 3.1 Hook 点设计

```python
# hooks/yx_diagnosis_hook.py

HOOK_POINTS = {
    # 每个 Agent 执行完成后触发
    "after_agent_execution": {
        "description": "Agent 执行完成后诊断",
        "trigger": [
            "pm-agent 完成",
            "design-agent 完成", 
            "coding-agent 完成",
            "deploy-agent 完成",
            "integration-test-agent 完成"
        ],
        "diagnosis_scope": "单 Agent 执行质量"
    },
    
    # 循环检测点
    "before_cycle_retry": {
        "description": "循环重试前诊断",
        "trigger": [
            "编码-部署-测试循环计数增加时"
        ],
        "diagnosis_scope": "循环失败根因分析"
    },
    
    # 流程阻塞时
    "on_flow_blocked": {
        "description": "流程阻塞时诊断",
        "trigger": [
            "work_status 标记为 blocked",
            "循环次数超过阈值",
            "SSO/环境错误"
        ],
        "diagnosis_scope": "全流程失败分析"
    },
    
    # 流程完成时
    "on_flow_completed": {
        "description": "流程完成时诊断",
        "trigger": [
            "overall_status = success/partial"
        ],
        "diagnosis_scope": "全流程质量评估"
    }
}
```

#### 3.2 数据集成

```python
# diagnosis_adapter.py

class YuanxiDiagnosisAdapter:
    """适配元析数据格式到诊断系统"""
    
    def __init__(self, multica_workspace: str):
        self.workspace = multica_workspace
        self.work_status_path = f"{multica_workspace}/work_status.md"
        
    def collect_session_data(self, agent_name: str) -> dict:
        """
        收集指定 Agent 的执行数据
        
        来源：
        1. ~/.claude/projects/ 下的 session JSONL
        2. work_status.md 状态记录
        3. 该 Agent 的子 Agent 日志（如有）
        """
        # 1. 找到最近的 session
        session = self._find_agent_session(agent_name)
        
        # 2. 读取 work_status 相关片段
        work_status_context = self._extract_work_status_context(agent_name)
        
        # 3. 组装诊断数据
        return {
            "session": session,
            "work_status": work_status_context,
            "agent_name": agent_name,
            "flow_context": self._get_flow_context()
        }
    
    def _extract_work_status_context(self, agent_name: str) -> dict:
        """提取 work_status 中与当前 Agent 相关的部分"""
        work_status = parse_work_status(self.work_status_path)
        
        # 提取当前阶段状态
        current_stage = work_status.get("status")
        current_agent = work_status.get("current_agent")
        
        # 提取历史循环记录
        loop_history = self._extract_loop_history(work_status)
        
        return {
            "current_stage": current_stage,
            "current_agent": current_agent,
            "loop_count": work_status.get("loop_count", 0),
            "loop_history": loop_history,
            "last_error": work_status.get("last_error"),
            "overall_status": work_status.get("overall_status")
        }
```

#### 3.3 诊断触发逻辑

```python
# yx_diagnosis_service.py

class YuanxiDiagnosisService:
    """元析诊断服务"""
    
    def __init__(self):
        self.adapter = YuanxiDiagnosisAdapter()
        self.diagnosis_engine = SessionDiagnosisEngine()
        
    def diagnose_after_agent(self, agent_name: str, workspace: str) -> dict:
        """Agent 执行后诊断"""
        
        # 1. 收集数据
        data = self.adapter.collect_session_data(agent_name)
        
        # 2. 增强规则检测（针对元析场景）
        findings = self._enhanced_rule_findings(data)
        
        # 3. 生成诊断报告
        diagnosis = self.diagnosis_engine.diagnose(
            context=data,
            findings=findings,
            prompt_template="yx_agent_diagnosis_prompt.md"
        )
        
        # 4. 决策建议
        decision = self._generate_decision(diagnosis, data)
        
        return {
            "diagnosis": diagnosis,
            "decision": decision,  # continue / retry / rollback / block
            "confidence": decision["confidence"]
        }
    
    def _enhanced_rule_findings(self, data: dict) -> list[dict]:
        """增强的规则检测（针对元析）"""
        findings = []
        
        # 原有检测
        findings.extend(self._detect_tool_failures(data))
        findings.extend(self._detect_implicit_failures(data))
        
        # 新增：元析特定检测
        findings.extend(self._detect_workstate_inconsistency(data))
        findings.extend(self._detect_cycle_anomaly(data))
        findings.extend(self._detect_agent_handoff_failure(data))
        
        return findings
    
    def _detect_workstate_inconsistency(self, data: dict) -> list[dict]:
        """检测 WorkState 状态不一致"""
        inconsistencies = []
        
        session = data["session"]
        work_status = data["work_status"]
        agent_name = data["agent_name"]
        
        # 检查1：Agent 声称完成但 work_status 未更新
        agent_claims_completion = self._check_agent_completion_claim(session)
        work_status_updated = work_status.get("current_stage") != agent_name
        
        if agent_claims_completion and not work_status_updated:
            inconsistencies.append({
                "type": "workstate_update_missing",
                "severity": "high",
                "agent": agent_name,
                "description": f"{agent_name} 声称完成任务但未更新 work_status",
                "suggestion": "检查 Agent 是否正确执行了状态更新操作"
            })
        
        # 检查2：work_status 标记完成但无实际执行证据
        if work_status_updated and not self._has_execution_evidence(session):
            inconsistencies.append({
                "type": "execution_evidence_missing",
                "severity": "high", 
                "agent": agent_name,
                "description": f"work_status 标记 {agent_name} 完成，但未找到执行证据",
                "suggestion": "可能是虚假进度，需要人工核查"
            })
        
        return inconsistencies
    
    def _detect_cycle_anomaly(self, data: dict) -> list[dict]:
        """检测循环异常"""
        anomalies = []
        work_status = data["work_status"]
        
        loop_count = work_status.get("loop_count", 0)
        loop_history = work_status.get("loop_history", [])
        
        # 检查1：循环次数过多
        if loop_count >= 2:
            anomalies.append({
                "type": "excessive_retry_cycles",
                "severity": "high",
                "loop_count": loop_count,
                "description": f"编码-部署-测试循环已达 {loop_count} 次",
                "suggestion": "可能存在深层问题，建议人工介入诊断",
                "history": loop_history
            })
        
        # 检查2：循环模式分析（是否在同类型错误间反复）
        error_pattern = self._analyze_cycle_pattern(loop_history)
        if error_pattern["is_repeating"]:
            anomalies.append({
                "type": "repeating_error_pattern",
                "severity": "high",
                "error_type": error_pattern["common_error"],
                "description": f"循环中重复出现相同错误类型：{error_pattern['common_error']}",
                "suggestion": "当前修复策略无效，需要调整方案"
            })
        
        return anomalies
    
    def _detect_agent_handoff_failure(self, data: dict) -> list[dict]:
        """检测 Agent 交接失败"""
        failures = []
        
        work_status = data["work_status"]
        current_agent = work_status.get("current_agent")
        expected_agent = self._infer_expected_agent(work_status)
        
        # 检查：当前 Agent 与期望 Agent 不匹配
        if current_agent != expected_agent:
            failures.append({
                "type": "agent_handoff_mismatch",
                "severity": "medium",
                "current_agent": current_agent,
                "expected_agent": expected_agent,
                "description": f"当前 Agent {current_agent} 与期望 {expected_agent} 不匹配",
                "suggestion": "检查 orchestrator 路由逻辑或 Agent 执行状态"
            })
        
        return failures
    
    def _generate_decision(self, diagnosis: dict, data: dict) -> dict:
        """基于诊断结果生成决策建议"""
        
        findings = diagnosis.get("findings", [])
        high_severity = [f for f in findings if f.get("severity") == "high"]
        
        # 决策逻辑
        if any(f["type"] == "workstate_update_missing" for f in high_severity):
            return {
                "action": "retry",
                "target": data["agent_name"],
                "reason": "状态更新缺失，需要重试",
                "confidence": 0.8
            }
        
        if any(f["type"] == "excessive_retry_cycles" for f in high_severity):
            return {
                "action": "block",
                "target": "flow",
                "reason": "循环次数过多，需要人工介入",
                "confidence": 0.9
            }
        
        if any(f["type"] == "execution_evidence_missing" for f in high_severity):
            return {
                "action": "block", 
                "target": "flow",
                "reason": "存在虚假进度风险",
                "confidence": 0.7
            }
        
        # 默认继续
        return {
            "action": "continue",
            "target": "next_agent",
            "reason": "诊断通过",
            "confidence": 0.9
        }
```

#### 3.4 与元析 Hook 系统集成

```python
# ~/.claude/skills/yx-common/scripts/plugin_dispatcher.py 增强

def dispatch_hook(event: str, work_status_path: str) -> dict:
    """
    增强的 hook 分发器，集成诊断能力
    """
    result = {
        "skills_to_execute": [],
        "diagnosis": None,
        "routing_decision": None
    }
    
    # 1. 原有逻辑：确定需要执行的 skills
    result["skills_to_execute"] = get_skills_for_event(event)
    
    # 2. 新增：诊断触发
    if should_trigger_diagnosis(event):
        diagnosis_service = YuanxiDiagnosisService()
        diagnosis_result = diagnosis_service.diagnose_after_event(
            event=event,
            work_status_path=work_status_path
        )
        
        result["diagnosis"] = diagnosis_result["diagnosis"]
        result["routing_decision"] = diagnosis_result["decision"]
        
        # 3. 根据诊断结果调整 routing
        if diagnosis_result["decision"]["action"] == "block":
            result["skills_to_execute"] = []  # 阻止继续执行
            result["block_reason"] = diagnosis_result["decision"]["reason"]
    
    return result
```

---

### 方案B：事后诊断

在流程结束后，生成完整的诊断报告。

#### 3.5 事后诊断流程

```python
# yx_post_hoc_diagnosis.py

class YuanxiPostHocDiagnosis:
    """事后全流程诊断"""
    
    def diagnose_flow(self, multica_workspace: str) -> dict:
        """
        对完成的流程进行事后诊断
        
        1. 收集所有 Agent 的 session 数据
        2. 重建完整执行时间线
        3. 分析跨 Agent 依赖关系
        4. 生成诊断报告
        """
        
        # 1. 收集所有 Agent sessions
        all_sessions = self._collect_all_agent_sessions(multica_workspace)
        
        # 2. 重建全局时间线
        timeline = self._rebuild_global_timeline(all_sessions)
        
        # 3. 跨 Agent 分析
        cross_agent_analysis = self._analyze_cross_agent_dependencies(timeline)
        
        # 4. 生成报告
        report = {
            "summary": self._generate_summary(timeline),
            "timeline": timeline,
            "cross_agent_issues": cross_agent_analysis.get("issues", []),
            "performance_metrics": self._calculate_metrics(timeline),
            "recommendations": self._generate_recommendations(cross_agent_analysis)
        }
        
        return report
    
    def _analyze_cross_agent_dependencies(self, timeline: list[dict]) -> dict:
        """分析跨 Agent 依赖关系"""
        
        issues = []
        
        # 分析1：Agent 间状态传递完整性
        for i, event in enumerate(timeline):
            if event["type"] == "agent_handoff":
                from_agent = event["from_agent"]
                to_agent = event["to_agent"]
                
                # 检查 handoff 数据完整性
                handoff_data = event.get("handoff_data", {})
                if not self._is_handoff_complete(handoff_data):
                    issues.append({
                        "type": "incomplete_handoff",
                        "from": from_agent,
                        "to": to_agent,
                        "timestamp": event["timestamp"],
                        "missing_fields": self._get_missing_handoff_fields(handoff_data)
                    })
        
        # 分析2：循环效率
        cycles = self._identify_cycles(timeline)
        for cycle in cycles:
            if cycle["efficiency"] < 0.5:  # 效率低于50%
                issues.append({
                    "type": "inefficient_cycle",
                    "cycle_type": cycle["type"],
                    "iterations": cycle["iterations"],
                    "efficiency": cycle["efficiency"],
                    "suggestion": "循环效率低，建议优化错误修复策略"
                })
        
        return {"issues": issues}
```

---

## 四、部署方案

### 4.1 文件结构

```
bizad_ai_yuanxi_skills/
├── skills/
│   └── yx-diagnosis/                    # 新增诊断 Skill
│       ├── SKILL.md
│       ├── diagnose_agent.py            # Agent 级诊断
│       ├── diagnose_flow.py             # 流程级诊断
│       └── diagnosis_reporter.py        # 报告生成
├── hooks/
│   ├── hooks.manifest                   # 添加诊断 hook 注册
│   └── yx_diagnosis_hook.py             # 诊断 hook 实现
└── lib/
    └── diagnosis/                       # 诊断库（复用 deep-ai-analysis）
        ├── dependency_graph.py
        ├── implicit_failure_detection.py
        └── state_machine_patterns.py
```

### 4.2 集成步骤

**步骤1：复制诊断核心模块**
```bash
# 从 deep-ai-analysis 复制核心诊断逻辑
cp -r /Users/elon-ge/workspace/deep-ai-analysis-session-report-clean/deep_ai_analysis/session_report \
  /Users/elon-ge/workspace/元析/bizad_ai_yuanxi_skills/lib/diagnosis/
```

**步骤2：创建适配层**
```python
# lib/diagnosis/yuanxi_adapter.py
# 适配元析数据格式
```

**步骤3：注册 Hook**
```yaml
# hooks/hooks.manifest 添加
- name: yx_diagnosis_hook
  events:
    - after_agent_execution
    - before_cycle_retry
    - on_flow_blocked
```

**步骤4：测试验证**
```bash
# 运行测试流程，验证诊断触发
claude --skill yx-multica-orchestrator --test-diagnosis
```

---

## 五、优先级建议

| 优先级 | 功能 | 工作量 | 价值 |
|--------|------|--------|------|
| P0 | WorkState 一致性检测 | 中 | 解决核心痛点（忘记打勾） |
| P0 | Agent 执行后实时诊断 | 中 | 及时发现单 Agent 问题 |
| P1 | 循环异常检测 | 低 | 防止无效循环 |
| P1 | 事后全流程诊断报告 | 中 | 复盘分析 |
| P2 | 跨 Agent 依赖分析 | 高 | 深度问题定位 |
| P2 | 诊断结果反馈路由 | 中 | 自动修复建议 |

---

## 六、预期效果

### 6.1 问题解决覆盖

| 问题场景 | 现状 | 整合后 |
|----------|------|--------|
| Agent 忘记更新 work_status | 人工发现 | 自动检测并告警 |
| 循环反复失败 | 次数超限才发现 | 模式分析，早期预警 |
| Agent 虚假完成声明 | 难以发现 | 声明 vs 证据比对 |
| 跨 Agent 状态不一致 | 调试困难 | 依赖图可视化 |
| 全流程复盘 | 无工具支持 | 自动生成诊断报告 |

### 6.2 使用流程

```
1. 正常启动元析流程
   claude --skill yx-multica-orchestrator

2. 诊断自动触发（无感知）
   - 每个 Agent 执行后 → 实时诊断
   - 循环重试前 → 循环分析
   - 流程结束后 → 生成报告

3. 诊断结果呈现
   - 实时：在 work_status 中添加诊断注释
   - 事后：生成 diagnosis_report.md

4. 人工介入决策
   - 根据诊断建议决定 continue / retry / block
```

---

*文档版本: 1.0*
*创建日期: 2026-07-09*
