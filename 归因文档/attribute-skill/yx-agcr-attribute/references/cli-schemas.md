# CLI 产物数据结构

本文档描述 CLI 日志洗数产物的数据结构、字段提取规则和 execution_trace.json 生成策略。数据采集主流程详见 `references/data-collection.md`。

## agcr.json 结构（每个 session 目录下）

```json
[{
  "session_id": "...",
  "repo": "repo-name",
  "branch": "feature/xxx",
  "merged": true,
  "result": {
    "status": "success",
    "repo": "repo-name",
    "branch": "feature/xxx",
    "base_ref": "base-commit-hash",
    "final_commit": "final-commit-hash",
    "final_lines": 120,
    "commits": [{
      "hash": "commit-hash",
      "date": "2026-...",
      "subject": "commit message",
      "commit_lines": 50,
      "final_lines": 45,
      "intersect": 42,
      "discard_lines": 3,
      "shot_ratio": 0.93,
      "discard_rate": 0.07,
      "skip": false
    }],
    "summary": {
      "valid_count": 5,
      "skip_count": 0,
      "shot_ge95": 3,
      "shot_50_95": 2,
      "shot_lt50": 0,
      "avg_discard": 0.05
    }
  },
  "commit_markers": {
    "a1b2c3d4": ["base"],
    "f7e6d5c4": ["tdd"],
    "1a2b3c4d": ["final"]
  }
}]
```

## commit 版本提取规则

从 `commit_markers` 提取三版本 commit：

| commit_markers key | 归因字段 | 说明 |
|---|---|---|
| marker 值包含 `"base"` 的 hash | `base_commit` | 分支基线 |
| marker 值包含 `"tdd"` 的 hash | `one_shot_commit` | AI 首轮编码完成 |
| marker 值包含 `"final"` 的 hash | `target_final_commit` | 最终版本（缺失时从代码平台读取远程分支 head） |

## short hash → full hash 映射

`commit_markers` 的 key 是 **8 字符短 hash**（如 `a1b2c3d4`），归因系统内部使用的 `base_commit`、`one_shot_commit`、`target_final_commit` 需要完整 hash。映射来源：

| 短 hash 来源 | 完整 hash 来源 | 获取方式 |
|---|---|---|
| `commit_markers` 中标记 `"base"` 的 key | `result.base_ref`（agcr.json 同条目） | agcr.json 中 `result.base_ref` 即为 base 完整 hash |
| `commit_markers` 中标记 `"final"` 的 key | `result.final_commit`（agcr.json 同条目） | agcr.json 中 `result.final_commit` 即为 final 完整 hash |
| `commit_markers` 中标记 `"tdd"` 的 key | `result.commits[].hash` 中前缀匹配 | 遍历 `result.commits[]`，找 `hash.startswith(short_hash)` 的条目 |

`fetch_diff.py` 接受短 hash（git 自动解析），无需预先转换为完整 hash。若 agcr.json 缺少 `result.base_ref` / `result.final_commit`，可通过 `git -C {local_path} rev-parse {short_hash}` 获取完整 hash。报告展示时使用 `short_sha()`（前 8 位）缩写显示。

## 阶段 commit 计数

报告 §2「代码版本与 Diff 概览」展示每个仓库两个阶段的 commit 数量：

| 阶段 | 字段 | 数据来源 | 含义 |
|---|---|---|---|
| AI 编码（base→one-shot） | `diff_overview[].b2o_commits` | CLI 洗数 `commits.json`：按 repo 汇总 commit 条目数 | AI 编码阶段产生的 commit 总数 |
| 人工修改（one-shot→final） | `diff_overview[].os2f_commits` | `commit-chain.json`（SubAgent-Diff 采集）：数组长度 | 人工迭代阶段的 commit 总数 |

`commit-chain.json` 由 SubAgent-Diff 通过 `git -C {local_path} log --format='%H|%an|%ae|%cn|%ce|%cI|%s' {one_shot_commit}..{target_final_commit}` 采集，覆盖 one-shot→final 范围内的所有提交。`commits.json` 来自 CLI 日志洗数，覆盖 AI 编码会话中的所有 git commit 记录。

当 `b2o_commits` 为 null 时，表示 CLI 洗数未产出该 repo 的 commit 记录（可能是回放数据或 CLI 版本不支持）。当 `os2f_commits` 为 null 时，表示 `commit-chain.json` 缺失（SubAgent-Diff 未成功采集该 repo 的提交链），`verify_attribution.py` 会发出 warn。

