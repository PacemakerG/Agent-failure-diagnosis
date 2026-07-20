#!/usr/bin/env python3
"""
normalize_hunks.py — 对 SubAgent-Attribution 输出的 intent fragment 做确定性归一化。

intent-fragments/ 是归因结果的唯一输出目录。每个 intent fragment
是 SubAgent-Attribution 三步归因的完整输出（穿透→类型→根因）。
本脚本加载 hunk-list.json（元数据真相源），按 hunk_id 聚合计算 intent 级 impact，
归一化 evidence_chain 字段，并做 Schema 验证。

用法：
  python3 normalize_hunks.py \
    --frag-dir  "$OUTPUT_DIR/intent-fragments" \
    --hunk-list "$OUTPUT_DIR/hunks/hunk-list.json" \
    --config-dir "$SKILL_DIR/config"

执行步骤：
  1. 加载 hunk-list.json，构建 hunk_id → 元数据 查找表
  2. 遍历 intent fragment 文件，归一化字段
  3. 从 hunk_ids 聚合计算 intent 级 impact（removed_lines / added_lines）
  4. evidence_chain 字段归一化（阶段名、before_vs_artifact）
  5. 字段名别名归一化（清理 SubAgent 可能输出的非标准字段名）
  6. 字段类型归一化（dict/list → string）
  7. Schema 验证（输出报告，不阻塞）
"""

import argparse
import json
import os
import sys
import glob

# ── 常量 ─────────────────────────────────────────────────────────────────────

# 非标准字段名 → 标准字段名（None = 移除）
FIELD_ALIASES = {
    "semantic_description": "change_summary",
    "hunk_description": "change_summary",
    "p_category": "problem_type",
    "p_sub_type": "root_cause_variant",
    "p_category_label": "problem_type_label",
    "surface_issue_label": None,
    "diff_lines": None,
    "one_shot_code_snippet": None,
    "final_code_snippet": None,
    "diff_snippet": None,
    "status": None,
}

# dict/list 字段 → 转 string
STRING_FIELDS = [
    "knowledge_check", "artifact_manifestation", "root_cause_verdict",
    "propagation_path", "direct_cause", "recommendation",
    "root_cause_evidence", "downstream_propagation",
    "change_summary", "before_code_summary",
]

# evidence_chain 每条记录的字段
EC_FIELDS = [
    "stage", "artifact", "finding", "before_vs_artifact",
    "artifact_snippet", "upstream_artifact", "upstream_finding",
    "upstream_snippet",
]

# 阶段名归一化
STAGE_NAME_MAP = {
    "N5": "N5 编码计划", "N4": "N4 技术方案", "N3": "N3 需求澄清",
    "N2": "N2 现状梳理", "N1": "N1 项目初始化",
    "N5 编码计划": "N5 编码计划", "N4 技术方案": "N4 技术方案",
    "N3 需求澄清": "N3 需求澄清", "N2 现状梳理": "N2 现状梳理",
    "N1 项目初始化": "N1 项目初始化",
}

# intent 级必填字段
REQUIRED_FIELDS = [
    "intent_id", "diff_nature",
    "surface_issue_type",
    "problem_type", "root_cause", "confidence",
    "first_cause_stage", "first_cause_nature",
    "evidence_chain",
    "direct_cause", "propagation_path", "recommendation",
    "knowledge_check", "artifact_manifestation", "root_cause_verdict",
    "hunk_ids",
]

# list 类型字段（允许空 list，只需 key 存在）
LIST_FIELDS = {"hunk_ids", "additional_tags", "evidence_missing_stages"}

# 可选字段（存在时归一化，不存在时不报错）
OPTIONAL_FIELDS = [
    "first_cause_skill", "problem_type_label", "root_cause_label",
    "root_cause_variant", "root_cause_evidence",
    "attribution_direction", "downstream_propagation",
    "additional_tags", "funnel_trace",
    "before_code_summary", "change_summary",
    "intent_label", "intent_descriptions",
    "evidence_type", "evidence_type_source", "evidence_type_derivation",
    "structure_type", "structure_type_source", "structure_type_derivation",
    "clustering_confidence", "is_composite", "pdg_edges",
]

