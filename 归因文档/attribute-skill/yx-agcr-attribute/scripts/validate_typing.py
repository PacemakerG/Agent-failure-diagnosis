#!/usr/bin/env python3
"""validate_typing.py — SubAgent-Typing 产出校验脚本。

校验 typing-result-{CI-xxx}.json 的字段完整性和一致性。
不通过时返回 exit code 1，主 Agent 应要求 SubAgent-Typing 重新执行。

用法:
  python3 validate_typing.py \\
      --frag-dir $OUTPUT_DIR/typing-results \\
      --config-dir $SKILL_DIR/config \\
      [--fix]

退出码:
  0 = 全部通过
  1 = 存在不可自动修复的校验失败
"""
import argparse
import glob
import json
import sys
from pathlib import Path


VALID_STAGES = {"N5", "N4", "N3", "N2", "N1"}


class ValidationError:
    def __init__(self, severity, field, message, fixable=False):
        self.severity = severity
        self.field = field
        self.message = message
        self.fixable = fixable

    def to_dict(self):
        return {
            "severity": self.severity,
            "field": self.field,
            "message": self.message,
            "fixable": self.fixable,
        }


def build_problem_type_map(config):
    """Build a lookup map: problem_type_id → {stage, label, evidence_type_default}."""
    pt_map = {}
    for stage in config.get("attribution_stages", []):
        stage_id = stage.get("stage", "")  # N5, N4, ...
        p_prefix = stage.get("id", "")  # P5, P4, ...
        for pt in stage.get("problem_types", []):
            pt_map[pt["id"]] = {
                "stage": stage_id,
                "stage_prefix": p_prefix,
                "label": pt.get("label", ""),
                "evidence_type_default": pt.get("evidence_type_default", "other"),
            }
    return pt_map


def build_decision_tree_map(config):
    """Build a lookup map: stage → {node_num → node_dict, entry_map}.
    Used for validating funnel_trace node numbers against the decision tree."""
    tree_map = {}
    for stage in config.get("attribution_stages", []):
        stage_id = stage.get("stage", "")
        dt = stage.get("decision_tree", {})
        nodes = {n["node"]: n for n in dt.get("nodes", [])}
        tree_map[stage_id] = {
            "nodes": nodes,
            "entry_map": dt.get("entry_map", {}),
        }
    return tree_map


# 偏差类型集合（不再跳过 root_cause，需通过 R1-R5 核验流程）
DEVIATION_TYPES = {"P3-11", "P4-14", "P5-4"}


