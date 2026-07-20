#!/usr/bin/env python3
"""Deterministic renderer: attribution-result.json + template -> attribution-report.html"""
import argparse, json, os, sys, html, re
from collections import defaultdict
from datetime import datetime

def esc(s):
    if s is None: return ""
    return html.escape(str(s), quote=True)

# ---------- SIT ID → 中文显示转换 ----------
# SubAgent 输出的 problem_type 是英文 SIT ID（如 FUNC_LOGIC_ERROR），
# 但报告中应只展示中文 label（如 "功能逻辑错误"），不带英文 ID。
# P-code（如 P5-1）保留 "P5-1 任务遗漏" 形式。
_SIT_ID_PATTERN = re.compile(r'^[A-Z][A-Z0-9_]+$')  # 全大写+下划线 = SIT ID

def _is_sit_id(pc: str) -> bool:
    """判断 pc 是否为英文 SIT ID（如 FUNC_LOGIC_ERROR）而非 P-code（如 P5-1）"""
    return bool(pc and _SIT_ID_PATTERN.match(pc))

def _display_pc(pc: str, label: str = "", maps: dict = None) -> str:
    """返回问题类型的展示文本，SIT ID 只显示中文 label，P-code 显示 'P5-1 label' 形式。
    如果 label 为空，会尝试从 maps["pc_label"] 查找。"""
    if not pc:
        return ""
    if not label and maps:
        label = maps.get("pc_label", {}).get(pc, "")
    if _is_sit_id(pc):
        return label if label else pc  # SIT ID: 只返回中文 label
    else:
        return f"{pc} {label}".strip() if label else pc  # P-code: 保留编号

def _format_field(val):
    """Format a field value for display: try to parse JSON and extract key info."""
    if not val:
        return ""
    s = str(val).strip()
    if s.startswith("{"):
        try:
            d = json.loads(s)
            parts = []
            for k, v in d.items():
                if v is True:
                    parts.append(f"{k}: 是")
                elif v is False:
                    parts.append(f"{k}: 否")
                elif v:
                    parts.append(f"{k}: {v}")
            return "; ".join(parts) if parts else s
        except (ValueError, TypeError):
            pass
    return s

def _strip_marker(val, marker):
    if not val:
        return val
    if isinstance(val, (dict, list)):
        val = json.dumps(val, ensure_ascii=False)
    val = str(val)
    if val.strip().startswith(marker):
        return val.strip()[len(marker):].strip()
    return val

def short_sha(sha):
    if not sha: return "-"
    return sha[:7]

def fmt_pct(x, digits=1):
    if x is None: return "-"
    try:
        return f"{float(x)*100:.{digits}f}%"
    except Exception:
        return "-"

def fmt_impact(impact_dict):
    if not impact_dict:
        return "-", False
    ab = impact_dict.get("abandonment_impact")
    ag = impact_dict.get("agcr_impact")
    gap = impact_dict.get("gap_impact")
    if ab is None and ag is None and gap is None:
        return "-", False
    parts = []
    if ab is not None:
        parts.append(f"废弃 {fmt_pct(ab)}")
    if ag is not None:
        parts.append(f"AGCR影响 {fmt_pct(ag)}")
    if gap is not None:
        parts.append(f"缺口 {fmt_pct(gap)}")
    return " / ".join(parts), True

def agcr_class(val):
    if val is None:
        return ""
    try:
        v = float(val)
        if v >= 0.7:
            return "agcr-good"
        elif v >= 0.4:
            return "agcr-fair"
        else:
            return "agcr-poor"
    except (ValueError, TypeError):
        return ""

def agcr_badge_html(val):
    cls = agcr_class(val)
    if not cls:
        return '<span class="badge badge-gray">N/A</span>'
    label = {"agcr-good": "良好", "agcr-fair": "一般", "agcr-poor": "偏低"}.get(cls, "")
    short_cls = cls.replace("agcr-", "")
    return f'<span class="badge badge-{short_cls}">{fmt_pct(val)} {label}</span>'

# Stage mapping
STAGE_MAP = {
    "P5": "N5 编码计划", "P4": "N4 技术方案", "P3": "N3 需求澄清",
    "P2": "N2 现状梳理", "P1": "N1 项目初始化",
    # Also accept N-prefixed codes (used by SubAgent propagation_path / evidence_chain)
    "N5": "N5 编码计划", "N4": "N4 技术方案", "N3": "N3 需求澄清",
    "N2": "N2 现状梳理", "N1": "N1 项目初始化",
}
STAGE_ORDER = ["N6 代码生成","N5 编码计划","N4 技术方案","N3 需求澄清","N2 现状梳理","N1 项目初始化","测试并行链路"]

# Diff nature labels
DN_LABEL = {
    "corrective": "corrective 修正类",
    "additive": "additive 补充类",
    "subtractive": "subtractive 删除类",
    "refining": "refining 精炼类",
}
DN_BADGE_CLS = {
    "corrective": "badge-orange",
    "additive": "badge-green",
    "subtractive": "badge-red",
    "refining": "badge-blue",
}

# Evidence type labels
ET_LABEL = {
    "logic_error": "逻辑错误",
    "omission": "遗漏",
    "ambiguity": "表述模糊",
    "external_input": "外部输入",
    "composite": "复合问题",
    "knowledge_gap": "知识缺口",
    "other": "其他",
}

def load_maps(cfg):
    sit_label = {t["id"]: t["label"] for t in cfg.get("surface_issue_types", [])}
    rc_label = {k: v["label"] if isinstance(v, dict) else v for k, v in cfg.get("root_causes", {}).items()}
    pc_label = {}
    sub_map = {}
    stage_of_pc = {}
    for st in cfg.get("attribution_stages", []):
        stage_disp = STAGE_MAP.get(st.get("id",""), st.get("stage",""))
        for pt in st.get("problem_types", []):
            pc_label[pt["id"]] = pt["label"]
            stage_of_pc[pt["id"]] = stage_disp
            for rv in pt.get("root_cause_variants", []):
                sub_map[rv["sub_type"]] = {"root_cause": rv.get("root_cause"),
                                           "description": rv.get("description","")}
    # Defensive fallback: merge surface_issue_type labels into pc_label so that
    # if a SIT ID (e.g. INTERFACE_MISMATCH) somehow leaks into problem_type
    # despite validation in aggregate_stats.py, it still gets a readable label.
    # This should not happen in normal operation — aggregate_stats.py now warns
    # and converts SIT IDs to "OTHER".
    for sit_id, sit_lbl in sit_label.items():
        if sit_id not in pc_label:
            pc_label[sit_id] = sit_lbl
    return {"sit_label": sit_label, "rc_label": rc_label, "pc_label": pc_label,
            "sub_map": sub_map, "stage_of_pc": stage_of_pc}


def merge_attribution_data(data):
    """Merge attribution info from intent_groups into change_intent_groups and top-level hunks.

    The JSON has two structures:
    - intent_groups: full attribution (first_cause_stage, problem_type, root_cause, confidence,
      direct_cause, evidence_chain, attribution_direction, etc.) keyed by intent_id
    - change_intent_groups: CI-level groups with hunk code details but empty attribution fields
    - hunks (top-level): code diff details but no attribution fields

    This function enriches change_intent_groups and hunks with attribution data from intent_groups.
    """
    intent_groups = data.get("intent_groups", [])
    if not intent_groups:
        return

    # Build intent_id -> attribution data map
    ci_attr_map = {}
    # Build hunk_id -> attribution data map
    hunk_attr_map = {}

    for grp in intent_groups:
        grp_stage = grp.get("first_cause_stage", "")
        grp_problem_type = grp.get("problem_type", "")
        grp_problem_type_label = grp.get("problem_type_label", "")
        for intent in grp.get("intents", []):
            ci_id = intent.get("intent_id", "")
            if not ci_id:
                continue

            # Use intent-level fields, fall back to group-level
            stage = intent.get("first_cause_stage", "") or grp_stage or ""
            pc = intent.get("problem_type", "") or grp_problem_type or ""
            pc_label = intent.get("problem_type_label", "") or grp_problem_type_label or ""
            rc = intent.get("root_cause", "")
            rc_label = intent.get("root_cause_label", "")
            rc_variant = intent.get("root_cause_variant", "")
            confidence = intent.get("confidence", "low")
            direct_cause = intent.get("direct_cause", "")
            attr_dir = intent.get("attribution_direction", "")
            evidence_chain = intent.get("evidence_chain", [])
            recommendation = intent.get("recommendation", "")
            sit = intent.get("surface_issue_type", "")
            first_cause_nature = intent.get("first_cause_nature", "")
            first_cause_skill = intent.get("first_cause_skill", "")

            propagation_path = intent.get("propagation_path", "")
            evidence_type = intent.get("evidence_type", "")
            structure_type = intent.get("structure_type", "")
            before_code_summary = intent.get("before_code_summary", "")
            change_summary = intent.get("change_summary", "")

            attr_data = {
                "first_cause_stage": stage,
                "p_category": pc,
                "p_category_label": pc_label,
                "root_cause": rc,
                "root_cause_label": rc_label,
                "root_cause_variant": rc_variant,
                "confidence": confidence,
                "direct_cause": direct_cause,
                "attribution_direction": attr_dir,
                "evidence_chain": evidence_chain,
                "recommendation": recommendation,
                "surface_issue_type": sit,
                "first_cause_nature": first_cause_nature,
                "first_cause_skill": first_cause_skill,
                "propagation_path": propagation_path,
                "evidence_type": evidence_type,
                "structure_type": structure_type,
                "before_code_summary": before_code_summary,
                "change_summary": change_summary,
            }
            ci_attr_map[ci_id] = attr_data

            # Map hunk_ids -> attribution data
            for hid in intent.get("hunk_ids", []):
                hunk_attr_map[hid] = attr_data

    # Enrich change_intent_groups
    for ci in data.get("change_intent_groups", []):
        ci_id = ci.get("intent_id", "")
        attr = ci_attr_map.get(ci_id)
        if not attr:
            continue
        # Fill in empty CI-level fields
        if not ci.get("first_cause_stage") or ci.get("first_cause_stage") == "-":
            ci["first_cause_stage"] = attr["first_cause_stage"]
        if not ci.get("p_category"):
            ci["p_category"] = attr["p_category"]
        if not ci.get("p_category_label"):
            ci["p_category_label"] = attr["p_category_label"]
        if not ci.get("root_cause"):
            ci["root_cause"] = attr["root_cause"]
        # Always set root_cause_label (new field)
        ci["root_cause_label"] = attr["root_cause_label"]
        # Set direct_cause and recommendation
        if not ci.get("direct_cause"):
            ci["direct_cause"] = attr["direct_cause"]
        if not ci.get("recommendation"):
            ci["recommendation"] = attr["recommendation"]
        # Set attribution_direction
        if not ci.get("attribution_direction"):
            ci["attribution_direction"] = attr["attribution_direction"]
        # Set evidence_chain at CI level
        if not ci.get("evidence_chain"):
            ci["evidence_chain"] = attr["evidence_chain"]
        # Set propagation_path
        if not ci.get("propagation_path"):
            ci["propagation_path"] = attr["propagation_path"]
        # Set first_cause_nature / first_cause_skill
        if not ci.get("first_cause_nature"):
            ci["first_cause_nature"] = attr["first_cause_nature"]
        if not ci.get("first_cause_skill"):
            ci["first_cause_skill"] = attr["first_cause_skill"]
        # Set evidence_type / structure_type
        if not ci.get("evidence_type"):
            ci["evidence_type"] = attr["evidence_type"]
        if not ci.get("structure_type"):
            ci["structure_type"] = attr["structure_type"]
        # Set root_cause_variant
        if not ci.get("root_cause_variant"):
            ci["root_cause_variant"] = attr["root_cause_variant"]
        # Set surface_issue_type
        if not ci.get("surface_issue_type"):
            ci["surface_issue_type"] = attr["surface_issue_type"]
        # Set before_code_summary / change_summary for before-after display
        if not ci.get("before_code_summary"):
            ci["before_code_summary"] = attr["before_code_summary"]
        if not ci.get("change_summary"):
            ci["change_summary"] = attr["change_summary"]
        # Set dominant_confidence from intent confidence
        # Normalize numeric confidence to string enum first
        raw_conf = attr["confidence"]
        if isinstance(raw_conf, (int, float)):
            if raw_conf >= 0.8:
                norm_conf = "high"
            elif raw_conf >= 0.5:
                norm_conf = "medium"
            else:
                norm_conf = "low"
        else:
            norm_conf = raw_conf if raw_conf else "low"
        # Safety net: also check cluster_confidence from change-intents.json
        # (aggregate_stats.py should have already merged it, but this catches any edge case)
        ci_cc_raw = ci.get("cluster_confidence", "")
        if isinstance(ci_cc_raw, (int, float)):
            ci_cc = "high" if ci_cc_raw >= 0.8 else "medium" if ci_cc_raw >= 0.5 else "low"
        else:
            ci_cc = str(ci_cc_raw).lower() if ci_cc_raw else ""
        # Upgrade dominant_confidence: prefer the highest confidence from any source
        conf_rank = {"low": 0, "medium": 1, "high": 2}
        current_dc = ci.get("dominant_confidence", "low")
        current_rank = conf_rank.get(current_dc, 0)
        for candidate in (norm_conf, ci_cc):
            cand_rank = conf_rank.get(candidate, -1)
            if cand_rank > current_rank:
                ci["dominant_confidence"] = candidate
                current_rank = cand_rank

        # Enrich hunks within this CI
        for h in ci.get("hunks", []):
            hid = h.get("hunk_id", "")
            h_attr = hunk_attr_map.get(hid)
            if h_attr:
                if not h.get("first_cause_stage"):
                    h["first_cause_stage"] = h_attr["first_cause_stage"]
                if not h.get("p_category"):
                    h["p_category"] = h_attr["p_category"]
                if not h.get("root_cause"):
                    h["root_cause"] = h_attr["root_cause"]
                if not h.get("confidence"):
                    h["confidence"] = h_attr["confidence"]
                if not h.get("attribution_direction"):
                    h["attribution_direction"] = h_attr["attribution_direction"]
                if not h.get("direct_cause"):
                    h["direct_cause"] = h_attr["direct_cause"]
                if not h.get("evidence_chain"):
                    h["evidence_chain"] = h_attr["evidence_chain"]
                if not h.get("surface_issue_type"):
                    h["surface_issue_type"] = h_attr["surface_issue_type"]

    # Enrich top-level hunks
    for h in data.get("hunks", []):
        hid = h.get("hunk_id", "")
        h_attr = hunk_attr_map.get(hid)
        if h_attr:
            if not h.get("first_cause_stage"):
                h["first_cause_stage"] = h_attr["first_cause_stage"]
            if not h.get("p_category"):
                h["p_category"] = h_attr["p_category"]
            if not h.get("root_cause"):
                h["root_cause"] = h_attr["root_cause"]
            if not h.get("confidence"):
                h["confidence"] = h_attr["confidence"]
            if not h.get("attribution_direction"):
                h["attribution_direction"] = h_attr["attribution_direction"]
            if not h.get("direct_cause"):
                h["direct_cause"] = h_attr["direct_cause"]
            if not h.get("evidence_chain"):
                h["evidence_chain"] = h_attr["evidence_chain"]
            if not h.get("surface_issue_type"):
                h["surface_issue_type"] = h_attr["surface_issue_type"]

    # Also store a ci-level evidence_chain map for hunk rendering
    data["_ci_evidence_map"] = {ci_id: attr["evidence_chain"] for ci_id, attr in ci_attr_map.items() if attr["evidence_chain"]}
    data["_ci_direct_cause_map"] = {ci_id: attr["direct_cause"] for ci_id, attr in ci_attr_map.items() if attr["direct_cause"]}

