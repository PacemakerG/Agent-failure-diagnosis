#!/usr/bin/env python3
"""parse_execution_trace.py — 执行轨迹三层融合解析脚本。

三层融合策略：
  Layer 1: phases.json（直接读取）→ 阶段框架 + skill_invocation 事件
  Layer 2: commits.json（直接读取）→ git_commit 事件
  Layer 3: dag_*.json（定向解析）→ knowledge/write/reasoning/agent 事件

产出 execution_trace.json，供 SubAgent-RootCause 的 R1b/R2 核验和报告展示使用。

用法:
  python3 parse_execution_trace.py \\
      --cli-dir $OUTPUT_DIR/cli-washing/{session_id}/ \\
      --output $OUTPUT_DIR/artifacts/execution_trace.json
"""
import json
import sys
import collections
import argparse
import datetime
from pathlib import Path


# ─── Layer 1: Read phases.json ───────────────────────────────────────────────

def load_phases(phases_path):
    """Load phase framework and skill invocations from phases.json.

    phases.json provides:
    - Phase framework: phase_name, start/end time, start/end UUID
    - Skill invocations: skill name, invocation method (skill_tool/read_skill_file/agent_prompt), timestamp
    This covers §11.4's skill_invocation event type — more complete than dag parsing
    because agent_prompt references in sub-agent sessions are invisible in the parent dag.
    """
    with open(phases_path, "r", encoding="utf-8") as f:
        phases = json.load(f)

    stages = {}
    for p in phases:
        pname = p.get("phase_name", "unknown")
        stages[pname] = {
            "phase_name": pname,
            "start_time": p.get("start_time", ""),
            "end_time": p.get("end_time", ""),
            "start_uuid": p.get("start_uuid", ""),
            "end_uuid": p.get("end_uuid", ""),
            "skill_events": [
                {
                    "skill": s.get("skill", ""),
                    "via": s.get("via", ""),
                    "timestamp": s.get("timestamp", ""),
                }
                for s in p.get("skills", [])
            ],
        }
    return stages


# ─── Layer 2: Read commits.json ──────────────────────────────────────────────

def load_commits(commits_path, stages):
    """Load git commit events from commits.json, grouped by phase_name."""
    with open(commits_path, "r", encoding="utf-8") as f:
        commits = json.load(f)

    for c in commits:
        pname = c.get("phase_name", "unknown")
        if pname not in stages:
            stages[pname] = {
                "phase_name": pname,
                "skill_events": [],
                "start_time": "",
                "end_time": "",
            }
        stages[pname].setdefault("commit_events", []).append({
            "commit_id": c.get("commit_id", ""),
            "message": c.get("message", ""),
            "repo": c.get("repo", ""),
            "timestamp": c.get("timestamp", ""),
        })
    return stages


# ─── Layer 3: Targeted dag parsing ────────────────────────────────────────────

def classify_file(file_path):
    """Classify a file path into a category for write_events."""
    if not file_path:
        return "unknown"
    if "/tmp/" in file_path:
        return "temp"
    if ".yx-" in file_path or "current-requirement" in file_path:
        return "state_file"
    if file_path.endswith(".md") and "docs/" in file_path:
        return "artifact"
    if any(file_path.endswith(ext) for ext in (".java", ".thrift", ".xml", ".groovy")):
        return "code"
    if "AGENTS.md" in file_path or "CLAUDE.md" in file_path:
        return "config"
    return "other"


def classify_retrieval(tool_name, inp, bash_cmd=""):
    """Classify a retrieval operation into a retrieval_type for knowledge_events."""
    if tool_name == "Read":
        path = inp.get("file_path", "")
        if "docs/" in path or "artifacts/" in path:
            return "artifact_read"
        return "file_read"
    if tool_name in ("Grep", "Glob"):
        return "codebase_search"
    if tool_name == "Bash":
        if "km.sankuai.com" in bash_cmd or "citadel" in bash_cmd:
            return "km_document"
        if "grep" in bash_cmd or "rg " in bash_cmd:
            return "codebase_search"
        if "cat " in bash_cmd:
            return "file_read"
    return "other"