def validate_fragment(frag_path, pt_map, tree_map):
    """Validate a single typing-result JSON file."""
    errors = []
    fixes = []

    with open(frag_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # ─── Required top-level fields ────────────────────────────────────────────
    required_fields = [
        "intent_id", "first_cause_stage", "problem_type",
        "problem_type_label", "funnel_trace", "evidence_detail",
        "root_cause_hints"
    ]
    for field in required_fields:
        if field not in data or data[field] is None:
            errors.append(ValidationError("error", field, f"{field} is missing or null"))

    # ─── first_cause_stage validation ────────────────────────────────────────
    stage = data.get("first_cause_stage", "")
    if stage and stage not in VALID_STAGES:
        errors.append(ValidationError("error", "first_cause_stage",
            f"Invalid stage '{stage}', must be one of {VALID_STAGES}"))

    # ─── problem_type validation ──────────────────────────────────────────────
    pt_id = data.get("problem_type", "")
    if pt_id:
        if pt_id not in pt_map:
            errors.append(ValidationError("error", "problem_type",
                f"Invalid problem_type '{pt_id}', not found in problem-types.json"))
        else:
            pt_info = pt_map[pt_id]

            # Check stage consistency: P-code prefix should match first_cause_stage
            expected_prefix = f"P{stage[1]}-" if stage else ""
            if expected_prefix and not pt_id.startswith(expected_prefix):
                errors.append(ValidationError("error", "problem_type",
                    f"problem_type '{pt_id}' (prefix {pt_info['stage_prefix']}) "
                    f"does not match first_cause_stage '{stage}' (expected prefix {expected_prefix})"))

            # Check problem_type_label consistency
            expected_label = pt_info.get("label", "")
            actual_label = data.get("problem_type_label", "")
            if expected_label and actual_label and actual_label != expected_label:
                errors.append(ValidationError("warning", "problem_type_label",
                    f"problem_type_label '{actual_label}' != expected '{expected_label}'",
                    fixable=True))
                if expected_label:
                    data["problem_type_label"] = expected_label
                    fixes.append(f"Auto-corrected problem_type_label to '{expected_label}'")

    # ─── funnel_trace validation ───────────────────────────────────────────────
    ft = data.get("funnel_trace")
    if ft:
        if not isinstance(ft, dict):
            errors.append(ValidationError("error", "funnel_trace",
                "funnel_trace must be an object"))
        else:
            if "entry_node" not in ft and "nodes_checked" not in ft:
                errors.append(ValidationError("warning", "funnel_trace",
                    "funnel_trace should have entry_node or nodes_checked"))

            nodes_checked = ft.get("nodes_checked", [])
            if nodes_checked:
                # 获取该阶段的决策树
                stage_tree = tree_map.get(stage, {})
                valid_nodes = stage_tree.get("nodes", {})
                entry_map = stage_tree.get("entry_map", {})

                for i, nc in enumerate(nodes_checked):
                    if "node" not in nc:
                        errors.append(ValidationError("warning",
                            f"funnel_trace.nodes_checked[{i}].node",
                            "node field is missing"))
                    else:
                        node_num = nc["node"]
                        # N3 及其他阶段节点有效性校验
                        if valid_nodes and node_num not in valid_nodes:
                            errors.append(ValidationError("error",
                                f"funnel_trace.nodes_checked[{i}].node",
                                f"node {node_num} is not a valid node in {stage} decision tree "
                                f"(valid nodes: {sorted(valid_nodes.keys())})"))

                    if "answer" not in nc:
                        errors.append(ValidationError("warning",
                            f"funnel_trace.nodes_checked[{i}].answer",
                            "answer field is missing"))
                    elif nc["answer"] not in ("yes", "no"):
                        errors.append(ValidationError("error",
                            f"funnel_trace.nodes_checked[{i}].answer",
                            f"answer must be 'yes' or 'no', got '{nc['answer']}'"))

                # 校验 entry_node 与 defect_category 的一致性
                entry_node = ft.get("entry_node")
                defect_category = ft.get("defect_category")
                if entry_node and defect_category and entry_map:
                    expected_entry = entry_map.get(defect_category)
                    if expected_entry and entry_node != expected_entry:
                        errors.append(ValidationError("warning",
                            "funnel_trace.entry_node",
                            f"entry_node={entry_node} but defect_category='{defect_category}' "
                            f"maps to node {expected_entry} in {stage} entry_map"))
    else:
        errors.append(ValidationError("error", "funnel_trace",
            "funnel_trace is missing"))

    # ─── evidence_detail validation ───────────────────────────────────────────
    ed = data.get("evidence_detail")
    if ed:
        if not isinstance(ed, dict):
            errors.append(ValidationError("error", "evidence_detail",
                "evidence_detail must be an object"))
        else:
            ed_required = ["artifact"]
            for field in ed_required:
                if not ed.get(field):
                    errors.append(ValidationError("warning",
                        f"evidence_detail.{field}",
                        f"{field} is empty"))
    else:
        errors.append(ValidationError("error", "evidence_detail",
            "evidence_detail is missing"))

    # ─── root_cause_hints validation ──────────────────────────────────────────
    rch = data.get("root_cause_hints")
    if rch:
        if not isinstance(rch, dict):
            errors.append(ValidationError("error", "root_cause_hints",
                "root_cause_hints must be an object"))
        else:
            # N1/P1-3 special case: no root_cause_hints needed
            if pt_id == "P1-3":
                pass  # P1-3 has no root cause, hints not required
            # 偏差类型校验: 不再跳过 root_cause，需有 root_cause_hints
            if pt_id in DEVIATION_TYPES:
                if not rch.get("root_cause") and not rch.get("root_cause_candidates"):
                    errors.append(ValidationError("warning",
                        "root_cause_hints",
                        f"{pt_id} is a deviation type — root_cause_hints should contain "
                        f"root_cause candidates (R1-R5) for RootCause subagent verification"))
            else:
                rch_recommended = ["knowledge_artifact", "upstream_artifact"]
                for field in rch_recommended:
                    if not rch.get(field):
                        errors.append(ValidationError("warning",
                            f"root_cause_hints.{field}",
                            f"{field} is empty — needed for RootCause step"))
    else:
        if pt_id != "P1-3":
            errors.append(ValidationError("error", "root_cause_hints",
                "root_cause_hints is missing"))

    # ─── Auto-fixable: problem_type_label ────────────────────────────────────
    if fixes and args_fix:
        with open(frag_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    return errors, fixes


# Module-level flag for --fix
args_fix = False


def main():
    global args_fix
    parser = argparse.ArgumentParser(
        description="SubAgent-Typing 产出校验脚本"
    )
    parser.add_argument("--frag-dir", required=True, help="typing-results 目录路径")
    parser.add_argument("--config-dir", required=True, help="config 目录路径")
    parser.add_argument("--fix", action="store_true", help="自动修复可修复的问题")
    args = parser.parse_args()
    args_fix = args.fix

    # Load config
    config_path = Path(args.config_dir) / "problem-types.json"
    if not config_path.exists():
        print(json.dumps({"status": "error", "message": f"Config not found: {config_path}"}, ensure_ascii=False))
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    pt_map = build_problem_type_map(config)
    tree_map = build_decision_tree_map(config)

    # Find all typing-result files
    frag_pattern = str(Path(args.frag_dir) / "typing-result-*.json")
    frag_files = sorted(glob.glob(frag_pattern))

    if not frag_files:
        single_file = Path(args.frag_dir)
        if single_file.is_file() and single_file.suffix == ".json":
            frag_files = [str(single_file)]

    if not frag_files:
        print(json.dumps({
            "status": "warning",
            "message": f"No typing-result files found in {args.frag_dir}"
        }, ensure_ascii=False))
        return

    all_errors = []
    all_fixes = []
    has_blocking = False

    for frag_path in frag_files:
        errors, fixes = validate_fragment(frag_path, pt_map, tree_map)
        blocking = [e for e in errors if e.severity == "error"]

        if blocking:
            has_blocking = True

        all_errors.extend([{**e.to_dict(), "file": frag_path} for e in errors])
        all_fixes.extend(fixes)

    report = {
        "total_files": len(frag_files),
        "total_errors": len([e for e in all_errors if e["severity"] == "error"]),
        "total_warnings": len([e for e in all_errors if e["severity"] == "warning"]),
        "has_blocking": has_blocking,
        "errors": all_errors,
        "fixes": all_fixes,
    }

    print(json.dumps(report, ensure_ascii=False, indent=2))

    if has_blocking:
        sys.exit(1)


if __name__ == "__main__":
    main()