def _norm_conf(val):
    """Normalize confidence to string enum 'high'/'medium'/'low'. Handles numeric and string."""
    if isinstance(val, (int, float)):
        return "high" if val >= 0.8 else "medium" if val >= 0.5 else "low"
    s = str(val).strip().lower() if val else "low"
    if s in ("high", "medium", "low"):
        return s
    try:
        fv = float(s)
        return "high" if fv >= 0.8 else "medium" if fv >= 0.5 else "low"
    except (ValueError, TypeError):
        return "low"

def normalize_stage(s):
    if not s: return "-"
    if s in STAGE_MAP.values(): return s
    if s in STAGE_MAP: return STAGE_MAP[s]
    return s

def _step_stage(step):
    """Extract stage display name from an evidence_chain step.

    The SubAgent may store the stage code in either ``stage`` or ``layer``.
    We try both, then normalise to a human-readable label via *normalize_stage*.
    """
    raw = step.get("stage") or step.get("layer") or "-"
    return normalize_stage(raw)

def _render_propagation_path(pp):
    """Render propagation_path as inline arrow-chain text, consistent with
    the plain-text style used by other CIs (e.g. "N4 技术方案 描述 → N5 编码计划 …").

    *pp* may be:
    - a JSON-encoded string (list of dicts)
    - an already-parsed list of dicts
    - a plain descriptive string
    """
    import json as _json
    steps = None
    if isinstance(pp, str):
        pp_stripped = pp.strip()
        if pp_stripped.startswith("["):
            try:
                steps = _json.loads(pp_stripped)
            except (_json.JSONDecodeError, ValueError):
                pass
    elif isinstance(pp, list):
        steps = pp

    if not steps or not isinstance(steps, list):
        # Plain-text rendering (same as other CIs)
        return (
            f'<div style="margin:6px 0;padding:6px 10px;background:#f8f9fa;border-left:3px solid #667eea;font-size:13px;color:#555;">'
            f'<strong>传导路径：</strong>{esc(str(pp))}'
            f'</div>'
        )

    # Convert JSON array to arrow-chain text, matching the style of other CIs
    segments = []
    for node in steps:
        if not isinstance(node, dict):
            continue
        n_stage = normalize_stage(node.get("stage") or "-")
        n_desc = node.get("error") or node.get("correction") or ""
        part = n_stage
        if n_desc:
            # Truncate very long descriptions to keep the chain readable
            if len(n_desc) > 80:
                n_desc = n_desc[:77] + "…"
            part += f" {n_desc}"
        segments.append(part)

    chain_text = " → ".join(segments) if segments else str(pp)
    return (
        f'<div style="margin:6px 0;padding:6px 10px;background:#f8f9fa;border-left:3px solid #667eea;font-size:13px;color:#555;">'
        f'<strong>传导路径：</strong>{esc(chain_text)}'
        f'</div>'
    )


def normalize_stage_short(s):
    """Extract short stage code like 'N4' from display name or P-code."""
    if not s: return ""
    if s in STAGE_MAP:
        return STAGE_MAP[s].split()[0]
    for prefix in ["N6","N5","N4","N3","N2","N1"]:
        if s.startswith(prefix):
            return prefix
    return ""

# ---------- Summary & Stats ----------

def r_executive_summary(data, maps):
    hunks = [h for h in data.get("hunks", []) if not h.get("excluded")]
    ca = data.get("calculated_agcr", {})
    agcr = ca.get("agcr") if ca else None
    repos = data.get("repos", [])
    ci_groups = data.get("change_intent_groups", []) or data.get("hunk_groups", [])

    parts = []
    parts.append(f'<p>本次分析覆盖 <span class="highlight">{len(repos)} 个仓库</span>，'
                 f'共识别 <span class="highlight">{len(hunks)} 个有效 Hunk</span>，'
                 f'聚合为 <span class="highlight">{len(ci_groups)} 个修改意图（CI）</span>。</p>')

    if agcr is not None:
        cls = agcr_class(agcr)
        hl = ' class="es-highlight"' if cls == "agcr-poor" else ''
        parts.append(f'<p>计算 AGCR 为<span{hl}>{fmt_pct(agcr)}</span>')
        abn = ca.get("abandonment_rate") if ca else None
        if abn is not None:
            parts.append(f'，废弃率 {fmt_pct(abn)}。</p>')
        else:
            parts.append('。</p>')
    else:
        parts.append('<p>AGCR 数据缺失。</p>')

    if ci_groups:
        # Top root cause (CI-level)
        rc_dist = {}
        rc_label_lookup = {}
        for ci in ci_groups:
            rc = ci.get("root_cause", "")
            if rc:
                rc_dist[rc] = rc_dist.get(rc, 0) + 1
                lbl = ci.get("root_cause_label", "")
                if lbl:
                    rc_label_lookup[rc] = lbl
        if rc_dist:
            top_rc = max(rc_dist, key=lambda k: rc_dist[k])
            rc_label = rc_label_lookup.get(top_rc, maps["rc_label"].get(top_rc, ""))
            rc_text = f'{top_rc} {rc_label}' if rc_label else top_rc
            parts.append(f'<p>问题根因主要来自 <span class="highlight">{rc_text}（{rc_dist[top_rc]} 个 CI）</span>。</p>')

        # Top stage (CI-level)
        st_dist = {}
        for ci in ci_groups:
            s = normalize_stage(ci.get("first_cause_stage"))
            st_dist[s] = st_dist.get(s, 0) + 1
        if st_dist:
            top_stage = max(st_dist, key=lambda k: st_dist[k])
            ci_total = len(ci_groups)
            parts.append(f'<p>首因阶段以 <span class="highlight">{top_stage} 为主（{st_dist[top_stage]} 个 CI，{st_dist[top_stage]*100//ci_total if ci_total else 0}%）</span>。</p>')

        # Diff nature distribution (already CI-level)
        dn_dist = {}
        for ci in ci_groups:
            dn = ci.get("diff_nature", "")
            if dn:
                dn_dist[dn] = dn_dist.get(dn, 0) + 1
        if dn_dist:
            dn_parts = []
            for dn, cnt in sorted(dn_dist.items(), key=lambda x: -x[1]):
                dn_label = DN_LABEL.get(dn, dn)
                dn_parts.append(f'{dn_label} {cnt} 个 CI')
            parts.append(f'<p>Diff 性质分布：{"、".join(dn_parts)}。</p>')

        # Confidence (CI-level, use dominant_confidence)
        conf = {}
        for ci in ci_groups:
            c_raw = ci.get("dominant_confidence", "low")
            c = _norm_conf(c_raw)
            conf[c] = conf.get(c, 0) + 1
        high = conf.get("high", 0)
        ci_total = len(ci_groups)
        parts.append(f'<p>置信度分布：高 {conf.get("high",0)} / 中 {conf.get("medium",0)} / 低 {conf.get("low",0)}'
                     f'（高置信度占比 {high*100//ci_total if ci_total else 0}%）。</p>')

    return "".join(parts) if parts else '<p class="muted">暂无摘要数据</p>'

def r_summary_cards(data, maps):
    hunks = [h for h in data.get("hunks", []) if not h.get("excluded")]
    repo_count = len(data.get("repos", []))
    hunk_count = len(hunks)
    ci_groups = data.get("change_intent_groups", []) or data.get("hunk_groups", [])
    ci_count = len(ci_groups)

    # Top issue type (CI-level)
    pc_dist = {}
    for ci in ci_groups:
        pc = ci.get("p_category", "")
        if pc:
            pc_dist[pc] = pc_dist.get(pc, 0) + 1
    if pc_dist:
        top_pc = max(pc_dist, key=lambda k: pc_dist[k])
        top_issue = _display_pc(top_pc, maps=maps)
    else:
        top_issue = "-"

    # Top stage (CI-level) – show full label like "N4 技术方案"
    st_dist = {}
    for ci in ci_groups:
        s = normalize_stage(ci.get("first_cause_stage"))
        if s and s != "-":
            st_dist[s] = st_dist.get(s, 0) + 1
    top_stage = max(st_dist, key=lambda k: st_dist[k]) if st_dist else "-"

    # Confidence (CI-level, use dominant_confidence)
    conf = {}
    for ci in ci_groups:
        c_raw = ci.get("dominant_confidence", "low")
        c = _norm_conf(c_raw)
        conf[c] = conf.get(c, 0) + 1
    high = conf.get("high", 0)
    ci_total = ci_count or 1
    conf_summary = f"{high}/{ci_count}" if ci_count else "-"

    return repo_count, hunk_count, ci_count, top_issue, top_stage, conf_summary

# ---------- §1 基本信息 ----------

def r_commit_source(data):
    sources = []
    if data.get("commit_source"):
        sources.append(esc(data["commit_source"]))
    else:
        if any(h.get("source") == "sdk_log" for h in data.get("hunks", [])):
            sources.append("sdk_log_washing")
        if any(h.get("source") == "cc_log" for h in data.get("hunks", [])):
            sources.append("cc_log_analysis")
    return " + ".join(sources) if sources else "-"

def r_gate_status(data):
    gate = data.get("gate_check", {})
    if not gate:
        return '<span class="gate-passed">✅ Gate 校验通过</span>'
    missing = gate.get("missing", [])
    invalid = gate.get("invalid", [])
    branch_errors = gate.get("branch_errors", [])
    if not missing and not invalid and not branch_errors:
        return '<span class="gate-passed">✅ Gate 校验通过（无 missing / invalid / branch_errors）</span>'
    issues = []
    if missing: issues.append(f"missing: {len(missing)}")
    if invalid: issues.append(f"invalid: {len(invalid)}")
    if branch_errors: issues.append(f"branch_errors: {len(branch_errors)}")
    return f'<span class="badge badge-red">⚠️ Gate 校验异常（{", ".join(issues)}）</span>'

# ---------- §2 代码版本与 Diff 概览 ----------

def _commit_count_badge(count, kind="ai"):
    """Render a commit count cell with a styled badge."""
    if count is None:
        return '<td style="text-align:center;"><span class="muted">-</span></td>'
    if kind == "ai":
        cls = "badge-blue"
    else:
        cls = "badge-purple" if count > 0 else "badge-gray"
    return f'<td style="text-align:center;"><span class="badge {cls}">{count}</span></td>'


def r_repo_diff_rows(data):
    hunks_by_repo = defaultdict(int)
    for h in data.get("hunks", []):
        if h.get("excluded"): continue
        rn = h.get("repo", "")
        hunks_by_repo[rn] += 1

    # Build diff_overview lookup for commit counts
    overview_map = {}
    for ov in data.get("diff_overview", []):
        overview_map[ov.get("repo", "")] = ov

    rows = []
    for r in data.get("repos", []):
        repo_name = r.get("repo", "")
        repo = esc(repo_name)
        branch = esc(r.get("branch","-"))
        base = esc(short_sha(r.get("base_commit")))
        one = esc(short_sha(r.get("one_shot_commit"))) if r.get("one_shot_commit") else '<span class="muted">N/A</span>'
        fin = esc(short_sha(r.get("target_final_commit")))
        hc = hunks_by_repo.get(repo_name, 0)
        chg = esc(r.get("change_summary","-"))

        ov = overview_map.get(repo_name, {})
        b2o = ov.get("b2o_commits")
        os2f = ov.get("os2f_commits")

        rows.append(
            f'<tr><td>{repo}</td><td>{branch}</td>'
            f'<td class="commit-hash">{base}</td><td class="commit-hash">{one}</td><td class="commit-hash">{fin}</td>'
            f'{_commit_count_badge(b2o, "ai")}{_commit_count_badge(os2f, "human")}'
            f'<td>{hc}</td>'
            f'<td>{chg}</td></tr>'
        )
    if not rows:
        rows.append('<tr><td colspan="9" class="empty">暂无数据</td></tr>')
    return "\n      ".join(rows)

