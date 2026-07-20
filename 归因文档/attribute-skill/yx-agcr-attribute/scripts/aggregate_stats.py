#!/usr/bin/env python3
"""
Phase 3 Step 9: Aggregate statistics from intent fragments into attribution-result.json.

Processes intent-fragments/ (intent-level attribution results). Each intent
fragment is the complete output of SubAgent-Attribution's three-step process
(penetration → typing → root cause).

Aggregation is at intent level. Field names: problem_type, root_cause_variant,
first_cause_nature, attribution_direction, additional_tags, diff_nature.
FC grouping matches intent.hunk_ids against design.md.
Problem clusters group by (first_cause_stage, problem_type, root_cause) at intent level.
Output includes both intents[] and hunks[] (hunks for metadata reference).

Reads: intent-fragments/*.json, hunk-list.json, agcr-calc.json, design.md,
repos-meta.json. Produces attribution-result.json compatible with render_report.py.

Usage:
  python3 aggregate_stats.py \
    --run-dir /tmp/agcr-{run_id} \
    --config-dir /path/to/skill/config \
    --repos-meta /tmp/agcr-{run_id}/repos-meta.json \
    --hunk-list /tmp/agcr-{run_id}/hunks/hunk-list.json \
    --output /tmp/agcr-{run_id}/attribution-result.json
"""
import argparse
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict


# ---------- Label maps (kept in sync with problem-types.json) ----------

ISSUE_LABELS = {
    "FUNC_MISSING": "功能缺失", "FUNC_EXTRA": "功能多余",
    "FUNC_LOGIC_ERROR": "功能逻辑错误",
    "BEHAVIOR_CONFLICT": "与现有行为冲突", "COMPAT_MISSING": "兼容性处理缺失",
    "INTERFACE_MISMATCH": "接口签名/参数不对", "PERSONAL_STYLE": "个人风格/偏好调整",
    "DATA_MODEL_ERROR": "数据模型/字段有误", "ARCH_VIOLATION": "架构/分层违反",
    "MIDDLEWARE_MISUSE": "中间件使用不当",
    "CODING_STYLE": "编码风格/命名不规范", "DEFENSIVE_MISSING": "防御性代码缺失",
    "TRANSACTION_ISSUE": "事务/一致性问题", "ROLLOUT_MISSING": "上线方案缺失",
    "PERFORMANCE_ISSUE": "性能问题", "OTHER": "其他问题",
}

CONF_MAP = {"high": "HIGH", "medium": "MEDIUM", "low": "LOW"}


def normalize_confidence(val):
    """Normalize confidence to string enum: 'high' / 'medium' / 'low'.

    SubAgent may output numeric (0.85) or string ('high'). This function
    ensures a consistent string enum for downstream consumption.
    """
    if isinstance(val, (int, float)):
        if val >= 0.8:
            return "high"
        elif val >= 0.5:
            return "medium"
        else:
            return "low"
    s = str(val).strip().lower()
    if s in ("high", "medium", "low"):
        return s
    # Try parsing as float string (e.g. "0.85")
    try:
        fval = float(s)
        if fval >= 0.8:
            return "high"
        elif fval >= 0.5:
            return "medium"
        else:
            return "low"
    except (ValueError, TypeError):
        return "low"


STAGE_ORDER = [
    "N6 代码生成", "N5 编码计划", "N4 技术方案",
    "N3 需求澄清", "N2 现状梳理", "N1 项目初始化",
    "测试并行链路",
]

# 阶段排序优先级（数字越小越靠前）
STAGE_PRIORITY = {s: i for i, s in enumerate(STAGE_ORDER)}

# ---------- Valid enums (kept in sync with problem-types.json) ----------

_VALID_STAGES = {"P1", "P2", "P3", "P4", "P5"}

_VALID_ROOT_CAUSES = {"R1", "R2", "R3", "R4", "R5"}

_VALID_SIT_IDS = {
    "FUNC_MISSING", "FUNC_EXTRA", "FUNC_LOGIC_ERROR", "BEHAVIOR_CONFLICT",
    "COMPAT_MISSING", "INTERFACE_MISMATCH", "DATA_MODEL_ERROR",
    "ARCH_VIOLATION", "MIDDLEWARE_MISUSE", "CODING_STYLE",
    "DEFENSIVE_MISSING", "TRANSACTION_ISSUE", "ROLLOUT_MISSING",
    "PERFORMANCE_ISSUE", "PERSONAL_STYLE", "OTHER",
}

_VALID_DIFF_NATURE = {"additive", "corrective", "subtractive", "refining"}

_VALID_ATTRIBUTION_DIR = {
    "artifact_defect", "knowledge_gap", "execution_deviation",
    "gate_escape", "clarification_gap",
}

_VALID_FIRST_CAUSE_NATURE = {
    "requirement_gap", "design_quality", "knowledge_missing",
    "execution_error", "review_escape",
}

_VALID_FIRST_CAUSE_SKILL = {
    "requirement", "design", "coding", "review", "testing",
}


def normalize_intent(intent):
    """Normalize a single intent fragment at intake time.

    Ensures all fields conform to the expected Schema regardless of
    SubAgent output format. Applied once when loading intent-fragments/
    so that all downstream code sees clean, consistent data.

    Normalizations performed:
    - confidence: numeric (0.85) → string enum ('high'/'medium'/'low')
    - first_cause_stage: validate against P1-P5, default 'P4'
    - root_cause: validate against R1-R5, default 'R3'
    - root_cause_variant: validate format Px-Na/b/c/d, keep as-is if valid
    - problem_type: keep if valid SIT ID or P-code
    - diff_nature: validate against known enums, default 'corrective'
    - attribution_direction: validate, default 'artifact_defect'
    - first_cause_nature: validate, default 'design_quality'
    - first_cause_skill: validate, default 'design'
    - impact: ensure dict with total_removed_lines / total_added_lines / hunk_count
    - evidence_chain / propagation_path / direct_cause: ensure string
    - evidence_type / structure_type: ensure string, keep as-is
    """
    if not isinstance(intent, dict):
        return intent

    # --- confidence ---
    intent["confidence"] = normalize_confidence(intent.get("confidence", "low"))

    # --- first_cause_stage ---
    stage = str(intent.get("first_cause_stage", "")).strip()
    # Normalize: "N4 技术方案" / "N4" / "P4" → "P4"
    import re as _stage_re
    _m = _stage_re.match(r'^([NnPp])(\d)', stage)
    if _m:
        stage = "P" + _m.group(2)
    if stage not in _VALID_STAGES:
        stage = "P4"
    intent["first_cause_stage"] = stage

    # --- root_cause ---
    rc = str(intent.get("root_cause", "")).strip().upper()
    if rc not in _VALID_ROOT_CAUSES:
        rc = "R3"
    intent["root_cause"] = rc

    # --- root_cause_variant ---
    rcv = str(intent.get("root_cause_variant", "")).strip()
    # Valid format: Px-Na/b/c... (e.g. P4-3b)
    if rcv and not re.match(r"^P\d+-\d+[a-z]?$", rcv):
        rcv = ""
    intent["root_cause_variant"] = rcv

    # --- problem_type ---
    pt = str(intent.get("problem_type", "")).strip()
    # problem_type MUST be a P-code (e.g. P4-3). SIT IDs (e.g. FUNC_LOGIC_ERROR)
    # are a separate classification axis (surface_issue_type) and should not
    # appear here. If a SIT ID leaks in, warn and fall back to OTHER.
    if pt and pt in _VALID_SIT_IDS:
        print(f"[aggregate] WARNING: intent {intent.get('intent_id','?')} has SIT ID "
              f"'{pt}' in problem_type (expected P-code like P4-3). "
              f"Falling back to OTHER.", file=sys.stderr)
        pt = "OTHER"
    elif pt and not re.match(r"^P\d+-\d+$", pt):
        pt = "OTHER"
    intent["problem_type"] = pt if pt else "OTHER"

    # --- diff_nature ---
    dn = str(intent.get("diff_nature", "")).strip().lower()
    if dn not in _VALID_DIFF_NATURE:
        dn = "corrective"
    intent["diff_nature"] = dn

    # --- attribution_direction ---
    ad = str(intent.get("attribution_direction", "")).strip().lower()
    if ad not in _VALID_ATTRIBUTION_DIR:
        ad = "artifact_defect"
    intent["attribution_direction"] = ad

    # --- first_cause_nature ---
    fcn = str(intent.get("first_cause_nature", "")).strip().lower()
    if fcn not in _VALID_FIRST_CAUSE_NATURE:
        fcn = "design_quality"
    intent["first_cause_nature"] = fcn

    # --- first_cause_skill ---
    fcs = str(intent.get("first_cause_skill", "")).strip().lower()
    if fcs not in _VALID_FIRST_CAUSE_SKILL:
        fcs = "design"
    intent["first_cause_skill"] = fcs

    # --- impact ---
    imp = intent.get("impact")
    if not isinstance(imp, dict):
        imp = {}
    intent["impact"] = {
        "total_removed_lines": int(imp.get("total_removed_lines", 0)),
        "total_added_lines": int(imp.get("total_added_lines", 0)),
        "hunk_count": int(imp.get("hunk_count", 0)),
    }

    # --- evidence_chain: may be list (structured) or string; preserve type ---
    ec = intent.get("evidence_chain")
    if ec is None:
        intent["evidence_chain"] = []
    # If SubAgent returned a string, keep as-is (render handles both)

    # --- string fields: ensure string, never None ---
    for field in ("propagation_path", "direct_cause",
                  "recommendation", "evidence_type", "structure_type",
                  "problem_type_label", "root_cause_label"):
        val = intent.get(field)
        if val is None:
            intent[field] = ""
        elif not isinstance(val, str):
            intent[field] = str(val)

    # --- labels: fill if missing ---
    if not intent.get("problem_type_label"):
        intent["problem_type_label"] = ISSUE_LABELS.get(
            intent["problem_type"], intent["problem_type"]
        )
    if not intent.get("root_cause_label"):
        rc_labels = {
            "R1": "知识不足", "R2": "执行损耗", "R3": "模型推理",
            "R4": "门禁漏检", "R5": "澄清交互不充分",
        }
        intent["root_cause_label"] = rc_labels.get(intent["root_cause"], "")

    return intent


# ── Short→full repo name mapping ─────────────────────────────────────────────

_REPO_SHORT_TO_FULL = {
    "server": "bizad_user_benefit_exchange_server",
    "client": "bizad_user_benefit_exchange_client",
    "api": "bizad_user_benefit_exchange_api",
}


def _repo_to_prefix(repo_name):
    """Extract short prefix from full repo name: bizad_user_benefit_exchange_server → server."""
    for prefix, full in _REPO_SHORT_TO_FULL.items():
        if repo_name == full or repo_name.endswith(f"_{prefix}"):
            return prefix
    # Fallback: last segment after _
    parts = repo_name.rsplit("_", 1)
    return parts[-1] if len(parts) > 1 else repo_name[:6]


def normalize_hunk_list(hunks, repos_meta):
    """Normalize hunk-list.json: repo full name, excluded field, symbol_hint.

    Lightweight normalization for data produced by split_hunks.py (which already
    has correct diff_content/before_code/after_code/line counts).
    Only fixes:
    - repo: short name → full name (for SubAgent-produced data)
    - excluded / is_excluded unification
    - symbol_hint / enclosing_class: None → derived from file_path
    - numeric fields: ensure int
    """
    # Build short→full mapping from repos_meta
    short_to_full = dict(_REPO_SHORT_TO_FULL)
    for r in repos_meta.get("repos", []):
        full = r.get("repo", "")
        prefix = _repo_to_prefix(full)
        if prefix and full:
            short_to_full[prefix] = full

    for h in hunks:
        if not isinstance(h, dict):
            continue

        # --- repo: short name → full name ---
        repo = h.get("repo", "")
        if repo in short_to_full:
            h["repo"] = short_to_full[repo]

        # --- excluded / is_excluded unification ---
        if "is_excluded" in h:
            if "excluded" not in h:
                h["excluded"] = h["is_excluded"]
            del h["is_excluded"]
        elif "excluded" not in h:
            h["excluded"] = False

        # --- symbol_hint / enclosing_class: None → derived from file_path ---
        for key in ("symbol_hint", "enclosing_class"):
            if h.get(key) is None or h.get(key) == "":
                fp = h.get("file_path", "")
                h[key] = os.path.basename(fp).rsplit(".", 1)[0] if fp else "unknown"

        # --- ensure numeric fields are int ---
        for key in ("removed_lines", "added_lines", "old_start", "old_lines",
                     "new_start", "new_lines"):
            val = h.get(key)
            if val is None:
                h[key] = 0
            elif isinstance(val, list):
                h[key] = sum(v for v in val if isinstance(v, (int, float))) or 0
            elif not isinstance(val, int):
                try:
                    h[key] = int(val)
                except (ValueError, TypeError):
                    h[key] = 0

    return hunks