# 元数据字段（从 hunk-list.json 聚合到 intent 级）
HUNK_METADATA_FIELDS = [
    "repo", "file", "old_start", "old_lines", "new_start", "new_lines",
    "symbol_hint", "change_summary", "source_commits", "commit_message",
    "task_ref", "removed_lines", "added_lines",
    "excluded", "exclude_reason",
    "related_hunks", "is_companion_of",
    "design_item_ref", "file_path", "symbol_type", "enclosing_class",
]


def load_hunk_list(hunk_list_path):
    """加载 hunk-list.json，构建 hunk_id → 元数据 查找表。"""
    if not os.path.isfile(hunk_list_path):
        print(f"[normalize] WARNING: hunk-list.json not found at {hunk_list_path}")
        return {}

    with open(hunk_list_path, encoding="utf-8") as f:
        hunks = json.load(f)

    lookup = {}
    for h in hunks:
        hid = h.get("hunk_id")
        if hid:
            lookup[hid] = h
    print(f"[normalize] Loaded {len(lookup)} hunks from hunk-list.json")
    return lookup


def load_problem_type_to_sit(config_dir):
    """从 problem-types.json 构建 problem_type → surface_issue_type 映射。"""
    path = os.path.join(config_dir, "problem-types.json")
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    pt_to_sit = {}
    for st in cfg.get("attribution_stages", []):
        for pt in st.get("problem_types", []):
            for rv in pt.get("root_cause_variants", []):
                sit = rv.get("surface_issue_type", "")
                if sit:
                    pt_to_sit[pt["id"]] = sit
                    break
    return pt_to_sit


def load_problem_type_to_evidence_type(config_dir):
    """从 problem-types.json 构建 problem_type → evidence_type_default 映射。"""
    path = os.path.join(config_dir, "problem-types.json")
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    pt_to_et = {}
    for st in cfg.get("attribution_stages", []):
        for pt in st.get("problem_types", []):
            et = pt.get("evidence_type_default", "")
            if et:
                pt_to_et[pt["id"]] = et
    return pt_to_et


# first_cause_stage → first_cause_skill 固定映射
STAGE_TO_SKILL = {
    "N5": "yx-code",
    "N4": "yx-plan",
    "N3": "yx-requirement",
    "N2": "yx-state",
    "N1": "yx-init",
    "N5 编码计划": "yx-code",
    "N4 技术方案": "yx-plan",
    "N3 需求澄清": "yx-requirement",
    "N2 现状梳理": "yx-state",
    "N1 项目初始化": "yx-init",
}

# first_cause_nature → attribution_direction 固定映射
NATURE_TO_DIRECTION = {
    "product_defect": "artifact_defect",
    "ai_deviation": "execution_deviation",
    "prd_quality": "artifact_defect",
}


def derive_evidence_type(problem_type, first_cause_nature, root_cause, pt_to_et):
    """从 problem_type 确定性推导 evidence_type，不依赖 LLM 措辞。"""
    # 特殊类型优先
    if first_cause_nature == "prd_quality" or problem_type == "P1-3":
        return "prd_quality"
    # 从 problem-types.json 读取 evidence_type_default
    et = pt_to_et.get(problem_type)
    if et:
        return et
    # R1 根因 + 知识缺失证据
    if root_cause == "R1":
        return "knowledge_gap"
    return "other"


def to_string(val):
    """dict/list → json string，其他 → string。"""
    if val is None:
        return ""
    if isinstance(val, (dict, list)):
        return json.dumps(val, ensure_ascii=False)
    return str(val)