def parse_dag_targeted(dag_path, stage_data):
    """Parse dag_*.json for knowledge_events, write_events, reasoning_events, agent_events.

    Skips Skill tool_use (covered by phases.json Layer 1) and TodoWrite (not needed for R1b/R2).
    Only extracts Layer 3 specific fields not available in Layer 1/2.
    """
    with open(dag_path, "r", encoding="utf-8") as f:
        d = json.load(f)

    msgs = d.get("messages", [])
    node_type_counts = collections.Counter()
    knowledge_events = []
    write_events = []
    reasoning_events = []
    agent_events = []
    human_interaction_events = []
    tool_result_map = {}  # tool_use_id → result preview
    max_depth = [0]

    def walk(node, depth=0):
        ntype = node.get("type", "?")
        idx = node.get("index", -1)
        ts = node.get("timestamp", "")
        content = node.get("content", {})
        node_type_counts[ntype] += 1
        if depth > max_depth[0]:
            max_depth[0] = depth

        # Collect tool_result previews for later pairing with tool_use
        if ntype == "tool_result" and isinstance(content, dict):
            tool_use_id = content.get("tool_use_id", "")
            output = content.get("output", {})
            text = output.get("content", "") if isinstance(output, dict) else str(output)
            tool_result_map[tool_use_id] = text[:200] if text else ""

        # Process tool_use nodes (skip Skill and TodoWrite)
        if ntype == "tool_use" and isinstance(content, dict):
            tool_name = content.get("tool_name", "")
            inp = content.get("input", {})
            tool_use_id = content.get("tool_use_id", "")

            # Skip Skill — already covered by phases.json
            if tool_name == "Skill":
                pass

            # Skip TodoWrite — not needed for R1b/R2
            elif tool_name == "TodoWrite":
                pass

            # Agent spawn — extract description + prompt preview
            elif tool_name == "Agent":
                nested = inp.get("input", {}) if isinstance(inp, dict) and "input" in inp else {}
                if not nested and isinstance(inp, dict):
                    # Try direct fields
                    nested = inp
                agent_events.append({
                    "node_index": idx,
                    "timestamp": ts,
                    "description": nested.get("description", ""),
                    "prompt_preview": nested.get("prompt", "")[:200],
                })

            # Write/Edit/MultiEdit — R2 critical (compare reasoning vs actual write)
            elif tool_name in ("Write", "Edit", "MultiEdit"):
                file_path = inp.get("file_path", "")
                content_str = str(inp.get("content", inp.get("new_string", "")))
                write_events.append({
                    "node_index": idx,
                    "timestamp": ts,
                    "tool_name": tool_name,
                    "file_path": file_path,
                    "content_preview": content_str[:200],
                    "content_length": len(content_str),
                    "file_category": classify_file(file_path),
                })

            # Read — R1b critical (knowledge retrieval, skip skill-file reads)
            elif tool_name == "Read":
                file_path = inp.get("file_path", "")
                if ".claude/skills/" not in file_path:
                    knowledge_events.append({
                        "node_index": idx,
                        "timestamp": ts,
                        "tool_name": "Read",
                        "target": file_path,
                        "retrieval_type": classify_retrieval("Read", inp),
                        "result_preview": tool_result_map.get(tool_use_id, ""),
                    })

            # Grep/Glob — R1b codebase search
            elif tool_name in ("Grep", "Glob"):
                pattern = inp.get("pattern", inp.get("glob_pattern", ""))
                knowledge_events.append({
                    "node_index": idx,
                    "timestamp": ts,
                    "tool_name": tool_name,
                    "target": str(pattern)[:100],
                    "retrieval_type": "codebase_search",
                    "result_preview": tool_result_map.get(tool_use_id, ""),
                })

            # Bash — R1b if km/grep/cat, otherwise skip (not relevant for R1b/R2)
            elif tool_name == "Bash":
                cmd = inp.get("command", "")
                rtype = classify_retrieval("Bash", inp, cmd)
                if rtype != "other":
                    knowledge_events.append({
                        "node_index": idx,
                        "timestamp": ts,
                        "tool_name": "Bash",
                        "target": cmd[:100],
                        "retrieval_type": rtype,
                        "result_preview": tool_result_map.get(tool_use_id, ""),
                    })

        # thinking — R2 critical (intermediate reasoning)
        elif ntype == "thinking" and isinstance(content, dict):
            text = content.get("thinking", "")
            if len(text) > 30:  # Skip trivially short thinking nodes
                reasoning_events.append({
                    "node_index": idx,
                    "timestamp": ts,
                    "type": "thinking",
                    "thinking_preview": text[:200],
                })

        # assistant — R2 + report display
        elif ntype == "assistant" and isinstance(content, dict):
            for item in content.get("items", []):
                if item.get("type") == "text" and len(item.get("text", "")) > 30:
                    reasoning_events.append({
                        "node_index": idx,
                        "timestamp": ts,
                        "type": "assistant",
                        "text_preview": item["text"][:200],
                    })

        # user — human interaction (instructions, feedback, corrections)
        elif ntype == "user":
            text = ""
            if isinstance(content, str):
                text = content
            elif isinstance(content, dict):
                # Skip if this is actually a tool_result disguised as user
                items = content.get("items", [])
                if items:
                    text_parts = [item.get("text", "") for item in items
                                 if item.get("type") == "text"]
                    text = " ".join(text_parts)
                else:
                    text = content.get("text", "")
            if text and len(text.strip()) > 5:
                human_interaction_events.append({
                    "node_index": idx,
                    "timestamp": ts,
                    "text_preview": text[:200],
                })

        # Recursively walk children
        for child in node.get("children", []):
            walk(child, depth + 1)

    for msg in msgs:
        walk(msg)

    # Sessions summary
    sessions = d.get("sessions", [])
    session_summaries = [
        {
            "depth": s.get("depth", 0),
            "is_fork_point": s.get("is_fork_point", False),
            "is_compaction_point": s.get("is_compaction_point", False),
            "message_count": s.get("message_count", 0),
            "first_user_preview": (s.get("first_user_message", "") or "")[:100],
        }
        for s in sessions
    ]

    stage_data["dag_file"] = Path(dag_path).name
    stage_data["node_count"] = sum(node_type_counts.values())
    stage_data["tool_call_count"] = node_type_counts.get("tool_use", 0)
    stage_data["max_depth"] = max_depth[0]
    stage_data["node_type_counts"] = dict(node_type_counts)
    stage_data["sessions"] = session_summaries
    stage_data["knowledge_events"] = knowledge_events
    stage_data["write_events"] = write_events
    stage_data["reasoning_events"] = reasoning_events
    stage_data["agent_events"] = agent_events
    stage_data["human_interaction_events"] = human_interaction_events
    return stage_data


