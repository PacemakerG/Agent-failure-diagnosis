#!/usr/bin/env python3
"""navigate_decision_tree.py — 决策树导航脚本。

LLM 只回答 yes/no，脚本负责节点跳转和命中判定。
消费 config/problem-types.json 中的 decision_tree 结构化数据。

用法:
  # 启动导航（根据 defect_category 跳到起始节点）
  python3 navigate_decision_tree.py --problem-types config/problem-types.json --stage N4 --defect-category existence
  # 输出: {"status": "ask", "node": 1, "question": "design.md 中的技术方案选型..."}

  # LLM 回答后继续（提交一组 yes/no 答案）
  python3 navigate_decision_tree.py --problem-types config/problem-types.json --stage N4 --answers '["no"]'
  # 输出: {"status": "hit", "node": 1, "problem_type": "P4-1", ...}

  # 或多步导航
  python3 navigate_decision_tree.py --problem-types config/problem-types.json --stage N4 --defect-category existence --answers '["yes", "yes", "no"]'
  # 输出: {"status": "hit", "node": 3, "problem_type": "P4-3", ...}

  # 查看特定阶段的完整决策树
  python3 navigate_decision_tree.py --problem-types config/problem-types.json --stage N4 --dump
"""
import json
import argparse
import sys
from pathlib import Path