def normalize_change_intents(ci_data, intent_frags=None):
    """Normalize change-intents.json: structure, field names, missing fields.

    Args:
      ci_data: raw JSON from change-intents.json (dict or list)
      intent_frags: optional list of intent fragments for diff_nature fallback

    Returns:
      list of normalized CI dicts with fields:
      intent_id, intent_description, diff_nature, hunk_ids,
      is_composite, cluster_confidence, cluster_method, clustering_inputs
    """
    # --- extract list from wrapper dict ---
    if isinstance(ci_data, dict):
        cis = ci_data.get("change_intents", ci_data.get("intents", []))
    elif isinstance(ci_data, list):
        cis = ci_data
    else:
        return []

    # Build intent_id → diff_nature map from fragments
    frag_dn_map = {}
    if intent_frags:
        for frag in intent_frags:
            fid = frag.get("intent_id", "")
            if fid:
                frag_dn_map[fid] = frag.get("diff_nature", "")

    normalized = []
    for ci in cis:
        if not isinstance(ci, dict):
            continue

        # --- field name mapping ---
        # intent_id
        if "intent_id" not in ci:
            ci["intent_id"] = ci.get("ci_id", ci.get("id", ""))
        elif "ci_id" in ci:
            ci.pop("ci_id", None)

        # intent_description
        if "intent_description" not in ci:
            ci["intent_description"] = ci.get("title", ci.get("description", ""))
        # Remove non-standard field names
        for old_key in ("title", "description"):
            ci.pop(old_key, None)

        # hunk_ids
        if "hunk_ids" not in ci:
            ci["hunk_ids"] = ci.get("related_hunks", [])
        elif "related_hunks" in ci:
            ci.pop("related_hunks", None)

        # --- supplement missing fields ---
        ci_id = ci.get("intent_id", "")
        if "diff_nature" not in ci or not ci.get("diff_nature"):
            ci["diff_nature"] = frag_dn_map.get(ci_id, "corrective")
        if "is_composite" not in ci:
            ci["is_composite"] = False
        if "cluster_confidence" not in ci or not ci.get("cluster_confidence"):
            ci["cluster_confidence"] = "high"
        if "cluster_method" not in ci or not ci.get("cluster_method"):
            ci["cluster_method"] = "llm_rationale"
        if "clustering_inputs" not in ci:
            ci["clustering_inputs"] = {}

        # Remove non-standard fields
        for old_key in ("design_items", "repos", "removed_lines", "added_lines"):
            ci.pop(old_key, None)

        normalized.append(ci)

    return normalized


def normalize_key_findings(kf_raw):
    """Normalize key-findings.json: extract list from wrapper dict, map field names.

    Returns:
      list of finding dicts with fields: finding, priority, description, related_hunks, related_fcs
    """
    # --- extract list from wrapper dict ---
    if isinstance(kf_raw, dict) and "findings" in kf_raw:
        findings = kf_raw["findings"]
    elif isinstance(kf_raw, list):
        findings = kf_raw
    else:
        return []

    normalized = []
    for f in findings:
        if not isinstance(f, dict):
            continue

        # Field name mapping: title → finding (keep title as fallback)
        if "finding" not in f and "title" in f:
            f["finding"] = f["title"]
        if "priority" not in f and "severity" in f:
            f["priority"] = f["severity"]

        # Ensure required fields exist
        if "finding" not in f:
            f["finding"] = ""
        if "priority" not in f:
            f["priority"] = ""
        if "description" not in f:
            f["description"] = ""
        if "related_hunks" not in f:
            f["related_hunks"] = []
        if "related_fcs" not in f:
            f["related_fcs"] = []

        normalized.append(f)

    return normalized


def load_problem_types(config_dir):
    """Load problem-types.json and build label lookup maps."""
    path = os.path.join(config_dir, "problem-types.json")
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)

    sit_label = {t["id"]: t["label"] for t in cfg.get("surface_issue_types", [])}
    pc_label = {}
    sub_map = {}
    stage_of_pc = {}
    pc_to_sit = {}
    stage_map = {
        "P5": "N5 编码计划", "P4": "N4 技术方案", "P3": "N3 需求澄清",
        "P2": "N2 现状梳理", "P1": "N1 项目初始化",
    }
    for st in cfg.get("attribution_stages", []):
        stage_disp = stage_map.get(st.get("id", ""), st.get("stage", ""))
        for pt in st.get("problem_types", []):
            pc_label[pt["id"]] = pt["label"]
            stage_of_pc[pt["id"]] = stage_disp
            for rv in pt.get("root_cause_variants", []):
                sub_map[rv["sub_type"]] = {
                    "root_cause": rv.get("root_cause"),
                    "description": rv.get("description", ""),
                }
                sit = rv.get("surface_issue_type", "")
                if sit and pt["id"] not in pc_to_sit:
                    pc_to_sit[pt["id"]] = sit
    rc_label = {}
    for k, v in cfg.get("root_causes", {}).items():
        rc_label[k] = v["label"] if isinstance(v, dict) else v

    # Load p_sub_labels.json for sub-type short descriptions
    p_sub_labels = {}
    psl_path = os.path.join(config_dir, "p_sub_labels.json")
    if os.path.isfile(psl_path):
        with open(psl_path, encoding="utf-8") as f:
            psl_data = json.load(f)
        p_sub_labels = psl_data.get("labels", {})

    # Merge surface_issue_type labels as fallback into pc_label.
    # SubAgent sometimes uses surface_issue_type IDs (e.g. INTERFACE_MISMATCH)
    # instead of P-code IDs (e.g. P4-3) for problem_type.
    for sit_id, sit_lbl in sit_label.items():
        if sit_id not in pc_label:
            pc_label[sit_id] = sit_lbl

    return {
        "sit_label": sit_label, "pc_label": pc_label,
        "sub_map": sub_map, "stage_of_pc": stage_of_pc,
        "rc_label": rc_label, "pc_to_sit": pc_to_sit,
        "p_sub_labels": p_sub_labels,
    }


def normalize_stage(s):
    """Normalize first_cause_stage to display name."""
    if not s:
        return "-"
    stage_map = {
        "P5": "N5 编码计划", "P4": "N4 技术方案", "P3": "N3 需求澄清",
        "P2": "N2 现状梳理", "P1": "N1 项目初始化",
    }
    if s in stage_map.values():
        return s
    if s in stage_map:
        return stage_map[s]
    return s


# ---------- Design.md parsing & FC grouping ----------

def parse_design_md(design_path):
    """Parse design.md to extract D-xx design items and associated references."""
    if not design_path or not os.path.isfile(design_path):
        return []

    with open(design_path, encoding="utf-8", errors="replace") as f:
        content = f.read()

    dxx_pattern = re.compile(
        r'^(?:#{1,6}\s+)?(?:\*\*)?(D-\d+)(?:\*\*)?\s*[:：]?\s*(.+)?$',
        re.MULTILINE
    )

    # Pattern to extract **对应用户故事**：US-xx：描述；US-yy：描述
    us_line_pattern = re.compile(
        r'\*\*对应用户故事\*\*[：:]\s*(.+?)(?:\n\s*\n|\n\*\*|\n###|\n---|\Z)',
        re.DOTALL
    )
    us_id_pattern = re.compile(r'(US-\d+)')

    file_patterns = [
        re.compile(r'[\w/]+\.java'),
        re.compile(r'[\w/]+\.kt'),
        re.compile(r'[\w/]+\.ts'),
        re.compile(r'[\w/]+\.go'),
        re.compile(r'[\w/]+\.py'),
    ]

    class_name_pattern = re.compile(r'\b[A-Z][a-zA-Z0-9]{3,}\b')

    CLASS_NAME_EXCLUDE = {
        "String", "List", "Map", "Set", "Override", "Exception", "System",
        "Math", "Integer", "Boolean", "Object", "Class", "Thread",
        "Step1", "Step2", "Step3", "Step4", "Step5", "Phase",
        "Header", "Token", "Hash", "Topic", "Consumer", "Producer",
        "Filter", "Matcher", "Handler", "Service", "Gateway",
        "Exchanger", "Mapper", "Repository", "Domain", "App",
        "InnoDB", "Kibana", "Mafka", "Thrift", "Redis", "Crane",
        "Lion", "DaoZong",
    }

    def is_class_name(word):
        return (len(word) >= 4
                and any(c.islower() for c in word)
                and word not in CLASS_NAME_EXCLUDE)

    design_items = []
    matches = list(dxx_pattern.finditer(content))

    for i, m in enumerate(matches):
        design_id = m.group(1)
        title = m.group(2).strip() if m.group(2) else ""
        title = re.sub(r'[*_`#]', '', title).strip()

        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        section_content = content[start:end]

        file_paths = set()
        for pat in file_patterns:
            for fp in pat.findall(section_content):
                file_paths.add(fp)

        class_name_counts = defaultdict(int)
        for word in class_name_pattern.findall(section_content):
            if is_class_name(word):
                class_name_counts[word] += 1

        # Extract **对应用户故事**：US-xx references
        user_stories = []
        us_match = us_line_pattern.search(section_content)
        if us_match:
            user_stories = us_id_pattern.findall(us_match.group(1))

        design_items.append({
            "design_id": design_id,
            "title": title,
            "file_paths": sorted(file_paths),
            "class_names": dict(class_name_counts),
            "user_stories": user_stories,
        })

    return design_items


def build_file_to_design_map(design_items):
    """Build file_path → [D-xx] mapping from parsed design items."""
    mapping = defaultdict(list)
    for item in design_items:
        for fp in item["file_paths"]:
            if item["design_id"] not in mapping[fp]:
                mapping[fp].append(item["design_id"])
    return dict(mapping)


def build_class_to_design_map(design_items):
    """Build class_name → [D-xx] mapping from parsed design items."""
    class_candidates = defaultdict(list)
    for item in design_items:
        for cn, cnt in item.get("class_names", {}).items():
            class_candidates[cn].append((item["design_id"], cnt))

    mapping = {}
    for cn, candidates in class_candidates.items():
        best = sorted(candidates, key=lambda x: (-x[1], int(x[0].split('-')[1]) if x[0].startswith('D-') else 999))[0]
        mapping[cn] = [best[0]]
    return mapping


def build_design_to_us_map(design_items):
    """Build D-xx → [US-xx] mapping from parsed design items.

    Extracts the **对应用户故事** field from each design item to
    provide explicit D-xx → US-xx associations for evidence chain validation.
    """
    mapping = {}
    for item in design_items:
        us_list = item.get("user_stories", [])
        if us_list:
            mapping[item["design_id"]] = us_list
    return mapping


def _match_hunk_to_design(hunk_meta, file_to_design, class_to_design):
    """Match a single hunk's metadata to design items. Returns list of D-xx or []."""
    hunk_file = hunk_meta.get("file") or hunk_meta.get("file_path", "")
    matched_dxx = []

    # Layer 1: exact file path match
    if hunk_file in file_to_design:
        matched_dxx = file_to_design[hunk_file]

    # Layer 2: basename match
    if not matched_dxx:
        basename = os.path.basename(hunk_file)
        for fp, dxx_list in file_to_design.items():
            if os.path.basename(fp) == basename:
                matched_dxx = dxx_list
                break

    # Layer 3: partial path match
    if not matched_dxx:
        for fp, dxx_list in file_to_design.items():
            if fp in hunk_file or hunk_file in fp:
                matched_dxx = dxx_list
                break

    # Layer 4: class name match
    if not matched_dxx:
        basename = os.path.basename(hunk_file)
        if '.' in basename:
            class_from_file = basename.rsplit('.', 1)[0]
            if len(class_from_file) >= 4 and class_from_file in class_to_design:
                matched_dxx = class_to_design[class_from_file]

        if not matched_dxx:
            symbol_hint = hunk_meta.get("symbol_hint", "")
            for word in re.findall(r'\b[A-Z][a-zA-Z0-9]{3,}\b', symbol_hint):
                if any(c.islower() for c in word) and word in class_to_design:
                    matched_dxx = class_to_design[word]
                    break

    return matched_dxx