# ─── Timeline construction ────────────────────────────────────────────────────

def build_timeline(stage_data):
    """Build a merged timeline from skill_events, commit_events, and Layer 3 events.

    The timeline is sorted by node_index (or timestamp) and includes all event types
    for report rendering. Each event has a 'seq' for sequential ordering.
    """
    timeline = []

    # skill_invocation events from Layer 1
    for i, s in enumerate(stage_data.get("skill_events", [])):
        timeline.append({
            "seq": len(timeline),
            "timestamp": s.get("timestamp", ""),
            "type": "skill_invocation",
            "skill_name": s.get("skill", ""),
            "via": s.get("via", ""),
            "summary": f"调用 {s.get('skill', '?')} ({s.get('via', '?')})",
        })

    # git_commit events from Layer 2
    for c in stage_data.get("commit_events", []):
        timeline.append({
            "seq": len(timeline),
            "timestamp": c.get("timestamp", ""),
            "type": "git_commit",
            "commit_id": c.get("commit_id", ""),
            "message": c.get("message", "")[:100],
            "repo": c.get("repo", ""),
            "summary": f"commit {c.get('commit_id', '?')[:8]}: {c.get('message', '')[:50]}",
        })

    # knowledge_retrieval events from Layer 3
    for ke in stage_data.get("knowledge_events", []):
        timeline.append({
            "seq": len(timeline),
            "node_index": ke.get("node_index", -1),
            "timestamp": ke.get("timestamp", ""),
            "type": "knowledge_retrieval",
            "tool_name": ke.get("tool_name", ""),
            "target": ke.get("target", ""),
            "retrieval_type": ke.get("retrieval_type", ""),
            "result_preview": ke.get("result_preview", ""),
            "summary": f"{ke.get('tool_name', '?')}: {ke.get('target', '')[:50]}",
        })

    # file_write events from Layer 3
    for we in stage_data.get("write_events", []):
        timeline.append({
            "seq": len(timeline),
            "node_index": we.get("node_index", -1),
            "timestamp": we.get("timestamp", ""),
            "type": "file_write",
            "tool_name": we.get("tool_name", ""),
            "file_path": we.get("file_path", ""),
            "content_preview": we.get("content_preview", ""),
            "content_length": we.get("content_length", 0),
            "file_category": we.get("file_category", ""),
            "summary": f"{we.get('tool_name', '?')} → {Path(we.get('file_path', '?')).name}",
        })

    # agent_spawn events from Layer 3
    for ae in stage_data.get("agent_events", []):
        timeline.append({
            "seq": len(timeline),
            "node_index": ae.get("node_index", -1),
            "timestamp": ae.get("timestamp", ""),
            "type": "agent_spawn",
            "description": ae.get("description", ""),
            "prompt_preview": ae.get("prompt_preview", ""),
            "summary": f"Agent: {ae.get('description', '')[:50]}",
        })

    # human_interaction events from Layer 3
    for he in stage_data.get("human_interaction_events", []):
        text_preview = he.get("text_preview", "")
        timeline.append({
            "seq": len(timeline),
            "node_index": he.get("node_index", -1),
            "timestamp": he.get("timestamp", ""),
            "type": "human_interaction",
            "text_preview": text_preview,
            "summary": f"👤 {text_preview[:80]}",
        })

    # Sort by timestamp (fall back to node_index)
    timeline.sort(key=lambda e: (
        e.get("timestamp", "") or "",
        e.get("node_index", 0) if e.get("node_index", 0) >= 0 else 99999
    ))

    # Re-assign seq after sorting
    for i, event in enumerate(timeline):
        event["seq"] = i

    return timeline


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="执行轨迹三层融合解析：phases.json + commits.json + dag_*.json → execution_trace.json"
    )
    parser.add_argument(
        "--cli-dir", required=True,
        help="CLI 洗数目录路径（cli-washing/{session_id}/）"
    )
    parser.add_argument(
        "--output", required=True,
        help="输出路径（artifacts/execution_trace.json）"
    )
    args = parser.parse_args()

    cli_dir = Path(args.cli_dir)
    output_path = Path(args.output)

    # Validate input files
    phases_path = cli_dir / "phases.json"
    commits_path = cli_dir / "commits.json"

    if not phases_path.exists():
        print(f"Error: phases.json not found at {phases_path}", file=sys.stderr)
        sys.exit(1)

    # Layer 1: phases.json
    print(f"[Layer 1] Loading phases.json...")
    stages = load_phases(str(phases_path))
    print(f"  Found {len(stages)} stages")

    # Layer 2: commits.json
    if commits_path.exists():
        print(f"[Layer 2] Loading commits.json...")
        stages = load_commits(str(commits_path), stages)
        total_commits = sum(len(s.get("commit_events", [])) for s in stages.values())
        print(f"  Found {total_commits} commits across {len(stages)} stages")
    else:
        print(f"[Layer 2] commits.json not found, skipping")

    # Layer 3: dag_*.json (targeted parsing only)
    dag_files = sorted(cli_dir.glob("dag_*.json"))
    # Exclude dag.json (the combined file, if any)
    dag_files = [f for f in dag_files if f.name != "dag.json"]
    print(f"[Layer 3] Found {len(dag_files)} dag files to parse")

    for dag_file in dag_files:
        stage_name = dag_file.stem.replace("dag_", "")
        if stage_name in stages:
            print(f"  Parsing {dag_file.name} → stage '{stage_name}'")
            parse_dag_targeted(str(dag_file), stages[stage_name])
        else:
            # Stage in dag but not in phases.json — create skeleton
            print(f"  Parsing {dag_file.name} → new stage '{stage_name}'")
            stages[stage_name] = {
                "phase_name": stage_name,
                "skill_events": [],
                "start_time": "",
                "end_time": "",
            }
            parse_dag_targeted(str(dag_file), stages[stage_name])

    # Build timeline for each stage
    for name, s in stages.items():
        s["timeline"] = build_timeline(s)

    # Construct final result
    result = {
        "dag_dir": str(cli_dir),
        "generated_at": datetime.datetime.now().isoformat(),
        "stages": stages,
    }

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\nWritten: {output_path}")
    print(f"Stages: {len(stages)}")
    for name, s in stages.items():
        ke = len(s.get("knowledge_events", []))
        we = len(s.get("write_events", []))
        re_ = len(s.get("reasoning_events", []))
        se = len(s.get("skill_events", []))
        ce = len(s.get("commit_events", []))
        hi = len(s.get("human_interaction_events", []))
        tl = len(s.get("timeline", []))
        nc = s.get("node_count", 0)
        tc = s.get("tool_call_count", 0)
        print(f"  {name}: nodes={nc} tools={tc} skills={se} commits={ce} knowledge={ke} writes={we} reasoning={re_} human={hi} timeline={tl}")


if __name__ == "__main__":
    main()