def r_repo_diff_note(data):
    repos = data.get("repos", [])
    hunks_by_repo = defaultdict(int)
    for h in data.get("hunks", []):
        if h.get("excluded"): continue
        hunks_by_repo[h.get("repo","")] += 1
    note = ""
    zero_hunk_repos = []
    for r in repos:
        repo_name = r.get("repo", "")
        hc = hunks_by_repo.get(repo_name, 0)
        if hc == 0:
            # Check if one_shot == final (no human modification at all)
            os_commit = r.get("one_shot_commit", "")
            fin_commit = r.get("target_final_commit", "")
            if os_commit and fin_commit and os_commit == fin_commit:
                note += f'<p style="margin-top:8px;font-size:12px;color:#999;">注：{esc(repo_name)} 仓库 one-shot = final（AI 生成的代码即为最终版本，无人工修改）。</p>'
            else:
                zero_hunk_repos.append(repo_name)
    if zero_hunk_repos:
        names = ", ".join(zero_hunk_repos)
        note += f'<p style="margin-top:8px;font-size:12px;color:#999;">注：{esc(names)} 仓库的人工修改未生成有效 Hunk（排除后为 0）。采纳率/废弃率见 §3。</p>'
    return note

def r_repo_commit_details(data):
    """Render collapsible commit lists for each repo (AI coding + human modification)."""
    overview_map = {}
    for ov in data.get("diff_overview", []):
        overview_map[ov.get("repo", "")] = ov

    parts = []
    for r in data.get("repos", []):
        repo_name = r.get("repo", "")
        ov = overview_map.get(repo_name, {})
        ai_commits = ov.get("ai_commits", [])
        human_commits = ov.get("human_commits", [])

        if not ai_commits and not human_commits:
            continue

        rows_html = []

        # AI coding commits
        if ai_commits:
            ai_commits = sorted(ai_commits, key=lambda c: c.get("date", ""))
            rows_html.append('<tr><td colspan="4" style="background:#f0f5ff;font-weight:600;font-size:11px;color:#2f54eb;">AI 编码 (base → one-shot)</td></tr>')
            for c in ai_commits:
                sha = esc(c.get("sha", ""))[:10]
                msg = esc(c.get("message", ""))[:70]
                date = esc(c.get("date", ""))
                shot = c.get("shot_ratio")
                shot_str = f"{shot:.1f}%" if shot is not None else "-"
                shot_cls = "badge-green" if shot and shot >= 0.8 else ("badge-orange" if shot and shot >= 0.5 else "badge-red")
                rows_html.append(
                    f'<tr><td class="commit-hash">{sha}</td><td>{msg}</td><td style="white-space:nowrap;">{date}</td>'
                    f'<td style="text-align:center;"><span class="badge {shot_cls}">{shot_str}</span></td></tr>'
                )

        # Human modification commits
        if human_commits:
            human_commits = sorted(human_commits, key=lambda c: c.get("date", ""))
            rows_html.append('<tr><td colspan="4" style="background:#fff0f6;font-weight:600;font-size:11px;color:#eb2f96;">人工修改 (one-shot → final)</td></tr>')
            for c in human_commits:
                sha = esc(c.get("sha", ""))[:10]
                msg = esc(c.get("message", ""))[:70]
                date = esc(c.get("date", ""))[:19]
                author = esc(c.get("author", ""))
                rows_html.append(
                    f'<tr><td class="commit-hash">{sha}</td><td>{msg}</td><td style="white-space:nowrap;">{date}</td>'
                    f'<td style="text-align:center;"><span style="font-size:11px;color:#999;">{author}</span></td></tr>'
                )

        table_html = (
            f'<table class="commit-table" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:4px;">'
            f'<thead><tr style="background:#fafafa;"><th style="padding:4px 8px;text-align:left;width:100px;">Commit</th>'
            f'<th style="padding:4px 8px;text-align:left;">Message</th>'
            f'<th style="padding:4px 8px;text-align:left;width:140px;">日期</th>'
            f'<th style="padding:4px 8px;text-align:center;width:80px;">Shot/Author</th></tr></thead>'
            f'<tbody>{"".join(rows_html)}</tbody></table>'
        )

        parts.append(
            f'<details style="margin-top:6px;">'
            f'<summary style="cursor:pointer;font-size:13px;font-weight:600;color:#333;">'
            f'{esc(repo_name)} commit 列表（AI {len(ai_commits)} + 人工 {len(human_commits)}）</summary>'
            f'{table_html}'
            f'</details>'
        )

    if not parts:
        return ""
    return f'<div style="margin-top:12px;">{"".join(parts)}</div>'

# ---------- §3 计算采纳率 ----------

def r_agcr_metric_cards(data):
    ca = data.get("calculated_agcr")
    if ca is None or ca.get("agcr") is None:
        return (
            '<div class="agcr-metric-card gray"><div class="metric-value">N/A</div><div class="metric-label">采纳率 (AGCR)</div></div>'
            '<div class="agcr-metric-card gray"><div class="metric-value">N/A</div><div class="metric-label">废弃率</div></div>'
            '<div class="agcr-metric-card gray"><div class="metric-value">0</div><div class="metric-label">One-shot 行数</div></div>'
            '<div class="agcr-metric-card gray"><div class="metric-value">0</div><div class="metric-label">废弃行数</div></div>'
            '<div class="agcr-metric-card gray"><div class="metric-value">0</div><div class="metric-label">最终版总行数</div></div>'
        )
    agcr = ca.get("agcr")
    abn = ca.get("abandonment_rate")
    gt = ca.get("grand_total", {})
    os_lines = gt.get("one_shot_lines", 0)
    rm_lines = gt.get("removed_lines", 0)
    fin_lines = gt.get("final_lines", 0)

    agcr_cls = agcr_class(agcr)
    card_cls = {"agcr-good": "success", "agcr-fair": "warn", "agcr-poor": "danger"}.get(agcr_cls, "gray")

    abn_cls = ""
    if abn is not None:
        if abn > 0.3: abn_cls = "danger"
        elif abn > 0.1: abn_cls = "warn"
        else: abn_cls = "success"

    return (
        f'<div class="agcr-metric-card {card_cls}"><div class="metric-value">{fmt_pct(agcr)}</div><div class="metric-label">采纳率 (AGCR)</div></div>'
        f'<div class="agcr-metric-card {abn_cls}"><div class="metric-value">{fmt_pct(abn)}</div><div class="metric-label">废弃率</div></div>'
        f'<div class="agcr-metric-card"><div class="metric-value">{os_lines}</div><div class="metric-label">One-shot 行数</div></div>'
        f'<div class="agcr-metric-card"><div class="metric-value">{rm_lines}</div><div class="metric-label">废弃行数</div></div>'
        f'<div class="agcr-metric-card"><div class="metric-value">{fin_lines}</div><div class="metric-label">最终版总行数</div></div>'
    )

def r_per_repo_rows(data):
    ca = data.get("calculated_agcr")
    per_repo = ca.get("per_repo", []) if ca else []
    hunk_by_repo = defaultdict(int)
    for h in data.get("hunks", []):
        if h.get("excluded"): continue
        hunk_by_repo[h.get("repo","")] += 1

    rows = []
    for pr in per_repo:
        repo = esc(pr.get("repo",""))
        os_commit = esc(short_sha(data.get("_os_commit",{}).get(pr.get("repo",""),"")))[:7]
        fin_commit = esc(short_sha(data.get("_fin_commit",{}).get(pr.get("repo",""),"")))[:7]
        hc = hunk_by_repo.get(pr.get("repo",""), "-")
        os_lines = pr.get("one_shot_lines", "-")
        rm_lines = pr.get("removed_lines", "-")
        fin_lines = pr.get("final_lines", "-")
        ag = pr.get("agcr")
        ab = pr.get("abandonment_rate")
        note = "removed 含预存在代码删除，已钳制" if pr.get("clamped") else ""
        ag_cls = agcr_class(ag) if ag is not None else ""
        ag_html = f'<span class="{ag_cls}">{fmt_pct(ag)}</span>' if ag is not None else '<span class="badge badge-gray">N/A</span>'
        ab_html = fmt_pct(ab) if ab is not None else '<span class="badge badge-gray">N/A</span>'
        rows.append(f'<tr><td>{repo}</td><td class="commit-hash">{os_commit}</td><td class="commit-hash">{fin_commit}</td><td>{hc}</td><td>{os_lines}</td><td>{rm_lines}</td><td>{fin_lines}</td><td>{ag_html}</td><td>{ab_html}</td><td>{esc(note)}</td></tr>')

    if not per_repo:
        for r in data.get("repos", []):
            repo = esc(r.get("repo",""))
            os_commit = esc(short_sha(r.get("one_shot_commit","")))[:7] if r.get("one_shot_commit") else "-"
            fin_commit = esc(short_sha(r.get("target_final_commit","")))[:7]
            rows.append(f'<tr><td>{repo}</td><td class="commit-hash">{os_commit}</td><td class="commit-hash">{fin_commit}</td><td>-</td><td>-</td><td>-</td><td>-</td><td><span class="badge badge-gray">N/A</span></td><td><span class="badge badge-gray">N/A</span></td><td></td></tr>')

    if not rows:
        rows.append('<tr><td colspan="10" class="empty">暂无数据</td></tr>')
    return "\n      ".join(rows)

def r_per_ci_table(data):
    ca = data.get("calculated_agcr")
    ci_groups = data.get("change_intent_groups", []) or data.get("hunk_groups", [])
    if not ci_groups:
        return '<div class="empty-state">暂无 CI 粒度数据</div>'

    rows = []
    total_hunks = 0
    total_removed = 0
    total_added = 0
    total_gap = 0
    for ci in ci_groups:
        ci_id = esc(ci.get("intent_id", ""))
        desc = esc(ci.get("intent_description", "") or "(无描述)")
        hc = ci.get("hunk_count", len(ci.get("hunks", [])))
        ci_impact = ci.get("impact") or {}
        rm_lines = ci_impact.get("total_removed_lines", 0)
        add_lines = ci_impact.get("total_added_lines", 0)
        ab_imp = ci_impact.get("abandonment_impact")
        ag_imp = ci_impact.get("agcr_impact")
        gap_imp = ci_impact.get("gap_impact")
        ab_html = fmt_pct(ab_imp) if ab_imp is not None else '<span class="badge badge-gray">N/A</span>'
        ag_html = fmt_pct(ag_imp) if ag_imp is not None else '<span class="badge badge-gray">N/A</span>'
        gap_html = fmt_pct(gap_imp) if gap_imp is not None else '<span class="badge badge-gray">N/A</span>'
        rows.append(f'<tr><td>{ci_id}</td><td>{desc}</td><td>{hc}</td><td>{rm_lines}</td><td>{add_lines}</td><td>{ab_html}</td><td>{ag_html}</td><td>{gap_html}</td></tr>')
        total_hunks += hc
        total_removed += rm_lines
        total_added += add_lines
        total_gap += gap_imp if gap_imp else 0

    one_minus_agcr = "-"
    ca = data.get("calculated_agcr")
    if ca and ca.get("agcr") is not None:
        one_minus_agcr = fmt_pct(1 - ca["agcr"])

    rows.append(f'<tr style="background:#fafafa;font-weight:600;"><td colspan="2">合计</td><td>{total_hunks}</td><td>{total_removed}</td><td>{total_added}</td><td>-</td><td>-</td><td>{fmt_pct(total_gap)}</td></tr>')
    rows.append(f'<tr style="background:#f0f5ff;font-size:12px;color:#666;"><td colspan="7">1 - AGCR（参照值）</td><td>{one_minus_agcr}</td></tr>')

    return (
        '<table><thead><tr><th>CI</th><th>描述</th><th>Hunk 数</th><th>废弃行数</th><th>新增行数</th>'
        '<th>废弃影响率</th><th>AGCR 影响率</th><th>AGCR 缺口占比</th></tr></thead><tbody>'
        + "\n".join(rows) + '</tbody></table>'
    )

def r_agcr_formula_note(data):
    ca = data.get("calculated_agcr")
    if ca is None or ca.get("agcr") is None:
        return (
            '<div class="direct-cause-box" style="margin-top:12px;">'
            '<span class="label">⚠️ 数据缺失说明：</span>'
            '本次分析中 AGCR 数据不可用。建议后续在 pipeline 中补全 hunk 级行数统计，以支持精确的采纳率/废弃率分析。'
            '</div>'
        )
    agcr = ca.get("agcr")
    abn = ca.get("abandonment_rate")
    return (
        '<p style="font-size:12px;color:#999;margin-top:8px;">'
        '<strong>AGCR 计算公式：</strong>AGCR = (One-shot 行数 - 废弃行数) / 最终交付行数 × 100%<br>'
        '<strong>废弃率公式：</strong>abandonment_rate = 废弃行数 / One-shot 行数 × 100%<br>'
        f'<strong>当前状态：</strong>AGCR = {fmt_pct(agcr)}，废弃率 = {fmt_pct(abn)}'
        '</p>'
    )