def group_intents_by_design(intents, hunk_lookup, design_path, maps):
    """Group intents by design.md D-xx design items.

    Matches intent.hunk_ids → hunk metadata → design.md file/class references.
    """
    non_excluded = [i for i in intents if not _is_intent_excluded(i, hunk_lookup)]

    design_items = parse_design_md(design_path)
    file_to_design = build_file_to_design_map(design_items)
    class_to_design = build_class_to_design_map(design_items)
    design_title_map = {item["design_id"]: item["title"] for item in design_items}
    design_to_us_map = build_design_to_us_map(design_items)

    # Store in maps for downstream validation and report rendering
    maps["design_to_us"] = design_to_us_map

    design_groups = defaultdict(list)
    file_default_groups = defaultdict(list)

    for intent in non_excluded:
        hunk_ids = intent.get("hunk_ids", [])
        matched_dxx_set = set()

        for hid in hunk_ids:
            hunk_meta = hunk_lookup.get(hid, {})
            dxx_list = _match_hunk_to_design(hunk_meta, file_to_design, class_to_design)
            matched_dxx_set.update(dxx_list)

        if matched_dxx_set:
            for dxx in sorted(matched_dxx_set):
                design_groups[dxx].append(intent)
        else:
            # Fallback: file-level grouping by first hunk's directory
            first_hunk = hunk_lookup.get(hunk_ids[0], {}) if hunk_ids else {}
            file_dir = os.path.dirname(first_hunk.get("file") or first_hunk.get("file_path", "")) or "root"
            file_default_groups[file_dir].append(intent)

    feature_changes = []
    fc_counter = 0

    for dxx in sorted(design_groups.keys()):
        fc_counter += 1
        fc_id = f"FC-{fc_counter:03d}"
        fc_intents = design_groups[dxx]
        title = design_title_map.get(dxx, "")
        desc = f"{dxx} {title}".strip() if title else dxx
        feature_changes.append(_build_fc_entry(fc_id, desc, dxx, "design_anchored", fc_intents, maps))

    for file_dir in sorted(file_default_groups.keys()):
        fc_counter += 1
        fc_id = f"FC-{fc_counter:03d}"
        fc_intents = file_default_groups[file_dir]
        desc = f"文件级分组: {file_dir}"
        feature_changes.append(_build_fc_entry(fc_id, desc, None, "file_default", fc_intents, maps))

    # Assign feature_change_id back to intents
    for fc in feature_changes:
        for intent in fc["_intents"]:
            intent["feature_change_id"] = fc["feature_change_id"]

    return feature_changes


def _is_intent_excluded(intent, hunk_lookup):
    """Check if all hunks in an intent are excluded."""
    hunk_ids = intent.get("hunk_ids", [])
    if not hunk_ids:
        return False
    excluded_count = 0
    for hid in hunk_ids:
        meta = hunk_lookup.get(hid, {})
        if meta.get("excluded"):
            excluded_count += 1
    return excluded_count == len(hunk_ids)


def _build_fc_entry(fc_id, description, design_item, grouping_method, fc_intents, maps):
    """Build a single FC entry with aggregated attribution (intent level)."""
    pc_label_map = maps.get("pc_label", {})
    rc_label_map = maps.get("rc_label", {})

    problem_types = sorted(set(i.get("problem_type", "") for i in fc_intents if i.get("problem_type")))

    cat_counts = Counter(i.get("problem_type", "") for i in fc_intents)
    primary_cat = cat_counts.most_common(1)[0][0] if cat_counts else ""

    stage_counts = Counter(i.get("first_cause_stage", "") for i in fc_intents)
    primary_stage = normalize_stage(stage_counts.most_common(1)[0][0] if stage_counts else "")

    rc_counts = Counter(i.get("root_cause", "") for i in fc_intents)
    primary_rc = rc_counts.most_common(1)[0][0] if rc_counts else ""

    stage_dist = defaultdict(int)
    for i in fc_intents:
        pt = i.get("problem_type", "")
        if pt:
            stage_prefix = pt.split("-")[0] if "-" in pt else pt
            stage_dist[stage_prefix] += 1

    rc_dist = defaultdict(int)
    for i in fc_intents:
        rc = i.get("root_cause", "")
        if rc:
            rc_dist[rc] += 1

    pp_counts = Counter(i.get("propagation_path", "") for i in fc_intents if i.get("propagation_path"))
    dominant_path = pp_counts.most_common(1)[0][0] if pp_counts else ""

    conf_counts = Counter(normalize_confidence(i.get("confidence", "low")) for i in fc_intents)
    if conf_counts.get("high", 0) > 0:
        priority = "HIGH"
    elif conf_counts.get("medium", 0) > 0:
        priority = "MEDIUM"
    else:
        priority = "LOW"

    total_removed = sum(i.get("impact", {}).get("total_removed_lines", 0) or 0 for i in fc_intents)
    total_added = sum(i.get("impact", {}).get("total_added_lines", 0) or 0 for i in fc_intents)

    # Collect all hunk_ids
    all_hunk_ids = []
    for i in fc_intents:
        all_hunk_ids.extend(i.get("hunk_ids", []))

    # Get related user stories from design_to_us map
    design_to_us = maps.get("design_to_us", {})
    related_user_stories = design_to_us.get(design_item, []) if design_item else []

    return {
        "feature_change_id": fc_id,
        "description": description,
        "related_design_item": design_item,
        "related_user_stories": related_user_stories,
        "grouping_method": grouping_method,
        "hunks": all_hunk_ids,
        "hunk_count": len(all_hunk_ids),
        "intent_count": len(fc_intents),
        "problem_types": problem_types,
        "aggregated_attribution": {
            "primary_category": primary_cat,
            "primary_stage": primary_stage,
            "primary_root_cause": primary_rc,
            "stage_distribution": dict(stage_dist),
            "root_cause_distribution": dict(rc_dist),
            "dominant_path": dominant_path,
            "improvement_priority": priority,
            "intent_count": len(fc_intents),
            "hunk_count": len(all_hunk_ids),
            "total_removed_lines": total_removed,
            "total_added_lines": total_added,
        },
        "_intents": fc_intents,
    }


# ---------- Intent groups for §6 (首因阶段 × 问题类型) ----------

def build_intent_groups(intents, hunk_lookup, maps):
    """Build intent groups for §6 rendering: grouped by first_cause_stage × problem_type.

    Returns:
      list of dicts sorted by STAGE_ORDER, then by problem_type ascending.
    """
    pc_label_map = maps.get("pc_label", {})
    non_excluded = [i for i in intents if not _is_intent_excluded(i, hunk_lookup)]

    groups = defaultdict(list)
    for intent in non_excluded:
        stage = intent.get("first_cause_stage", "未知")
        pt = intent.get("problem_type", "UNKNOWN")
        key = f"{stage}|{pt}"
        groups[key].append(intent)

    def sort_key(item):
        key = item[0]
        stage, pt = key.split("|", 1) if "|" in key else ("未知", "UNKNOWN")
        stage_pri = STAGE_PRIORITY.get(stage, 99)
        return (stage_pri, pt)

    result = []
    for key, group_intents in sorted(groups.items(), key=sort_key):
        stage, pt = key.split("|", 1) if "|" in key else ("未知", "UNKNOWN")
        conf_order = {"high": 0, "medium": 1, "low": 2}
        group_intents_sorted = sorted(
            group_intents,
            key=lambda i: conf_order.get(i.get("confidence", "low"), 3)
        )
        result.append({
            "group_key": key,
            "first_cause_stage": stage,
            "problem_type": pt,
            "problem_type_label": pc_label_map.get(pt, pt),
            "intents": group_intents_sorted,
        })

    return result


def load_change_intents(run_dir):
    """Load change-intents.json produced by SubAgent-Intent.

    Returns:
      list of CI dicts: [{
        intent_id, intent_description, diff_nature, hunk_ids,
        is_composite, evidence_type, evidence_type_source,
        evidence_type_derivation, pdg_edges, cluster_confidence, cluster_method
      }, ...]
      Returns empty list if file not found.
    """
    ci_path = os.path.join(run_dir, "hunks", "change-intents.json")
    if not os.path.isfile(ci_path):
        return []
    with open(ci_path, encoding="utf-8") as f:
        data = json.load(f)
    # Support both list format and {"change_intents": [...]} format
    if isinstance(data, list):
        return data
    elif isinstance(data, dict):
        return data.get("change_intents", data.get("intents", []))
    return []