## execution_trace.json 生成（三层融合）

CLI 洗数产出的 `dag_*.json` 是各阶段的完整 session 执行轨迹（含消息树、工具调用链）。主 Agent 在数据采集阶段调用 `scripts/parse_execution_trace.py`，采用三层融合策略生成 `execution_trace.json`，写入 `$OUTPUT_DIR/artifacts/execution_trace.json`（替代旧版 `trace_by_stage.json`）。

```bash
python3 "$SCRIPT_DIR/parse_execution_trace.py" \
  --cli-washing-dir "$OUTPUT_DIR/cli-washing/{session_id}" \
  --output "$OUTPUT_DIR/artifacts/execution_trace.json"
```

**三层融合策略**：

Layer 1 — phases.json（直接读取，不解析 dag）：阶段框架（phase_name, start_time, end_time）+ skill_invocation 事件（skill_name, via, timestamp）。CLI SDK 的 phases.json 已覆盖 skill 调用的完整链路（包括 agent_prompt 类型的隐式引用），比从 dag 解析 tool_use 节点更完整。

Layer 2 — commits.json（直接读取，不解析 dag）：git_commit 事件（commit_id, message, repo, timestamp），按 phase_name 归入对应阶段。

Layer 3 — dag_*.json（定向解析，仅提取 Layer 1/2 未覆盖的字段）：
- knowledge_events：Read（非 skill 文件）/ Grep / Glob / Bash(km/grep) 调用 + result_preview
- write_events：Write / Edit 的 file_path + content_preview
- reasoning_events：thinking / assistant 文本预览
- agent_events：Agent tool_use 的 description + prompt

**生成时机**：数据采集阶段，先读 phases.json + commits.json 建立阶段框架和 skill/commit 事件，再定向解析 dag_*.json 补充 knowledge/write/reasoning 事件。

输出格式示例：

```json
{
  "session_id": "d73a99c1-...",
  "dag_dir": "cli-washing/d73a99c1-.../dag_*.json",
  "generated_at": "2026-06-17T14:30:00",
  "stages": {
    "scope_bootstrap": {
      "dag_file": "dag_scope_bootstrap.json",
      "node_count": 418,
      "node_type_counts": {"tool_use": 168, "thinking": 25, ...},
      "timeline": [
        {"seq": 0, "type": "skill_invocation", "skill_name": "yx-fsd-req-km-extractor", ...},
        {"seq": 1, "type": "knowledge_retrieval", "tool_name": "Read", ...},
        {"seq": 2, "type": "git_commit", "commit_id": "f6f87a5", ...}
      ]
    }
  }
}
```

此文件供 `aggregate_stats.py` 传递到 `attribution-result.json.execution_trace` 字段，供 `render_report.py` 渲染执行轨迹时间线，以及供 SubAgent-RootCause 在 R1b/R2 根因判定时参考各阶段的执行轨迹（知识检索目标、产出物写入内容、中间推理过程）。

**回退策略**：如果 execution_trace.json 不存在（旧数据），aggregate_stats.py 回退到读取 trace_by_stage.json（如果存在），render_report.py 不渲染执行轨迹章节。

## repos-meta.json 结构

`repos-meta.json` 是 Phase 1 数据采集的最终产物，汇总了所有仓库的元数据和 commit 信息，供后续 Phase 2/3 使用。

```json
{
  "requirement_id": "94842225",
  "requirement_name": "满赠权益兑换优化",
  "developers": "zhangsan,lisi",
  "commit_developers": "zhangsan,lisi",
  "developer_source": "commit_chain",
  "fsd_url": "https://fsd.sankuai.com/...",
  "run_id": "yx-xxx-...",
  "session_id": "...",
  "agcr_value": 95.0,
  "commit_source": "sdk_log_washing",
  "target_final_commit_source": "remote_branch_head",
  "target_final_kind": "remote_branch_head",
  "code_source": "remote_code_platform",
  "remote_provider": "meituan_code_compare_api",
  "repos": [
    {
      "repo": "bizad_server",
      "branch": "feature/94842225-xxx",
      "base_commit": "a1b2c3d4e5f6789",
      "one_shot_commit": "f7e6d5c4b3a2918",
      "target_final_commit": "1a2b3c4d5e6f789",
      "change_summary": "满赠权益兑换接口新增 activityNo 参数"
    }
  ],
  "commit_gate": {
    "status": "passed",
    "missing": [],
    "invalid": [],
    "branch_errors": []
  }
}
```