# ---------- §4 问题分布 ----------

def r_problem_legends(data, maps):
    # Collect problem type IDs actually present in data
    used_pc_ids = set()
    for ci in (data.get("change_intent_groups", []) or data.get("hunk_groups", [])):
        pc = ci.get("p_category", "") or ci.get("problem_type", "")
        if pc:
            used_pc_ids.add(pc)
    # Also check intent_groups (§6) for problem_type
    for ig in data.get("intent_groups", []):
        pt = ig.get("problem_type", "")
        if pt:
            used_pc_ids.add(pt)

    # Problem type legend – only show types that appear in data
    pc_items = []
    for pc_id, label in maps["pc_label"].items():
        if pc_id not in used_pc_ids:
            continue
        disp = _display_pc(pc_id, label, maps)
        pc_items.append(f'<span class="legend-item"><strong>{esc(disp)}</strong></span>')
    pc_legend = (
        '<div class="legend-box"><div class="legend-title">问题类型说明</div>'
        + "".join(pc_items) + '</div>'
    ) if pc_items else ""

    # Collect root cause IDs actually present in data
    used_rc_ids = set()
    for ci in (data.get("change_intent_groups", []) or data.get("hunk_groups", [])):
        rc = ci.get("root_cause", "")
        if rc:
            used_rc_ids.add(rc)
    for ig in data.get("intent_groups", []):
        for intent in ig.get("intents", []):
            rc = intent.get("root_cause", "")
            if rc:
                used_rc_ids.add(rc)

    # Root cause legend – only show types that appear in data
    rc_items = []
    for rc_id, label in maps["rc_label"].items():
        if used_rc_ids and rc_id not in used_rc_ids:
            continue
        rc_items.append(f'<span class="legend-item"><strong>{esc(rc_id)}</strong> {esc(label)}</span>')
    rc_legend = (
        '<div class="legend-box"><div class="legend-title">根因说明</div>'
        + "".join(rc_items) + '</div>'
    ) if rc_items else ""

    # Diff nature legend
    dn_items = []
    for dn, label in DN_LABEL.items():
        dn_items.append(f'<span class="legend-item"><strong>{label}</strong> — {DN_DESC.get(dn, "")}</span>')
    dn_legend = (
        '<div class="legend-box"><div class="legend-title">Diff 性质说明</div>'
        + "".join(dn_items) + '</div>'
    ) if dn_items else ""

    return pc_legend + rc_legend + dn_legend

DN_DESC = {
    "corrective": "修正 AI 生成代码中的错误逻辑",
    "additive": "人工新增 AI 未生成的功能代码",
    "subtractive": "人工删除 AI 生成的多余代码",
    "refining": "人工优化 AI 代码的命名/风格",
}

def r_stage_problem_grid(data, maps):
    ci_groups = data.get("change_intent_groups", []) or data.get("hunk_groups", [])
    by_stage = defaultdict(lambda: defaultdict(int))
    for ci in ci_groups:
        s = normalize_stage(ci.get("first_cause_stage"))
        pc = ci.get("p_category", "") or "UNKNOWN"
        by_stage[s][pc] += 1

    if not by_stage:
        return '<div class="empty-state">暂无数据</div>'

    stage_keys = [s for s in STAGE_ORDER if s in by_stage]
    colors = ["#667eea", "#764ba2", "#f093fb", "#4facfe", "#43e97b", "#fa709a", "#faad14"]
    cards = []
    for s in stage_keys:
        pcs = by_stage[s]
        total = sum(pcs.values())
        items_html = []
        for i, (pc, cnt) in enumerate(sorted(pcs.items(), key=lambda x: -x[1])):
            label = maps["pc_label"].get(pc, pc)
            pct = cnt / total * 100 if total else 0
            color = colors[i % len(colors)]
            disp_pc = _display_pc(pc, label, maps)
            items_html.append(
                f'<div class="stage-problem-item">'
                f'<span class="badge badge-purple">{esc(disp_pc)}</span>'
                f'<div class="mini-bar"><div class="mini-bar-fill" style="width:{pct:.1f}%;background:{color};">{cnt}</div></div>'
                f'</div>'
            )
        cards.append(
            f'<div class="stage-problem-card">'
            f'<div class="stage-problem-header">'
            f'<span class="badge badge-blue">{esc(s)}</span>'
            f'<span class="stage-problem-total">{total} CI</span>'
            f'</div>'
            f'<div class="stage-problem-items">{"".join(items_html)}</div>'
            f'</div>'
        )
    return f'<div class="stage-problem-grid">{"".join(cards)}</div>'

def r_diff_nature_bars(data, maps):
    ci_groups = data.get("change_intent_groups", []) or data.get("hunk_groups", [])
    dn_dist = defaultdict(int)
    for ci in ci_groups:
        dn = ci.get("diff_nature", "")
        if dn:
            dn_dist[dn] += 1
    total = sum(dn_dist.values()) or 1
    if not dn_dist:
        return '<div class="empty-state">暂无数据</div>'

    colors = {"corrective": "c1", "subtractive": "c6", "additive": "c5", "refining": "c4"}
    bars = []
    for dn, cnt in sorted(dn_dist.items(), key=lambda x: -x[1]):
        label = DN_LABEL.get(dn, dn)
        pct = cnt / total * 100
        color_cls = colors.get(dn, "c7")
        bars.append(
            f'<div class="dist-bar-row">'
            f'<div class="dist-bar-label">{esc(label)}</div>'
            f'<div class="dist-bar-track"><div class="dist-bar-fill {color_cls}" style="width:{pct:.1f}%;">{cnt} CI ({pct:.1f}%)</div></div>'
            f'</div>'
        )
    return "".join(bars)

def r_attribution_direction_bars(data, maps):
    ci_groups = data.get("change_intent_groups", []) or data.get("hunk_groups", [])
    dir_dist = defaultdict(int)
    for ci in ci_groups:
        d = ci.get("attribution_direction", "")
        if d:
            dir_dist[d] += 1
    total = sum(dir_dist.values()) or 1
    if not dir_dist:
        return '<div class="empty-state">暂无数据</div>'

    DIR_LABEL = {
        "artifact_defect": "产物缺陷 (artifact_defect)",
        "ai_execution": "AI执行偏差 (ai_execution)",
    }
    DIR_DESC = {
        "artifact_defect": "设计文档/编码计划本身有缺陷，AI 忠实执行了错误的产物",
        "ai_execution": "产物正确，但 AI 未遵循产物的指令",
    }
    colors = {"artifact_defect": "c6", "ai_execution": "c1"}
    bars = []
    for d, cnt in sorted(dir_dist.items(), key=lambda x: -x[1]):
        label = DIR_LABEL.get(d, d)
        pct = cnt / total * 100
        color_cls = colors.get(d, "c7")
        bars.append(
            f'<div class="dist-bar-row">'
            f'<div class="dist-bar-label">{esc(label)}</div>'
            f'<div class="dist-bar-track"><div class="dist-bar-fill {color_cls}" style="width:{pct:.1f}%;">{cnt} CI ({pct:.1f}%)</div></div>'
            f'</div>'
        )
    desc_parts = []
    for d in dir_dist:
        desc_parts.append(f'<strong>{DIR_LABEL.get(d, d)}</strong> = {DIR_DESC.get(d, "")}')
    desc = '<br>'.join(desc_parts)
    bars.append(f'<p style="font-size:12px;color:#999;margin-top:4px;">{desc}</p>')
    return "".join(bars)

# ---------- §5 归因明细 ----------

def r_filter_bar(data, maps):
    ci_groups = data.get("change_intent_groups", []) or data.get("hunk_groups", [])
    if not ci_groups:
        return ""

    # Collect unique values
    stages = set()
    ptypes = set()
    rcauses = set()
    dnatures = set()
    for ci in ci_groups:
        s = normalize_stage_short(ci.get("first_cause_stage", ""))
        if s: stages.add(s)
        pc = ci.get("p_category", "")
        if pc: ptypes.add(pc)
        rc = ci.get("root_cause", "")
        if rc: rcauses.add(rc)
        dn = ci.get("diff_nature", "")
        if dn: dnatures.add(dn)

    # Build stage -> ptype map for cascading filter (use display text, not raw SIT IDs)
    stage_ptype_map = {}
    for ci in ci_groups:
        s = normalize_stage_short(ci.get("first_cause_stage", ""))
        pc = ci.get("p_category", "")
        if s and pc:
            lbl = ci.get("p_category_label", "") or maps.get("pc_label", {}).get(pc, "")
            disp = _display_pc(pc, lbl, maps)
            stage_ptype_map.setdefault(s, set()).add(disp)
    # Also convert the global ptypes set to display text
    ptypes_disp = set()
    for pc in ptypes:
        lbl = maps.get("pc_label", {}).get(pc, "")
        ptypes_disp.add(_display_pc(pc, lbl, maps))
    stage_ptype_json = {}
    for s, pcs in stage_ptype_map.items():
        stage_ptype_json[s] = sorted(pcs)
    stage_ptype_json["all"] = sorted(ptypes_disp)

    # Stage buttons
    stage_btns = ['<button class="filter-btn active" data-filter="stage" data-value="all">全部</button>']
    stage_full_map = {v.split()[0]: v for v in STAGE_MAP.values()}
    for s in sorted(stages):
        s_label = stage_full_map.get(s, s)
        stage_btns.append(f'<button class="filter-btn" data-filter="stage" data-value="{esc(s)}">{esc(s_label)}</button>')

    # Problem type buttons - collect labels from CI data
    ptype_btns = ['<button class="filter-btn active" data-filter="ptype" data-value="all">全部</button>']
    pc_label_map = {}
    for ci in ci_groups:
        pc = ci.get("p_category", "")
        if pc:
            lbl = ci.get("p_category_label", "")
            if lbl:
                pc_label_map[pc] = lbl
    for pc in sorted(ptypes):
        label = pc_label_map.get(pc, maps["pc_label"].get(pc, ""))
        disp_pc = _display_pc(pc, label, maps)
        # data-value 也使用展示文本，确保筛选一致
        ptype_btns.append(f'<button class="filter-btn" data-filter="ptype" data-value="{esc(disp_pc)}">{esc(disp_pc)}</button>')

    # Root cause buttons - collect labels from CI data
    rcause_btns = ['<button class="filter-btn active" data-filter="rcause" data-value="all">全部</button>']
    rc_label_map = {}
    for ci in ci_groups:
        rc = ci.get("root_cause", "")
        if rc:
            lbl = ci.get("root_cause_label", "")
            if lbl:
                rc_label_map[rc] = lbl
    for rc in sorted(rcauses):
        label = rc_label_map.get(rc, maps["rc_label"].get(rc, ""))
        btn_text = f'{esc(rc)} {esc(label)}' if label else esc(rc)
        rcause_btns.append(f'<button class="filter-btn" data-filter="rcause" data-value="{esc(rc)}">{btn_text}</button>')

    # Diff nature buttons
    dnature_btns = ['<button class="filter-btn active" data-filter="dnature" data-value="all">全部</button>']
    for dn in sorted(dnatures):
        label = DN_LABEL.get(dn, dn)
        dnature_btns.append(f'<button class="filter-btn" data-filter="dnature" data-value="{esc(dn)}">{esc(label)}</button>')

    ci_count = len(ci_groups)
    return (
        '<div class="filter-bar">'
        f'<div class="filter-group"><span class="filter-label">首因阶段</span>{"".join(stage_btns)}</div>'
        f'<div class="filter-group"><span class="filter-label">问题类型</span>{"".join(ptype_btns)}</div>'
        f'<div class="filter-group"><span class="filter-label">根因</span>{"".join(rcause_btns)}</div>'
        f'<div class="filter-group"><span class="filter-label">Diff 性质</span>{"".join(dnature_btns)}</div>'
        f'<div class="filter-count">当前展示 <strong id="ci-count">{ci_count}</strong> / {ci_count} 个修改意图</div>'
        f'</div>'
        f'<script>window._stagePtypeMap = {json.dumps(stage_ptype_json, ensure_ascii=False)};</script>'
    )