def build_change_intent_groups(hunks, change_intents, maps, intent_frag_map=None):
    """Build Change Intent groups for §6 rendering: each CI is a card,
    with its associated hunks nested inside.

    Falls back to legacy hunk_groups (stage × p_category) if no CIs.

    Args:
      intent_frag_map: optional {intent_id: intent_fragment} for attribution fields

    Returns:
      list of dicts: [{
        "intent_id": "CI-001",
        "intent_description": "...",
        "diff_nature": "corrective",
        "evidence_type": "logic_error",
        "cluster_method": "llm_rationale",
        "is_composite": false,
        "hunks": [full hunk objects with impact],
        "hunk_count": 2,
        "first_cause_stage": "N4 技术方案",
        "p_category": "P4-2",
        "p_category_label": "设计项逻辑错误",
        "root_cause": "R3",
        "dominant_confidence": "high",
        "impact": {"abandonment_impact": 0.05, "agcr_impact": 0.03},
      }, ...]

    Sorted by first_cause_stage (STAGE_ORDER N6→N1), then by hunk_count desc.
    """
    pc_label_map = maps.get("pc_label", {})
    non_excluded = [h for h in hunks if not h.get("excluded")]

    if not change_intents:
        # Fallback: legacy hunk_groups (stage × p_category)
        return _build_legacy_hunk_groups(non_excluded, pc_label_map)

    # Build hunk_id → hunk lookup
    hunk_map = {h.get("hunk_id"): h for h in non_excluded}

    # Also collect hunks not covered by any CI
    covered_ids = set()
    result = []
    for ci in change_intents:
        ci_hunks = []
        for hid in ci.get("hunk_ids", []):
            h = hunk_map.get(hid)
            if h:
                ci_hunks.append(h)
                covered_ids.add(hid)

        if not ci_hunks:
            continue

        # Sort hunks within CI by confidence (high→medium→low)
        conf_order = {"high": 0, "medium": 1, "low": 2}
        ci_hunks_sorted = sorted(
            ci_hunks,
            key=lambda h: conf_order.get(h.get("confidence", "low"), 3)
        )

        # Aggregate CI-level attribution
        # Prefer intent fragment data (has correct problem_type/root_cause/stage)
        ci_id = ci.get("intent_id", "")
        frag = intent_frag_map.get(ci_id, {}) if intent_frag_map else {}

        if frag:
            # Use intent fragment's attribution directly
            dominant_stage = normalize_stage(frag.get("first_cause_stage", ""))
            dominant_pc = frag.get("problem_type", "UNKNOWN")
            dominant_rc = frag.get("root_cause", "")
            # Prefer cluster_confidence from change-intents.json (authoritative from clustering);
            # fall back to fragment's confidence (which may have been merged above)
            ci_conf = normalize_confidence(ci.get("cluster_confidence", ""))
            frag_conf = normalize_confidence(frag.get("confidence", "low"))
            dominant_conf = ci_conf or frag_conf or "low"
        else:
            # Fallback: aggregate from hunks
            stage_counts = Counter(normalize_stage(h.get("first_cause_stage", "")) for h in ci_hunks)
            dominant_stage = stage_counts.most_common(1)[0][0] if stage_counts else "未知"

            pc_counts = Counter(h.get("p_category", "") for h in ci_hunks)
            dominant_pc = pc_counts.most_common(1)[0][0] if pc_counts else "UNKNOWN"

            rc_counts = Counter(h.get("root_cause", "") for h in ci_hunks)
            dominant_rc = rc_counts.most_common(1)[0][0] if rc_counts else ""

            conf_counts = Counter(normalize_confidence(h.get("confidence", "low")) for h in ci_hunks)
            if conf_counts.get("high", 0) > 0:
                dominant_conf = "high"
            elif conf_counts.get("medium", 0) > 0:
                dominant_conf = "medium"
            else:
                dominant_conf = "low"

        # Use CI's diff_nature if present, otherwise fall back to first hunk's
        diff_nature = ci.get("diff_nature", "") or ci_hunks_sorted[0].get("diff_nature", "")

        # Get problem_type_label from fragment or maps
        if frag:
            pc_label = frag.get("problem_type_label", "") or pc_label_map.get(dominant_pc, dominant_pc)
            rc_label = frag.get("root_cause_label", "") or maps.get("rc_label", {}).get(dominant_rc, dominant_rc)
        else:
            pc_label = pc_label_map.get(dominant_pc, dominant_pc)
            rc_label = ""

        result.append({
            "intent_id": ci.get("intent_id", ""),
            "intent_description": ci.get("intent_description", ""),
            "diff_nature": diff_nature,
            "evidence_type": ci.get("evidence_type", ""),
            "evidence_type_source": ci.get("evidence_type_source", ""),
            "evidence_type_derivation": ci.get("evidence_type_derivation", ""),
            "structure_type": ci.get("structure_type", ""),
            "cluster_confidence": ci.get("cluster_confidence", ""),
            "cluster_method": ci.get("cluster_method", ""),
            "is_composite": ci.get("is_composite", False),
            "hunks": ci_hunks_sorted,
            "hunk_count": len(ci_hunks_sorted),
            "first_cause_stage": dominant_stage,
            "p_category": dominant_pc,
            "problem_type": dominant_pc,  # alias for render_report.py compatibility
            "p_category_label": pc_label,
            "root_cause": dominant_rc,
            "root_cause_label": rc_label,
            "dominant_confidence": dominant_conf,
            "confidence": dominant_conf,
            "first_cause_nature": frag.get("first_cause_nature", "") if frag else "",
            "attribution_direction": frag.get("attribution_direction", "") if frag else "",
            # Pass through full attribution fields from intent fragment
            "evidence_chain": frag.get("evidence_chain", []) if frag else [],
            "direct_cause": frag.get("direct_cause", "") if frag else "",
            "propagation_path": frag.get("propagation_path", "") if frag else "",
            "recommendation": frag.get("recommendation", "") if frag else "",
            "root_cause_variant": frag.get("root_cause_variant", "") if frag else "",
            "root_cause_evidence": frag.get("root_cause_evidence", "") if frag else "",
            "downstream_propagation": frag.get("downstream_propagation", "") if frag else "",
            "surface_issue_type": frag.get("surface_issue_type", "") if frag else "",
            "first_cause_skill": frag.get("first_cause_skill", "") if frag else "",
            "additional_tags": frag.get("additional_tags", []) if frag else [],
            "knowledge_check": frag.get("knowledge_check", "") if frag else "",
            "artifact_manifestation": frag.get("artifact_manifestation", "") if frag else "",
            "root_cause_verdict": frag.get("root_cause_verdict", "") if frag else "",
            "before_code_summary": frag.get("before_code_summary", "") if frag else "",
            "change_summary": frag.get("change_summary", "") if frag else "",
            "impact": None,  # filled later in aggregate()
        })

    # Handle orphan hunks (not covered by any CI)
    orphans = [h for h in non_excluded if h.get("hunk_id") not in covered_ids]
    if orphans:
        # Group orphans by stage × p_category as fallback CIs
        orphan_groups = defaultdict(list)
        for h in orphans:
            stage = normalize_stage(h.get("first_cause_stage", "未知"))
            pc = h.get("p_category", "UNKNOWN")
            orphan_groups[f"{stage}|{pc}"].append(h)

        for key, group_hunks in orphan_groups.items():
            stage, pc = key.split("|", 1) if "|" in key else ("未知", "UNKNOWN")
            conf_order = {"high": 0, "medium": 1, "low": 2}
            group_hunks_sorted = sorted(
                group_hunks,
                key=lambda h: conf_order.get(h.get("confidence", "low"), 3)
            )
            fallback_desc = group_hunks_sorted[0].get("change_summary", "") or f"未聚类 hunk ({stage} · {pc})"
            result.append({
                "intent_id": "CI-ORPHAN",
                "intent_description": f"[未聚类] {fallback_desc}",
                "diff_nature": group_hunks_sorted[0].get("diff_nature", ""),
                "evidence_type": group_hunks_sorted[0].get("evidence_type", ""),
                "cluster_confidence": "low",
                "cluster_method": "orphan_fallback",
                "is_composite": False,
                "hunks": group_hunks_sorted,
                "hunk_count": len(group_hunks_sorted),
                "first_cause_stage": stage,
                "p_category": pc,
                "p_category_label": pc_label_map.get(pc, pc),
                "root_cause": group_hunks_sorted[0].get("root_cause", ""),
                "dominant_confidence": group_hunks_sorted[0].get("confidence", "low"),
                "impact": None,
            })

    # Sort by CI numeric id (CI-001, CI-002, ...) ascending
    def _ci_sort_key(g):
        cid = g.get("intent_id", "")
        m = re.match(r"CI-(\d+)", cid)
        return int(m.group(1)) if m else 9999
    result.sort(key=_ci_sort_key)

    return result


def _build_legacy_hunk_groups(non_excluded, pc_label_map):
    """Fallback: build hunk groups by stage × p_category when no CIs exist."""
    groups = defaultdict(list)
    for h in non_excluded:
        stage = normalize_stage(h.get("first_cause_stage", "未知"))
        pc = h.get("p_category", "UNKNOWN")
        key = f"{stage}|{pc}"
        groups[key].append(h)

    def sort_key(item):
        key = item[0]
        stage, pc = key.split("|", 1) if "|" in key else ("未知", "UNKNOWN")
        stage_pri = STAGE_PRIORITY.get(stage, 99)
        return (stage_pri, pc)

    result = []
    for key, group_hunks in sorted(groups.items(), key=sort_key):
        stage, pc = key.split("|", 1) if "|" in key else ("未知", "UNKNOWN")
        conf_order = {"high": 0, "medium": 1, "low": 2}
        group_hunks_sorted = sorted(
            group_hunks,
            key=lambda h: conf_order.get(h.get("confidence", "low"), 3)
        )
        fallback_desc = group_hunks_sorted[0].get("change_summary", "") or f"{stage} · {pc}"
        result.append({
            "intent_id": "CI-LEGACY",
            "intent_description": f"[回退模式] {fallback_desc}",
            "diff_nature": group_hunks_sorted[0].get("diff_nature", ""),
            "evidence_type": group_hunks_sorted[0].get("evidence_type", ""),
            "cluster_confidence": "low",
            "cluster_method": "legacy_fallback",
            "is_composite": False,
            "hunks": group_hunks_sorted,
            "hunk_count": len(group_hunks_sorted),
            "first_cause_stage": stage,
            "p_category": pc,
            "p_category_label": pc_label_map.get(pc, pc),
            "root_cause": group_hunks_sorted[0].get("root_cause", ""),
            "dominant_confidence": group_hunks_sorted[0].get("confidence", "low"),
            "impact": None,
        })
    return result


# ---------- Loading functions ----------