def load_config(problem_types_path):
    """加载 problem-types.json 配置文件。"""
    with open(problem_types_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_stage_config(config, stage):
    """根据 stage 标识符（N5/N4/N3/N2/N1）找到对应的阶段配置。"""
    for s in config.get("attribution_stages", []):
        if s.get("stage") == stage:
            return s
    return None


def get_decision_tree(config, stage):
    """获取指定阶段的决策树。"""
    stage_config = get_stage_config(config, stage)
    if not stage_config:
        raise ValueError(f"Stage '{stage}' not found in problem-types.json")
    tree = stage_config.get("decision_tree")
    if not tree:
        raise ValueError(f"Stage '{stage}' has no decision_tree field")
    return tree


def determine_start_node(tree, defect_category=None):
    """根据 defect_category 确定起始节点。"""
    entry_map = tree.get("entry_map", {})
    if defect_category and defect_category in entry_map:
        return entry_map[defect_category]
    return 1  # 默认从第 1 节点开始


def navigate(config_path, stage, defect_category=None, answers=None):
    """根据 answers 列表导航决策树，返回命中类型或下一节点问题。

    Args:
        config_path: problem-types.json 路径
        stage: 阶段标识符（N5/N4/N3/N2/N1）
        defect_category: 缺陷类别（existence/correctness/completeness/execution_deviation）
        answers: yes/no 答案列表

    Returns:
        dict: 导航结果
            - status: "ask"（需要 LLM 回答）/ "hit"（命中类型）/ "all_passed"（全部通过）
            - node: 当前节点编号
            - question: 当前节点问题（status=ask 时）
            - problem_type: 命中的类型（status=hit 时）
            - skip_rootcause: 是否跳过根因判定（status=hit 时）
            - forced_root_cause: 强制根因（status=hit 时）
    """
    config = load_config(config_path)
    tree = get_decision_tree(config, stage)
    nodes = {n["node"]: n for n in tree["nodes"]}

    # 确定起始节点
    current_node = determine_start_node(tree, defect_category)

    # 如果有 answers，逐步导航
    if answers:
        for i, answer in enumerate(answers):
            if current_node not in nodes:
                return {
                    "status": "error",
                    "error": f"Node {current_node} not found in decision tree",
                    "last_answered": i
                }

            node = nodes[current_node]

            if answer == "yes":
                next_node = node.get("yes_next")
                if next_node is None:
                    # 全部通过，与穿透判定矛盾
                    return {
                        "status": "all_passed",
                        "last_node": current_node,
                        "message": "All nodes passed — contradicts penetration result. "
                                   "Use fallback: take last node's no_type with confidence=low."
                    }
                current_node = next_node

            elif answer == "no":
                result = {
                    "status": "hit",
                    "node": current_node,
                    "problem_type": node["no_type"],
                    # no_skip_rootcause 已从 problem-types.json 中移除，
                    # 偏差节点不再跳过 root_cause，通过 R1-R5 核验流程判定
                    "skip_rootcause": False,
                    "forced_root_cause": None,
                }
                # 附加 evidence_type_default 和 problem_type_label
                stage_config = get_stage_config(config, stage)
                pt_found = False
                for pt in stage_config.get("problem_types", []):
                    if pt["id"] == node["no_type"]:
                        result["evidence_type_default"] = pt.get("evidence_type_default", "other")
                        result["problem_type_label"] = pt.get("label", "")
                        pt_found = True
                        break
                if not pt_found:
                    result["validation_warning"] = (
                        f"problem_type '{node['no_type']}' not found in stage {stage}'s "
                        f"problem_types list — check problem-types.json"
                    )
                return result

            else:
                return {
                    "status": "error",
                    "error": f"Invalid answer '{answer}' at position {i}. Use 'yes' or 'no'."
                }

    # 返回当前节点问题（等待 LLM 回答）
    if current_node not in nodes:
        return {
            "status": "error",
            "error": f"Node {current_node} not found in decision tree"
        }

    node = nodes[current_node]
    return {
        "status": "ask",
        "node": current_node,
        "question": node["question"],
        "entry_source": f"defect_category: {defect_category}" if defect_category else "default"
    }


def validate_tree(config_path, stage):
    """校验决策树完整性：no_type 引用的 problem_type 是否存在，problem_types 是否被引用。"""
    config = load_config(config_path)
    stage_config = get_stage_config(config, stage)
    if not stage_config:
        return {"status": "error", "error": f"Stage '{stage}' not found"}

    tree = stage_config.get("decision_tree", {})
    nodes = tree.get("nodes", [])
    problem_types = stage_config.get("problem_types", [])

    # 收集所有 no_type
    no_types_in_tree = set()
    for n in nodes:
        nt = n.get("no_type")
        if nt:
            no_types_in_tree.add(nt)

    # 收集所有 problem_type id
    pt_ids = set(pt["id"] for pt in problem_types)

    # 检查: tree 中的 no_type 是否都在 problem_types 中
    orphan_no_types = no_types_in_tree - pt_ids

    # 检查: problem_types 是否都被 tree 引用
    unreferenced_pts = pt_ids - no_types_in_tree

    # 检查: entry_map 引用的节点是否存在
    entry_map = tree.get("entry_map", {})
    node_ids = set(n["node"] for n in nodes)
    invalid_entry = {k: v for k, v in entry_map.items() if v not in node_ids}

    # 检查: yes_next 引用的节点是否存在
    broken_yes_next = []
    for n in nodes:
        yn = n.get("yes_next")
        if yn is not None and yn not in node_ids:
            broken_yes_next.append({"node": n["node"], "yes_next": yn})

    return {
        "status": "ok" if not (orphan_no_types or unreferenced_pts or invalid_entry or broken_yes_next) else "issues",
        "stage": stage,
        "tree_nodes": len(nodes),
        "problem_types": len(problem_types),
        "orphan_no_types": sorted(orphan_no_types),
        "unreferenced_problem_types": sorted(unreferenced_pts),
        "invalid_entry_map": invalid_entry,
        "broken_yes_next": broken_yes_next,
    }


def dump_tree(config_path, stage):
    """输出指定阶段的完整决策树结构。"""
    config = load_config(config_path)
    tree = get_decision_tree(config, stage)
    return tree


def main():
    parser = argparse.ArgumentParser(
        description="决策树导航脚本。LLM 只回答 yes/no，脚本负责节点跳转和命中判定。"
    )
    parser.add_argument(
        "--problem-types", required=True,
        help="problem-types.json 路径"
    )
    parser.add_argument(
        "--stage", required=True,
        help="阶段标识符：N5/N4/N3/N2/N1"
    )
    parser.add_argument(
        "--defect-category", default=None,
        help="缺陷类别：existence/correctness/completeness/execution_deviation"
    )
    parser.add_argument(
        "--answers", default=None,
        help='JSON 数组，如 \'["yes", "no"]\''
    )
    parser.add_argument(
        "--dump", action="store_true",
        help="输出完整决策树结构（调试用）"
    )
    parser.add_argument(
        "--validate", action="store_true",
        help="校验决策树完整性（no_type 引用 / problem_types 引用 / entry_map / yes_next）"
    )
    args = parser.parse_args()

    if args.dump:
        result = dump_tree(args.problem_types, args.stage)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.validate:
        result = validate_tree(args.problem_types, args.stage)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    answers = None
    if args.answers:
        try:
            answers = json.loads(args.answers)
        except json.JSONDecodeError as e:
            print(json.dumps({"status": "error", "error": f"Invalid answers JSON: {e}"}, ensure_ascii=False))
            sys.exit(1)

    result = navigate(args.problem_types, args.stage, args.defect_category, answers)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