def compute_intent_impact(hunk_ids, hunk_lookup):
    """从 hunk_ids 聚合计算 intent 级 impact。"""
    total_removed = 0
    total_added = 0
    involved_repos = set()
    involved_files = set()

    for hid in hunk_ids:
        meta = hunk_lookup.get(hid)
        if meta:
            total_removed += meta.get("removed_lines", 0) or 0
            total_added += meta.get("added_lines", 0) or 0
            if meta.get("repo"):
                involved_repos.add(meta["repo"])
            if meta.get("file") or meta.get("file_path"):
                involved_files.add(meta.get("file") or meta.get("file_path"))

    return {
        "total_removed_lines": total_removed,
        "total_added_lines": total_added,
        "involved_repos": sorted(involved_repos),
        "involved_files": sorted(involved_files),
        "hunk_count": len(hunk_ids),
    }


def normalize_intent(intent, hunk_lookup, pt_to_sit, pt_to_et=None):
    """对单个 intent fragment 做归一化，返回 (intent, fixes_count)。"""
    fixes = 0

    # 1. 字段名别名归一化（清理非标准字段名）
    for alias, target in FIELD_ALIASES.items():
        if alias in intent:
            val = intent.pop(alias)
            if target and not intent.get(target):
                intent[target] = val
                fixes += 1

    # 2. 字段类型归一化
    for field in STRING_FIELDS:
        if field in intent:
            val = intent[field]
            if isinstance(val, (dict, list)):
                intent[field] = json.dumps(val, ensure_ascii=False)
                fixes += 1

    # 3. evidence_chain 归一化
    ec = intent.get("evidence_chain", [])
    if not isinstance(ec, list):
        intent["evidence_chain"] = []
        fixes += 1
        ec = []
    for entry in ec:
        if not isinstance(entry, dict):
            continue
        # 阶段名归一化
        stage = entry.get("stage", "")
        if stage in STAGE_NAME_MAP and stage != STAGE_NAME_MAP[stage]:
            entry["stage"] = STAGE_NAME_MAP[stage]
            fixes += 1
        # 确保所有 EC_FIELDS 都存在
        for f in EC_FIELDS:
            if f not in entry:
                entry[f] = None
                fixes += 1
        # artifact_snippet / upstream_snippet 类型归一化
        for f in ["artifact_snippet", "upstream_snippet"]:
            if isinstance(entry.get(f), (dict, list)):
                entry[f] = json.dumps(entry[f], ensure_ascii=False)

    # 4. hunk_ids 确保 list
    hunk_ids = intent.get("hunk_ids")
    if not isinstance(hunk_ids, list):
        intent["hunk_ids"] = []
        fixes += 1
        hunk_ids = []

    # 5. additional_tags 确保 list
    at = intent.get("additional_tags")
    if at is not None and not isinstance(at, list):
        intent["additional_tags"] = [to_string(at)] if at else []
        fixes += 1
    elif at is None:
        intent.setdefault("additional_tags", [])

    # 6. evidence_missing_stages 确保 list
    ems = intent.get("evidence_missing_stages")
    if not isinstance(ems, list):
        intent["evidence_missing_stages"] = []
        fixes += 1

    # 7. 补全 surface_issue_type（如果缺失，从 problem_type 推断）
    if not intent.get("surface_issue_type"):
        pt = intent.get("problem_type", "")
        sit = pt_to_sit.get(pt, "OTHER")
        intent["surface_issue_type"] = sit
        intent["surface_issue_type_source"] = "enum" if sit in pt_to_sit else "custom"
        fixes += 1
    elif not intent.get("surface_issue_type_source"):
        intent["surface_issue_type_source"] = "enum"
        fixes += 1

    # 8. first_cause_stage 阶段名归一化
    fcs = intent.get("first_cause_stage", "")
    if fcs in STAGE_NAME_MAP and fcs != STAGE_NAME_MAP[fcs]:
        intent["first_cause_stage"] = STAGE_NAME_MAP[fcs]
        fixes += 1

    # 8a. 补全 first_cause_skill（从 first_cause_stage 确定性推导）
    stage_key = intent.get("first_cause_stage", "")
    expected_skill = STAGE_TO_SKILL.get(stage_key, "")
    if expected_skill and intent.get("first_cause_skill") != expected_skill:
        intent["first_cause_skill"] = expected_skill
        fixes += 1

    # 8b. 补全 attribution_direction（从 first_cause_nature 确定性推导）
    nature = intent.get("first_cause_nature", "")
    expected_dir = NATURE_TO_DIRECTION.get(nature, "")
    if expected_dir and intent.get("attribution_direction") != expected_dir:
        intent["attribution_direction"] = expected_dir
        fixes += 1

    # 8c. 补全 evidence_type（从 problem_type → evidence_type_default 确定性推导）
    if pt_to_et is not None:
        pt = intent.get("problem_type", "")
        rc = intent.get("root_cause", "")
        derived_et = derive_evidence_type(pt, nature, rc, pt_to_et)
        if intent.get("evidence_type") != derived_et:
            intent["evidence_type"] = derived_et
            intent["evidence_type_source"] = "derived"
            intent["evidence_type_derivation"] = f"problem_type {pt} → evidence_type_default: {derived_et}" if pt else "fallback: other"
            fixes += 1

    # 8d. 补全 structure_type（从 is_composite 确定性推导）
    is_comp = intent.get("is_composite", False)
    derived_st = "composite" if is_comp else "single"
    if intent.get("structure_type") != derived_st:
        intent["structure_type"] = derived_st
        intent["structure_type_source"] = "derived"
        intent["structure_type_derivation"] = f"R-S1: is_composite = {is_comp}" if is_comp else f"R-S2: is_composite = {is_comp}"
        fixes += 1

    # 9. 从 hunk_ids 聚合计算 impact（覆写 SubAgent 可能输出的值）
    impact = compute_intent_impact(hunk_ids, hunk_lookup)
    existing_impact = intent.get("impact", {})
    if isinstance(existing_impact, dict):
        # 保留 SubAgent 可能计算的 abandonment_impact / agcr_impact
        # 但用 hunk-list.json 的确定值覆写行数统计
        existing_impact["total_removed_lines"] = impact["total_removed_lines"]
        existing_impact["total_added_lines"] = impact["total_added_lines"]
        intent["impact"] = existing_impact
    else:
        intent["impact"] = impact
    fixes += 1  # impact 总是更新

    # 10. 补全 involved_repos / involved_files（方便下游聚合）
    if not intent.get("involved_repos"):
        intent["involved_repos"] = impact["involved_repos"]
    if not intent.get("involved_files"):
        intent["involved_files"] = impact["involved_files"]

    return intent, fixes