def _build_trace_evidence_html(ci, data, group_hunks):
    """Build trace evidence HTML for a CI card.

    Only shown when root_cause is R1~R5 (stage-specific root causes).
    Shows relevant execution_trace events from the CI's first_cause_stage,
    filtered by root cause type:
    - R1 知识不足: skill/knowledge retrieval events
    - R2 执行损耗: file write events matching hunk paths
    - R3 模型推理: thinking/reasoning events
    - R4 门禁漏检: human interaction events (gate reviews)
    - R5 澄清交互不充分: human interaction events
    """
    # Only show trace evidence for stage-specific root causes R1~R5
    rc = ci.get("root_cause", "")
    if rc not in ("R1", "R2", "R3", "R4", "R5"):
        return ""

    et = data.get("execution_trace")
    if not et or not isinstance(et, dict):
        return ""

    stages = et.get("stages", [])
    if not stages:
        return ""

    # parse_execution_trace.py outputs stages as a dict (phase_name → stage_data)
    if isinstance(stages, dict):
        stages = list(stages.values())

    # Get CI's first_cause_stage and normalize to short code
    fc_stage = ci.get("first_cause_stage", "")
    if not fc_stage:
        return ""

    fc_short = normalize_stage_short(fc_stage)  # e.g., "N4"
    fc_full = normalize_stage(fc_stage)  # e.g., "N4 技术方案"

    # Find matching trace stage by short code or full name
    matched_stage = None
    for s in stages:
        s_name = s.get("phase_name", s.get("stage_name", ""))
        s_short = normalize_stage_short(s_name)
        # Match by short code (N4, N5, etc.)
        if fc_short and s_short == fc_short:
            matched_stage = s
            break
        # Also try full name match
        if fc_full and s_name == fc_full:
            matched_stage = s
            break
        # Try substring match (e.g., "技术方案" in "N4 技术方案")
        if fc_short and fc_short in s_name:
            matched_stage = s
            break

    if not matched_stage:
        return ""

    # Root cause → relevant trace event types
    # R1 知识不足: 检查知识源是否加载/召回 → skill/knowledge retrieval
    # R2 执行损耗: 对比中间推理与最终写入 → file writes matching hunk paths
    # R3 模型推理: 检查推理过程 → thinking/reasoning events
    # R4 门禁漏检: 检查 Gate 人工确认 → human interaction events
    # R5 澄清交互不充分: 检查澄清提问 → human interaction events
    RC_EVENT_FILTERS = {
        "R1": {"skill_invocation", "knowledge_retrieval"},
        "R2": {"file_write"},
        "R3": {"thinking", "assistant"},
        "R4": {"human_interaction"},
        "R5": {"human_interaction"},
    }
    rc_types = RC_EVENT_FILTERS.get(rc, set())

    # Extract relevant events from timeline (copy to avoid mutating original data)
    timeline = matched_stage.get("timeline", [])
    human_events = list(matched_stage.get("human_interaction_events", []))
    skill_events = list(matched_stage.get("skill_events", []))

    # Get hunk file paths (short names) for matching file_write events
    hunk_files = set()
    for h in group_hunks:
        fp = h.get("file_path") or h.get("file") or ""
        if fp:
            hunk_files.add(os.path.basename(fp))

    # Filter timeline events by root-cause-specific types
    filtered_events = []
    for ev in timeline:
        ev_type = ev.get("type", "")
        if ev_type not in rc_types:
            continue
        # For file_write, only include those matching hunk file paths
        if ev_type == "file_write":
            fp = ev.get("file_path", "")
            if not fp or os.path.basename(fp) not in hunk_files:
                continue
        filtered_events.append(ev)

    # For R4/R5, also pull human_interaction_events directly (may have richer data)
    if rc in ("R4", "R5") and human_events:
        # Merge: prefer direct human_interaction_events (has text_preview),
        # supplement with timeline human_interaction events
        existing_texts = {he.get("text_preview", "") for he in human_events}
        for ev in filtered_events:
            if ev.get("type") == "human_interaction":
                tp = ev.get("text_preview", "")
                if tp and tp not in existing_texts:
                    human_events.append(ev)

    # For R1, also pull skill_events directly (has skill/via fields)
    if rc == "R1" and skill_events:
        # skill_events already has the structured data; timeline skill_invocation
        # events have the same info. Prefer skill_events, supplement if needed.
        existing_skills = {(se.get("skill", ""), se.get("via", "")) for se in skill_events}
        for ev in filtered_events:
            if ev.get("type") == "skill_invocation":
                key = (ev.get("skill_name", ""), ev.get("via", ""))
                if key not in existing_skills and key[0]:
                    skill_events.append({
                        "skill": ev.get("skill_name", ""),
                        "via": ev.get("via", ""),
                        "timestamp": ev.get("timestamp", ""),
                    })

    # Build the display label for root cause
    rc_labels = {"R1": "知识不足", "R2": "执行损耗", "R3": "模型推理",
                 "R4": "门禁漏检", "R5": "澄清交互不充分"}
    rc_label = rc_labels.get(rc, rc)

    # Count relevant events
    human_count = len(human_events) if rc in ("R4", "R5") else 0
    write_count = len([e for e in filtered_events if e.get("type") == "file_write"])
    skill_count = len(skill_events) if rc == "R1" else 0
    reasoning_count = len(filtered_events) if rc == "R3" else 0

    # If nothing relevant found, skip
    total = len(filtered_events) + human_count + skill_count
    if total == 0:
        return ""

    # Build summary line
    tool_count = matched_stage.get("tool_call_count", 0)
    summary_parts = [f"根因 {rc} {rc_label}", f"{tool_count} 工具调用"]
    if human_count:
        summary_parts.append(f"{human_count} 人工交互")
    if write_count:
        summary_parts.append(f"{write_count} 相关文件写入")
    if skill_count:
        summary_parts.append(f"{skill_count} 技能调用")
    if reasoning_count:
        summary_parts.append(f"{reasoning_count} 推理事件")
    summary = " · ".join(summary_parts)

    # Build event items
    items = []

    # R4/R5: Human interactions
    if rc in ("R4", "R5"):
        for he in human_events[:15]:
            text = esc(str(he.get("text_preview", he.get("summary", "")))[:200])
            ts = esc(str(he.get("timestamp", ""))[:19])
            items.append(
                f'<div style="padding:4px 10px;border-bottom:1px solid #eee;">'
                f'<span style="color:#fa709a;font-size:11px;margin-right:6px;">👤 人工交互</span>'
                f'<span style="font-size:11px;color:#aaa;margin-right:6px;">{ts}</span>'
                f'<span style="font-size:12px;color:#333;">{text}</span></div>'
            )

    # R2: Matching file writes
    if rc == "R2":
        write_events = [e for e in filtered_events if e.get("type") == "file_write"]
        for we in write_events[:15]:
            fp = esc(os.path.basename(we.get("file_path", "")))
            tool = esc(we.get("tool_name", ""))
            summary_text = esc(str(we.get("summary", we.get("write_summary", "")))[:150])
            ts = esc(str(we.get("timestamp", ""))[:19])
            items.append(
                f'<div style="padding:4px 10px;border-bottom:1px solid #eee;">'
                f'<span style="color:#43e97b;font-size:11px;margin-right:6px;">📝 文件写入</span>'
                f'<span style="font-size:11px;color:#aaa;margin-right:6px;">{ts}</span>'
                f'<span style="font-size:12px;color:#333;">{tool} → {fp}</span>'
                f'<div style="margin-top:2px;font-size:11px;color:#888;">{summary_text}</div></div>'
            )

    # R1: Skill invocations + knowledge retrieval
    if rc == "R1":
        for se in skill_events[:10]:
            skill = esc(se.get("skill", ""))
            via = esc(se.get("via", ""))
            ts = esc(str(se.get("timestamp", ""))[:19])
            items.append(
                f'<div style="padding:4px 10px;border-bottom:1px solid #eee;">'
                f'<span style="color:#667eea;font-size:11px;margin-right:6px;">🔧 技能调用</span>'
                f'<span style="font-size:11px;color:#aaa;margin-right:6px;">{ts}</span>'
                f'<span style="font-size:12px;color:#333;">{skill} ({via})</span></div>'
            )
        # Also show knowledge_retrieval events from timeline
        kr_events = [e for e in filtered_events if e.get("type") == "knowledge_retrieval"]
        for ke in kr_events[:5]:
            target = esc(str(ke.get("retrieval_target", ke.get("summary", "")))[:150])
            result = esc(str(ke.get("result_summary", ""))[:150])
            ts = esc(str(ke.get("timestamp", ""))[:19])
            items.append(
                f'<div style="padding:4px 10px;border-bottom:1px solid #eee;">'
                f'<span style="color:#4facfe;font-size:11px;margin-right:6px;">🔍 知识检索</span>'
                f'<span style="font-size:11px;color:#aaa;margin-right:6px;">{ts}</span>'
                f'<span style="font-size:12px;color:#333;">{target}</span>'
                f'<div style="margin-top:2px;font-size:11px;color:#888;">{result}</div></div>'
            )

    # R3: Thinking/reasoning events
    if rc == "R3":
        for te in filtered_events[:15]:
            ev_type = te.get("type", "")
            icon = "💭" if ev_type == "thinking" else "💬"
            label = "推理" if ev_type == "thinking" else "助手回复"
            summary_text = esc(str(te.get("summary", te.get("reasoning_summary", te.get("reply_summary", ""))))[:200])
            ts = esc(str(te.get("timestamp", ""))[:19])
            items.append(
                f'<div style="padding:4px 10px;border-bottom:1px solid #eee;">'
                f'<span style="color:#764ba2;font-size:11px;margin-right:6px;">{icon} {label}</span>'
                f'<span style="font-size:11px;color:#aaa;margin-right:6px;">{ts}</span>'
                f'<span style="font-size:12px;color:#333;">{summary_text}</span></div>'
            )

    body = "".join(items) if items else '<div style="padding:8px;color:#999;">无相关事件</div>'

    return (
        f'<details style="margin:8px 0;">'
        f'<summary style="cursor:pointer;font-size:13px;font-weight:600;color:#57534e;">'
        f'🔍 执行轨迹证据（{esc(fc_full)} · {esc(rc_label)}）<span style="font-weight:400;color:#999;margin-left:8px;">{summary}</span></summary>'
        f'<div style="border:1px solid #e8e8e8;border-radius:6px;margin-top:4px;max-height:300px;overflow:auto;">'
        f'{body}</div></details>'
    )