def load_all_intents(run_dir, hunk_list_path):
    """Load intent-fragments/*.json and hunk-list.json.

    Reads from intent-fragments/ directory. Each file is one intent's
    complete attribution result. Also loads hunk-list.json for metadata.
    """
    frag_dir = os.path.join(run_dir, "intent-fragments")

    # Load hunk-list.json (for excluded hunks and metadata)
    hunk_list = []
    if hunk_list_path and os.path.isfile(hunk_list_path):
        with open(hunk_list_path, encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                hunk_list = data
            elif isinstance(data, dict):
                hunk_list = data.get("hunks", data.get("hunks_list", []))

    # Normalize field name: is_excluded → excluded (SKILL.md uses is_excluded,
    # all scripts use excluded; unify at data intake)
    for h in hunk_list:
        if "is_excluded" in h and "excluded" not in h:
            h["excluded"] = h.pop("is_excluded")
        elif "is_excluded" in h:
            h.pop("is_excluded")

    # Load all intent fragments
    all_intents = []
    if os.path.isdir(frag_dir):
        for frag_path in sorted(glob.glob(os.path.join(frag_dir, "*.json"))):
            with open(frag_path, encoding="utf-8") as f:
                frag = json.load(f)
            # Support multiple formats
            if isinstance(frag, dict) and "intent_id" in frag:
                all_intents.append(frag)
            elif isinstance(frag, dict) and "intents" in frag:
                all_intents.extend(frag["intents"])
            elif isinstance(frag, dict) and "hunks" in frag:
                # compat: treat as intents
                all_intents.extend(frag["hunks"])

    # Save original values before normalize_intent() overwrites them
    # (normalize_intent maps first_cause_nature to a different enum set)
    for it in all_intents:
        it["_orig_first_cause_nature"] = it.get("first_cause_nature", "")
        it["_orig_attribution_direction"] = it.get("attribution_direction", "")

    # Normalize all intents at intake — fix SubAgent Schema deviations once
    all_intents = [normalize_intent(it) for it in all_intents]

    # Restore original enum values for downstream rendering
    for it in all_intents:
        if it.get("_orig_first_cause_nature"):
            it["first_cause_nature"] = it["_orig_first_cause_nature"]
        if it.get("_orig_attribution_direction"):
            it["attribution_direction"] = it["_orig_attribution_direction"]

    return all_intents, hunk_list


def _count_diff_lines(diff_path):
    """Parse a git diff file and return (file_count, total_added, total_removed)."""
    if not os.path.isfile(diff_path):
        return 0, 0, 0
    file_count = 0
    added = 0
    removed = 0
    with open(diff_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("diff --git"):
                file_count += 1
                continue
            if line.startswith("+++") or line.startswith("---"):
                continue
            if line.startswith("+"):
                added += 1
            elif line.startswith("-"):
                removed += 1
    return file_count, added, removed


def _count_commit_chain(run_dir, repo):
    """Read commit-chain.json for a repo and return the commit count (one-shot→final)."""
    chain_path = os.path.join(run_dir, "diffs", repo, "commit-chain.json")
    if not os.path.isfile(chain_path):
        return None
    try:
        with open(chain_path, encoding="utf-8") as f:
            chain = json.load(f)
        commits = chain if isinstance(chain, list) else chain.get("commits", [])
        return len(commits)
    except (json.JSONDecodeError, OSError):
        return None


def _get_human_commits(run_dir, repo):
    """Read commit-chain.json for a repo and return detailed commit list (one-shot→final).

    Returns list of {sha, message, date, author} dicts.
    """
    chain_path = os.path.join(run_dir, "diffs", repo, "commit-chain.json")
    if not os.path.isfile(chain_path):
        return []
    try:
        with open(chain_path, encoding="utf-8") as f:
            chain = json.load(f)
        commits = chain if isinstance(chain, list) else chain.get("commits", [])
        result = []
        for c in commits:
            email = c.get("author_email", "")
            result.append({
                "sha": c.get("sha", ""),
                "message": c.get("message", ""),
                "date": c.get("timestamp", ""),
                "author": email.split("@")[0] if "@" in email else c.get("author_name", ""),
            })
        return result
    except (json.JSONDecodeError, OSError):
        return []


def _get_ai_commits(run_dir, repo):
    """Read AI coding commits from cli-washing/*/agcr.json for a repo.

    agcr.json's result.commits[] contains per-commit shot_ratio data.
    Returns list of {sha, message, date, author, shot_ratio} dicts.
    """
    ai_commits = []
    seen_shas = set()
    cli_dir = os.path.join(run_dir, "cli-washing")
    if not os.path.isdir(cli_dir):
        return ai_commits
    for session_dir in os.listdir(cli_dir):
        agcr_path = os.path.join(cli_dir, session_dir, "agcr.json")
        if not os.path.isfile(agcr_path):
            continue
        try:
            with open(agcr_path, encoding="utf-8") as f:
                agcr_data = json.load(f)
            if not isinstance(agcr_data, list):
                continue
            for entry in agcr_data:
                entry_repo = entry.get("repo", "")
                if entry_repo != repo:
                    continue
                result = entry.get("result", {})
                for c in result.get("commits", []):
                    sha = c.get("hash", "")
                    if sha in seen_shas:
                        continue
                    seen_shas.add(sha)
                    shot = c.get("shot_ratio")
                    ai_commits.append({
                        "sha": sha,
                        "message": c.get("subject", ""),
                        "date": c.get("date", ""),
                        "author": "",
                        "shot_ratio": shot,
                    })
        except (json.JSONDecodeError, OSError):
            continue
    return ai_commits


def _extract_repo_from_path(repo_str):
    """Extract standard repo name from worktree path or repo name.

    "/Users/.../bizad_user_benefit_exchange_server/.worktrees/..." → "bizad_user_benefit_exchange_server"
    "" → ""
    "bizad_user_benefit_exchange_server" → "bizad_user_benefit_exchange_server"
    """
    if not repo_str:
        return ""
    # If it's a path, extract the repo directory name
    parts = repo_str.replace("\\", "/").split("/")
    for part in reversed(parts):
        # Skip worktree-related segments
        if part in (".worktrees", "repos", "code", "waimai", ""):
            continue
        # Check if it looks like a repo name (contains underscore or is a known repo)
        if "_" in part or part in ("server", "client", "api"):
            return part
    # Fallback: return the original string
    return repo_str


def _count_cli_commits_by_repo(run_dir):
    """Scan cli-washing/*/commits.json and return {repo: total_commit_count}.

    commits.json entries have: session_id, command, message, repo, commit_id, branch, timestamp, phase_name.
    This counts all commits per repo across all sessions — represents AI coding phase commits (base→one-shot).

    Handles repo field being:
    - Full repo name: "bizad_user_benefit_exchange_server"
    - Worktree path: "/Users/.../bizad_user_benefit_exchange_server/.worktrees/..."
    - Empty string: tries to derive from agcr.json or branch field
    """
    repo_counts = defaultdict(int)
    cli_dir = os.path.join(run_dir, "cli-washing")
    if not os.path.isdir(cli_dir):
        return repo_counts

    # First pass: load agcr.json to get per-repo commit counts as fallback
    agcr_commit_counts = {}
    for session_dir in os.listdir(cli_dir):
        agcr_path = os.path.join(cli_dir, session_dir, "agcr.json")
        if not os.path.isfile(agcr_path):
            continue
        try:
            with open(agcr_path, encoding="utf-8") as f:
                agcr_data = json.load(f)
            if isinstance(agcr_data, list):
                for entry in agcr_data:
                    repo = entry.get("repo", "")
                    result = entry.get("result", {})
                    commits = result.get("commits", [])
                    if repo and len(commits) > 0:
                        agcr_commit_counts[repo] = len(commits)
        except (json.JSONDecodeError, OSError):
            continue

    # Second pass: count from commits.json
    for session_dir in os.listdir(cli_dir):
        commits_path = os.path.join(cli_dir, session_dir, "commits.json")
        if not os.path.isfile(commits_path):
            continue
        try:
            with open(commits_path, encoding="utf-8") as f:
                commits = json.load(f)
            if not isinstance(commits, list):
                continue
            for c in commits:
                repo = c.get("repo", "")
                # Extract standard repo name from worktree path
                repo = _extract_repo_from_path(repo)
                if not repo:
                    # Try to derive from branch field
                    branch = c.get("branch", "")
                    if branch:
                        for known in _REPO_SHORT_TO_FULL.values():
                            if known in branch or known.split("_")[-1] in branch:
                                repo = known
                                break
                if repo:
                    repo_counts[repo] += 1
        except (json.JSONDecodeError, OSError):
            continue

    # Fallback: if commits.json gave insufficient counts, use agcr.json counts
    for repo, cnt in agcr_commit_counts.items():
        if repo_counts.get(repo, 0) < cnt:
            repo_counts[repo] = cnt

    return dict(repo_counts)


def build_diff_overview(all_hunks, repos_meta, run_dir):
    """Build diff_overview array for render_report.py."""
    by_repo = defaultdict(list)
    for h in all_hunks:
        if h.get("excluded"):
            continue
        by_repo[h.get("repo", "")].append(h)

    repos_dir = os.path.join(run_dir, "repos")
    available_dirs = []
    if os.path.isdir(repos_dir):
        available_dirs = [d for d in os.listdir(repos_dir)
                          if os.path.isdir(os.path.join(repos_dir, d))]
    _priority = ["promo", "client", "api", "server"]
    for d in sorted(available_dirs, key=len, reverse=True):
        if d not in _priority:
            _priority.insert(0, d)

    repo_short_map = {}
    for r in repos_meta.get("repos", []):
        full = r["repo"].lower()
        short = None
        for d in _priority:
            if d in available_dirs and d in full:
                short = d
                break
        if short is None:
            for suffix, s in [("_server", "server"), ("_client", "client"),
                              ("_api", "api"), ("_promo", "promo")]:
                if r["repo"].endswith(suffix):
                    short = s
                    break
        if short is None:
            short = available_dirs[0] if available_dirs else r["repo"]
        repo_short_map[r["repo"]] = short

    # Collect commit counts per phase
    cli_commit_counts = _count_cli_commits_by_repo(run_dir)

    overview = []
    for r in repos_meta.get("repos", []):
        repo = r["repo"]
        repo_hunks = by_repo.get(repo, [])
        diff_path = os.path.join(run_dir, "diffs", repo, f"{repo}-one-shot-to-target-final.diff")
        diff_file_count, total_added, total_removed = _count_diff_lines(diff_path)
        summary = r.get("change_summary", "-")
        if not summary or summary == "-":
            summary = repo_hunks[0].get("change_summary", "-") if repo_hunks else "-"

        # Commit counts per phase
        os2f_commits = _count_commit_chain(run_dir, repo)
        # base→one-shot: match CLI commits by repo name (may be partial match)
        b2o_commits = cli_commit_counts.get(repo)
        if b2o_commits is None:
            # Try matching by repo short name suffix
            for cli_repo, cnt in cli_commit_counts.items():
                if cli_repo in repo or repo in cli_repo:
                    b2o_commits = cnt
                    break

        # Detailed commit lists for render_report.py r_repo_commit_details()
        human_commits = _get_human_commits(run_dir, repo)
        ai_commits = _get_ai_commits(run_dir, repo)

        overview.append({
            "repo": repo,
            "file_count": diff_file_count,
            "hunk_count": len(repo_hunks),
            "added": total_added,
            "removed": total_removed,
            "summary": summary[:150],
            "b2o_commits": b2o_commits,
            "os2f_commits": os2f_commits,
            "ai_commits": ai_commits,
            "human_commits": human_commits,
        })
    return overview


def build_propagation_chain(non_excluded_intents):
    """Group propagation paths by (first_cause_stage, problem_type, root_cause).

    Operates at intent level.
    """
    groups = {}
    for intent in non_excluded_intents:
        pp = intent.get("propagation_path", "")
        if not pp:
            continue
        key = (
            intent.get("first_cause_stage", ""),
            intent.get("problem_type", ""),
            intent.get("root_cause", ""),
        )
        if key not in groups:
            groups[key] = {
                "first_cause_stage": key[0],
                "problem_type": key[1],
                "root_cause": key[2],
                "paths": {},
                "intent_ids": [],
                "hunk_ids": [],
            }
        g = groups[key]
        g["paths"][pp] = g["paths"].get(pp, 0) + 1
        g["intent_ids"].append(intent.get("intent_id", ""))
        g["hunk_ids"].extend(intent.get("hunk_ids", []))

    chain = []
    for key, g in groups.items():
        best_path = max(g["paths"].items(), key=lambda x: x[1])[0]
        chain.append({
            "first_cause_stage": g["first_cause_stage"],
            "problem_type": g["problem_type"],
            "root_cause": g["root_cause"],
            "propagation_path": best_path,
            "intent_count": len(g["intent_ids"]),
            "hunk_count": len(g["hunk_ids"]),
            "intent_ids": g["intent_ids"],
            "hunk_ids": g["hunk_ids"],
        })

    stage_order = {"N1 项目初始化": 0, "N2 现状梳理": 1, "N3 需求澄清": 2,
                   "N4 技术方案": 3, "N5 编码计划": 4, "N6 代码生成": 5}
    chain.sort(key=lambda x: (-x["hunk_count"], stage_order.get(x["first_cause_stage"], 99)))
    return chain


def build_problem_clusters(non_excluded_intents, maps):
    """Cluster non-excluded intents by (first_cause_stage, problem_type, root_cause).

    Operates at intent level. Each cluster represents a distinct systemic issue.
    """
    p_sub_labels = maps.get("p_sub_labels", {})
    groups = {}
    for intent in non_excluded_intents:
        key = (
            intent.get("first_cause_stage", ""),
            intent.get("problem_type", ""),
            intent.get("root_cause", ""),
        )
        if not key[0] or not key[1]:
            continue
        if key not in groups:
            groups[key] = []
        groups[key].append(intent)

    clusters = []
    for key, intents in groups.items():
        stage, pt, rc = key
        stage_disp = normalize_stage(stage)
        pt_label = maps.get("pc_label", {}).get(pt, pt)
        rc_label = maps.get("rc_label", {}).get(rc, rc)

        total_removed = sum(i.get("impact", {}).get("total_removed_lines", 0) or 0 for i in intents)
        total_added = sum(i.get("impact", {}).get("total_added_lines", 0) or 0 for i in intents)

        # Collect involved files/repos from intent metadata
        involved_files = set()
        involved_repos = set()
        all_hunk_ids = []
        for i in intents:
            involved_files.update(i.get("involved_files", []))
            involved_repos.update(i.get("involved_repos", []))
            all_hunk_ids.extend(i.get("hunk_ids", []))

        conf_dist = {"high": 0, "medium": 0, "low": 0}
        for i in intents:
            c = i.get("confidence", "low")
            conf_dist[c] = conf_dist.get(c, 0) + 1

        if conf_dist["high"] > 0:
            priority = "HIGH"
        elif conf_dist["medium"] > 0:
            priority = "MEDIUM"
        else:
            priority = "LOW"

        # Root cause variant distribution
        rc_variants = {}
        for i in intents:
            rv = i.get("root_cause_variant", "")
            if rv:
                rc_variants[rv] = rc_variants.get(rv, 0) + 1

        sub_type_labels = {}
        for rv in rc_variants:
            label = p_sub_labels.get(rv, "")
            if label:
                sub_type_labels[rv] = label

        # Diff nature distribution
        nature_dist = {}
        for i in intents:
            dn = i.get("diff_nature", "")
            if dn:
                nature_dist[dn] = nature_dist.get(dn, 0) + 1

        # Attribution direction distribution
        direction_dist = {}
        for i in intents:
            ad = i.get("attribution_direction", "")
            if ad:
                direction_dist[ad] = direction_dist.get(ad, 0) + 1

        # Representative recommendation: most common text
        rec_counter = Counter()
        for i in intents:
            rec = i.get("recommendation", "")
            if rec:
                rec_counter[rec] += 1
        rep_rec = rec_counter.most_common(1)[0][0] if rec_counter else ""

        pp_counter = Counter()
        for i in intents:
            pp = i.get("propagation_path", "")
            if pp:
                pp_counter[pp] += 1
        rep_pp = pp_counter.most_common(1)[0][0] if pp_counter else ""

        # Representative evidence: from highest confidence intent
        conf_rank = {"high": 3, "medium": 2, "low": 1}
        best_intent = max(intents, key=lambda i: conf_rank.get(i.get("confidence", "low"), 0))
        rep_evidence = ""
        ec = best_intent.get("evidence_chain", [])
        if ec and isinstance(ec, list) and len(ec) > 0:
            first_entry = ec[0]
            if isinstance(first_entry, dict):
                rep_evidence = first_entry.get("finding", "")
        rep_direct_cause = best_intent.get("direct_cause", "")

        clusters.append({
            "cluster_id": "",
            "first_cause_stage": stage_disp,
            "problem_type": pt,
            "problem_type_label": pt_label,
            "root_cause": rc,
            "root_cause_label": rc_label,
            "cluster_label": f"{stage_disp} · {pt} {pt_label} · {rc} {rc_label}",
            "intent_count": len(intents),
            "hunk_count": len(all_hunk_ids),
            "total_removed_lines": total_removed,
            "total_added_lines": total_added,
            "involved_files": sorted(involved_files),
            "involved_repos": sorted(involved_repos),
            "intent_ids": [i.get("intent_id", "") for i in intents],
            "hunk_ids": all_hunk_ids,
            "root_cause_variant_distribution": rc_variants,
            "sub_type_labels": sub_type_labels,
            "diff_nature_distribution": nature_dist,
            "attribution_direction_distribution": direction_dist,
            "confidence_distribution": conf_dist,
            "improvement_priority": priority,
            "representative_recommendation": rep_rec,
            "representative_propagation_path": rep_pp,
            "representative_evidence": rep_evidence,
            "representative_direct_cause": rep_direct_cause,
        })

    clusters.sort(key=lambda c: (-c["total_removed_lines"], -c["hunk_count"]))

    for idx, c in enumerate(clusters, 1):
        c["cluster_id"] = f"C{idx:02d}"

    return clusters


def build_recommendations(non_excluded_intents, maps, clusters):
    """Build cluster-based recommendations, deduplicated by cluster key.

    Operates at intent level.
    """
    result = []
    for cluster in clusters:
        rec_text = cluster.get("representative_recommendation", "")
        if not rec_text:
            continue
        pt = cluster.get("problem_type", "")
        pt_label = cluster.get("problem_type_label", "")
        stage = cluster.get("first_cause_stage", "")
        priority = cluster.get("improvement_priority", "LOW")
        intent_count = cluster.get("intent_count", 0)
        hunk_count = cluster.get("hunk_count", 0)
        file_count = len(cluster.get("involved_files", []))
        cluster_id = cluster.get("cluster_id", "")

        # Display problem type: SIT IDs (e.g. FUNC_LOGIC_ERROR) show only Chinese label,
        # P-codes (e.g. P5-1) keep "P5-1 label" form.
        if pt and re.match(r'^[A-Z][A-Z0-9_]+$', pt):
            pt_display = pt_label if pt_label else pt
        else:
            pt_display = f"{pt} {pt_label}".strip() if pt_label else pt
        text = f"[{cluster_id} | {pt_display} / {stage}] {rec_text}（涉及 {intent_count} 个 intent，{hunk_count} 个 hunk，{file_count} 个文件）"
        result.append({"priority": priority, "text": text})

    result.sort(key=lambda r: -priority_order_val(r["priority"]))
    return result


def priority_order_val(p):
    return {"HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(p, 0)


def build_key_findings(non_excluded_intents, maps, clusters, agcr_calc):
    """Synthesize key findings from attribution data.

    Generates high-level insights ranked by severity:
    1. Dominant stage concentration (if one stage accounts for ≥70% of CIs)
    2. Top problem type cluster (largest by hunk count)
    3. Root cause concentration (if one root cause accounts for ≥60%)
    4. High-waste CIs (individual CIs with ≥50 removed lines)
    5. Cross-repo impact (if a cluster spans multiple repos)
    """
    findings = []
    if not non_excluded_intents:
        return findings

    total_cis = len(non_excluded_intents)
    pc_label_map = maps.get("pc_label", {})
    rc_label_map = maps.get("rc_label", {})

    # --- 1. Stage concentration ---
    stage_counts = {}
    for i in non_excluded_intents:
        s = normalize_stage(i.get("first_cause_stage", ""))
        stage_counts[s] = stage_counts.get(s, 0) + 1
    if stage_counts:
        top_stage, top_cnt = max(stage_counts.items(), key=lambda x: x[1])
        ratio = top_cnt / total_cis if total_cis else 0
        if ratio >= 0.7 and total_cis >= 3:
            pct = int(ratio * 100)
            findings.append({
                "title": f"首因集中在 {top_stage}",
                "description": f"{top_cnt}/{total_cis} 个修改意图（{pct}%）的首因阶段为 {top_stage}，"
                               f"建议重点优化该阶段的产物质量检查。",
                "severity": "high",
                "related_fcs": [],
                "related_hunks": [],
            })

    # --- 2. Top problem cluster ---
    if clusters:
        top_cluster = max(clusters, key=lambda c: c.get("hunk_count", 0))
        tc_pt = top_cluster.get("problem_type", "")
        tc_pt_label = top_cluster.get("problem_type_label", tc_pt)
        tc_stage = top_cluster.get("first_cause_stage", "")
        tc_hunks = top_cluster.get("hunk_count", 0)
        tc_intents = top_cluster.get("intent_count", 0)
        tc_removed = top_cluster.get("total_removed_lines", 0)
        # Format display
        if tc_pt and re.match(r'^[A-Z][A-Z0-9_]+$', tc_pt):
            tc_disp = tc_pt_label if tc_pt_label else tc_pt
        else:
            tc_disp = f"{tc_pt} {tc_pt_label}".strip() if tc_pt_label else tc_pt
        findings.append({
            "title": f"最大问题簇：{tc_disp}（{tc_stage}）",
            "description": f"涉及 {tc_intents} 个 CI、{tc_hunks} 个 Hunk、"
                           f"共 {tc_removed} 行废弃代码。"
                           f"{top_cluster.get('representative_direct_cause', '') or ''}",
            "severity": "high" if tc_removed >= 50 else "medium",
            "related_hunks": top_cluster.get("hunk_ids", []),
            "related_fcs": [],
        })

    # --- 3. Root cause concentration ---
    rc_counts = {}
    for i in non_excluded_intents:
        rc = i.get("root_cause", "")
        if rc:
            rc_counts[rc] = rc_counts.get(rc, 0) + 1
    if rc_counts:
        top_rc, top_rc_cnt = max(rc_counts.items(), key=lambda x: x[1])
        rc_ratio = top_rc_cnt / total_cis if total_cis else 0
        if rc_ratio >= 0.6 and total_cis >= 3:
            rc_disp = f"{top_rc} {rc_label_map.get(top_rc, '')}".strip()
            pct = int(rc_ratio * 100)
            findings.append({
                "title": f"根因集中：{rc_disp}",
                "description": f"{top_rc_cnt}/{total_cis} 个 CI（{pct}%）归因于 {rc_disp}，"
                               f"表明该类根因是本次需求的系统性问题来源。",
                "severity": "medium",
                "related_hunks": [],
                "related_fcs": [],
            })

    # --- 4. High-waste individual CIs ---
    high_waste = []
    for i in non_excluded_intents:
        removed = i.get("impact", {}).get("total_removed_lines", 0) or 0
        if removed >= 50:
            high_waste.append(i)
    high_waste.sort(key=lambda x: -(x.get("impact", {}).get("total_removed_lines", 0) or 0))
    for hw in high_waste[:3]:  # Top 3
        cid = hw.get("intent_id", "")
        removed = hw.get("impact", {}).get("total_removed_lines", 0) or 0
        desc = hw.get("intent_description", "")
        if len(desc) > 60:
            desc = desc[:57] + "…"
        findings.append({
            "title": f"{cid} 废弃 {removed} 行",
            "description": desc,
            "severity": "medium" if removed >= 100 else "low",
            "related_hunks": hw.get("hunk_ids", []),
            "related_fcs": [],
        })

    # --- 5. Cross-repo cluster ---
    for c in clusters:
        repos = c.get("involved_repos", [])
        if len(repos) >= 2:
            tc_pt = c.get("problem_type", "")
            tc_pt_label = c.get("problem_type_label", tc_pt)
            if tc_pt and re.match(r'^[A-Z][A-Z0-9_]+$', tc_pt):
                tc_disp = tc_pt_label if tc_pt_label else tc_pt
            else:
                tc_disp = f"{tc_pt} {tc_pt_label}".strip() if tc_pt_label else tc_pt
            findings.append({
                "title": f"跨仓库影响：{tc_disp}",
                "description": f"该问题簇跨越 {len(repos)} 个仓库（{', '.join(repos)}），"
                               f"说明设计缺陷传导范围较广。",
                "severity": "medium",
                "related_hunks": c.get("hunk_ids", []),
                "related_fcs": [],
            })

    # --- 6. AGCR headline ---
    agcr_val = agcr_calc.get("agcr_value")
    abandonment = agcr_calc.get("abandonment_rate")
    if agcr_val is not None:
        agcr_pct = round(agcr_val * 100, 1) if agcr_val <= 1 else round(agcr_val, 1)
        abd_pct = round(abandonment * 100, 1) if abandonment and abandonment <= 1 else (round(abandonment, 1) if abandonment else 0)
        sev = "high" if abd_pct >= 20 else "medium" if abd_pct >= 10 else "low"
        findings.insert(0, {
            "title": f"AGCR {agcr_pct}%，废弃率 {abd_pct}%",
            "description": f"AI 一次性生成代码的保留率为 {agcr_pct}%，"
                           f"有 {abd_pct}% 的代码在人工审阅后被废弃修改。",
            "severity": sev,
            "related_hunks": [],
            "related_fcs": [],
        })

    # Sort: HIGH first, then MEDIUM, then LOW
    sev_order = {"high": 3, "medium": 2, "low": 1}
    findings.sort(key=lambda f: -sev_order.get(f.get("severity", "low"), 0))
    return findings


def _compute_impact(removed_lines, total_one_shot_lines, total_final_lines, added_lines=0):
    """Compute impact rates for an intent or FC.

    Metrics:
      abandonment_impact: removed / one_shot — 该 CI 废弃的 AI 代码占 AI 总生成量的比例
      agcr_impact: removed / final — 该 CI 废弃的 AI 代码占最终代码的比例（废弃部分）
      gap_impact: (removed + net_new) / final — 该 CI 导致的 AGCR 缺口占比（废弃 + 人工补写）
        net_new = max(added - removed, 0)，排除"修改行"的重复计数（删1行+加1行=净0变化）
      gap_impact 加和 ≈ 1 - AGCR（可解释 AGCR 下降的全部原因）
    """
    result = {}
    if total_one_shot_lines and total_one_shot_lines > 0:
        result["abandonment_impact"] = round(removed_lines / total_one_shot_lines, 6)
    else:
        result["abandonment_impact"] = None
    if total_final_lines and total_final_lines > 0:
        result["agcr_impact"] = round(removed_lines / total_final_lines, 6)
        net_new = max(added_lines - removed_lines, 0)
        result["gap_impact"] = round((removed_lines + net_new) / total_final_lines, 6)
    else:
        result["agcr_impact"] = None
        result["gap_impact"] = None
    return result


def passthrough_execution_trace(run_dir):
    """Load execution_trace.json (three-layer fusion) and pass it through to attribution-result.json.

    Per REFACTOR-PLAN §11.8, execution_trace.json replaces trace_by_stage.json.
    Falls back to trace_by_stage.json for backward compat with older runs.

    Returns the parsed dict, or None if neither file exists.
    """
    et_path = os.path.join(run_dir, "artifacts", "execution_trace.json")
    if not os.path.isfile(et_path):
        et_path = os.path.join(run_dir, "execution_trace.json")  # also check run_dir root
    if not os.path.isfile(et_path):
        # Backward compat: try trace_by_stage.json
        et_path = os.path.join(run_dir, "artifacts", "trace_by_stage.json")
        if not os.path.isfile(et_path):
            et_path = os.path.join(run_dir, "trace_by_stage.json")
    if not os.path.isfile(et_path):
        return None
    try:
        with open(et_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def build_artifact_summary(run_dir, repos_meta):
    """Build artifact_summary covering ALL known artifacts (per subagent-artifact spec) + session trace."""
    # Full artifact registry: (filename, stage_label, artifact_display_name)
    ARTIFACT_REGISTRY = [
        ("design.md",                 "技术方案",     "技术方案设计文档"),
        ("design-interface.md",       "技术方案",     "接口设计文档"),
        ("constraint-check.md",       "技术方案",     "约束检查文档"),
        ("tasks.md",                  "编码计划",     "编码计划 / 任务拆解"),
        ("requirement.md",            "需求澄清",     "需求分析文档"),
        ("clarification-log.md",      "需求澄清",     "澄清交互日志"),
        ("clarification-summary.md",  "需求澄清",     "澄清交互摘要"),
        ("current-state.md",          "现状梳理",     "现状基线文档"),
        ("original-requirement.md",   "项目初始化",   "PRD 原始需求"),
        ("feature-points.md",         "项目初始化",   "功能点拆解"),
        ("domain-knowledge.md",       "项目初始化",   "领域知识文档"),
        ("evidence.md",               "项目初始化",   "调研证据文档"),
        ("repo.md",                   "项目初始化",   "仓库范围识别"),
        ("work_status.md",            "项目初始化",   "领域识别与工作状态"),
    ]
    artifacts_dir = os.path.join(run_dir, "artifacts")
    summary = []
    for fname, stage_label, display_name in ARTIFACT_REGISTRY:
        fpath = os.path.join(artifacts_dir, fname)
        if os.path.isfile(fpath):
            # Check file is non-empty
            fsize = os.path.getsize(fpath)
            if fsize > 0:
                summary.append({
                    "stage": stage_label,
                    "artifact_name": display_name,
                    "status": "已读取",
                    "note": fpath,
                })
            else:
                summary.append({
                    "stage": stage_label,
                    "artifact_name": display_name,
                    "status": "缺失",
                    "note": f"文件存在但内容为空: {fpath}",
                })
        else:
            summary.append({
                "stage": stage_label,
                "artifact_name": display_name,
                "status": "缺失",
                "note": f"产物文件未找到: {fpath}",
            })

    # Execution trace (three-layer fusion: phases + commits + dag)
    et_path = os.path.join(run_dir, "artifacts", "execution_trace.json")
    if not os.path.isfile(et_path):
        et_path = os.path.join(run_dir, "execution_trace.json")
    if not os.path.isfile(et_path):
        # Backward compat: try trace_by_stage.json
        et_path = os.path.join(run_dir, "artifacts", "trace_by_stage.json")
        if not os.path.isfile(et_path):
            et_path = os.path.join(run_dir, "trace_by_stage.json")
    session_id = repos_meta.get("session_id", "")
    if os.path.isfile(et_path):
        summary.append({
            "stage": "全链路",
            "artifact_name": "Execution Trace（三层融合链路）",
            "status": "已读取",
            "note": "phases + commits + dag 三层融合，用于 R2/R3 区分",
        })
    else:
        reason = "无 session_id，未执行 trace 提取" if not session_id else f"execution_trace.json 未生成 (session_id={session_id})"
        summary.append({
            "stage": "全链路",
            "artifact_name": "Execution Trace（三层融合链路）",
            "status": "缺失",
            "note": reason,
        })

    return summary


def extract_developers_from_commits(run_dir, repos_meta, hunk_list):
    """Extract unique developer MIS IDs from commit-chain.json and hunk source_commits.

    Priority:
      1. commit-chain.json per repo (author_email → MIS, or author_name)
      2. hunk-level source_commits[].author
      3. Fallback to repos_meta.developers (may be the 执行人 from Observability API)

    Returns (commit_developers: str, developer_source: str).
    commit_developers is comma-separated MIS list; developer_source describes where it came from.
    """
    authors = set()

    # 1. Try commit-chain.json for each repo
    for r in repos_meta.get("repos", []):
        repo = r.get("repo", "")
        chain_path = os.path.join(run_dir, "diffs", repo, "commit-chain.json")
        if os.path.isfile(chain_path):
            try:
                with open(chain_path, encoding="utf-8") as f:
                    chain = json.load(f)
                commits = chain if isinstance(chain, list) else chain.get("commits", [])
                for c in commits:
                    # Try author_email (extract MIS from xxx@xxx.com → xxx)
                    email = c.get("author_email") or c.get("committer_email") or ""
                    if email and "@" in email:
                        mis = email.split("@")[0].strip()
                        if mis and mis not in ("noreply", "git", "merge"):
                            authors.add(mis)
                            continue
                    # Try author_name / author / committer
                    name = c.get("author_name") or c.get("author") or c.get("committer_name") or ""
                    if name and name.strip() not in ("", "-", "unknown"):
                        authors.add(name.strip())
            except (json.JSONDecodeError, OSError):
                pass

    chain_source = bool(authors)

    # 2. Fallback: scan hunk source_commits for author field
    if not authors:
        for h in hunk_list:
            if h.get("excluded"):
                continue
            for sc in (h.get("source_commits") or []):
                author = sc.get("author") or sc.get("author_name") or ""
                if author and author.strip() not in ("", "-", "unknown"):
                    authors.add(author.strip())
                email = sc.get("author_email") or ""
                if email and "@" in email:
                    mis = email.split("@")[0].strip()
                    if mis and mis not in ("noreply", "git", "merge"):
                        authors.add(mis)

    if authors:
        source = "commit_chain" if chain_source else "source_commits"
        return ",".join(sorted(authors)), source

    # 3. Final fallback: repos_meta.developers (may be 执行人)
    meta_dev = repos_meta.get("developers", "")
    if meta_dev and str(meta_dev).strip() not in ("", "-"):
        return str(meta_dev).strip(), "repos_meta"

    return "", "unknown"


def _is_low_confidence(val):
    """Check if a confidence value is 'low' (supports both numeric and string formats)."""
    if isinstance(val, (int, float)):
        return val < 0.5
    return str(val).strip().lower() in ("low", "")


def build_evidence_gaps(hunks, artifact_summary, intents=None):
    """Detect evidence gaps: intents/hunks missing key evidence fields, and missing artifacts.

    Checks are performed at the intent level (CI) when intents are available,
    falling back to hunk-level checks for removed_lines data pipeline issues.
    """
    gaps = []

    # Check for missing artifacts
    for a in artifact_summary:
        if a.get("status") == "缺失":
            gaps.append({
                "stage": a.get("stage", "-"),
                "gap": f"产物 {a.get('artifact_name', '-')} 缺失",
                "impact": "该阶段无产物可用于归因分析，可能影响首因判定准确性",
                "suggestion": f"检查产物生成流程，确保 {a.get('artifact_name', '-')} 正常输出到 artifacts/ 目录",
            })

    # Use intent-level data for evidence checks when available (归因数据在 intent 级别)
    if intents:
        # Check for intents with low-confidence
        low_conf = [i for i in intents if _is_low_confidence(i.get("confidence", "low"))]
        if low_conf:
            gaps.append({
                "stage": "全阶段",
                "gap": f"{len(low_conf)}/{len(intents)} 个 Intent 置信度为低",
                "impact": "低置信度归因可能不准确，影响整体报告可信度",
                "suggestion": "补充上游产物片段或 trace 证据，提升归因置信度",
            })

        # Check for intents missing evidence_chain
        no_chain = [i for i in intents if not i.get("evidence_chain")]
        if no_chain:
            gaps.append({
                "stage": "全阶段",
                "gap": f"{len(no_chain)}/{len(intents)} 个 Intent 无证据链 (evidence_chain)",
                "impact": "缺少证据链的 Intent 难以追溯根因，归因结果可解释性降低",
                "suggestion": "在归因阶段为每个 Intent 补充证据链，记录从首因到体现的完整路径",
            })

        # Check for intents missing direct_cause
        no_cause = [i for i in intents if not i.get("direct_cause")
                    or str(i.get("direct_cause", "")).strip() in ("-", "")]
        if no_cause:
            gaps.append({
                "stage": "全阶段",
                "gap": f"{len(no_cause)}/{len(intents)} 个 Intent 缺少直接成因 (direct_cause)",
                "impact": "缺少直接成因描述的 Intent 归因依据不足",
                "suggestion": "在归因阶段补充每个 Intent 的直接成因描述",
            })

        # Check for evidence_chain steps with missing upstream_snippet (§4.2 硬约束)
        broken_snippets = []
        for i in intents:
            ec = i.get("evidence_chain", [])
            if not isinstance(ec, list):
                continue
            for step in ec:
                if not isinstance(step, dict):
                    continue
                up_art = step.get("upstream_artifact")
                up_snip = step.get("upstream_snippet")
                if up_art and not up_snip:
                    broken_snippets.append(i.get("intent_id", "?"))
        if broken_snippets:
            gaps.append({
                "stage": "全阶段",
                "gap": f"{len(broken_snippets)} 个 Intent 的 evidence_chain 存在 upstream_artifact 不为 null 但 upstream_snippet 为空",
                "impact": "证据链断裂：上游产物已引用但缺少具体文本片段，无法追溯上游证据",
                "suggestion": "在 evidence_chain 中为每个非 null 的 upstream_artifact 补充 upstream_snippet（至少一行原文）",
            })

        # Check for evidence_chain steps missing dependency_path (§4.1)
        missing_dep_path = []
        for i in intents:
            ec = i.get("evidence_chain", [])
            if not isinstance(ec, list):
                continue
            for step in ec:
                if not isinstance(step, dict):
                    continue
                # Only check non-signal-sufficient layers (where upstream_artifact is not null)
                if step.get("upstream_artifact") and not step.get("dependency_path"):
                    missing_dep_path.append(i.get("intent_id", "?"))
        if missing_dep_path:
            gaps.append({
                "stage": "全阶段",
                "gap": f"{len(missing_dep_path)} 个 Intent 的 evidence_chain 传导层/首因层缺少 dependency_path",
                "impact": "缺少依赖传导路径，无法追溯缺陷沿固定依赖链的传导方向",
                "suggestion": "在 evidence_chain 的首因层和传导层补充 dependency_path 字段",
            })
    else:
        # Fallback: hunk-level checks (legacy mode)
        non_excluded = [h for h in hunks if not h.get("excluded")]
        low_conf = [h for h in non_excluded if _is_low_confidence(h.get("confidence", "low"))]
        if low_conf:
            gaps.append({
                "stage": "全阶段",
                "gap": f"{len(low_conf)} 个 Hunk 置信度为低",
                "impact": "低置信度归因可能不准确，影响整体报告可信度",
                "suggestion": "补充上游产物片段或 trace 证据，提升归因置信度",
            })

        no_chain = [h for h in non_excluded if not h.get("evidence_chain")]
        if no_chain:
            gaps.append({
                "stage": "全阶段",
                "gap": f"{len(no_chain)} 个 Hunk 无证据链 (evidence_chain)",
                "impact": "缺少证据链的 Hunk 难以追溯根因，归因结果可解释性降低",
                "suggestion": "在归因阶段为每个 Hunk 补充证据链，记录从首因到体现的完整路径",
            })

        no_cause = [h for h in non_excluded if not h.get("direct_cause")
                    or str(h.get("direct_cause", "")).strip() in ("-", "")]
        if no_cause:
            gaps.append({
                "stage": "全阶段",
                "gap": f"{len(no_cause)} 个 Hunk 缺少直接成因 (direct_cause)",
                "impact": "缺少直接成因描述的 Hunk 归因依据不足",
                "suggestion": "在归因阶段补充每个 Hunk 的直接成因描述",
            })

    # Check for hunks with all removed_lines = 0 (data pipeline issue, always hunk-level)
    non_excluded = [h for h in hunks if not h.get("excluded")]
    zero_removed = [h for h in non_excluded if (h.get("removed_lines", 0) or 0) == 0]
    if zero_removed and len(zero_removed) == len(non_excluded):
        gaps.append({
            "stage": "全阶段",
            "gap": "所有 Hunk 的 removed_lines 均为 0",
            "impact": "无法计算 AGCR 废弃率和 CI 级别影响率，所有 impact 指标为 N/A",
            "suggestion": "检查 calc_agcr.py diff 解析流程，确认 hunk 级别 removed_lines 字段正确填充",
        })

    return gaps


# ---------- Main aggregation ----------

def aggregate(run_dir, config_dir, repos_meta_path, hunk_list_path):
    """Main aggregation function (intent-level)."""
    with open(repos_meta_path, encoding="utf-8") as f:
        repos_meta = json.load(f)

    maps = load_problem_types(config_dir)
    all_intents, hunk_list = load_all_intents(run_dir, hunk_list_path)

    # Normalize hunk-list: fix hunk_id format, repo names, before_code/after_code, line counts
    hunk_list = normalize_hunk_list(hunk_list, repos_meta)

    # Build hunk_id → metadata lookup
    hunk_lookup = {}
    for h in hunk_list:
        hid = h.get("hunk_id")
        if hid:
            hunk_lookup[hid] = h

    # Load agcr-calc.json
    agcr_calc_path = os.path.join(run_dir, "agcr-calc.json")
    with open(agcr_calc_path, encoding="utf-8") as f:
        agcr_calc = json.load(f)

    # Split excluded / non-excluded at intent level
    non_excluded_intents = [i for i in all_intents if not _is_intent_excluded(i, hunk_lookup)]
    excluded_intents = [i for i in all_intents if _is_intent_excluded(i, hunk_lookup)]

    # Hunk-level stats (for diff_overview and compatibility)
    non_excluded_hunks = [h for h in hunk_list if not h.get("excluded")]
    excluded_hunks = [h for h in hunk_list if h.get("excluded")]

    # Aggregate intent-level statistics
    by_stage = Counter(i.get("first_cause_stage", "未知") for i in non_excluded_intents)
    by_problem_type = Counter(i.get("problem_type", "") for i in non_excluded_intents)
    by_root_cause = Counter(i.get("root_cause", "") for i in non_excluded_intents)
    by_confidence = Counter(normalize_confidence(i.get("confidence", "low")) for i in non_excluded_intents)
    by_diff_nature = Counter(i.get("diff_nature", "") for i in non_excluded_intents)
    by_attribution_direction = Counter(i.get("attribution_direction", "") for i in non_excluded_intents)

    # Surface issue type stats
    sit_label = maps.get("sit_label", {})
    surface_counts = Counter(i.get("surface_issue_type", "OTHER") for i in non_excluded_intents)
    enum_hit = sum(1 for i in non_excluded_intents if i.get("surface_issue_type") in sit_label)
    custom_count = len(non_excluded_intents) - enum_hit

    # Excluded by reason (hunk-level)
    excluded_by_reason = {
        "whitespace": sum(1 for h in excluded_hunks if h.get("exclude_reason") == "whitespace"),
        "auto_import": sum(1 for h in excluded_hunks if h.get("exclude_reason") == "auto_import"),
        "auto_generated": sum(1 for h in excluded_hunks if h.get("exclude_reason") == "auto_generated"),
        "test_file": sum(1 for h in excluded_hunks if h.get("exclude_reason") == "test_file"),
        "doc_only": sum(1 for h in excluded_hunks if h.get("exclude_reason") == "doc_only"),
        "config_only": sum(1 for h in excluded_hunks if h.get("exclude_reason") == "config_only"),
        "merge_master": sum(1 for h in excluded_hunks if h.get("exclude_reason") == "merge_master"),
    }

    # Build diff_overview
    diff_overview = build_diff_overview(hunk_list, repos_meta, run_dir)

    # Build propagation chain
    propagation_chain = build_propagation_chain(non_excluded_intents)

    # Build problem clusters
    problem_clusters = build_problem_clusters(non_excluded_intents, maps)

    # Build recommendations
    recommendations = build_recommendations(non_excluded_intents, maps, problem_clusters)

    # Load key findings: prefer AI-generated file, fallback to auto-synthesis
    key_findings = []
    key_findings_path = os.path.join(run_dir, "key-findings.json")
    if os.path.isfile(key_findings_path):
        with open(key_findings_path, encoding="utf-8") as f:
            key_findings_raw = json.load(f)
        # Normalize: extract list from wrapper dict, map field names
        key_findings = normalize_key_findings(key_findings_raw)
    if not key_findings:
        key_findings = build_key_findings(non_excluded_intents, maps, problem_clusters, agcr_calc)

    # FC grouping via design.md D-xx anchoring
    design_path = os.path.join(run_dir, "artifacts", "design.md")
    grand_total = agcr_calc.get("grand_total", {})
    grand_one_shot = grand_total.get("one_shot_lines", 0)
    grand_final = grand_total.get("final_lines", 0)

    feature_changes = group_intents_by_design(all_intents, hunk_lookup, design_path, maps)

    # Compute impact rates for FCs and individual intents
    for fc in feature_changes:
        fc_intents = fc.pop("_intents", [])
        fc_removed = sum(i.get("impact", {}).get("total_removed_lines", 0) or 0 for i in fc_intents)
        fc_added = sum(i.get("impact", {}).get("total_added_lines", 0) or 0 for i in fc_intents)
        fc["impact"] = _compute_impact(fc_removed, grand_one_shot, grand_final, fc_added)
        for intent in fc_intents:
            i_removed = intent.get("impact", {}).get("total_removed_lines", 0) or 0
            i_added = intent.get("impact", {}).get("total_added_lines", 0) or 0
            if "impact" not in intent:
                intent["impact"] = {}
            intent["impact"].update(_compute_impact(i_removed, grand_one_shot, grand_final, i_added))

    # Build intent_groups for §6 (首因阶段 × 问题类型)
    intent_groups = build_intent_groups(all_intents, hunk_lookup, maps)

    # Build change_intent_groups for §6 (修改意图粒度)
    change_intents = load_change_intents(run_dir)
    # Normalize change-intents: fix field names, supplement missing fields
    change_intents = normalize_change_intents(change_intents, all_intents)

    # ── Merge cluster_confidence into intent fragments ──
    # SubAgent-RootCause may not inherit cluster_confidence from change-intents.json,
    # writing a uniform "medium". We fix this here by overriding the fragment's
    # confidence with the authoritative cluster_confidence from the clustering step.
    ci_conf_map = {}
    for ci in change_intents:
        ci_id = ci.get("intent_id", "")
        cc = ci.get("cluster_confidence", "")
        if ci_id and cc:
            ci_conf_map[ci_id] = normalize_confidence(cc)
    if ci_conf_map:
        merged_count = 0
        for it in all_intents:
            ci_id = it.get("intent_id", "")
            if ci_id in ci_conf_map:
                it["confidence"] = ci_conf_map[ci_id]
                merged_count += 1
        print(f"[aggregate] Merged cluster_confidence into {merged_count} intent fragments "
              f"(out of {len(all_intents)})", file=sys.stderr)

    # Build intent_id → intent fragment lookup for attribution fields
    intent_frag_map = {i.get("intent_id", ""): i for i in all_intents if i.get("intent_id")}
    change_intent_groups = build_change_intent_groups(hunk_list, change_intents, maps, intent_frag_map)

    # Compute impact for CI groups
    for ci_group in change_intent_groups:
        ci_hunks = ci_group.get("hunks", [])
        ci_removed = sum(h.get("removed_lines", 0) or 0 for h in ci_hunks)
        ci_added = sum(h.get("added_lines", 0) or 0 for h in ci_hunks)
        ci_impact = _compute_impact(ci_removed, grand_one_shot, grand_final, ci_added)
        ci_impact["total_removed_lines"] = ci_removed
        ci_impact["total_added_lines"] = ci_added
        ci_group["impact"] = ci_impact

    # Build artifact summary
    artifact_summary = build_artifact_summary(run_dir, repos_meta)

    # Resolve developers: prefer repos_meta.commit_developers (set by main Agent from commit chain),
    # then try extracting from commit-chain.json files (fallback), then repos_meta.developers (observability).
    meta_commit_devs = repos_meta.get("commit_developers", "")
    meta_developers = repos_meta.get("developers", "")
    meta_dev_source = repos_meta.get("developer_source", "")
    if meta_commit_devs:
        # Main Agent already extracted from commit chain
        final_developers = meta_commit_devs
        developer_source = meta_dev_source or "commit_chain"
    else:
        # Fallback: try extracting ourselves from commit-chain.json files
        commit_developers, developer_source = extract_developers_from_commits(run_dir, repos_meta, hunk_list)
        final_developers = commit_developers or meta_developers or ""

    # Build result JSON
    result = {
        "requirement_id": repos_meta.get("requirement_id", ""),
        "requirement_name": repos_meta.get("requirement_name", ""),
        "developers": final_developers,
        "developer_source": developer_source,
        "meta_developers": meta_developers,
        "fsd_url": repos_meta.get("fsd_url", ""),
        "run_id": repos_meta.get("run_id", ""),
        "agcr_value": repos_meta.get("agcr_value"),
        "commit_source": repos_meta.get("commit_source", "agcr_data_json"),
        "target_final_commit_source": repos_meta.get("target_final_commit_source", "pr_merge_commit"),
        "target_final_kind": repos_meta.get("target_final_kind", "online_or_merged"),
        "code_source": repos_meta.get("code_source", "remote_code_platform"),
        "remote_provider": repos_meta.get("remote_provider", "meituan_code_compare_api"),
        "repos": repos_meta.get("repos", []),
        "commit_gate": repos_meta.get("commit_gate", {
            "status": "passed", "missing": [], "invalid": [], "branch_errors": []
        }),
        "summary": {
            "by_stage": dict(by_stage),
            "by_problem_type": dict(by_problem_type),
            "by_root_cause": dict(by_root_cause),
            "by_confidence": dict(by_confidence),
            "by_diff_nature": dict(by_diff_nature),
            "by_attribution_direction": dict(by_attribution_direction),
            "surface_issue_type_stats": {
                "enum_hit_count": enum_hit,
                "custom_count": custom_count,
                "custom_types": [],
            },
        },
        "feature_changes": feature_changes,
        "intent_groups": intent_groups,
        "change_intent_groups": change_intent_groups,
        "change_intents": change_intents,
        "diff_overview": diff_overview,
        "propagation_chain": propagation_chain,
        "problem_clusters": problem_clusters,
        "key_findings": key_findings,
        "recommendations": recommendations,
        "excluded_hunks_count": len(excluded_hunks),
        "excluded_hunks_by_reason": excluded_by_reason,
        "calculated_agcr": agcr_calc,
        "artifact_summary": artifact_summary,
        "execution_trace": passthrough_execution_trace(run_dir),
        "intents": all_intents,
        "hunks": hunk_list,
        "stage_attributions": [],
        "evidence_gaps": build_evidence_gaps(hunk_list, artifact_summary, intents=all_intents),
        "outputs": {
            "report_html_path": "",
            "report_html_s3_url": "",
            "result_json_path": "",
            "result_json_s3_url": "",
        },
    }

    return result


def main():
    ap = argparse.ArgumentParser(
        description="Aggregate intent fragments into attribution-result.json"
    )
    ap.add_argument("--run-dir", required=True, help="Run output directory (e.g. /tmp/agcr-{run_id})")
    ap.add_argument("--config-dir", required=True, help="Skill config directory")
    ap.add_argument("--repos-meta", required=True, help="repos-meta.json path")
    ap.add_argument("--hunk-list", required=True, help="hunk-list.json path (metadata source of truth)")
    ap.add_argument("--output", required=True, help="Output attribution-result.json path")
    args = ap.parse_args()

    result = aggregate(args.run_dir, args.config_dir, args.repos_meta, args.hunk_list)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    non_excl_intents = sum(1 for i in result.get("intents", []) if i.get("first_cause_stage"))
    non_excl_hunks = sum(1 for h in result.get("hunks", []) if not h.get("excluded"))
    excl_hunks = sum(1 for h in result.get("hunks", []) if h.get("excluded"))
    agcr = result.get("calculated_agcr", {}).get("agcr")
    agcr_str = f"{agcr*100:.1f}%" if agcr is not None else "N/A"
    abn = result.get("calculated_agcr", {}).get("abandonment_rate")
    abn_str = f"{abn*100:.1f}%" if abn is not None else "N/A"

    fc_count = len(result.get("feature_changes", []))
    group_count = len(result.get("intent_groups", []))
    ci_count = len(result.get("change_intent_groups", []))

    print(f"[aggregate] intents: {non_excl_intents}, hunks: {non_excl_hunks} non-excluded, {excl_hunks} excluded", file=sys.stderr)
    print(f"[aggregate] FC groups: {fc_count} (design-anchored + file-default)", file=sys.stderr)
    print(f"[aggregate] §6 intent groups: {group_count} (stage × problem_type)", file=sys.stderr)
    print(f"[aggregate] §6 change_intent_groups: {ci_count} (CI-level cards)", file=sys.stderr)
    print(f"[aggregate] AGCR (one-shot 采纳率): {agcr_str}", file=sys.stderr)
    print(f"[aggregate] Abandonment (one-shot 废弃率): {abn_str}", file=sys.stderr)
    print(f"[aggregate] Written to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