def normalize_fragment(frag_path, hunk_lookup, pt_to_sit, pt_to_et=None):
    """归一化单个 intent fragment 文件。

    fragment 格式：每个文件是一个 intent 的完整归因结果（JSON 对象）。
    兼容 {"intents": [...]} 和 {"hunks": [...]} 包装格式。
    """
    with open(frag_path, encoding="utf-8") as f:
        data = json.load(f)

    # 兼容多种格式：
    # 1. 直接 intent 对象（标准格式）
    # 2. {"intents": [...]} 包装
    # 3. {"hunks": [...]} 包装（兼容格式，按 hunk 处理）
    if isinstance(data, dict) and "intent_id" in data:
        # 单个 intent 对象
        intent, fixes = normalize_intent(data, hunk_lookup, pt_to_sit, pt_to_et)
        with open(frag_path, "w", encoding="utf-8") as f:
            json.dump(intent, f, ensure_ascii=False, indent=2)
        return 1, fixes
    elif isinstance(data, dict) and "intents" in data:
        # intents 列表包装
        intents = data["intents"]
        total_fixes = 0
        for intent in intents:
            intent, fixes = normalize_intent(intent, hunk_lookup, pt_to_sit, pt_to_et)
            total_fixes += fixes
        with open(frag_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return len(intents), total_fixes
    elif isinstance(data, dict) and "hunks" in data:
        # 兼容格式：hunks 列表，逐个归一化
        hunks = data["hunks"]
        total_fixes = 0
        for h in hunks:
            h, fixes = normalize_intent(h, hunk_lookup, pt_to_sit, pt_to_et)
            total_fixes += fixes
        with open(frag_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return len(hunks), total_fixes
    else:
        print(f"[normalize] WARNING: unknown fragment format in {frag_path}")
        return 0, 0


def validate_fragments(frag_dir):
    """验证所有 intent fragment 的必填字段。"""
    total = 0
    passed = 0
    failed = 0
    failures = []

    for frag_path in sorted(glob.glob(os.path.join(frag_dir, "*.json"))):
        with open(frag_path, encoding="utf-8") as f:
            data = json.load(f)

        # 提取 intent 对象列表
        intents = []
        if isinstance(data, dict) and "intent_id" in data:
            intents = [data]
        elif isinstance(data, dict) and "intents" in data:
            intents = data["intents"]
        elif isinstance(data, dict) and "hunks" in data:
            intents = data["hunks"]

        for intent in intents:
            total += 1
            empty = []
            for field in REQUIRED_FIELDS:
                val = intent.get(field)
                if field in LIST_FIELDS:
                    if field not in intent:
                        empty.append(field)
                elif not val or (isinstance(val, list) and len(val) == 0):
                    # root_cause 允许为 null（P1-3 PRD 质量问题）
                    if field == "root_cause" and val is None:
                        continue
                    empty.append(field)
            if empty:
                failed += 1
                failures.append(f"{intent.get('intent_id', '?')}: {empty}")
            else:
                passed += 1

    return total, passed, failed, failures


def main():
    ap = argparse.ArgumentParser(
        description="归一化 SubAgent-Attribution 输出的 intent fragment 文件（intent 级归一化）"
    )
    ap.add_argument("--frag-dir", required=True, help="intent-fragments 目录")
    ap.add_argument("--hunk-list", required=True, help="hunk-list.json 路径（元数据真相源）")
    ap.add_argument("--config-dir", required=True, help="config 目录（含 problem-types.json）")
    args = ap.parse_args()

    frag_dir = args.frag_dir
    config_dir = args.config_dir
    hunk_list_path = args.hunk_list

    # 1. 加载 hunk-list.json
    hunk_lookup = load_hunk_list(hunk_list_path)

    # 2. 加载 problem-types.json
    pt_to_sit = load_problem_type_to_sit(config_dir)
    pt_to_et = load_problem_type_to_evidence_type(config_dir)

    total_intents = 0
    total_fixes = 0

    for frag_path in sorted(glob.glob(os.path.join(frag_dir, "*.json"))):
        frag_name = os.path.basename(frag_path).replace(".json", "")
        intent_count, fixes = normalize_fragment(frag_path, hunk_lookup, pt_to_sit, pt_to_et)
        total_intents += intent_count
        total_fixes += fixes
        print(f"[normalize] {frag_name}: {intent_count} intents, {fixes} fixes")

    # 3. Schema 验证
    total, passed, failed, failures = validate_fragments(frag_dir)

    print(f"\n[normalize] total: {total_intents} intents, {total_fixes} field fixes")
    print(f"[normalize] validation: {passed}/{total} passed, {failed} failed")
    if failures:
        print("[normalize] FAILURES:")
        for fmsg in failures[:20]:
            print(f"  [FAIL] {fmsg}")
        if len(failures) > 20:
            print(f"  ... and {len(failures) - 20} more")


if __name__ == "__main__":
    raise SystemExit(main())