def _build_ci_card(ci, data, maps):
    intent_id = esc(ci.get("intent_id", ""))
    intent_desc = esc(ci.get("intent_description", "") or "(无描述)")
    diff_nature = ci.get("diff_nature", "")
    dn_label = DN_LABEL.get(diff_nature, diff_nature)
    dn_badge_cls = DN_BADGE_CLS.get(diff_nature, "badge-gray")

    stage = ci.get("first_cause_stage", "")
    stage_disp = normalize_stage(stage)
    stage_short = normalize_stage_short(stage)
    pc = ci.get("p_category", "")
    pc_label = ci.get("p_category_label", "") or maps["pc_label"].get(pc, pc)
    rc = ci.get("root_cause", "")
    rc_label = ci.get("root_cause_label", "") or maps["rc_label"].get(rc, rc) if rc else ""

    group_hunks = ci.get("hunks", [])
    hunk_count = ci.get("hunk_count", len(group_hunks))
    dominant_conf_raw = ci.get("dominant_confidence", "low")
    # Normalize numeric confidence to string enum for display
    if isinstance(dominant_conf_raw, (int, float)):
        dominant_conf = "high" if dominant_conf_raw >= 0.8 else "medium" if dominant_conf_raw >= 0.5 else "low"
    else:
        dominant_conf = str(dominant_conf_raw).lower() if dominant_conf_raw else "low"
    conf_zh = {"high": "高", "medium": "中", "low": "低"}.get(dominant_conf, dominant_conf)
    conf_badge_cls = {"high": "badge-high", "medium": "badge-medium", "low": "badge-gray"}.get(dominant_conf, "badge-gray")

    ci_impact = ci.get("impact") or {}
    ab_imp = ci_impact.get("abandonment_impact")
    ag_imp = ci_impact.get("agcr_impact")
    gap_imp = ci_impact.get("gap_impact")
    ab_imp_html = fmt_pct(ab_imp) if ab_imp is not None else '<span class="badge badge-gray">N/A</span>'
    ag_imp_html = fmt_pct(ag_imp) if ag_imp is not None else '<span class="badge badge-gray">N/A</span>'
    gap_imp_html = fmt_pct(gap_imp) if gap_imp is not None else '<span class="badge badge-gray">N/A</span>'

    evidence_type = ci.get("evidence_type", "")
    et_label = ET_LABEL.get(evidence_type, evidence_type)
    cluster_method = ci.get("cluster_method", "")
    is_composite = ci.get("is_composite", False)

    # Header tags
    header_tags = []
    if dn_label:
        header_tags.append(f'<span class="badge {dn_badge_cls}">{esc(dn_label)}</span>')
    if pc:
        disp_pc = _display_pc(pc, pc_label, maps)
        header_tags.append(f'<span class="badge badge-purple">{esc(disp_pc)}</span>')
    if rc:
        header_tags.append(f'<span class="badge badge-gray">{esc(rc)} {esc(rc_label)}</span>')
    header_tags.append(f'<span class="badge {conf_badge_cls}">{esc(conf_zh)}</span>')
    header_tags.append(f'<span class="badge badge-gray">{hunk_count} Hunk</span>')

    # Additional CI-level attribution details
    first_cause_nature = ci.get("first_cause_nature", "")
    FCN_LABEL = {
        "product_defect": "产物缺陷",
        "design_quality": "设计质量缺陷",
        "ai_deviation": "AI 执行偏差",
        "upstream_propagation": "上游传导",
        "prd_quality": "PRD 质量",
    }
    fcn_label = FCN_LABEL.get(first_cause_nature, first_cause_nature)
    root_cause_variant = ci.get("root_cause_variant", "")
    propagation_path = ci.get("propagation_path", "")
    additional_tags = ci.get("additional_tags", []) or []
    attribution_direction = ci.get("attribution_direction", "")
    ATTR_DIR_LABEL = {"artifact_defect": "产物缺陷", "ai_execution": "AI 执行偏差"}
    attr_dir_label = ATTR_DIR_LABEL.get(attribution_direction, attribution_direction)

    # Total removed/added lines from impact
    total_removed = ci_impact.get("total_removed_lines", 0) or 0
    total_added = ci_impact.get("total_added_lines", 0) or 0

    # Meta grid (enriched with full CI-level details)
    meta_rows = [
        f'<div class="ci-meta-item"><span class="ci-meta-label">首因阶段</span><span class="ci-meta-value">{esc(stage_disp)}</span></div>',
        f'<div class="ci-meta-item"><span class="ci-meta-label">问题类型</span><span class="ci-meta-value">{esc(_display_pc(pc, pc_label, maps))}</span></div>',
        f'<div class="ci-meta-item"><span class="ci-meta-label">根因</span><span class="ci-meta-value">{esc(rc)} {esc(rc_label)}</span></div>',
        f'<div class="ci-meta-item"><span class="ci-meta-label">置信度</span><span class="ci-meta-value"><span class="badge {conf_badge_cls}">{esc(conf_zh)}</span></span></div>',
    ]
    if first_cause_nature:
        fcn_cls = "badge-red" if first_cause_nature in ("product_defect", "design_quality") else "badge-blue" if first_cause_nature == "ai_deviation" else "badge-gray"
        meta_rows.append(f'<div class="ci-meta-item"><span class="ci-meta-label">首因性质</span><span class="ci-meta-value"><span class="badge {fcn_cls}">{esc(fcn_label)}</span></span></div>')
    if attribution_direction:
        ad_cls = "badge-red" if attribution_direction == "artifact_defect" else "badge-blue"
        meta_rows.append(f'<div class="ci-meta-item"><span class="ci-meta-label">归因方向</span><span class="ci-meta-value"><span class="badge {ad_cls}">{esc(attr_dir_label)}</span></span></div>')
    if root_cause_variant:
        rv_desc = maps.get("sub_map", {}).get(root_cause_variant, {})
        rv_disp = rv_desc.get("description", root_cause_variant) if isinstance(rv_desc, dict) else root_cause_variant
        meta_rows.append(f'<div class="ci-meta-item"><span class="ci-meta-label">根因变体</span><span class="ci-meta-value">{esc(root_cause_variant)} {esc(rv_disp)}</span></div>')
    meta_rows.append(f'<div class="ci-meta-item"><span class="ci-meta-label">废弃行数</span><span class="ci-meta-value">{total_removed}</span></div>')
    meta_rows.append(f'<div class="ci-meta-item"><span class="ci-meta-label">新增行数</span><span class="ci-meta-value">{total_added}</span></div>')
    meta_html = f'<div class="ci-meta">{"".join(meta_rows)}</div>'

    # Additional tags
    additional_tags_html = ""
    if additional_tags:
        tag_badges = " ".join(f'<span class="badge badge-orange">{esc(t)}</span>' for t in additional_tags)
        additional_tags_html = f'<div style="margin:4px 0;">{tag_badges}</div>'

    # Impact row
    impact_html = (
        f'<div class="ci-impact-row">'
        f'<div class="ci-impact-item"><span class="ci-impact-label">废弃影响率</span><span class="ci-impact-value">{ab_imp_html}</span></div>'
        f'<div class="ci-impact-item"><span class="ci-impact-label">AGCR 影响率</span><span class="ci-impact-value">{ag_imp_html}</span></div>'
        f'<div class="ci-impact-item"><span class="ci-impact-label">AGCR 缺口占比</span><span class="ci-impact-value">{gap_imp_html}</span></div>'
        f'</div>'
    )

    # Propagation path
    propagation_html = ""
    if propagation_path and str(propagation_path).strip() not in ("-", ""):
        propagation_html = _render_propagation_path(propagation_path)

    # Derivation hint
    derivation_parts = []
    if et_label:
        derivation_parts.append(f'证据类型：{esc(et_label)}')
    if cluster_method and cluster_method not in ("legacy_fallback", "orphan_fallback"):
        derivation_parts.append(f'聚类方法：{esc(cluster_method)}')
    derivation_html = f'<div class="derivation-hint">{" · ".join(derivation_parts)}</div>' if derivation_parts else ""

    # Direct cause
    direct_cause_html = ""
    direct_cause = ci.get("direct_cause", "")
    if not direct_cause and group_hunks:
        direct_cause = group_hunks[0].get("direct_cause", "")
    if not direct_cause and intent_id:
        direct_cause = data.get("_ci_direct_cause_map", {}).get(intent_id, "")
    if direct_cause and str(direct_cause).strip() not in ("-", ""):
        direct_cause_html = f'<div class="direct-cause-box"><span class="label">直接原因：</span>{esc(direct_cause)}</div>'

    # CI-level evidence chain
    ci_evidence_chain = ci.get("evidence_chain", [])
    if not ci_evidence_chain and intent_id:
        ci_evidence_chain = data.get("_ci_evidence_map", {}).get(intent_id, [])
    ci_chain_html = ""
    if ci_evidence_chain:
        ci_chain_steps = []
        for step in ci_evidence_chain:
            s_stage = esc(_step_stage(step))
            s_art = esc(step.get("artifact") or "-")
            s_find = esc(step.get("finding", "-"))
            s_snippet = step.get("artifact_snippet")
            s_bva = step.get("before_vs_artifact", "")
            s_up_art = step.get("upstream_artifact")
            s_up_find = step.get("upstream_finding")
            s_up_snippet = step.get("upstream_snippet")
            s_dep_path = step.get("dependency_path")
            step_html = f'<div class="evidence-step"><span class="ev-stage">{s_stage}</span> · <span class="ev-artifact">{s_art}'
            step_html += '</span>'
            # before_vs_artifact tag (N5/N4 layers)
            if s_bva:
                bva_cls = "badge-green" if s_bva == "consistent" else "badge-red"
                bva_label = "AI代码与产物一致" if s_bva == "consistent" else "AI代码与产物不一致"
                step_html += f' <span class="badge {bva_cls}">{esc(bva_label)}</span>'
            step_html += f'<div class="ev-finding">{s_find}</div>'
            # artifact_snippet collapsible panel
            if s_snippet:
                step_html += (
                    f'<details class="snippet-panel" style="margin:4px 0;"><summary class="snippet-summary" style="cursor:pointer;font-size:12px;color:#667eea;">📄 {s_art}</summary>'
                    f'<pre class="snippet-content" style="font-size:11px;background:#f8f9fa;padding:8px;border-radius:4px;max-height:200px;overflow:auto;white-space:pre-wrap;">{esc(s_snippet)}</pre></details>'
                )
            # Upstream comparison
            if s_up_art or s_up_find:
                step_html += f'<div class="ev-upstream" style="margin-top:4px;padding-left:10px;border-left:2px solid #e0e0e0;font-size:12px;color:#888;"><strong>上游追溯：</strong>{esc(s_up_art or "-")}'
                if s_up_find:
                    step_html += f' — {esc(s_up_find)}'
                if s_up_snippet:
                    step_html += (
                        f'<details class="snippet-panel" style="margin:2px 0;"><summary class="snippet-summary" style="cursor:pointer;font-size:11px;color:#999;">📄 上游产物片段</summary>'
                        f'<pre class="snippet-content" style="font-size:11px;background:#fafafa;padding:6px;border-radius:4px;max-height:150px;overflow:auto;white-space:pre-wrap;">{esc(s_up_snippet)}</pre></details>'
                    )
                step_html += '</div>'
            # dependency_path rendering
            if s_dep_path:
                step_html += (
                    f'<div class="ev-dependency-path" style="margin-top:4px;padding:4px 8px;background:#f0f5ff;border-left:2px solid #4a90d9;font-size:11px;color:#3a6ea5;border-radius:0 3px 3px 0;">'
                    f'<strong>依赖传导路径：</strong>{esc(s_dep_path)}'
                    f'</div>'
                )
            step_html += '</div>'
            ci_chain_steps.append(step_html)
        ci_chain_html = f'<div class="evidence-chain" style="margin:8px 0;">{"".join(ci_chain_steps)}</div>'

    # Trace evidence from execution_trace
    trace_evidence_html = _build_trace_evidence_html(ci, data, group_hunks)

    # Recommendation
    recommendation_html = ""
    recommendation = ci.get("recommendation", "")
    if recommendation and str(recommendation).strip() not in ("-", ""):
        recommendation_html = f'<div class="direct-cause-box" style="border-left-color:#52c41a;"><span class="label" style="color:#52c41a;">改进建议：</span>{esc(recommendation)}</div>'

    # Hunk list — all hunks in a single collapsible block
    hunk_items = []
    for idx, h in enumerate(group_hunks):
        hunk_items.append(_build_hunk_item(h, maps, idx, ci))

    if hunk_items:
        hunk_list_html = (
            f'<details class="hunk-list-details" style="margin:8px 0;">'
            f'<summary style="cursor:pointer;font-size:13px;font-weight:600;color:#667eea;padding:6px 0;">'
            f'📂 Hunk 归因明细（{len(hunk_items)} 个 Hunk）</summary>'
            f'<div class="hunk-list" style="margin-top:6px;">{"".join(hunk_items)}</div>'
            f'</details>'
        )
    else:
        hunk_list_html = ""

    # Data attributes for filtering
    disp_pc_for_attr = _display_pc(pc, pc_label, maps)
    data_attrs = f'data-stage="{esc(stage_short)}" data-ptype="{esc(disp_pc_for_attr)}" data-rcause="{esc(rc)}" data-dnature="{esc(diff_nature)}"'

    return (
        f'<div class="ci-card" {data_attrs}>'
        f'<div class="ci-card-header">'
        f'<span class="ci-id">{intent_id}</span>'
        f'<span class="ci-desc">{intent_desc}</span>'
        f'<div class="ci-tags">{"".join(header_tags)}</div>'
        f'</div>'
        f'<div class="ci-card-body">'
        f'<div class="ci-desc-full">{intent_desc}</div>'
        f'{meta_html}'
        f'{additional_tags_html}'
        f'{impact_html}'
        f'{propagation_html}'
        f'{derivation_html}'
        f'{direct_cause_html}'
        f'{ci_chain_html}'
        f'{trace_evidence_html}'
        f'{recommendation_html}'
        f'{hunk_list_html}'
        f'</div>'
        f'</div>'
    )

def _build_hunk_item(h, maps, idx, ci):
    hid = h.get("hunk_id", f"H-{idx+1:03d}")
    pos_file = h.get("file_path") or h.get("file") or h.get("symbol_hint") or "-"
    # Show short file name
    if pos_file and pos_file != "-" and "/" in pos_file:
        pos_file = pos_file.rsplit("/", 1)[-1]
    pos_line = h.get("new_start")
    pos = f'{esc(pos_file)}:{pos_line}' if pos_line else f'{esc(pos_file)}'
    csum = esc(h.get("change_summary", "-"))
    conf = h.get("confidence", "low")
    conf_zh = {"high":"高","medium":"中","low":"低"}.get(conf, conf)
    conf_badge_cls = {"high":"badge-high","medium":"badge-medium","low":"badge-gray"}.get(conf, "badge-gray")

    # Tags: attribution direction + consistency
    tags_html = ""
    attr_dir = h.get("attribution_direction", "")
    if attr_dir:
        dir_label = {"artifact_defect": "产物缺陷", "ai_execution": "AI执行偏差"}.get(attr_dir, attr_dir)
        dir_cls = {"artifact_defect": "badge-red", "ai_execution": "badge-blue"}.get(attr_dir, "badge-gray")
        tags_html += f'<span class="badge {dir_cls}">{esc(dir_label)}</span>'

    consistency = h.get("consistency", "")
    if consistency:
        if consistency == "consistent":
            tags_html += '<span class="badge badge-green">AI代码与产物一致</span>'
        else:
            tags_html += f'<span class="badge badge-orange">{esc(consistency)}</span>'

    tags_html += f'<span class="badge {conf_badge_cls}">{esc(conf_zh)}</span>'

    # Hunk-level line metrics
    h_removed = h.get("removed_lines", 0) or 0
    h_added = h.get("added_lines", 0) or 0
    line_metrics_html = ""
    if h_removed or h_added:
        parts = []
        if h_removed:
            parts.append(f'<span style="color:#cf1322;">-{h_removed} 废弃</span>')
        if h_added:
            parts.append(f'<span style="color:#389e0d;">+{h_added} 新增</span>')
        line_metrics_html = f'<div style="font-size:12px;margin:2px 0 4px 0;">{" / ".join(parts)} · <span style="color:#888;">{pos}</span></div>'
    else:
        line_metrics_html = f'<div style="font-size:12px;margin:2px 0 4px 0;color:#888;">{pos}</div>'

    # Evidence chain (collapsed by default — CI-level already shows the key change)
    chain = h.get("evidence_chain", [])
    chain_inner = ""
    if chain and isinstance(chain, list):
        steps_html = []
        for step in chain:
            if not isinstance(step, dict):
                continue
            s_stage = esc(_step_stage(step))
            s_art = esc(step.get("artifact") or "-")
            s_find = esc(step.get("finding", "-"))
            step_html = (
                f'<div class="evidence-step"><span class="ev-stage">{s_stage}</span> · '
                f'<span class="ev-artifact">{s_art}'
            )
            step_html += f'</span><div class="ev-finding">{s_find}</div></div>'
            steps_html.append(step_html)
        if steps_html:
            chain_inner = "".join(steps_html)

    chain_html = ""
    if chain_inner:
        chain_html = (
            f'<details class="hunk-evidence-details" style="margin:4px 0;">'
            f'<summary style="cursor:pointer;font-size:12px;color:#667eea;">展开证据链（{len(chain) if isinstance(chain, list) else 1} 步）</summary>'
            f'<div class="evidence-chain" style="margin-top:4px;">{chain_inner}</div>'
            f'</details>'
        )

    # Before-after diff block — extract from change-intents.json before_code/after_code
    # (fallback to diff_content extraction if before_code/after_code not available)
    diff_html = ""
    diff_content = h.get("diff_content", "")
    before_code = h.get("before_code", "")
    after_code = h.get("after_code", "")
    if not before_code and not after_code and diff_content:
        # Fallback: extract from diff_content (only - and + lines, no context)
        bl = []
        al = []
        for line in diff_content.splitlines():
            if line.startswith("@@"):
                continue
            if line.startswith("-") and not line.startswith("---"):
                bl.append(line[1:])
            elif line.startswith("+") and not line.startswith("+++"):
                al.append(line[1:])
        before_code = "\n".join(bl).strip()
        after_code = "\n".join(al).strip()
    if before_code or after_code:
            ba_parts = []
            if before_code:
                ba_parts.append(
                    f'<div class="ba-panel ba-before">'
                    f'<div class="ba-label" style="font-weight:600;font-size:11px;color:#cf1322;margin-bottom:3px;">Before（废弃代码）</div>'
                    f'<pre style="font-size:11px;background:#fff1f0;padding:6px;border-radius:4px;max-height:300px;overflow:auto;white-space:pre-wrap;border:1px solid #ffa39e;margin:0;">{esc(before_code)}</pre>'
                    f'</div>'
                )
            if after_code:
                ba_parts.append(
                    f'<div class="ba-panel ba-after">'
                    f'<div class="ba-label" style="font-weight:600;font-size:11px;color:#389e0d;margin-bottom:3px;">After（最终代码）</div>'
                    f'<pre style="font-size:11px;background:#f6ffed;padding:6px;border-radius:4px;max-height:300px;overflow:auto;white-space:pre-wrap;border:1px solid #b7eb8f;margin:0;">{esc(after_code)}</pre>'
                    f'</div>'
                )
            diff_html = (
                f'<div class="hunk-diff-block" style="margin:4px 0;">'
                f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;">{"".join(ba_parts)}</div>'
                f'</div>'
            )

    return (
        f'<div class="hunk-item">'
        f'<div class="hunk-header"><span class="hunk-id">{esc(hid)}</span>{tags_html}</div>'
        f'{line_metrics_html}'
        f'<div class="hunk-summary">{csum}</div>'
        f'{diff_html}'
        f'{chain_html}'
        f'</div>'
    )

def r_ci_cards(data, maps):
    ci_groups = data.get("change_intent_groups", []) or data.get("hunk_groups", [])
    if not ci_groups:
        hunks = [h for h in data.get("hunks", []) if not h.get("excluded")]
        if not hunks:
            return '<div class="empty-state">暂无归因明细数据</div>'
        # Fallback: group by stage × p_category
        by_stage = defaultdict(lambda: defaultdict(list))
        for h in hunks:
            s = normalize_stage(h.get("first_cause_stage"))
            pc = h.get("p_category", "") or "UNKNOWN"
            by_stage[s][pc].append(h)
        stage_priority = {s: i for i, s in enumerate(STAGE_ORDER)}
        for s in sorted(by_stage.keys(), key=lambda x: stage_priority.get(x, 99)):
            for pc in sorted(by_stage[s].keys()):
                pc_label = maps["pc_label"].get(pc, pc)
                group_hunks = by_stage[s][pc]
                ci_groups.append({
                    "intent_id": f"CI-{len(ci_groups)+1:03d}",
                    "intent_description": f"[回退模式] {s} · {_display_pc(pc, pc_label, maps)}",
                    "diff_nature": group_hunks[0].get("diff_nature", ""),
                    "evidence_type": group_hunks[0].get("evidence_type", ""),
                    "cluster_method": "legacy_fallback",
                    "hunks": group_hunks,
                    "hunk_count": len(group_hunks),
                    "first_cause_stage": s,
                    "p_category": pc,
                    "p_category_label": pc_label,
                    "root_cause": group_hunks[0].get("root_cause", ""),
                    "dominant_confidence": group_hunks[0].get("confidence", "low"),
                    "impact": None,
                })

    if not ci_groups:
        return '<div class="empty-state">暂无归因明细数据</div>'

    data["_os_commit"] = {r.get("repo"): r.get("one_shot_commit") for r in data.get("repos",[])}
    data["_fin_commit"] = {r.get("repo"): r.get("target_final_commit") for r in data.get("repos",[])}

    cards = []
    for ci in ci_groups:
        cards.append(_build_ci_card(ci, data, maps))
    return "\n      ".join(cards)

def r_ci_intro_text(data):
    ci_groups = data.get("change_intent_groups", []) or data.get("hunk_groups", [])
    ci_count = len(ci_groups)
    hunks = [h for h in data.get("hunks", []) if not h.get("excluded")]
    hunk_count = len(hunks)
    return (f'{ci_count} 个修改意图，按首因阶段、问题类型、根因、Diff 性质聚合。'
            f'每张卡片包含影响率统计和完整证据链。'
            f'证据链默认展开，点击卡片标题可折叠。'
            f'使用下方筛选条件聚焦关注维度（首因阶段与问题类型联动筛选）。')

# ---------- §6 排除 Hunk ----------

def r_excluded_hunks(data):
    excl = [h for h in data.get("hunks", []) if h.get("excluded")]
    cnt = len(excl)
    by_reason = data.get("excluded_hunks_by_reason", {})

    reason_labels = [
        ("whitespace", "空白/格式化"),
        ("auto_import", "import 自动整理"),
        ("auto_generated", "自动生成代码"),
        ("test_file", "测试文件"),
        ("doc_only", "纯文档变更"),
        ("config_only", "纯配置变更"),
    ]

    reason_rows = []
    for key, label in reason_labels:
        c = by_reason.get(key, 0)
        if c > 0:
            reason_rows.append(f'<tr><td>{esc(label)}（{esc(key)}）</td><td>{c}</td><td></td></tr>')
    if not reason_rows:
        reason_rows.append('<tr><td colspan="3" class="empty">无排除 Hunk</td></tr>')
    else:
        reason_rows.append(f'<tr style="font-weight:600;background:#fafafa;"><td>合计</td><td>{cnt}</td><td></td></tr>')

    # By repo
    by_repo = defaultdict(lambda: {"valid": 0, "excluded": 0})
    for h in data.get("hunks", []):
        rn = h.get("repo", "") or "未知"
        if h.get("excluded"):
            by_repo[rn]["excluded"] += 1
        else:
            by_repo[rn]["valid"] += 1

    repo_rows = []
    for rn in sorted(by_repo.keys()):
        info = by_repo[rn]
        if info["excluded"] > 0:
            valid_badge = f'<span class="badge badge-green">{info["valid"]}</span>' if info["valid"] > 0 else '<span class="badge badge-red">0</span>'
            repo_rows.append(f'<tr><td>{esc(rn)}</td><td>{valid_badge}</td><td><span class="badge badge-gray">{info["excluded"]}</span></td></tr>')
    if not repo_rows:
        repo_rows.append('<tr><td colspan="3" class="empty">无排除 Hunk</td></tr>')

    return (
        f'<h3>6.1 按排除原因</h3>'
        f'<table><thead><tr><th>排除原因</th><th>数量</th><th>说明</th></tr></thead><tbody>{"".join(reason_rows)}</tbody></table>'
        f'<h3 style="margin-top:16px;">6.2 按仓库分布</h3>'
        f'<table><thead><tr><th>仓库</th><th>有效 Hunk</th><th>排除 Hunk</th></tr></thead><tbody>{"".join(repo_rows)}</tbody></table>'
    )

# ---------- §7 改进建议 ----------

def r_key_findings(data, maps):
    findings = data.get("key_findings", [])
    if not findings:
        return '<div class="empty">暂无数据</div>'
    parts = []
    # Normalize severity to priority mapping
    SEVERITY_TO_PRIORITY = {
        "high": "HIGH", "medium": "MEDIUM", "low": "LOW", "info": "INFO",
        "HIGH": "HIGH", "MEDIUM": "MEDIUM", "LOW": "LOW", "INFO": "INFO",
    }
    for f in findings:
        if isinstance(f, dict):
            # Support both field naming conventions:
            #   SubAgent format: {id, title, description, severity}
            #   Legacy format:   {finding, priority, related_hunks, related_fcs, stage}
            text = f.get("finding", "") or f.get("title", "")
            description = f.get("description", "")
            raw_priority = f.get("priority", "") or f.get("severity", "")
            priority = SEVERITY_TO_PRIORITY.get(raw_priority, raw_priority.upper() if raw_priority else "")
            related = f.get("related_hunks", [])
            related_fcs = f.get("related_fcs", [])
            stage = f.get("stage", "")
        else:
            text = str(f)
            description = ""
            priority = ""
            related = []
            related_fcs = []
            stage = ""

        badge = ""
        if priority:
            p_cls = {"HIGH": "badge-HIGH", "MEDIUM": "badge-MEDIUM", "LOW": "badge-gray", "INFO": "badge-blue"}.get(priority, "badge-gray")
            badge = f'<span class="badge {p_cls}" style="margin-right:4px;">{esc(priority)}</span>'

        meta_parts = []
        if related:
            meta_parts.append(f'{len(related)} hunks')
        if related_fcs:
            meta_parts.append(f'{len(related_fcs)} FCs')
        meta_html = f' <span class="muted">({" · ".join(meta_parts)})</span>' if meta_parts else ''

        desc_html = f'<div style="font-size:12px;color:#666;margin-top:2px;">{esc(description)}</div>' if description else ''
        parts.append(f'<div class="kf-item">{badge}<strong>{esc(text)}</strong>{meta_html}{desc_html}</div>')
    return "\n        ".join(parts)

def r_recommendations(data, maps):
    recs = data.get("recommendations", [])
    if not recs:
        return '<div class="empty">暂无数据</div>'
    priority_order = ["HIGH", "MEDIUM", "LOW"]
    by_priority = {"HIGH": [], "MEDIUM": [], "LOW": []}
    for r in recs:
        if isinstance(r, dict):
            priority = r.get("priority", "LOW")
            text = r.get("text", "")
        else:
            priority = "LOW"
            text = str(r)
        by_priority.setdefault(priority, []).append(text)

    parts = []
    for p in priority_order:
        items = by_priority.get(p, [])
        if not items:
            continue
        title_cls = {"HIGH": "high", "MEDIUM": "medium"}.get(p, "")
        parts.append(
            f'<div class="rec-group">'
            f'<div class="rec-group-title {title_cls}" onclick="var n=this.nextElementSibling; n.style.display=n.style.display===\'none\'?\'block\':\'none\';">{p} 优先级（{len(items)} 项）</div>'
            f'<div>'
        )
        for text in items:
            parts.append(f'<div class="rec-item">{esc(text)}</div>')
        parts.append('</div></div>')
    return "\n        ".join(parts)

# ---------- §8 证据缺口 ----------

def r_evidence_gaps(data, maps):
    gaps = data.get("evidence_gaps", [])
    if not gaps:
        return '<div class="empty-state">✅ 本次分析无证据缺口。所有有效 Hunk 均有完整的 evidence_chain 和上游产物引用。</div>'
    rows = []
    for g in gaps:
        rows.append(f'<tr><td>{esc(g.get("stage","-"))}</td><td>{esc(g.get("gap","-"))}</td><td>{esc(g.get("impact","-"))}</td><td>{esc(g.get("suggestion","-"))}</td></tr>')
    return '<table><thead><tr><th>阶段</th><th>缺口</th><th>影响</th><th>建议</th></tr></thead><tbody>' + "\n".join(rows) + '</tbody></table>'

# ---------- §9 产物读取 ----------

def _status_badge(status_str):
    if not status_str:
        return '<span class="badge badge-gray">-</span>'
    s = str(status_str).lower().strip()
    if s in ("ok", "found", "loaded", "success", "complete", "已完成", "已加载"):
        return f'<span class="badge badge-green">{esc(status_str)}</span>'
    elif s in ("missing", "not_found", "absent", "缺失", "未找到"):
        return f'<span class="badge badge-red">{esc(status_str)}</span>'
    elif s in ("partial", "incomplete", "部分", "不完整"):
        return f'<span class="badge badge-orange">{esc(status_str)}</span>'
    else:
        return f'<span class="badge badge-gray">{esc(status_str)}</span>'

def r_artifact_summary(data):
    """Render full artifact checklist. Falls back to a complete registry when data is missing."""
    # Complete registry: (stage_label, display_name) — must match aggregate_stats.ARTIFACT_REGISTRY
    FULL_REGISTRY = [
        ("技术方案",   "技术方案设计文档"),
        ("技术方案",   "接口设计文档"),
        ("技术方案",   "约束检查文档"),
        ("编码计划",   "编码计划 / 任务拆解"),
        ("需求澄清",   "需求分析文档"),
        ("需求澄清",   "澄清交互日志"),
        ("需求澄清",   "澄清交互摘要"),
        ("现状梳理",   "现状基线文档"),
        ("项目初始化", "PRD 原始需求"),
        ("项目初始化", "功能点拆解"),
        ("项目初始化", "领域知识文档"),
        ("项目初始化", "调研证据文档"),
        ("项目初始化", "仓库范围识别"),
        ("项目初始化", "领域识别与工作状态"),
        ("全链路",     "Session JSONL（ai-trace）"),
    ]

    arts = data.get("artifact_summary", [])

    # Build a lookup: (stage, artifact_name) -> {status, note}
    art_lookup = {}
    for a in arts:
        key = (a.get("stage", ""), a.get("artifact_name", ""))
        art_lookup[key] = a

    # Track extra items in data not in registry (in case upstream adds new ones)
    registry_keys = set((s, n) for s, n in FULL_REGISTRY)
    extra_items = [a for a in arts if (a.get("stage", ""), a.get("artifact_name", "")) not in registry_keys]

    rows = []
    loaded_count = 0
    missing_count = 0
    cur_stage = None

    for stage_label, display_name in FULL_REGISTRY:
        key = (stage_label, display_name)
        item = art_lookup.get(key)
        status = item.get("status", "缺失") if item else "缺失"
        note = item.get("note", "未提供") if item else "数据中无此产物记录"
        status_html = _status_badge(status)

        s_lower = str(status).lower().strip()
        if s_lower in ("已读取", "ok", "found", "loaded", "success", "complete", "已完成", "已加载"):
            loaded_count += 1
        else:
            missing_count += 1

        # Merge cells for same-stage rows
        stage_cell = ""
        if stage_label != cur_stage:
            # Count how many entries share this stage
            stage_span = sum(1 for s, _ in FULL_REGISTRY if s == stage_label)
            stage_cell = f'<td rowspan="{stage_span}" style="vertical-align:middle;font-weight:600;">{esc(stage_label)}</td>'
            cur_stage = stage_label

        rows.append(f'<tr>{stage_cell}<td>{esc(display_name)}</td><td>{status_html}</td><td>{esc(note)}</td></tr>')

    # Append any extra items from data not in registry
    for a in extra_items:
        status = a.get("status", "-")
        status_html = _status_badge(status)
        s_lower = str(status).lower().strip()
        if s_lower in ("已读取", "ok", "found", "loaded", "success", "complete", "已完成", "已加载"):
            loaded_count += 1
        else:
            missing_count += 1
        rows.append(f'<tr><td>{esc(a.get("stage", "-"))}</td><td>{esc(a.get("artifact_name", "-"))}</td><td>{status_html}</td><td>{esc(a.get("note", "-"))}</td></tr>')

    total = loaded_count + missing_count
    # Summary row at top
    summary_row = (
        f'<tr style="background:#f0f5ff;font-weight:600;">'
        f'<td colspan="2">产物清单汇总（共 {total} 项）</td>'
        f'<td><span class="badge badge-green">已读取 {loaded_count}</span> '
        f'<span class="badge badge-red">缺失 {missing_count}</span></td>'
        f'<td>覆盖率 {loaded_count*100//total if total else 0}%</td>'
        f'</tr>'
    )

    return summary_row + "\n".join(rows)

# ---------- Main ----------

def render_execution_trace(data):
    """Render execution_trace section: timeline cards by stage.

    Reads data["execution_trace"] which is a dict with "stages" key,
    each stage has "timeline" events. Falls back gracefully if missing.
    """
    et = data.get("execution_trace")
    if not et or not isinstance(et, dict):
        return '<div style="color:#999;padding:12px;">执行轨迹数据未生成。</div>'

    stages = et.get("stages", [])
    if not stages:
        return '<div style="color:#999;padding:12px;">无阶段数据。</div>'

    # parse_execution_trace.py outputs stages as a dict (stage_name → stage_data);
    # convert to list for iteration if needed
    if isinstance(stages, dict):
        stages = list(stages.values())

    # Event type icons (emoji-free, using text labels)
    TYPE_ICONS = {
        "skill_invocation": "🔧",
        "knowledge_retrieval": "🔍",
        "file_write": "📝",
        "agent_spawn": "🤖",
        "bash_command": "⚡",
        "thinking": "💭",
        "assistant": "💬",
        "git_commit": "📦",
        "human_interaction": "👤",
    }

    parts = []
    for stage in stages:
        stage_name = esc(stage.get("phase_name", stage.get("stage_name", stage.get("stage", "未知阶段"))))
        node_count = stage.get("node_count", 0)
        tool_count = stage.get("tool_call_count", 0)
        timeline = stage.get("timeline", [])
        human_count = len(stage.get("human_interaction_events", []))

        # Truncate timeline to 50 events per stage
        if len(timeline) > 50:
            timeline = timeline[:50]

        header = (
            f'<div class="ci-card-header" style="cursor:pointer;padding:10px 14px;'
            f'background:#f5f7fa;border-radius:6px 6px 0 0;">'
            f'<span style="font-weight:600;">{stage_name}</span>'
            f'<span style="margin-left:12px;font-size:12px;color:#888;">'
            f'{node_count} 节点 · {tool_count} 工具调用 · {human_count} 人工交互 · {len(timeline)} 事件</span>'
            f'</div>'
        )

        if not timeline:
            body = '<div style="padding:10px 14px;color:#999;">无事件记录。</div>'
        else:
            event_items = []
            for ev in timeline:
                seq = ev.get("seq", "")
                ev_type = ev.get("type", "unknown")
                icon = TYPE_ICONS.get(ev_type, "·")
                timestamp = ev.get("timestamp", "")
                summary = ev.get("summary", ev.get("content_preview", ""))

                # Build event-specific detail
                detail_parts = []
                if ev_type == "skill_invocation":
                    skill_name = ev.get("skill_name", "")
                    if skill_name:
                        detail_parts.append(f"Skill: {esc(skill_name)}")
                    param_summary = ev.get("param_summary", "")
                    if param_summary:
                        detail_parts.append(f"参数: {esc(param_summary)}")
                elif ev_type == "knowledge_retrieval":
                    retrieval_target = ev.get("retrieval_target", "")
                    if retrieval_target:
                        detail_parts.append(f"检索: {esc(retrieval_target)}")
                    result_summary = ev.get("result_summary", "")
                    if result_summary:
                        detail_parts.append(f"结果: {esc(str(result_summary)[:200])}")
                elif ev_type == "file_write":
                    file_path = ev.get("file_path", "")
                    if file_path:
                        detail_parts.append(f"文件: {esc(os.path.basename(file_path))}")
                    write_summary = ev.get("write_summary", ev.get("content_preview", ""))
                    if write_summary:
                        detail_parts.append(f"摘要: {esc(str(write_summary)[:200])}")
                elif ev_type == "agent_spawn":
                    agent_desc = ev.get("agent_description", ev.get("description", ""))
                    if agent_desc:
                        detail_parts.append(f"子代理: {esc(agent_desc)}")
                elif ev_type == "bash_command":
                    cmd_category = ev.get("category", "")
                    cmd_summary = ev.get("command_summary", ev.get("summary", ""))
                    if cmd_category:
                        detail_parts.append(f"类别: {esc(cmd_category)}")
                    if cmd_summary:
                        detail_parts.append(f"命令摘要: {esc(str(cmd_summary)[:150])}")
                elif ev_type == "thinking":
                    reasoning_summary = ev.get("reasoning_summary", ev.get("summary", ""))
                    if reasoning_summary:
                        detail_parts.append(f"推理: {esc(str(reasoning_summary)[:200])}")
                elif ev_type == "assistant":
                    reply_summary = ev.get("reply_summary", ev.get("summary", ""))
                    if reply_summary:
                        detail_parts.append(f"回复: {esc(str(reply_summary)[:200])}")
                elif ev_type == "human_interaction":
                    text_preview = ev.get("text_preview", "")
                    if text_preview:
                        detail_parts.append(f"人工输入: {esc(str(text_preview)[:200])}")
                elif ev_type == "git_commit":
                    commit_msg = ev.get("message", "")
                    if commit_msg:
                        detail_parts.append(f"提交: {esc(str(commit_msg)[:150])}")

                detail_html = ""
                if detail_parts:
                    detail_html = (
                        f'<div style="margin-top:4px;font-size:12px;color:#666;">'
                        f'{" · ".join(detail_parts)}</div>'
                    )

                event_items.append(
                    f'<div style="padding:6px 14px;border-bottom:1px solid #eee;">'
                    f'<span style="color:#aaa;font-size:11px;margin-right:6px;">{seq}</span>'
                    f'<span style="margin-right:6px;">{icon}</span>'
                    f'<span style="font-size:12px;color:#333;">{esc(str(summary)[:300])}</span>'
                    f'{detail_html}'
                    f'</div>'
                )

            body = (
                f'<div class="ci-card-body" style="border:1px solid #e0e0e0;'
                f'border-top:none;border-radius:0 0 6px 6px;">'
                f'{"".join(event_items)}'
                f'</div>'
            )

        parts.append(
            f'<div class="ci-card collapsed" style="margin-bottom:12px;">'
            f'{header}{body}</div>'
        )

    return "".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', required=True)
    ap.add_argument('--template', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--config-dir', default='')
    args = ap.parse_args()

    try:
        with open(args.input, encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"[render] ERROR: Failed to parse input JSON: {e}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print(f"[render] ERROR: Input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)
    with open(args.template, encoding='utf-8') as f:
        tpl = f.read()
    cfg = {}
    cfg_path = os.path.join(args.config_dir, 'problem-types.json') if args.config_dir else ''
    if cfg_path and os.path.exists(cfg_path):
        with open(cfg_path, encoding='utf-8') as f:
            cfg = json.load(f)
    maps = load_maps(cfg)

    # Normalize field name: is_excluded → excluded (defensive, in case data
    # was not produced by aggregate_stats.py which already normalizes)
    for h in data.get("hunks", []):
        if "is_excluded" in h and "excluded" not in h:
            h["excluded"] = h.pop("is_excluded")
        elif "is_excluded" in h:
            h.pop("is_excluded")

    # Merge attribution data from intent_groups into change_intent_groups and hunks
    merge_attribution_data(data)

    data["_os_commit"] = {r.get("repo"): r.get("one_shot_commit") for r in data.get("repos",[])}
    data["_fin_commit"] = {r.get("repo"): r.get("target_final_commit") for r in data.get("repos",[])}

    repo_count, hunk_count, ci_count, top_issue, top_stage, conf_summary = r_summary_cards(data, maps)

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S +0800")
    empty_notice = data.get("empty_diff_notice","")
    if empty_notice:
        empty_notice_html = f'<div class="direct-cause-box">{esc(empty_notice)}</div>'
    else:
        empty_notice_html = ""

    req_name = data.get("requirement_name") or data.get("requirement_id") or "-"
    req_id = data.get("requirement_id","-")

    # Developer display: show source badge (commit vs observability)
    developers_raw = data.get("developers") or "-"
    dev_source = data.get("developer_source", "")
    meta_developers = data.get("meta_developers", "")
    if dev_source in ("commit_chain", "source_commits"):
        dev_source_badge = '<span class="badge badge-green" style="font-size:11px;margin-left:6px;">来自 commit</span>'
    elif dev_source == "observability":
        dev_source_badge = '<span class="badge badge-orange" style="font-size:11px;margin-left:6px;">来自 Observability（执行人）</span>'
    elif dev_source == "repos_meta":
        dev_source_badge = '<span class="badge badge-gray" style="font-size:11px;margin-left:6px;">来自 repos-meta</span>'
    else:
        dev_source_badge = ""
    developers_html = f'{esc(developers_raw)}{dev_source_badge}'
    # If commit_developers differs from meta_developers, show both
    if meta_developers and developers_raw != meta_developers and dev_source in ("commit_chain", "source_commits"):
        developers_html += f'<span style="font-size:12px;color:#999;margin-left:8px;">（执行人：{esc(meta_developers)}）</span>'

    repl = {
        "{{generated_at}}": esc(generated_at),
        "{{requirement_name}}": esc(req_name),
        "{{requirement_id}}": esc(req_id),
        "{{developers}}": developers_html,
        "{{run_id}}": esc(data.get("run_id","-")),
        "{{empty_diff_notice}}": empty_notice_html,
        "{{executive_summary}}": r_executive_summary(data, maps),
        "{{repo_count}}": esc(repo_count),
        "{{hunk_count}}": esc(hunk_count),
        "{{ci_count}}": esc(ci_count),
        "{{top_issue_type}}": esc(top_issue),
        "{{top_stage}}": esc(top_stage),
        "{{confidence_summary}}": esc(conf_summary),
        "{{commit_source}}": r_commit_source(data),
        "{{gate_status}}": r_gate_status(data),
        "{{repo_diff_rows}}": r_repo_diff_rows(data),
        "{{repo_diff_note}}": r_repo_diff_note(data),
        "{{repo_commit_details}}": r_repo_commit_details(data),
        "{{agcr_metric_cards}}": r_agcr_metric_cards(data),
        "{{per_repo_rows}}": r_per_repo_rows(data),
        "{{per_ci_table}}": r_per_ci_table(data),
        "{{agcr_formula_note}}": r_agcr_formula_note(data),
        "{{problem_legends}}": r_problem_legends(data, maps),
        "{{stage_problem_grid}}": r_stage_problem_grid(data, maps),
        "{{diff_nature_bars}}": r_diff_nature_bars(data, maps),
        "{{attribution_direction_bars}}": r_attribution_direction_bars(data, maps),
        "{{ci_intro_text}}": r_ci_intro_text(data),
        "{{filter_bar}}": r_filter_bar(data, maps),
        "{{ci_cards}}": r_ci_cards(data, maps),
        "{{excluded_hunk_summary}}": r_excluded_hunks(data),
        "{{key_findings_items}}": r_key_findings(data, maps),
        "{{recommendation_items}}": r_recommendations(data, maps),
        "{{evidence_gap_content}}": r_evidence_gaps(data, maps),
        "{{artifact_summary_rows}}": r_artifact_summary(data),
        "{{execution_trace_section}}": render_execution_trace(data),
    }
    out = tpl
    for k, v in repl.items():
        out = out.replace(k, v)
    # catch any remaining placeholders
    remaining = set(re.findall(r'\{\{[a-zA-Z0-9_]+\}\}', out))
    for m in remaining:
        out = out.replace(m, "-")

    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(out)
    print(f"[render] wrote {args.output} ({len(out)} bytes)", file=sys.stderr)

if __name__ == '__main__':
    main()
