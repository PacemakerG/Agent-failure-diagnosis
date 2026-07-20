#!/usr/bin/env python3
"""
SubAgent 输出后处理校验脚本（统一入口）。

覆盖两个 SubAgent 的全字段硬校验：

  --mode=attribution  校验 SubAgent-Attribution 的 intent fragment（intent-fragments/*.json）
  --mode=intent       校验 SubAgent-Intent 的 change-intents.json（change_intents[] + hunks[]）
                      包含完整的 9 项后置交叉校验（即规格中所谓 validate_clusters.py 的职责，
                      本脚本不另建独立文件，直接在 --mode intent 下完成），并将规格要求的
                      顶层 warnings[] / auto_fixes[] 写回 change-intents.json 的 validation 字段。

不通过的字段生成结构化错误报告，供主 Agent 要求 SubAgent 重新分类/重新聚类。

校验规则来源：
  - config/problem-types.json（阶段-P-code 映射、allowed_root_causes、root_cause_variants）
  - references/subagent-penetration.md（穿透输出格式约束）
  - references/subagent-typing.md（类型输出格式约束）
  - references/subagent-rootcause.md（evidence_chain 结构要求、根因输出格式）
  - references/output-format.md（完整字段清单）
  - references/derivation-rules.md（evidence_type / structure_type 推导规则）
  - references/subagent-intent.md（change-intents.json 字段约束、9 项后置校验）
  - SKILL.md（枚举定义、约束规则）

用法：
  # 校验 SubAgent-Attribution 输出
  python3 validate_subagent_output.py \\
    --mode attribution \\
    --frag-dir  "$OUTPUT_DIR/intent-fragments" \\
    --config-dir "$SKILL_DIR/config" \\
    [--fix]

  # 校验 SubAgent-Intent 输出
  python3 validate_subagent_output.py \\
    --mode intent \\
    --change-intents "$OUTPUT_DIR/hunks/change-intents.json" \\
    [--hunk-list "$OUTPUT_DIR/hunks/hunk-list.json"] \\
    [--pre-cluster "$OUTPUT_DIR/hunks/pre-cluster-hints.json"] \\
    [--fix]

退出码：
  0 = 全部通过
  1 = 存在不可自动修复的校验失败（需要 SubAgent 重新执行）

输出：
  validation-report.json（供主 Agent 读取，含顶层 warnings[]/auto_fixes[] 以及详细 targets[]）
  --mode intent 时同时会将 validation: {warnings[], auto_fixes[]} 写回输入的 change-intents.json
"""

import argparse
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict


# ══════════════════════════════════════════════════════════════════════════════
# 1. 从 problem-types.json 构建校验知识
# ══════════════════════════════════════════════════════════════════════════════

def load_validation_schema(config_dir: str) -> dict:
    """
    从 problem-types.json 加载校验所需的全部映射关系。

    返回 dict:
      stage_to_pcodes:    {"N5": {"P5-1", ..., "P5-3"}, "N4": {...}, ...}
      pcode_to_stage:     {"P5-1": "N5", "P4-3": "N4", ...}
      pcode_to_label:     {"P5-1": "任务遗漏", ...}
      stage_allowed_rc:   {"N5": {"R1","R2","R3","R4"}, "N4": {...}, ...}
      valid_pcodes:       {"P5-1", "P5-2", ..., "P1-3"}
      valid_rc_variants:  {"P5-1a", "P5-1b", ...}  所有合法 sub_type
      variant_to_rc:      {"P5-1a": "R1", "P5-1b": "R3", ...}
      variant_to_pcode:   {"P5-1a": "P5-1", ...}
      pcode_allowed_rc:   {"P5-1": {"R1","R2","R3","R4"}, ...}  每个 P-code 的合法根因
      ai_deviation_pcodes:{"P4-14"}  执行偏差类型，必须 R3（N5 无执行偏差类型）
      prd_quality_pcodes: {"P1-3"}  PRD 质量问题，root_cause = null
      stage_display:      {"N5": "N5 编码计划", ...}
    """
    path = os.path.join(config_dir, "problem-types.json")
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)

    schema = {
        "stage_to_pcodes": {},
        "pcode_to_stage": {},
        "pcode_to_label": {},
        "stage_allowed_rc": {},
        "valid_pcodes": set(),
        "valid_rc_variants": set(),
        "variant_to_rc": {},
        "variant_to_pcode": {},
        "pcode_allowed_rc": {},
        "ai_deviation_pcodes": {"P4-14"},
        "prd_quality_pcodes": {"P1-3"},
        "stage_display": {},
    }

    for st in cfg.get("attribution_stages", []):
        stage_id = st["stage"]  # "N5", "N4", ...
        stage_display = f"{stage_id} {st['stage_name']}"
        schema["stage_display"][stage_id] = stage_display
        schema["stage_allowed_rc"][stage_id] = set(st.get("allowed_root_causes", []))
        schema["stage_to_pcodes"][stage_id] = set()

        for pt in st.get("problem_types", []):
            pid = pt["id"]  # "P5-1"
            schema["valid_pcodes"].add(pid)
            schema["pcode_to_stage"][pid] = stage_id
            schema["pcode_to_label"][pid] = pt.get("label", "")
            schema["stage_to_pcodes"][stage_id].add(pid)

            pcode_rcs = set()
            for rv in pt.get("root_cause_variants", []):
                sub_type = rv["sub_type"]
                rc = rv["root_cause"]
                schema["valid_rc_variants"].add(sub_type)
                schema["variant_to_rc"][sub_type] = rc
                schema["variant_to_pcode"][sub_type] = pid
                pcode_rcs.add(rc)
            schema["pcode_allowed_rc"][pid] = pcode_rcs

    return schema


# ══════════════════════════════════════════════════════════════════════════════
# 2. 枚举常量
# ══════════════════════════════════════════════════════════════════════════════

VALID_STAGES_FULL = {
    "N5 编码计划", "N4 技术方案", "N3 需求澄清",
    "N2 现状梳理", "N1 项目初始化",
}

STAGE_SHORT_TO_FULL = {
    "N5": "N5 编码计划", "N4": "N4 技术方案", "N3": "N3 需求澄清",
    "N2": "N2 现状梳理", "N1": "N1 项目初始化",
}

STAGE_FULL_TO_SHORT = {v: k for k, v in STAGE_SHORT_TO_FULL.items()}

VALID_DIFF_NATURE = {"corrective", "additive", "subtractive", "refining"}
VALID_FIRST_CAUSE_NATURE = {"product_defect", "ai_deviation", "upstream_propagation", "prd_quality"}
VALID_ATTRIBUTION_DIRECTION = {"artifact_defect", "ai_execution"}
VALID_CONFIDENCE = {"high", "medium", "low"}
VALID_ROOT_CAUSES = {"R1", "R2", "R3", "R4", "R5"}
BEFORE_VS_ARTIFACT_STAGES = {"N5 编码计划", "N4 技术方案"}
VALID_BEFORE_VS_ARTIFACT = {"consistent", "inconsistent"}
VALID_CLUSTER_METHOD = {"pdg_hard_merge", "llm_rationale", "layer0_design_cluster", "combined"}

STAGE_ORDER = ["N5 编码计划", "N4 技术方案", "N3 需求澄清", "N2 现状梳理", "N1 项目初始化"]

# 穿透语义关键词（用于 evidence_chain 内容级校验）
_OMISSION_KEYWORDS = re.compile(
    r"遗漏|缺失|未覆盖|未识别|未扫到|未分析|漏扫|影响范围|波及|没有.*识别|没有.*覆盖"
)
_AI_DEVIATION_KEYWORDS = re.compile(
    r"AI\s*未|模型未|未按.*实现|偏离|未遵循|AI\s*偏|执行偏差"
)
_PRODUCT_DEFECT_KEYWORDS = re.compile(
    r"产物.*缺陷|设计.*遗漏|设计.*缺失|设计.*未覆盖|需求.*遗漏|现状.*缺失|产物.*错误"
)
_R2_KEYWORDS = re.compile(r"丢失|截断|传递.*丢|写入.*丢|合并.*丢|落盘|变形")
_R3_KEYWORDS = re.compile(r"推理|理解|判断|推断|认知|推理偏差|推理不充分")

# 需要穿透到 N2 检查的 P4 problem_type（设计遗漏/链路梳理/逻辑错误）
_P4_REQUIRE_N2_CHECK = {"P4-2", "P4-3", "P4-4"}

# SIT IDs（不应出现在 problem_type 中）
SIT_IDS = {
    "FUNC_MISSING", "FUNC_EXTRA", "FUNC_LOGIC_ERROR", "BEHAVIOR_CONFLICT",
    "COMPAT_MISSING", "INTERFACE_MISMATCH", "DATA_MODEL_ERROR",
    "ARCH_VIOLATION", "MIDDLEWARE_MISUSE", "CODING_STYLE",
    "DEFENSIVE_MISSING", "TRANSACTION_ISSUE", "ROLLOUT_MISSING",
    "PERFORMANCE_ISSUE", "PERSONAL_STYLE", "OTHER",
}


# ══════════════════════════════════════════════════════════════════════════════
# 3. 校验结果数据结构
# ══════════════════════════════════════════════════════════════════════════════

# ── commit_message / intent_description 方向性关键词表（规则 3/6/8 共用） ──
# 用于确定性提取“方向”信号，不依赖 NLP 分词库，仅做子串命中判断。
_DIRECTION_KEYWORDS = {
    "additive": ["新增", "补充", "增加", "添加", "补全"],
    "subtractive": ["删除", "移除", "去掉", "去除", "剔除"],
    "corrective": ["修复", "修正", "纠正", "修改错误", "更正"],
    "refining": ["重构", "优化", "调整格式", "重命名", "提取方法", "内联"],
}

# commit_message 中用于剔除的通用前缀（如 [FIX-1234]、[TASK-01] 等工单号），
# 避免工单号被误判为“关键词”。
_COMMIT_TAG_RE = re.compile(r"^\s*\[[^\]]*\]\s*")


def _extract_direction(text: str) -> set:
    """从文本中确定性提取方向标签集合（可能同时命中多个方向）。"""
    if not text:
        return set()
    hits = set()
    for direction, kws in _DIRECTION_KEYWORDS.items():
        for kw in kws:
            if kw in text:
                hits.add(direction)
                break
    return hits


def _commit_keywords(commit_message: str) -> set:
    """从单条 commit_message 提取去除工单号前缀后的原始文本，按常见分隔符切词。"""
    if not commit_message:
        return set()
    text = _COMMIT_TAG_RE.sub("", commit_message).strip()
    # 按常见分隔符（空格、中文标点）粗切分，过滤长度 <2 的碎片
    parts = re.split(r"[\s,，。;；:：、/\\\-_]+", text)
    return {p for p in parts if len(p) >= 2}


class Violation:
    """单条校验违规。"""

    SEVERITY_ERROR = "error"      # 必须 SubAgent 重新执行
    SEVERITY_WARNING = "warning"  # 可自动修复或降级处理
    SEVERITY_INFO = "info"        # 信息提示

    def __init__(self, field: str, rule: str, message: str,
                 current_value=None, expected=None,
                 severity: str = "error", auto_fixable: bool = False,
                 fix_value=None):
        self.field = field
        self.rule = rule
        self.message = message
        self.current_value = current_value
        self.expected = expected
        self.severity = severity
        self.auto_fixable = auto_fixable
        self.fix_value = fix_value

    def to_dict(self):
        d = {
            "field": self.field,
            "rule": self.rule,
            "message": self.message,
            "severity": self.severity,
            "auto_fixable": self.auto_fixable,
        }
        if self.current_value is not None:
            d["current_value"] = self.current_value
        if self.expected is not None:
            d["expected"] = self.expected
        if self.auto_fixable and self.fix_value is not None:
            d["fix_value"] = self.fix_value
        return d


# ══════════════════════════════════════════════════════════════════════════════
# 4. SubAgent-Attribution 校验逻辑
# ══════════════════════════════════════════════════════════════════════════════

def _normalize_stage(stage_str: str) -> str:
    """尝试将阶段名归一化为全名。"""
    if stage_str in VALID_STAGES_FULL:
        return stage_str
    if stage_str in STAGE_SHORT_TO_FULL:
        return STAGE_SHORT_TO_FULL[stage_str]
    m = re.match(r"(N\d)", stage_str)
    if m and m.group(1) in STAGE_SHORT_TO_FULL:
        return STAGE_SHORT_TO_FULL[m.group(1)]
    return stage_str


def validate_attribution_intent(intent: dict, schema: dict) -> list:
    """
    对单个 SubAgent-Attribution intent fragment 做全字段校验。

    返回 Violation 列表。空列表 = 全部通过。
    """
    violations = []

    # ── 4.1 intent_id ──
    if not intent.get("intent_id"):
        violations.append(Violation(
            "intent_id", "REQUIRED",
            "intent_id 缺失",
            severity=Violation.SEVERITY_ERROR
        ))

    # ── 4.2 diff_nature ──
    dn = intent.get("diff_nature", "")
    if not dn:
        violations.append(Violation(
            "diff_nature", "REQUIRED",
            "diff_nature 缺失",
            severity=Violation.SEVERITY_ERROR
        ))
    elif dn not in VALID_DIFF_NATURE:
        violations.append(Violation(
            "diff_nature", "ENUM",
            f"diff_nature 值 '{dn}' 不合法",
            current_value=dn,
            expected=sorted(VALID_DIFF_NATURE),
            severity=Violation.SEVERITY_ERROR
        ))

    # ── 4.3 first_cause_stage ──
    fcs_raw = intent.get("first_cause_stage", "")
    fcs = _normalize_stage(fcs_raw)
    fcs_short = STAGE_FULL_TO_SHORT.get(fcs, "")

    if not fcs_raw:
        violations.append(Violation(
            "first_cause_stage", "REQUIRED",
            "first_cause_stage 缺失",
            severity=Violation.SEVERITY_ERROR
        ))
    elif fcs not in VALID_STAGES_FULL:
        violations.append(Violation(
            "first_cause_stage", "ENUM",
            f"first_cause_stage '{fcs_raw}' 无法识别为合法阶段",
            current_value=fcs_raw,
            expected=sorted(VALID_STAGES_FULL),
            severity=Violation.SEVERITY_ERROR
        ))
    elif fcs_raw != fcs:
        violations.append(Violation(
            "first_cause_stage", "NORMALIZE",
            f"first_cause_stage 使用了非标准名 '{fcs_raw}'，应为 '{fcs}'",
            current_value=fcs_raw,
            expected=fcs,
            severity=Violation.SEVERITY_WARNING,
            auto_fixable=True,
            fix_value=fcs,
        ))

    # ── 4.4 first_cause_nature ──
    fcn = intent.get("first_cause_nature", "")
    if not fcn:
        violations.append(Violation(
            "first_cause_nature", "REQUIRED",
            "first_cause_nature 缺失",
            severity=Violation.SEVERITY_ERROR
        ))
    elif fcn not in VALID_FIRST_CAUSE_NATURE:
        violations.append(Violation(
            "first_cause_nature", "ENUM",
            f"first_cause_nature '{fcn}' 不合法",
            current_value=fcn,
            expected=sorted(VALID_FIRST_CAUSE_NATURE),
            severity=Violation.SEVERITY_ERROR
        ))

    # ── 4.5 problem_type（核心校验：阶段-P-code 绑定） ──
    pt = intent.get("problem_type", "")
    if not pt:
        violations.append(Violation(
            "problem_type", "REQUIRED",
            "problem_type 缺失",
            severity=Violation.SEVERITY_ERROR
        ))
    elif pt in SIT_IDS:
        violations.append(Violation(
            "problem_type", "SIT_CONTAMINATION",
            f"problem_type 字段使用了 SIT ID '{pt}'，"
            f"problem_type 必须是 P-code（如 P4-3），SIT ID 由 normalize_hunks.py 推导",
            current_value=pt,
            expected="P{阶段}-{序号} 格式，如 P4-3",
            severity=Violation.SEVERITY_ERROR
        ))
    elif pt not in schema["valid_pcodes"]:
        violations.append(Violation(
            "problem_type", "INVALID_PCODE",
            f"problem_type '{pt}' 不在 {len(schema['valid_pcodes'])} 种合法 P-code 中",
            current_value=pt,
            expected=sorted(schema["valid_pcodes"]),
            severity=Violation.SEVERITY_ERROR
        ))
    else:
        expected_stage = schema["pcode_to_stage"].get(pt)
        if fcs_short and expected_stage and expected_stage != fcs_short:
            allowed_pcodes = schema["stage_to_pcodes"].get(fcs_short, set())
            violations.append(Violation(
                "problem_type", "STAGE_MISMATCH",
                f"problem_type '{pt}' 属于 {expected_stage} 阶段，"
                f"但 first_cause_stage 为 '{fcs}'（{fcs_short}）。"
                f"首因阶段 {fcs_short} 的合法 P-code 为: "
                f"{sorted(allowed_pcodes)}",
                current_value=pt,
                expected=sorted(allowed_pcodes),
                severity=Violation.SEVERITY_ERROR
            ))

    # ── 4.6 root_cause ──
    rc = intent.get("root_cause")
    is_prd_quality = pt in schema["prd_quality_pcodes"]
    is_ai_deviation = pt in schema["ai_deviation_pcodes"]

    if is_prd_quality:
        if rc is not None:
            violations.append(Violation(
                "root_cause", "PRD_QUALITY_NO_RC",
                f"P1-3 (PRD 质量问题) 的 root_cause 应为 null，当前为 '{rc}'",
                current_value=rc,
                expected=None,
                severity=Violation.SEVERITY_ERROR
            ))
    elif is_ai_deviation:
        if rc != "R3":
            violations.append(Violation(
                "root_cause", "AI_DEVIATION_MUST_R3",
                f"AI 执行偏差类型 {pt} 必须 root_cause = R3，当前为 '{rc}'",
                current_value=rc,
                expected="R3",
                severity=Violation.SEVERITY_ERROR,
                auto_fixable=True,
                fix_value="R3"
            ))
    elif rc is None:
        violations.append(Violation(
            "root_cause", "REQUIRED",
            "root_cause 缺失（仅 P1-3 允许为 null）",
            severity=Violation.SEVERITY_ERROR
        ))
    elif rc not in VALID_ROOT_CAUSES:
        violations.append(Violation(
            "root_cause", "ENUM",
            f"root_cause '{rc}' 不合法",
            current_value=rc,
            expected=sorted(VALID_ROOT_CAUSES),
            severity=Violation.SEVERITY_ERROR
        ))
    else:
        if fcs_short and fcs_short in schema["stage_allowed_rc"]:
            allowed = schema["stage_allowed_rc"][fcs_short]
            if rc not in allowed:
                violations.append(Violation(
                    "root_cause", "STAGE_RC_MISMATCH",
                    f"root_cause '{rc}' 不在阶段 {fcs_short} 的合法根因 {sorted(allowed)} 中",
                    current_value=rc,
                    expected=sorted(allowed),
                    severity=Violation.SEVERITY_ERROR
                ))

        if pt in schema["pcode_allowed_rc"]:
            pcode_rcs = schema["pcode_allowed_rc"][pt]
            if pcode_rcs and rc not in pcode_rcs:
                violations.append(Violation(
                    "root_cause", "PCODE_RC_MISMATCH",
                    f"root_cause '{rc}' 不在 {pt} 的合法根因 {sorted(pcode_rcs)} 中",
                    current_value=rc,
                    expected=sorted(pcode_rcs),
                    severity=Violation.SEVERITY_WARNING
                ))

    # ── 4.7 root_cause_variant ──
    rcv = intent.get("root_cause_variant", "")
    if rcv:
        if rcv not in schema["valid_rc_variants"]:
            if not re.match(r"^P\d+-\d+[a-z]$", rcv):
                violations.append(Violation(
                    "root_cause_variant", "FORMAT",
                    f"root_cause_variant '{rcv}' 格式不合法，应为 P{{x}}-{{n}}{{a-e}} 如 P4-3b",
                    current_value=rcv,
                    severity=Violation.SEVERITY_ERROR
                ))
            else:
                violations.append(Violation(
                    "root_cause_variant", "INVALID",
                    f"root_cause_variant '{rcv}' 不在合法枚举中",
                    current_value=rcv,
                    severity=Violation.SEVERITY_WARNING
                ))
        else:
            expected_pcode = schema["variant_to_pcode"].get(rcv)
            if expected_pcode and pt and expected_pcode != pt:
                violations.append(Violation(
                    "root_cause_variant", "VARIANT_PCODE_MISMATCH",
                    f"root_cause_variant '{rcv}' 属于 {expected_pcode}，"
                    f"但 problem_type 为 '{pt}'",
                    current_value=rcv,
                    expected=f"应属于 {pt} 的子变体",
                    severity=Violation.SEVERITY_ERROR
                ))

            expected_rc = schema["variant_to_rc"].get(rcv)
            if expected_rc and rc and expected_rc != rc:
                violations.append(Violation(
                    "root_cause_variant", "VARIANT_RC_MISMATCH",
                    f"root_cause_variant '{rcv}' 对应 root_cause={expected_rc}，"
                    f"但 intent 的 root_cause 为 '{rc}'",
                    current_value=rcv,
                    expected=f"root_cause 应为 {expected_rc}",
                    severity=Violation.SEVERITY_ERROR
                ))

    # ── 4.8 confidence ──
    conf = intent.get("confidence", "")
    if not conf:
        violations.append(Violation(
            "confidence", "REQUIRED",
            "confidence 缺失",
            severity=Violation.SEVERITY_ERROR
        ))
    else:
        norm_conf = _normalize_confidence(conf)
        if norm_conf is None:
            violations.append(Violation(
                "confidence", "ENUM",
                f"confidence '{conf}' 无法归一化为 high/medium/low",
                current_value=conf,
                expected=sorted(VALID_CONFIDENCE),
                severity=Violation.SEVERITY_ERROR
            ))
        elif str(conf) != norm_conf:
            violations.append(Violation(
                "confidence", "NORMALIZE",
                f"confidence '{conf}' 已归一化为 '{norm_conf}'",
                current_value=conf,
                severity=Violation.SEVERITY_WARNING,
                auto_fixable=True,
                fix_value=norm_conf
            ))

    # ── 4.9 attribution_direction ──
    ad = intent.get("attribution_direction")
    if ad is not None and ad not in VALID_ATTRIBUTION_DIRECTION:
        violations.append(Violation(
            "attribution_direction", "ENUM",
            f"attribution_direction '{ad}' 不合法",
            current_value=ad,
            expected=sorted(VALID_ATTRIBUTION_DIRECTION),
            severity=Violation.SEVERITY_WARNING
        ))

    # 交叉校验：first_cause_nature 与 attribution_direction 一致性
    if fcn and ad:
        if fcn == "ai_deviation" and ad != "ai_execution":
            violations.append(Violation(
                "attribution_direction", "NATURE_DIRECTION_MISMATCH",
                f"first_cause_nature='ai_deviation' 时 attribution_direction 应为 'ai_execution'，当前为 '{ad}'",
                current_value=ad,
                expected="ai_execution",
                severity=Violation.SEVERITY_WARNING,
                auto_fixable=True,
                fix_value="ai_execution"
            ))
        elif fcn in ("product_defect", "upstream_propagation", "prd_quality") and ad != "artifact_defect":
            violations.append(Violation(
                "attribution_direction", "NATURE_DIRECTION_MISMATCH",
                f"first_cause_nature='{fcn}' 时 attribution_direction 应为 'artifact_defect'，当前为 '{ad}'",
                current_value=ad,
                expected="artifact_defect",
                severity=Violation.SEVERITY_WARNING,
                auto_fixable=True,
                fix_value="artifact_defect"
            ))

    # ── 4.10 first_cause_nature 与 problem_type 交叉校验 ──
    if fcn and pt:
        if is_ai_deviation and fcn != "ai_deviation":
            violations.append(Violation(
                "first_cause_nature", "AI_DEV_NATURE_MISMATCH",
                f"problem_type '{pt}' 是 AI 执行偏差类型，"
                f"first_cause_nature 应为 'ai_deviation'，当前为 '{fcn}'",
                current_value=fcn,
                expected="ai_deviation",
                severity=Violation.SEVERITY_ERROR,
                auto_fixable=True,
                fix_value="ai_deviation"
            ))
        if is_prd_quality and fcn != "prd_quality":
            violations.append(Violation(
                "first_cause_nature", "PRD_NATURE_MISMATCH",
                f"problem_type 'P1-3' 时 first_cause_nature 应为 'prd_quality'，当前为 '{fcn}'",
                current_value=fcn,
                expected="prd_quality",
                severity=Violation.SEVERITY_ERROR,
                auto_fixable=True,
                fix_value="prd_quality"
            ))

    # ── 4.11 evidence_chain ──
    chain = intent.get("evidence_chain", [])
    if not chain:
        violations.append(Violation(
            "evidence_chain", "REQUIRED",
            "evidence_chain 缺失或为空",
            severity=Violation.SEVERITY_ERROR
        ))
    elif not isinstance(chain, list):
        violations.append(Violation(
            "evidence_chain", "TYPE",
            f"evidence_chain 应为 list，当前为 {type(chain).__name__}",
            severity=Violation.SEVERITY_ERROR
        ))
    else:
        chain_stages = []
        for idx, step in enumerate(chain):
            if not isinstance(step, dict):
                violations.append(Violation(
                    f"evidence_chain[{idx}]", "TYPE",
                    f"evidence_chain 第 {idx} 条不是 dict",
                    severity=Violation.SEVERITY_ERROR
                ))
                continue

            stage = step.get("stage", "")
            norm_stage = _normalize_stage(stage)

            if not stage:
                violations.append(Violation(
                    f"evidence_chain[{idx}].stage", "REQUIRED",
                    "evidence_chain 条目缺少 stage",
                    severity=Violation.SEVERITY_ERROR
                ))
            elif norm_stage not in VALID_STAGES_FULL:
                violations.append(Violation(
                    f"evidence_chain[{idx}].stage", "ENUM",
                    f"evidence_chain 中阶段名 '{stage}' 不合法",
                    current_value=stage,
                    expected=sorted(VALID_STAGES_FULL),
                    severity=Violation.SEVERITY_ERROR
                ))
            elif stage != norm_stage:
                violations.append(Violation(
                    f"evidence_chain[{idx}].stage", "NORMALIZE",
                    f"evidence_chain 中阶段名 '{stage}' 应为 '{norm_stage}'",
                    current_value=stage,
                    expected=norm_stage,
                    severity=Violation.SEVERITY_WARNING,
                    auto_fixable=True,
                    fix_value=norm_stage
                ))

            chain_stages.append(norm_stage)

            if not step.get("finding"):
                violations.append(Violation(
                    f"evidence_chain[{idx}].finding", "REQUIRED",
                    f"evidence_chain [{norm_stage}] 缺少 finding",
                    severity=Violation.SEVERITY_ERROR
                ))

            # before_vs_artifact 校验（N5/N4 必填）
            if norm_stage in BEFORE_VS_ARTIFACT_STAGES:
                bva = step.get("before_vs_artifact")
                is_signal_sufficient = step.get("finding", "").startswith("信号充足")
                if bva is None and not is_signal_sufficient:
                    violations.append(Violation(
                        f"evidence_chain[{idx}].before_vs_artifact", "REQUIRED_N5N4",
                        f"evidence_chain [{norm_stage}] 缺少 before_vs_artifact"
                        f"（N5/N4 层在逆向归因中必填）",
                        severity=Violation.SEVERITY_ERROR
                    ))
                elif bva is not None and bva not in VALID_BEFORE_VS_ARTIFACT:
                    violations.append(Violation(
                        f"evidence_chain[{idx}].before_vs_artifact", "ENUM",
                        f"before_vs_artifact 值 '{bva}' 不合法",
                        current_value=bva,
                        expected=sorted(VALID_BEFORE_VS_ARTIFACT),
                        severity=Violation.SEVERITY_ERROR
                    ))

            # 首因层字段完整性
            if norm_stage == fcs:
                if not step.get("artifact"):
                    violations.append(Violation(
                        f"evidence_chain[{idx}].artifact", "FIRST_CAUSE_REQUIRED",
                        f"首因层 [{norm_stage}] 缺少 artifact",
                        severity=Violation.SEVERITY_WARNING
                    ))
                # artifact_snippet 已由 4.11c R8 FIRST_CAUSE_NO_EVIDENCE 做 error 级检查

            # N3-N1 层 before_vs_artifact 应为 null
            if norm_stage not in BEFORE_VS_ARTIFACT_STAGES:
                bva = step.get("before_vs_artifact")
                if bva is not None:
                    violations.append(Violation(
                        f"evidence_chain[{idx}].before_vs_artifact", "N3N1_SHOULD_NULL",
                        f"evidence_chain [{norm_stage}] 的 before_vs_artifact 应为 null（仅 N5/N4 必填）",
                        current_value=bva,
                        severity=Violation.SEVERITY_WARNING,
                        auto_fixable=True,
                        fix_value=None
                    ))

        # evidence_chain 完整性：必须包含 N5，且从 N5 到首因层不跳跃
        if fcs in VALID_STAGES_FULL:
            if "N5 编码计划" not in chain_stages:
                violations.append(Violation(
                    "evidence_chain", "MISSING_N5",
                    "evidence_chain 缺少 N5 编码计划（必须从 N5 开始）",
                    severity=Violation.SEVERITY_ERROR
                ))
            else:
                n5_idx = STAGE_ORDER.index("N5 编码计划")
                try:
                    fc_idx = STAGE_ORDER.index(fcs)
                    expected = STAGE_ORDER[n5_idx:fc_idx + 1]
                    missing = [s for s in expected if s not in chain_stages]
                    if missing:
                        violations.append(Violation(
                            "evidence_chain", "STAGE_GAP",
                            f"evidence_chain 从 N5 到首因层 {fcs} 之间缺少阶段: {missing}",
                            current_value=[s for s in chain_stages],
                            expected=expected,
                            severity=Violation.SEVERITY_ERROR
                        ))
                except ValueError:
                    pass

        # ── 4.11a 穿透完整性校验（PENETRATION_INCOMPLETE / SHALLOW / STOPPED） ──
        # R1: 首因 N4 + product_defect → chain 至少到 N3
        if fcs_short == "N4" and fcn == "product_defect":
            if "N3 需求澄清" not in chain_stages:
                violations.append(Violation(
                    "evidence_chain", "PENETRATION_INCOMPLETE",
                    f"首因层 N4 + product_defect，但 evidence_chain 未穿透到 N3。"
                    f"按穿透规则，N4 产物缺陷应继续穿透到 N3 检查需求是否正确传递了设计",
                    current_value=[s for s in chain_stages],
                    expected="evidence_chain 应至少包含 N3 需求澄清",
                    severity=Violation.SEVERITY_ERROR
                ))

        # R2: 首因 N4 + P4-3/P4-2/P4-4 + finding 含遗漏语义 → 应检查 N2
        if fcs_short == "N4" and pt in _P4_REQUIRE_N2_CHECK:
            fc_finding = ""
            for step in (chain if isinstance(chain, list) else []):
                if isinstance(step, dict):
                    s = _normalize_stage(step.get("stage", ""))
                    if s == fcs:
                        fc_finding = step.get("finding", "")
                        break
            if fc_finding and _OMISSION_KEYWORDS.search(fc_finding):
                if "N2 现状梳理" not in chain_stages:
                    violations.append(Violation(
                        "evidence_chain", "PENETRATION_SHALLOW",
                        f"首因层 N4 的 finding 含遗漏语义"
                        f"（'{fc_finding[:80]}...'），但 evidence_chain 未穿透到 N2。"
                        f"N4 设计遗漏（{pt}）可能由 N2 现状梳理缺失传导，"
                        f"建议继续穿透到 N2 检查 current-state.md 是否识别了该波及点",
                        current_value=[s for s in chain_stages],
                        severity=Violation.SEVERITY_ERROR
                    ))

        # R3: 首因 N3 + product_defect → chain 至少到 N2
        if fcs_short == "N3" and fcn == "product_defect":
            if "N2 现状梳理" not in chain_stages:
                violations.append(Violation(
                    "evidence_chain", "PENETRATION_INCOMPLETE",
                    f"首因层 N3 + product_defect，但 evidence_chain 未穿透到 N2。"
                    f"N3 需求缺陷可能由 N2 现状梳理缺失传导，应继续穿透检查",
                    current_value=[s for s in chain_stages],
                    expected="evidence_chain 应至少包含 N2 现状梳理",
                    severity=Violation.SEVERITY_ERROR
                ))

        # R4: product_defect 且首因层 > N2 → chain 终止层应 ≤ N2 或至少超越首因层
        if fcn == "product_defect" and fcs_short in ("N5", "N4", "N3"):
            fcs_idx = STAGE_ORDER.index(fcs) if fcs in STAGE_ORDER else -1
            if fcs_idx >= 0:
                deepest_idx = -1
                for cs in chain_stages:
                    try:
                        ci = STAGE_ORDER.index(cs)
                        if ci > deepest_idx:
                            deepest_idx = ci
                    except ValueError:
                        pass
                if deepest_idx >= 0 and deepest_idx <= fcs_idx:
                    violations.append(Violation(
                        "evidence_chain", "PENETRATION_STOPPED_AT_FIRST_CAUSE",
                        f"first_cause_nature=product_defect 但 evidence_chain 在首因层 "
                        f"{fcs} 就停止了，没有继续向上游穿透。"
                        f"产物缺陷类的穿透应持续到信号充足层（某层 A✓B✓），"
                        f"至少应超越首因层检查上游是否传导",
                        current_value=[s for s in chain_stages],
                        severity=Violation.SEVERITY_WARNING
                    ))

        # ── 4.11b 首因层 finding 语义校验（FINDING_NATURE_CONFLICT） ──
        for step in (chain if isinstance(chain, list) else []):
            if not isinstance(step, dict):
                continue
            norm_stage = _normalize_stage(step.get("stage", ""))
            finding_text = step.get("finding", "")

            # R5/R6: 首因层 finding 与 first_cause_nature 矛盾
            if norm_stage == fcs and finding_text:
                if fcn == "product_defect" and _AI_DEVIATION_KEYWORDS.search(finding_text):
                    violations.append(Violation(
                        "evidence_chain.finding", "FINDING_NATURE_CONFLICT",
                        f"首因层 [{norm_stage}] 的 finding 含 AI 执行偏差语义"
                        f"（'{finding_text[:80]}...'），但 first_cause_nature='product_defect'。"
                        f"finding 描述与首因性质矛盾，请确认归因方向",
                        current_value=finding_text[:100],
                        severity=Violation.SEVERITY_WARNING
                    ))
                elif fcn == "ai_deviation" and _PRODUCT_DEFECT_KEYWORDS.search(finding_text):
                    violations.append(Violation(
                        "evidence_chain.finding", "FINDING_NATURE_CONFLICT",
                        f"首因层 [{norm_stage}] 的 finding 含产物缺陷语义"
                        f"（'{finding_text[:80]}...'），但 first_cause_nature='ai_deviation'。"
                        f"finding 描述与首因性质矛盾，请确认归因方向",
                        current_value=finding_text[:100],
                        severity=Violation.SEVERITY_WARNING
                    ))

            # R7: 信号充足层 finding 过长
            if norm_stage != fcs and finding_text.startswith("信号充足"):
                if len(finding_text) > 200:
                    violations.append(Violation(
                        f"evidence_chain.finding", "SIGNAL_SUFFICIENT_TOO_VERBOSE",
                        f"[{norm_stage}] 标记为信号充足但 finding 长 {len(finding_text)} 字符"
                        f"（应 ≤200）。过长可能意味着该层实际发现了问题但被标记为信号充足，"
                        f"请确认该层是否真的无缺陷",
                        current_value=finding_text[:100] + "...",
                        severity=Violation.SEVERITY_WARNING
                    ))

        # ── 4.11c 证据质量校验（EVIDENCE_QUALITY） ──
        for idx2, step in enumerate(chain if isinstance(chain, list) else []):
            if not isinstance(step, dict):
                continue
            norm_stage = _normalize_stage(step.get("stage", ""))

            # R8: 首因层必须有 artifact_snippet（升级为 error）
            if norm_stage == fcs:
                if not step.get("artifact_snippet"):
                    violations.append(Violation(
                        f"evidence_chain[{idx2}].artifact_snippet",
                        "FIRST_CAUSE_NO_EVIDENCE",
                        f"首因层 [{norm_stage}] 缺少 artifact_snippet。"
                        f"没有引用任何产物证据就下了归因结论，无法判断穿透是否真正执行",
                        severity=Violation.SEVERITY_ERROR
                    ))

                # R9: 首因层 + product_defect 必须有 upstream_artifact
                if fcn == "product_defect":
                    if not step.get("upstream_artifact"):
                        violations.append(Violation(
                            f"evidence_chain[{idx2}].upstream_artifact",
                            "PRODUCT_DEFECT_NO_UPSTREAM",
                            f"首因层 [{norm_stage}] first_cause_nature=product_defect，"
                            f"但缺少 upstream_artifact。产物缺陷的归因应标明"
                            f"上游正确参照是什么（如 requirement.md 的哪条 AC）",
                            severity=Violation.SEVERITY_ERROR
                        ))

            # R10: 传导层（非首因、has_problem=true）应有 upstream_finding
            if norm_stage != fcs:
                has_problem = step.get("has_problem", False)
                problem_nature = step.get("problem_nature", "")
                if has_problem or problem_nature == "upstream_propagation":
                    if not step.get("upstream_finding"):
                        violations.append(Violation(
                            f"evidence_chain[{idx2}].upstream_finding",
                            "PROPAGATION_NO_UPSTREAM",
                            f"传导层 [{norm_stage}] 标记为有问题"
                            f"（has_problem=true / problem_nature='{problem_nature}'），"
                            f"但缺少 upstream_finding，无法判断缺陷如何从上游传导到此层",
                            severity=Violation.SEVERITY_WARNING
                        ))

            # R11: 所有 N5/N4 层的 bva=consistent + AI偏差语义加强
            if norm_stage in BEFORE_VS_ARTIFACT_STAGES and norm_stage != fcs:
                bva = step.get("before_vs_artifact")
                p_nature = step.get("problem_nature", "")
                finding_text = step.get("finding", "")
                if bva == "consistent" and (
                    p_nature == "ai_deviation"
                    or _AI_DEVIATION_KEYWORDS.search(finding_text)
                ):
                    violations.append(Violation(
                        f"evidence_chain[{idx2}]",
                        "BVA_CONSISTENT_AI_DEVIATION_NON_FC",
                        f"[{norm_stage}] before_vs_artifact='consistent'"
                        f"（AI 遵循了产物），但 problem_nature='{p_nature}'"
                        f" 或 finding 含 AI 偏差语义。AI 既已遵循产物，"
                        f"问题应在产物本身而非 AI 执行",
                        severity=Violation.SEVERITY_WARNING
                    ))

            # R13: upstream_snippet 完整性硬约束 (§4.2)
            up_art = step.get("upstream_artifact")
            up_snip = step.get("upstream_snippet")
            if up_art and not up_snip:
                violations.append(Violation(
                    f"evidence_chain[{idx2}].upstream_snippet",
                    "UPSTREAM_SNIPPET_MISSING",
                    f"[{norm_stage}] upstream_artifact='{up_art}' 不为 null，"
                    f"但 upstream_snippet 为空。证据链断裂："
                    f"上游产物已引用但缺少具体文本片段",
                    severity=Violation.SEVERITY_ERROR
                ))

            # R14: 非标准字段名检测 (§4.3 格式统一约束)
            banned_fields = {"doc", "section", "snippet", "relevance"}
            found_banned = [f for f in banned_fields if f in step]
            if found_banned:
                violations.append(Violation(
                    f"evidence_chain[{idx2}]",
                    "NON_STANDARD_FIELD",
                    f"[{norm_stage}] evidence_chain 使用了非标准字段名: {found_banned}。"
                    f"标准字段: stage, artifact, finding, before_vs_artifact, "
                    f"artifact_snippet, upstream_artifact, upstream_finding, "
                    f"upstream_snippet, dependency_path",
                    severity=Violation.SEVERITY_WARNING
                ))

        # R12: root_cause 与 evidence_chain 首因层 finding 交叉校验
        if rc and isinstance(chain, list):
            fc_finding_text = ""
            for step in chain:
                if isinstance(step, dict):
                    s = _normalize_stage(step.get("stage", ""))
                    if s == fcs:
                        fc_finding_text = step.get("finding", "")
                        break
            if fc_finding_text:
                if rc == "R2" and _R3_KEYWORDS.search(fc_finding_text) \
                        and not _R2_KEYWORDS.search(fc_finding_text):
                    violations.append(Violation(
                        "root_cause", "RC_EVIDENCE_MISMATCH",
                        f"root_cause='R2'（执行损耗）但首因层 finding 含 R3 语义"
                        f"（推理/理解/判断）且无 R2 语义（丢失/截断/传递丢失）。"
                        f"finding: '{fc_finding_text[:80]}...'。"
                        f"请确认根因应为 R2（信息传递中丢失）还是 R3（模型推理偏差）",
                        current_value="R2",
                        expected="可能应为 R3",
                        severity=Violation.SEVERITY_WARNING
                    ))
                elif rc == "R3" and _R2_KEYWORDS.search(fc_finding_text) \
                        and not _R3_KEYWORDS.search(fc_finding_text):
                    violations.append(Violation(
                        "root_cause", "RC_EVIDENCE_MISMATCH",
                        f"root_cause='R3'（模型推理）但首因层 finding 含 R2 语义"
                        f"（丢失/截断/传递）且无 R3 语义（推理/理解/判断）。"
                        f"finding: '{fc_finding_text[:80]}...'。"
                        f"请确认根因应为 R3（模型推理偏差）还是 R2（信息传递中丢失）",
                        current_value="R3",
                        expected="可能应为 R2",
                        severity=Violation.SEVERITY_WARNING
                    ))

    # ── 4.12 before_vs_artifact 与 first_cause_nature 交叉校验 ──
    if chain and fcs in VALID_STAGES_FULL:
        for step in (chain if isinstance(chain, list) else []):
            if not isinstance(step, dict):
                continue
            norm_stage = _normalize_stage(step.get("stage", ""))
            if norm_stage == fcs and norm_stage in BEFORE_VS_ARTIFACT_STAGES:
                bva = step.get("before_vs_artifact")
                if bva == "consistent" and fcn == "ai_deviation":
                    violations.append(Violation(
                        "first_cause_nature", "BVA_CONSISTENT_NO_AI_DEV",
                        f"首因层 [{norm_stage}] before_vs_artifact='consistent' "
                        f"（AI 忠实遵循了产物），但 first_cause_nature='ai_deviation'。"
                        f"当 AI 代码与产物一致时，问题应在产物本身（product_defect），"
                        f"而非 AI 执行偏差",
                        current_value="ai_deviation",
                        expected="product_defect",
                        severity=Violation.SEVERITY_ERROR
                    ))

    # ── 4.13 必填文本字段 ──
    for field in ["direct_cause", "propagation_path"]:
        val = intent.get(field)
        if not val:
            violations.append(Violation(
                field, "REQUIRED",
                f"必填字段 '{field}' 缺失或为空",
                severity=Violation.SEVERITY_ERROR
            ))

    # ── 4.14 推荐填写字段 ──
    for field in ["knowledge_check", "artifact_manifestation", "root_cause_verdict",
                   "recommendation", "root_cause_evidence"]:
        val = intent.get(field)
        if not val:
            violations.append(Violation(
                field, "RECOMMENDED",
                f"推荐字段 '{field}' 缺失或为空",
                severity=Violation.SEVERITY_WARNING
            ))

    # ── 4.14b 中文语言校验 ──
    # 归因报告面向中文用户，所有描述性文本字段应以中文为主。
    # 包含 Java 类名/字段名等技术术语是允许的，但整体应以中文叙述。
    _CHINESE_TEXT_FIELDS = [
        "direct_cause", "propagation_path", "recommendation",
        "knowledge_check", "artifact_manifestation", "root_cause_verdict",
        "root_cause_evidence",
    ]
    for field in _CHINESE_TEXT_FIELDS:
        val = intent.get(field, "")
        if not val or not isinstance(val, str) or len(val) < 20:
            continue
        # 计算中文字符占比（CJK Unified Ideographs 范围）
        cjk_count = sum(1 for c in val if '\u4e00' <= c <= '\u9fff')
        cjk_ratio = cjk_count / len(val) if val else 0
        # 中文占比 < 5% 且长度 > 20 → 报 warning
        if cjk_ratio < 0.05:
            violations.append(Violation(
                field, "NOT_CHINESE",
                f"字段 '{field}' 中文占比过低（{cjk_ratio:.1%}，长度 {len(val)}），"
                f"归因报告面向中文用户，描述性文本应以中文为主。"
                f"预览: {val[:80]}...",
                current_value=val[:100],
                severity=Violation.SEVERITY_WARNING,
            ))

    # evidence_chain 中的 finding / upstream_finding 也检查中文
    for idx, step in enumerate(chain if isinstance(chain, list) else []):
        if not isinstance(step, dict):
            continue
        for ef_field in ["finding", "upstream_finding"]:
            ef_val = step.get(ef_field, "")
            if not ef_val or not isinstance(ef_val, str) or len(ef_val) < 20:
                continue
            cjk_count = sum(1 for c in ef_val if '\u4e00' <= c <= '\u9fff')
            cjk_ratio = cjk_count / len(ef_val) if ef_val else 0
            if cjk_ratio < 0.05:
                norm_stage = _normalize_stage(step.get("stage", ""))
                violations.append(Violation(
                    f"evidence_chain[{idx}].{ef_field}", "NOT_CHINESE",
                    f"evidence_chain [{norm_stage}].{ef_field} 中文占比过低"
                    f"（{cjk_ratio:.1%}，长度 {len(ef_val)}），应以中文为主。"
                    f"预览: {ef_val[:80]}...",
                    current_value=ef_val[:100],
                    severity=Violation.SEVERITY_WARNING,
                ))

    # ── 4.15 hunk_ids ──
    hunk_ids = intent.get("hunk_ids")
    if hunk_ids is None:
        violations.append(Violation(
            "hunk_ids", "REQUIRED",
            "hunk_ids 缺失",
            severity=Violation.SEVERITY_ERROR
        ))
    elif not isinstance(hunk_ids, list):
        violations.append(Violation(
            "hunk_ids", "TYPE",
            f"hunk_ids 应为 list，当前为 {type(hunk_ids).__name__}",
            severity=Violation.SEVERITY_ERROR
        ))
    elif len(hunk_ids) == 0:
        violations.append(Violation(
            "hunk_ids", "EMPTY",
            "hunk_ids 为空列表",
            severity=Violation.SEVERITY_WARNING
        ))

    # ── 4.16 additional_tags 类型校验 ──
    at = intent.get("additional_tags")
    if at is not None and not isinstance(at, list):
        violations.append(Violation(
            "additional_tags", "TYPE",
            f"additional_tags 应为 list，当前为 {type(at).__name__}",
            severity=Violation.SEVERITY_WARNING,
            auto_fixable=True,
            fix_value=[str(at)] if at else []
        ))

    # ── 4.17 impact 字段校验 ──
    impact = intent.get("impact")
    if impact is not None:
        if not isinstance(impact, dict):
            violations.append(Violation(
                "impact", "TYPE",
                f"impact 应为 dict，当前为 {type(impact).__name__}",
                severity=Violation.SEVERITY_WARNING
            ))
        else:
            for num_field in ["total_removed_lines", "total_added_lines"]:
                val = impact.get(num_field)
                if val is not None and not isinstance(val, (int, float)):
                    violations.append(Violation(
                        f"impact.{num_field}", "TYPE",
                        f"impact.{num_field} 应为数值，当前为 '{val}'",
                        severity=Violation.SEVERITY_WARNING
                    ))

    # ── 4.18 归因一致性校准（确定性规则自动修正） ──
    # 根据 evidence_chain 中首因层的 before_vs_artifact，强制校准
    # first_cause_nature / attribution_direction / problem_type 三个字段的逻辑一致性
    calibrations = _calibrate_attribution_consistency(intent, schema, fcs, fcn, pt, ad, chain)
    for cal in calibrations:
        violations.append(cal)

    return violations


# ── 归因一致性校准规则 ─────────────────────────────────────────────────────────

def _calibrate_attribution_consistency(intent, schema, fcs, fcn, pt, ad, chain):
    """根据 before_vs_artifact 和归因规则，校准 first_cause_nature /
    attribution_direction / problem_type 的逻辑一致性。

    校准规则（按优先级）：
    1. before_vs_artifact=consistent → 不可能是 ai_deviation，应为 product_defect
    2. before_vs_artifact=inconsistent → 不可能是 product_defect，应为 ai_deviation
    3. first_cause_nature=ai_deviation → attribution_direction=ai_execution
       + problem_type 应为 P4-14（AI 执行偏差类型，N5 无对应类型）
    4. first_cause_nature=product_defect → attribution_direction=artifact_defect
       + problem_type 不能是 P4-14
    5. problem_type 的 P-code 前缀必须与 first_cause_stage 的阶段一致

    返回 violation 列表（auto_fixable=True 的会被 --fix 自动修正）。
    """
    violations = []

    if not fcs or not chain:
        return violations

    fcs_norm = _normalize_stage(fcs)
    if fcs_norm not in VALID_STAGES_FULL:
        return violations

    # 找到首因层在 evidence_chain 中的 before_vs_artifact
    fc_bva = None
    for step in (chain if isinstance(chain, list) else []):
        if not isinstance(step, dict):
            continue
        norm_stage = _normalize_stage(step.get("stage", ""))
        if norm_stage == fcs_norm and norm_stage in BEFORE_VS_ARTIFACT_STAGES:
            fc_bva = step.get("before_vs_artifact")
            break

    if fc_bva is None:
        return violations

    is_ai_deviation_pt = pt in schema.get("ai_deviation_pcodes", {"P4-14"})
    fcs_short = STAGE_FULL_TO_SHORT.get(fcs_norm, "")

    # 规则 1: consistent + ai_deviation → 改为 product_defect
    if fc_bva == "consistent" and fcn == "ai_deviation":
        violations.append(Violation(
            "first_cause_nature", "CALIBRATE_CONSISTENT_TO_PRODUCT_DEFECT",
            f"归因校准：首因层 before_vs_artifact='consistent'（AI 遵循了产物），"
            f"first_cause_nature 应为 'product_defect' 而非 'ai_deviation'",
            current_value="ai_deviation",
            expected="product_defect",
            severity=Violation.SEVERITY_ERROR,
            auto_fixable=True,
            fix_value="product_defect"
        ))
        # 连带修正 attribution_direction
        if ad != "artifact_defect":
            violations.append(Violation(
                "attribution_direction", "CALIBRATE_DIR_TO_ARTIFACT_DEFECT",
                f"归因校准：first_cause_nature 校准为 product_defect，"
                f"attribution_direction 应为 'artifact_defect'",
                current_value=ad,
                expected="artifact_defect",
                severity=Violation.SEVERITY_ERROR,
                auto_fixable=True,
                fix_value="artifact_defect"
            ))
        # 连带修正 problem_type：P4-14 → 对应阶段的产物缺陷类型
        if is_ai_deviation_pt:
            if fcs_short == "N4":
                new_pt = "P4-3"
            else:
                new_pt = "P5-2"
            violations.append(Violation(
                "problem_type", "CALIBRATE_PT_FROM_AI_DEV",
                f"归因校准：first_cause_nature 校准为 product_defect，"
                f"problem_type 不能是 AI 执行偏差类型 '{pt}'，应为 '{new_pt}'",
                current_value=pt,
                expected=new_pt,
                severity=Violation.SEVERITY_ERROR,
                auto_fixable=True,
                fix_value=new_pt
            ))

    # 规则 2: inconsistent + product_defect → 改为 ai_deviation
    if fc_bva == "inconsistent" and fcn in ("product_defect", "upstream_propagation"):
        violations.append(Violation(
            "first_cause_nature", "CALIBRATE_INCONSISTENT_TO_AI_DEV",
            f"归因校准：首因层 before_vs_artifact='inconsistent'（AI 偏离了产物），"
            f"first_cause_nature 应为 'ai_deviation' 而非 '{fcn}'",
            current_value=fcn,
            expected="ai_deviation",
            severity=Violation.SEVERITY_ERROR,
            auto_fixable=True,
            fix_value="ai_deviation"
        ))
        # 连带修正 attribution_direction
        if ad != "ai_execution":
            violations.append(Violation(
                "attribution_direction", "CALIBRATE_DIR_TO_AI_EXECUTION",
                f"归因校准：first_cause_nature 校准为 ai_deviation，"
                f"attribution_direction 应为 'ai_execution'",
                current_value=ad,
                expected="ai_execution",
                severity=Violation.SEVERITY_ERROR,
                auto_fixable=True,
                fix_value="ai_execution"
            ))
        # 连带修正 problem_type：非 P4-14 → AI 执行偏差类型
        # 注意：仅当该阶段有合法的 AI 偏差 P-code 时才修正
        if not is_ai_deviation_pt:
            if fcs_short == "N4":
                new_pt = "P4-14"
            else:
                # N5 没有 AI 执行偏差类型，保持原 problem_type 但标注为 ai_deviation
                new_pt = None
            if new_pt:
                violations.append(Violation(
                    "problem_type", "CALIBRATE_PT_TO_AI_DEV",
                    f"归因校准：first_cause_nature 校准为 ai_deviation，"
                    f"problem_type 应为 AI 执行偏差类型 '{new_pt}' 而非 '{pt}'",
                    current_value=pt,
                    expected=new_pt,
                    severity=Violation.SEVERITY_ERROR,
                    auto_fixable=True,
                    fix_value=new_pt
                ))

    # 规则 3: problem_type 阶段前缀与 first_cause_stage 一致性
    if pt and fcs_short and not is_ai_deviation_pt:
        expected_stage = schema.get("pcode_to_stage", {}).get(pt)
        if expected_stage and expected_stage != fcs_short:
            allowed = schema.get("stage_to_pcodes", {}).get(fcs_short, set())
            violations.append(Violation(
                "problem_type", "CALIBRATE_PT_STAGE_MISMATCH",
                f"归因校准：problem_type '{pt}' 属于 {expected_stage} 阶段，"
                f"但 first_cause_stage 为 '{fcs_short}'。"
                f"该阶段的合法 P-code: {sorted(allowed)}",
                current_value=pt,
                expected=sorted(allowed),
                severity=Violation.SEVERITY_ERROR,
            ))

    return violations
# ══════════════════════════════════════════════════════════════════════════════

def _normalize_confidence(conf) -> str | None:
    """归一化 confidence 值，返回 high/medium/low 或 None（不合法时）。"""
    if isinstance(conf, (int, float)):
        if conf >= 0.8:
            return "high"
        elif conf >= 0.5:
            return "medium"
        else:
            return "low"
    elif isinstance(conf, str):
        norm = conf.strip().lower()
        try:
            fval = float(norm)
            if fval >= 0.8:
                return "high"
            elif fval >= 0.5:
                return "medium"
            else:
                return "low"
        except ValueError:
            pass
        if norm in VALID_CONFIDENCE:
            return norm
    return None


def validate_intent_ci(ci: dict) -> list:
    """
    校验 change-intents.json 的单个 change_intent 条目全字段。

    对应 SubAgent-Intent 的 change_intents[] 输出。
    """
    violations = []
    cid = ci.get("intent_id", "?")

    # ── 5.1 intent_id ──
    iid = ci.get("intent_id")
    if not iid:
        violations.append(Violation(
            "intent_id", "REQUIRED",
            "intent_id 缺失",
            severity=Violation.SEVERITY_ERROR
        ))
    elif not isinstance(iid, str):
        violations.append(Violation(
            "intent_id", "TYPE",
            f"intent_id 应为 string，当前为 {type(iid).__name__}",
            severity=Violation.SEVERITY_ERROR
        ))
    elif not re.match(r"^CI-\d{3,}$", iid):
        violations.append(Violation(
            "intent_id", "FORMAT",
            f"intent_id '{iid}' 格式不合法，应为 CI-{{NNN}} 如 CI-001",
            current_value=iid,
            severity=Violation.SEVERITY_WARNING
        ))

    # ── 5.2 intent_description ──
    desc = ci.get("intent_description")
    if not desc:
        violations.append(Violation(
            "intent_description", "REQUIRED",
            "intent_description 缺失或为空",
            severity=Violation.SEVERITY_ERROR
        ))
    elif not isinstance(desc, str):
        violations.append(Violation(
            "intent_description", "TYPE",
            f"intent_description 应为 string，当前为 {type(desc).__name__}",
            severity=Violation.SEVERITY_ERROR
        ))
    elif len(desc) < 10:
        violations.append(Violation(
            "intent_description", "TOO_SHORT",
            f"intent_description 过短（{len(desc)} 字符），应具体描述 AI 原始代码缺陷",
            current_value=desc,
            severity=Violation.SEVERITY_WARNING
        ))

    # ── 5.3 diff_nature ──
    dn = ci.get("diff_nature", "")
    if not dn:
        violations.append(Violation(
            "diff_nature", "REQUIRED",
            "diff_nature 缺失",
            severity=Violation.SEVERITY_ERROR
        ))
    elif dn not in VALID_DIFF_NATURE:
        violations.append(Violation(
            "diff_nature", "ENUM",
            f"diff_nature 值 '{dn}' 不合法",
            current_value=dn,
            expected=sorted(VALID_DIFF_NATURE),
            severity=Violation.SEVERITY_ERROR
        ))

    # ── 5.4 hunk_ids ──
    hids = ci.get("hunk_ids")
    if hids is None:
        violations.append(Violation(
            "hunk_ids", "REQUIRED",
            "hunk_ids 缺失",
            severity=Violation.SEVERITY_ERROR
        ))
    elif not isinstance(hids, list):
        violations.append(Violation(
            "hunk_ids", "TYPE",
            f"hunk_ids 应为 list，当前为 {type(hids).__name__}",
            severity=Violation.SEVERITY_ERROR
        ))
    elif len(hids) == 0:
        violations.append(Violation(
            "hunk_ids", "EMPTY",
            "hunk_ids 为空列表，Change Intent 至少应包含 1 个 hunk",
            severity=Violation.SEVERITY_ERROR
        ))

    # ── 5.5 is_composite ──
    ic = ci.get("is_composite")
    if ic is None:
        violations.append(Violation(
            "is_composite", "REQUIRED",
            "is_composite 缺失",
            severity=Violation.SEVERITY_ERROR
        ))
    elif not isinstance(ic, bool):
        violations.append(Violation(
            "is_composite", "TYPE",
            f"is_composite 应为 bool，当前为 {type(ic).__name__}（值={ic}）",
            current_value=ic,
            severity=Violation.SEVERITY_WARNING,
            auto_fixable=True,
            fix_value=bool(ic)
        ))

    # ── 5.6 cluster_confidence ──
    cc = ci.get("cluster_confidence")
    if not cc:
        violations.append(Violation(
            "cluster_confidence", "REQUIRED",
            "cluster_confidence 缺失",
            severity=Violation.SEVERITY_ERROR
        ))
    else:
        norm_cc = _normalize_confidence(cc)
        if norm_cc is None:
            violations.append(Violation(
                "cluster_confidence", "ENUM",
                f"cluster_confidence '{cc}' 无法归一化为 high/medium/low",
                current_value=cc,
                expected=sorted(VALID_CONFIDENCE),
                severity=Violation.SEVERITY_ERROR
            ))
        elif str(cc) != norm_cc:
            violations.append(Violation(
                "cluster_confidence", "NORMALIZE",
                f"cluster_confidence '{cc}' 已归一化为 '{norm_cc}'",
                current_value=cc,
                severity=Violation.SEVERITY_WARNING,
                auto_fixable=True,
                fix_value=norm_cc
            ))

    # ── 5.7 cluster_method ──
    cm = ci.get("cluster_method")
    if not cm:
        violations.append(Violation(
            "cluster_method", "REQUIRED",
            "cluster_method 缺失",
            severity=Violation.SEVERITY_WARNING
        ))
    elif cm not in VALID_CLUSTER_METHOD:
        violations.append(Violation(
            "cluster_method", "ENUM",
            f"cluster_method '{cm}' 不合法",
            current_value=cm,
            expected=sorted(VALID_CLUSTER_METHOD),
            severity=Violation.SEVERITY_WARNING
        ))

    # ── 5.8 clustering_inputs（llm_rationale 方法必填） ──
    if cm == "llm_rationale":
        ci_inputs = ci.get("clustering_inputs")
        if ci_inputs is None:
            violations.append(Violation(
                "clustering_inputs", "REQUIRED_FOR_LLM",
                "cluster_method='llm_rationale' 时 clustering_inputs 必填",
                severity=Violation.SEVERITY_WARNING
            ))
        elif not isinstance(ci_inputs, dict):
            violations.append(Violation(
                "clustering_inputs", "TYPE",
                f"clustering_inputs 应为 dict，当前为 {type(ci_inputs).__name__}",
                severity=Violation.SEVERITY_WARNING
            ))

    # ── 5.9 pdg_edges（pdg_hard_merge 方法推荐填写） ──
    if cm == "pdg_hard_merge":
        pdg = ci.get("pdg_edges")
        if pdg is not None and not isinstance(pdg, list):
            violations.append(Violation(
                "pdg_edges", "TYPE",
                f"pdg_edges 应为 list，当前为 {type(pdg).__name__}",
                severity=Violation.SEVERITY_WARNING
            ))

    return violations


def validate_intent_hunk(hunk: dict) -> list:
    """
    校验 change-intents.json 的单个 hunks[] 条目全字段。

    对应 SubAgent-Intent 对每个 hunk 提取的 before/after 和 intent_description。
    """
    violations = []
    hid = hunk.get("hunk_id", "?")

    # ── 5h.1 hunk_id ──
    if not hunk.get("hunk_id"):
        violations.append(Violation(
            "hunk_id", "REQUIRED",
            "hunk_id 缺失",
            severity=Violation.SEVERITY_ERROR
        ))

    # ── 5h.2 intent_descriptions ──
    descs = hunk.get("intent_descriptions")
    if descs is None:
        violations.append(Violation(
            "intent_descriptions", "REQUIRED",
            "intent_descriptions 缺失",
            severity=Violation.SEVERITY_ERROR
        ))
    elif not isinstance(descs, list):
        violations.append(Violation(
            "intent_descriptions", "TYPE",
            f"intent_descriptions 应为 list，当前为 {type(descs).__name__}",
            severity=Violation.SEVERITY_ERROR
        ))
    elif len(descs) == 0:
        violations.append(Violation(
            "intent_descriptions", "EMPTY",
            "intent_descriptions 为空列表",
            severity=Violation.SEVERITY_ERROR
        ))
    else:
        for idx, d in enumerate(descs):
            if not isinstance(d, str) or not d.strip():
                violations.append(Violation(
                    f"intent_descriptions[{idx}]", "EMPTY",
                    f"intent_descriptions[{idx}] 为空或非字符串",
                    severity=Violation.SEVERITY_ERROR
                ))

    # ── 5h.3 diff_nature ──
    dn = hunk.get("diff_nature", "")
    if not dn:
        violations.append(Violation(
            "diff_nature", "REQUIRED",
            f"hunk {hid} 缺少 diff_nature",
            severity=Violation.SEVERITY_ERROR
        ))
    elif dn not in VALID_DIFF_NATURE:
        violations.append(Violation(
            "diff_nature", "ENUM",
            f"hunk {hid} diff_nature '{dn}' 不合法",
            current_value=dn,
            expected=sorted(VALID_DIFF_NATURE),
            severity=Violation.SEVERITY_ERROR
        ))

    # ── 5h.4 before_code ──
    bc = hunk.get("before_code")
    if bc is None:
        violations.append(Violation(
            "before_code", "REQUIRED",
            f"hunk {hid} 缺少 before_code（AI 原始代码）",
            severity=Violation.SEVERITY_ERROR
        ))
    elif not isinstance(bc, str):
        violations.append(Violation(
            "before_code", "TYPE",
            f"hunk {hid} before_code 应为 string",
            severity=Violation.SEVERITY_ERROR
        ))

    # ── 5h.5 after_code ──
    ac = hunk.get("after_code")
    if ac is None:
        violations.append(Violation(
            "after_code", "REQUIRED",
            f"hunk {hid} 缺少 after_code（人工修正后代码）",
            severity=Violation.SEVERITY_ERROR
        ))
    elif not isinstance(ac, str):
        violations.append(Violation(
            "after_code", "TYPE",
            f"hunk {hid} after_code 应为 string",
            severity=Violation.SEVERITY_ERROR
        ))

    # ── 5h.6 change_summary ──
    cs = hunk.get("change_summary")
    if not cs:
        violations.append(Violation(
            "change_summary", "REQUIRED",
            f"hunk {hid} 缺少 change_summary",
            severity=Violation.SEVERITY_ERROR
        ))

    # ── 5h.7 is_composite ──
    ic = hunk.get("is_composite")
    if ic is None:
        violations.append(Violation(
            "is_composite", "REQUIRED",
            f"hunk {hid} 缺少 is_composite",
            severity=Violation.SEVERITY_WARNING
        ))
    elif not isinstance(ic, bool):
        violations.append(Violation(
            "is_composite", "TYPE",
            f"hunk {hid} is_composite 应为 bool，当前为 {type(ic).__name__}",
            severity=Violation.SEVERITY_WARNING,
            auto_fixable=True,
            fix_value=bool(ic)
        ))

    # ── 5h.8 before_code 与 after_code 相同 → 无实际改动 ──
    if bc and ac and isinstance(bc, str) and isinstance(ac, str):
        if bc.strip() == ac.strip():
            violations.append(Violation(
                "before_code/after_code", "IDENTICAL",
                f"hunk {hid} 的 before_code 和 after_code 完全相同（无实际改动）",
                severity=Violation.SEVERITY_WARNING
            ))

    return violations


def validate_intent_cross_checks(data: dict, hunk_list: dict | None,
                                  pre_cluster: dict | None) -> list:
    """
    change-intents.json 的 9 项后置校验（references/subagent-intent.md 后置校验章节定义的全部 9 项规则）。

    这些校验需要跨 CI/hunk 做交叉检查：
      1. symbol_hint 矛盾检测
      2. 文件重叠检测（跨 CI）
      3. commit 链时序检测
      4. 规模合理性检测
      5. D-xx 映射一致性
      6. intent_description 语义矛盾检测
      7. diff_nature 混合检测
      8. commit_message 与 diff 一致性检测
      9. 跨仓 design_cluster 一致性检测
    """
    violations = []
    cis = data.get("change_intents", [])
    hunks_map = {}
    if hunk_list:
        for h in hunk_list.get("hunks", []):
            hunks_map[h.get("hunk_id")] = h

    # 构建 hunk → CI 映射
    hunk_to_ci = {}
    for ci in cis:
        cid = ci.get("intent_id", "?")
        for hid in ci.get("hunk_ids", []):
            if hid in hunk_to_ci:
                # 一个 hunk 不应出现在多个 CI 中
                violations.append(Violation(
                    f"hunk_ids({hid})", "HUNK_MULTI_CI",
                    f"hunk '{hid}' 同时出现在 {hunk_to_ci[hid]} 和 {cid} 中（不应跨 CI 重复）",
                    current_value=[hunk_to_ci[hid], cid],
                    severity=Violation.SEVERITY_ERROR
                ))
            hunk_to_ci[hid] = cid

    # 构建 intent_id 去重检查
    seen_ids = Counter(ci.get("intent_id") for ci in cis)
    for iid, count in seen_ids.items():
        if count > 1:
            violations.append(Violation(
                f"intent_id({iid})", "DUPLICATE",
                f"intent_id '{iid}' 重复出现 {count} 次",
                severity=Violation.SEVERITY_ERROR
            ))

    for ci in cis:
        cid = ci.get("intent_id", "?")
        hids = ci.get("hunk_ids", [])
        dn = ci.get("diff_nature", "")

        # ── 校验 1: symbol_hint 矛盾检测 ──
        if hunks_map and len(hids) > 1:
            symbols = set()
            for hid in hids:
                h = hunks_map.get(hid, {})
                sh = h.get("symbol_hint")
                if sh:
                    symbols.add(sh)
            if len(symbols) > 3:
                violations.append(Violation(
                    f"{cid}.symbol_hint", "SYMBOL_CONFLICT",
                    f"{cid} 内 hunk 的 symbol_hint 差异过大（{len(symbols)} 个不同符号）：{sorted(symbols)[:5]}...",
                    current_value=sorted(symbols),
                    severity=Violation.SEVERITY_WARNING
                ))

        # ── 校验 2: 文件重叠检测（跨 CI） ──
        # （在外层循环后统一做）

        # ── 校验 4: 规模合理性检测 ──
        if len(hids) > 8:
            violations.append(Violation(
                f"{cid}.hunk_ids", "OVER_AGGREGATION_HUNKS",
                f"{cid} 包含 {len(hids)} 个 hunk（>8），可能过度聚合",
                current_value=len(hids),
                severity=Violation.SEVERITY_WARNING
            ))

        if hunks_map:
            files = set()
            for hid in hids:
                h = hunks_map.get(hid, {})
                fp = h.get("file_path")
                if fp:
                    files.add(fp)
            if len(files) > 4:
                violations.append(Violation(
                    f"{cid}.files", "OVER_AGGREGATION_FILES",
                    f"{cid} 跨 {len(files)} 个文件（>4），可能过度聚合",
                    current_value=len(files),
                    severity=Violation.SEVERITY_WARNING
                ))

        # ── 校验 5: D-xx 映射一致性 ──
        if hunks_map:
            dcids = set()
            for hid in hids:
                h = hunks_map.get(hid, {})
                dc = h.get("design_cluster_id")
                if dc:
                    dcids.add(dc)
            if len(dcids) > 2:
                violations.append(Violation(
                    f"{cid}.design_cluster", "DESIGN_CLUSTER_CONFLICT",
                    f"{cid} 内 hunk 映射到 {len(dcids)} 个不同 design_cluster_id：{sorted(dcids)}，"
                    f"建议拆分（阈值 >2）",
                    current_value=sorted(dcids),
                    severity=Violation.SEVERITY_WARNING
                ))

        # ── 校验 3: commit 链时序检测 ──
        # 不同 commit message 表达不同功能但被聚到同一 Change Intent。
        if hunks_map and len(hids) > 1:
            commit_kw_sets = []  # [(hunk_id, keyword_set, direction_set)]
            for hid in hids:
                h = hunks_map.get(hid, {})
                for sc in h.get("source_commits", []) or []:
                    cm = sc.get("commit_message")
                    if cm:
                        kws = _commit_keywords(cm)
                        dirs = _extract_direction(cm)
                        if kws:
                            commit_kw_sets.append((hid, kws, dirs))
            if len(commit_kw_sets) > 1:
                # 任意两条 commit_message 关键词无交集 且 方向标签也不同 → 判定为不同功能
                conflicting_pairs = []
                for i in range(len(commit_kw_sets)):
                    for j in range(i + 1, len(commit_kw_sets)):
                        hid_a, kws_a, dirs_a = commit_kw_sets[i]
                        hid_b, kws_b, dirs_b = commit_kw_sets[j]
                        if hid_a == hid_b:
                            continue
                        no_kw_overlap = len(kws_a & kws_b) == 0
                        no_dir_overlap = (dirs_a and dirs_b and len(dirs_a & dirs_b) == 0)
                        if no_kw_overlap and no_dir_overlap:
                            conflicting_pairs.append((hid_a, hid_b))
                if conflicting_pairs:
                    violations.append(Violation(
                        f"{cid}.source_commits", "COMMIT_TIMELINE_MISMATCH",
                        f"{cid} 内 hunk 关联的 commit_message 关键词与方向均无交集（可能表达不同功能）："
                        f"{conflicting_pairs[:5]}",
                        current_value=conflicting_pairs[:10],
                        severity=Violation.SEVERITY_WARNING
                    ))

        # ── 校验 6: intent_description 语义矛盾检测 ──
        # 同一 CI 内 hunks[].intent_descriptions[] 的方向标签互相冲突（如 additive vs subtractive）。
        if len(hids) > 1:
            hunk_intent_dirs = []  # [(hunk_id, direction_set)]
            for hid in hids:
                h_intent = None
                for hi in data.get("hunks", []):
                    if hi.get("hunk_id") == hid:
                        h_intent = hi
                        break
                if not h_intent:
                    continue
                descs = h_intent.get("intent_descriptions", []) or []
                dirs = set()
                for d in descs:
                    dirs |= _extract_direction(d)
                if dirs:
                    hunk_intent_dirs.append((hid, dirs))

            # 互斥方向对：additive/subtractive 语义相反；corrective/refining 与两者均可能矛盾
            _OPPOSITE_PAIRS = [("additive", "subtractive")]
            conflicts = []
            for i in range(len(hunk_intent_dirs)):
                for j in range(i + 1, len(hunk_intent_dirs)):
                    hid_a, dirs_a = hunk_intent_dirs[i]
                    hid_b, dirs_b = hunk_intent_dirs[j]
                    for d1, d2 in _OPPOSITE_PAIRS:
                        if (d1 in dirs_a and d2 in dirs_b) or (d2 in dirs_a and d1 in dirs_b):
                            conflicts.append((hid_a, hid_b, d1, d2))
            if conflicts:
                violations.append(Violation(
                    f"{cid}.intent_descriptions", "INTENT_DESCRIPTION_CONFLICT",
                    f"{cid} 内 hunk 的 intent_descriptions 语义方向相互矛盾："
                    f"{[(a, b, f'{d1}<->{d2}') for a, b, d1, d2 in conflicts[:5]]}",
                    current_value=[(a, b, d1, d2) for a, b, d1, d2 in conflicts[:10]],
                    severity=Violation.SEVERITY_WARNING
                ))

        # ── 校验 8: commit_message 与 diff 一致性检测 ──
        # 单个 hunk 的 commit_message 方向与其 intent_description（AI 代码缺陷方向）不一致。
        if hunks_map:
            for hid in hids:
                h = hunks_map.get(hid, {})
                commit_dirs = set()
                for sc in h.get("source_commits", []) or []:
                    cm = sc.get("commit_message")
                    if cm:
                        commit_dirs |= _extract_direction(cm)
                if not commit_dirs:
                    continue

                h_intent = None
                for hi in data.get("hunks", []):
                    if hi.get("hunk_id") == hid:
                        h_intent = hi
                        break
                if not h_intent:
                    continue
                descs = h_intent.get("intent_descriptions", []) or []
                desc_dirs = set()
                for d in descs:
                    desc_dirs |= _extract_direction(d)
                if not desc_dirs:
                    continue

                # commit_message 方向与 intent_description 方向完全无交集 → 不一致
                if commit_dirs.isdisjoint(desc_dirs):
                    violations.append(Violation(
                        f"{cid}.{hid}.commit_message", "COMMIT_DIFF_MISMATCH",
                        f"hunk '{hid}' 的 commit_message 方向 {sorted(commit_dirs)} 与 "
                        f"intent_description 方向 {sorted(desc_dirs)} 不一致",
                        current_value={"commit_dirs": sorted(commit_dirs), "desc_dirs": sorted(desc_dirs)},
                        severity=Violation.SEVERITY_WARNING
                    ))

        # ── 校验 7: diff_nature 混合检测 ──
        if hunks_map and len(hids) > 1:
            hunk_dns = set()
            hunk_dcids = set()
            for hid in hids:
                # 尝试从 change-intents.json 的 hunks[] 获取 diff_nature
                # （优先用 hunks[] 的 diff_nature，因为 CI 级别的是聚合后的）
                h_intent = None
                for hi in data.get("hunks", []):
                    if hi.get("hunk_id") == hid:
                        h_intent = hi
                        break
                if h_intent:
                    hdn = h_intent.get("diff_nature")
                    if hdn:
                        hunk_dns.add(hdn)
                h = hunks_map.get(hid, {})
                dc = h.get("design_cluster_id")
                if dc:
                    hunk_dcids.add(dc)

            if len(hunk_dns) > 1:
                has_refining = "refining" in hunk_dns
                same_design = len(hunk_dcids) == 1
                if has_refining and not same_design:
                    violations.append(Violation(
                        f"{cid}.diff_nature", "DIFF_NATURE_MIX",
                        f"{cid} 内 hunk 包含不同 diff_nature：{sorted(hunk_dns)}，"
                        f"refining 与其他类型混合需拆分（除非同一 design_cluster_id）",
                        current_value=sorted(hunk_dns),
                        severity=Violation.SEVERITY_WARNING
                    ))

    # ── 校验 2: 文件重叠检测（跨 CI） ──
    if hunks_map:
        # 构建 (file_path, line_range) → CI 映射
        file_line_to_ci = defaultdict(list)
        for ci in cis:
            cid = ci.get("intent_id", "?")
            for hid in ci.get("hunk_ids", []):
                h = hunks_map.get(hid, {})
                fp = h.get("file_path")
                old_start = h.get("old_start", 0)
                old_lines = h.get("old_lines", 0)
                new_start = h.get("new_start", 0)
                new_lines = h.get("new_lines", 0)
                if fp:
                    file_line_to_ci[(fp, old_start, old_start + old_lines)].append(cid)

        for (fp, start, end), ci_ids in file_line_to_ci.items():
            unique_cis = list(set(ci_ids))
            if len(unique_cis) > 1:
                violations.append(Violation(
                    f"file_overlap({fp}:{start}-{end})", "FILE_LINE_OVERLAP",
                    f"文件 {fp} 行 {start}-{end} 同时被 {unique_cis} 包含",
                    current_value=unique_cis,
                    severity=Violation.SEVERITY_WARNING
                ))

    # ── 校验 9: 跨仓 design_cluster 一致性 ──
    if hunks_map:
        dc_to_cis = defaultdict(set)
        for ci in cis:
            cid = ci.get("intent_id", "?")
            for hid in ci.get("hunk_ids", []):
                h = hunks_map.get(hid, {})
                dc = h.get("design_cluster_id")
                if dc:
                    dc_to_cis[dc].add(cid)
        for dc, ci_set in dc_to_cis.items():
            if len(ci_set) > 1:
                # 检查是否跨仓
                repos_per_ci = {}
                for ci_id in ci_set:
                    ci_obj = next((c for c in cis if c.get("intent_id") == ci_id), None)
                    if ci_obj:
                        repos = set()
                        for hid in ci_obj.get("hunk_ids", []):
                            h = hunks_map.get(hid, {})
                            r = h.get("repo")
                            if r:
                                repos.add(r)
                        repos_per_ci[ci_id] = repos

                all_repos = set()
                for repos in repos_per_ci.values():
                    all_repos |= repos

                if len(all_repos) > 1:
                    violations.append(Violation(
                        f"design_cluster({dc})", "CROSS_REPO_DC_SPLIT",
                        f"design_cluster_id '{dc}' 的 hunk 分布在多个仓库 {sorted(all_repos)} "
                        f"且被分到不同 CI {sorted(ci_set)}。Layer 0 已建立跨仓关联，"
                        f"未合并可能意味着聚类遗漏了设计意图信号",
                        current_value={"design_cluster_id": dc, "ci_ids": sorted(ci_set), "repos": sorted(all_repos)},
                        severity=Violation.SEVERITY_WARNING
                    ))

    # ── hunk 覆盖完整性：change-intents hunks[] 中的 hunk 应全部被某 CI 引用 ──
    declared_hunks = set()
    for h in data.get("hunks", []):
        hid = h.get("hunk_id")
        if hid:
            declared_hunks.add(hid)

    referenced_hunks = set()
    for ci in cis:
        for hid in ci.get("hunk_ids", []):
            referenced_hunks.add(hid)

    orphaned = declared_hunks - referenced_hunks
    if orphaned:
        violations.append(Violation(
            "hunks_coverage", "ORPHANED_HUNKS",
            f"hunks[] 中 {len(orphaned)} 个 hunk 未被任何 Change Intent 引用：{sorted(list(orphaned)[:10])}",
            current_value=sorted(list(orphaned)[:20]),
            severity=Violation.SEVERITY_WARNING
        ))

    return violations


def validate_change_intents_file(data: dict, hunk_list: dict | None = None,
                                  pre_cluster: dict | None = None,
                                  auto_fix: bool = False):
    """
    校验整个 change-intents.json 文件。

    返回:
      results: [{"target", "violations", "error_count", "warning_count"}]
      summary: {total, passed, failed, total_errors, total_warnings}
      validation: {"warnings": [...], "auto_fixes": [...]}
        —— 对齐 references/subagent-intent.md 规格中定义的顶层 warnings[] / auto_fixes[]
        结构，供写入 change-intents.json 的 validation 字段或独立的
        cluster-validation.json。
    """
    results = []
    total_errors = 0
    total_warnings = 0
    total_fixed = 0

    # 校验 change_intents[]
    cis = data.get("change_intents", [])
    if not cis:
        results.append({
            "target": "change_intents",
            "target_type": "structure",
            "violations": [Violation(
                "change_intents", "REQUIRED",
                "change_intents 数组缺失或为空",
                severity=Violation.SEVERITY_ERROR
            ).to_dict()],
            "error_count": 1,
            "warning_count": 0,
        })
        total_errors += 1

    for ci in cis:
        cid = ci.get("intent_id", "?")
        violations = validate_intent_ci(ci)
        ec = sum(1 for v in violations if v.severity == Violation.SEVERITY_ERROR)
        wc = sum(1 for v in violations if v.severity == Violation.SEVERITY_WARNING)

        fc = 0
        if auto_fix:
            fc = apply_fixes(ci, violations)
            total_fixed += fc

        total_errors += ec
        total_warnings += wc

        result = {
            "target": cid,
            "target_type": "change_intent",
            "violations": [v.to_dict() for v in violations],
            "error_count": ec,
            "warning_count": wc,
        }
        if auto_fix:
            result["fixed_count"] = fc
        if ec > 0:
            result["retry_instruction"] = _build_intent_retry_instruction(cid, violations)
        results.append(result)

    # 校验 hunks[]
    hunks = data.get("hunks", [])
    if not hunks:
        results.append({
            "target": "hunks",
            "target_type": "structure",
            "violations": [Violation(
                "hunks", "REQUIRED",
                "hunks 数组缺失或为空",
                severity=Violation.SEVERITY_ERROR
            ).to_dict()],
            "error_count": 1,
            "warning_count": 0,
        })
        total_errors += 1

    for hunk in hunks:
        hid = hunk.get("hunk_id", "?")
        violations = validate_intent_hunk(hunk)
        ec = sum(1 for v in violations if v.severity == Violation.SEVERITY_ERROR)
        wc = sum(1 for v in violations if v.severity == Violation.SEVERITY_WARNING)

        fc = 0
        if auto_fix:
            fc = apply_fixes(hunk, violations)
            total_fixed += fc

        total_errors += ec
        total_warnings += wc

        result = {
            "target": hid,
            "target_type": "hunk",
            "violations": [v.to_dict() for v in violations],
            "error_count": ec,
            "warning_count": wc,
        }
        if auto_fix:
            result["fixed_count"] = fc
        if ec > 0:
            result["retry_instruction"] = _build_intent_retry_instruction(hid, violations)
        results.append(result)

    # 9 项跨 CI 后置校验
    cross_violations = validate_intent_cross_checks(data, hunk_list, pre_cluster)
    if cross_violations:
        ec = sum(1 for v in cross_violations if v.severity == Violation.SEVERITY_ERROR)
        wc = sum(1 for v in cross_violations if v.severity == Violation.SEVERITY_WARNING)
        total_errors += ec
        total_warnings += wc
        results.append({
            "target": "cross_check",
            "target_type": "cross_check",
            "violations": [v.to_dict() for v in cross_violations],
            "error_count": ec,
            "warning_count": wc,
        })

    passed = sum(1 for r in results if r["error_count"] == 0)
    failed = sum(1 for r in results if r["error_count"] > 0)

    summary = {
        "total_targets": len(results),
        "passed": passed,
        "failed": failed,
        "total_errors": total_errors,
        "total_warnings": total_warnings,
    }
    if auto_fix:
        summary["total_auto_fixed"] = total_fixed

    # ── 对齐 references/subagent-intent.md 规格的顶层 warnings[] / auto_fixes[] 结构 ──
    # warnings：所有 severity=warning 的 violation 平铺为带 target 上下文的条目
    # auto_fixes：所有已实际应用修复（auto_fix=True 且 fixed_count>0 的 target）的修复记录
    warnings = []
    auto_fixes = []
    for r in results:
        target = r.get("target")
        target_type = r.get("target_type")
        for v in r.get("violations", []):
            if v.get("severity") == Violation.SEVERITY_WARNING:
                warnings.append({
                    "target": target,
                    "target_type": target_type,
                    "rule": v.get("rule"),
                    "field": v.get("field"),
                    "message": v.get("message"),
                })
        if auto_fix and r.get("fixed_count", 0) > 0:
            for v in r.get("violations", []):
                if v.get("auto_fixable") and "fix_value" in v:
                    auto_fixes.append({
                        "target": target,
                        "target_type": target_type,
                        "rule": v.get("rule"),
                        "field": v.get("field"),
                        "fix_value": v.get("fix_value"),
                    })

    validation = {"warnings": warnings, "auto_fixes": auto_fixes}

    return results, summary, validation


# ══════════════════════════════════════════════════════════════════════════════
# 6. 自动修复
# ══════════════════════════════════════════════════════════════════════════════

def apply_fixes(obj: dict, violations: list) -> int:
    """对可自动修复的 violations 进行修复，返回修复数量。"""
    fix_count = 0
    for v in violations:
        if not v.auto_fixable:
            continue

        path = v.field
        m_ec = re.match(r"evidence_chain\[(\d+)\]\.(.+)", path)
        if m_ec:
            idx = int(m_ec.group(1))
            sub_field = m_ec.group(2)
            ec = obj.get("evidence_chain", [])
            if idx < len(ec) and isinstance(ec[idx], dict):
                ec[idx][sub_field] = v.fix_value
                fix_count += 1
        elif "." in path:
            parts = path.split(".", 1)
            parent = obj.get(parts[0])
            if isinstance(parent, dict):
                parent[parts[1]] = v.fix_value
                fix_count += 1
        else:
            obj[path] = v.fix_value
            fix_count += 1

    return fix_count


# ══════════════════════════════════════════════════════════════════════════════
# 6b. D-xx → US-xx 一致性校验（design.md 交叉校验）
# ══════════════════════════════════════════════════════════════════════════════

_DXX_PATTERN = re.compile(r'(D-\d+)')
_US_PATTERN = re.compile(r'(US-\d+)')


def parse_design_us_map(design_md_path: str) -> dict:
    """Parse design.md to extract D-xx → [US-xx] mapping.

    Reads the **对应用户故事**：US-xx field from each D-xx section.
    Returns {D-xx: [US-01, US-04, ...]} or {} if file not found.
    """
    if not design_md_path or not os.path.isfile(design_md_path):
        return {}

    with open(design_md_path, encoding="utf-8", errors="replace") as f:
        content = f.read()

    dxx_pattern = re.compile(
        r'^(?:#{1,6}\s+)?(?:\*\*)?(D-\d+)(?:\*\*)?\s*[:：]?\s*(.+)?$',
        re.MULTILINE
    )
    us_line_pattern = re.compile(
        r'\*\*对应用户故事\*\*[：:]\s*(.+?)(?:\n\s*\n|\n\*\*|\n###|\n---|\Z)',
        re.DOTALL
    )

    matches = list(dxx_pattern.finditer(content))
    mapping = {}
    for i, m in enumerate(matches):
        design_id = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        section = content[start:end]
        us_match = us_line_pattern.search(section)
        if us_match:
            us_ids = _US_PATTERN.findall(us_match.group(1))
            if us_ids:
                mapping[design_id] = us_ids
    return mapping


def validate_us_consistency(intent: dict, design_us_map: dict) -> list:
    """Cross-check evidence_chain US-xx references against design.md mapping.

    For each evidence_chain step where artifact is design.md, extract D-xx.
    For upstream steps where upstream_artifact is requirement.md, extract US-xx.
    Verify US-xx matches the D-xx → US-xx mapping from design.md.

    Returns Violation list (warnings only).
    """
    if not design_us_map:
        return []

    violations = []
    chain = intent.get("evidence_chain", [])
    if not isinstance(chain, list):
        return []

    # Step 1: Find D-xx referenced in design.md steps
    referenced_dxx = set()
    for step in chain:
        if not isinstance(step, dict):
            continue
        artifact = step.get("artifact", "") or ""
        if "design" in artifact.lower():
            for field in ("finding", "artifact_snippet"):
                text = step.get(field, "") or ""
                referenced_dxx.update(_DXX_PATTERN.findall(text))

    if not referenced_dxx:
        return []

    # Step 2: Find US-xx referenced in requirement.md steps (upstream)
    referenced_us = set()
    for step in chain:
        if not isinstance(step, dict):
            continue
        # Check upstream_artifact (N4 step tracing to requirement.md)
        upstream_art = step.get("upstream_artifact", "") or ""
        if "requirement" in upstream_art.lower():
            for field in ("upstream_finding", "upstream_snippet"):
                text = step.get(field, "") or ""
                referenced_us.update(_US_PATTERN.findall(text))
        # Also check artifact itself (N3 step with artifact=requirement.md)
        artifact = step.get("artifact", "") or ""
        if "requirement" in artifact.lower():
            for field in ("finding", "artifact_snippet"):
                text = step.get(field, "") or ""
                referenced_us.update(_US_PATTERN.findall(text))

    if not referenced_us:
        return []

    # Step 3: Cross-check — do referenced US-xx appear in the design.md mapping?
    expected_us = set()
    unmatched_dxx = []
    for dxx in referenced_dxx:
        us_list = design_us_map.get(dxx)
        if us_list:
            expected_us.update(us_list)
        else:
            unmatched_dxx.append(dxx)

    if not expected_us:
        # Design.md has no US mapping for the referenced D-xx — can't validate
        return []

    # Find US-xx in evidence_chain that are NOT in design.md's mapping
    mismatched_us = referenced_us - expected_us
    if mismatched_us:
        violations.append(Violation(
            "evidence_chain.us_consistency", "US_MISMATCH",
            f"证据链引用的用户故事 {sorted(mismatched_us)} 与 design.md 中 D-xx "
            f"({sorted(referenced_dxx)}) 的「对应用户故事」字段不匹配。"
            f"design.md 中 D-xx 对应的用户故事为: {sorted(expected_us)}。"
            f"请检查 SubAgent 是否正确读取了 design.md 的 **对应用户故事** 字段。",
            current_value=sorted(mismatched_us),
            expected=sorted(expected_us),
            severity=Violation.SEVERITY_WARNING,
        ))

    return violations


# ══════════════════════════════════════════════════════════════════════════════
# 7. SubAgent-Attribution 批量校验
# ══════════════════════════════════════════════════════════════════════════════

def validate_all_attribution_fragments(frag_dir: str, schema: dict,
                                        auto_fix: bool = False,
                                        design_us_map: dict = None):
    """
    校验 frag_dir 下所有 SubAgent-Attribution intent fragment。

    返回:
      results: [{intent_id, file, violations, error_count, warning_count}]
      summary: {total, passed, failed, total_errors, total_warnings}
    """
    results = []
    total_errors = 0
    total_warnings = 0
    total_fixed = 0
    total = 0
    passed = 0
    failed = 0

    skip_basenames = {"validation-report.json", "report.json"}
    for frag_path in sorted(glob.glob(os.path.join(frag_dir, "*.json"))):
        if os.path.basename(frag_path) in skip_basenames:
            continue
        with open(frag_path, encoding="utf-8") as f:
            data = json.load(f)

        intents = []
        if isinstance(data, dict) and "intent_id" in data:
            intents = [data]
        elif isinstance(data, dict) and "intents" in data:
            intents = data.get("intents", [])

        modified = False
        for intent in intents:
            total += 1
            violations = validate_attribution_intent(intent, schema)

            # US-xx consistency cross-check against design.md
            if design_us_map:
                violations.extend(validate_us_consistency(intent, design_us_map))

            error_count = sum(1 for v in violations if v.severity == Violation.SEVERITY_ERROR)
            warning_count = sum(1 for v in violations if v.severity == Violation.SEVERITY_WARNING)
            fixed_count = 0

            if auto_fix:
                fixed_count = apply_fixes(intent, violations)
                if fixed_count > 0:
                    modified = True
                    total_fixed += fixed_count
                # 已自动修复的 error 不计入 remaining error_count
                fixed_errors = sum(1 for v in violations
                                   if v.severity == Violation.SEVERITY_ERROR and v.auto_fixable)
                error_count = max(0, error_count - fixed_errors)

            total_errors += error_count
            total_warnings += warning_count

            iid = intent.get("intent_id", "?")
            result = {
                "intent_id": iid,
                "file": os.path.basename(frag_path),
                "violations": [v.to_dict() for v in violations],
                "error_count": error_count,
                "warning_count": warning_count,
            }
            if auto_fix:
                result["fixed_count"] = fixed_count

            if error_count > 0:
                failed += 1
                result["retry_instruction"] = _build_attribution_retry_instruction(
                    iid, violations, schema
                )
            else:
                passed += 1

            results.append(result)

        if auto_fix and modified:
            with open(frag_path, "w", encoding="utf-8") as f:
                if isinstance(data, dict) and "intent_id" in data:
                    json.dump(intents[0], f, ensure_ascii=False, indent=2)
                else:
                    json.dump(data, f, ensure_ascii=False, indent=2)

    summary = {
        "total_intents": total,
        "passed": passed,
        "failed": failed,
        "total_errors": total_errors,
        "total_warnings": total_warnings,
    }
    if auto_fix:
        summary["total_auto_fixed"] = total_fixed

    return results, summary


# ══════════════════════════════════════════════════════════════════════════════
# 8. 重试指令构建
# ══════════════════════════════════════════════════════════════════════════════

def _build_attribution_retry_instruction(intent_id: str, violations: list,
                                          schema: dict) -> str:
    """为 SubAgent-Attribution 校验失败构建结构化重试指令。"""
    errors = [v for v in violations if v.severity == Violation.SEVERITY_ERROR]
    if not errors:
        return ""

    lines = [
        f"[校验失败] Intent {intent_id} 有 {len(errors)} 个错误需要修正：",
        "",
    ]

    for i, v in enumerate(errors, 1):
        lines.append(f"  {i}. [{v.rule}] {v.message}")
        if v.current_value is not None:
            lines.append(f"     当前值: {v.current_value}")
        if v.expected is not None:
            expected_str = v.expected
            if isinstance(expected_str, list) and len(expected_str) > 10:
                expected_str = str(expected_str[:10]) + f"... (共{len(v.expected)}个)"
            lines.append(f"     合法值: {expected_str}")

    stage_mismatch = any(v.rule == "STAGE_MISMATCH" for v in errors)
    if stage_mismatch:
        lines.append("")
        lines.append("  [核心约束提醒] problem_type 的 P-code 前缀必须与 first_cause_stage 匹配：")
        lines.append("    N5 → P5-1 ~ P5-3")
        lines.append("    N4 → P4-1 ~ P4-14")
        lines.append("    N3 → P3-1 ~ P3-10")
        lines.append("    N2 → P2-1 ~ P2-5")
        lines.append("    N1 → P1-1 ~ P1-3")
        lines.append("  请重新判定首因阶段或重新选择该阶段的 P-code。")

    bva_conflict = any(v.rule == "BVA_CONSISTENT_NO_AI_DEV" for v in errors)
    if bva_conflict:
        lines.append("")
        lines.append("  [核心约束提醒] before_vs_artifact='consistent' 时，")
        lines.append("  AI 代码忠实遵循了产物，问题根因在产物本身，")
        lines.append("  first_cause_nature 不可为 'ai_deviation'，应为 'product_defect'。")

    # 穿透完整性提醒
    penetration_rules = {"PENETRATION_INCOMPLETE", "PENETRATION_SHALLOW",
                         "PENETRATION_STOPPED_AT_FIRST_CAUSE"}
    has_penetration = any(v.rule in penetration_rules for v in errors)
    if has_penetration:
        lines.append("")
        lines.append("  [穿透规则提醒] 产物缺陷类（product_defect）的穿透不应在发现缺陷层停止：")
        lines.append("    - N4 发现设计遗漏 → 必须继续穿透到 N3 检查需求是否正确")
        lines.append("    - N4 设计遗漏（P4-2/P4-3/P4-4）含遗漏语义 → 继续穿透到 N2 检查 current-state.md")
        lines.append("    - N3 发现需求缺陷 → 必须继续穿透到 N2 检查现状梳理")
        lines.append("    - 产物缺陷的穿透应持续到信号充足层（某层 A✓B✓），不应在首因层就停止")
        lines.append("  请从当前首因层继续向上游穿透，直到找到信号充足层或最上游独立缺陷源。")

    # 证据质量提醒
    evidence_rules = {"FIRST_CAUSE_NO_EVIDENCE", "PRODUCT_DEFECT_NO_UPSTREAM"}
    has_evidence = any(v.rule in evidence_rules for v in errors)
    if has_evidence:
        lines.append("")
        lines.append("  [证据规则提醒] 首因层归因结论必须有产物证据支撑：")
        lines.append("    - artifact_snippet：必须引用首因层产物的具体文本片段（如 design.md D-07 的原文）")
        lines.append("    - upstream_artifact + upstream_finding：product_defect 类型必须标明上游参照")
        lines.append("      （如 requirement.md 哪条 AC 要求了该功能但 design.md 未设计）")
        lines.append("  请补充首因层的产物证据后重新输出。")

    lines.append("")
    lines.append("请修正上述错误后重新输出。")

    return "\n".join(lines)


def _build_intent_retry_instruction(target_id: str, violations: list) -> str:
    """为 SubAgent-Intent 校验失败构建结构化重试指令。"""
    errors = [v for v in violations if v.severity == Violation.SEVERITY_ERROR]
    if not errors:
        return ""

    lines = [
        f"[校验失败] {target_id} 有 {len(errors)} 个错误需要修正：",
        "",
    ]

    for i, v in enumerate(errors, 1):
        lines.append(f"  {i}. [{v.rule}] {v.message}")
        if v.current_value is not None:
            lines.append(f"     当前值: {v.current_value}")
        if v.expected is not None:
            expected_str = v.expected
            if isinstance(expected_str, list) and len(expected_str) > 10:
                expected_str = str(expected_str[:10]) + f"... (共{len(v.expected)}个)"
            lines.append(f"     合法值: {expected_str}")

    lines.append("")
    lines.append("请修正上述错误后重新输出。")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# 9. 主入口
# ══════════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(
        description="SubAgent 输出后处理校验（统一入口）"
    )
    ap.add_argument("--mode", required=True, choices=["attribution", "intent"],
                    help="校验模式: attribution=SubAgent-Attribution, intent=SubAgent-Intent")
    ap.add_argument("--frag-dir", default=None,
                    help="[attribution] intent-fragments 目录")
    ap.add_argument("--config-dir", default=None,
                    help="[attribution] config 目录（含 problem-types.json）")
    ap.add_argument("--change-intents", default=None,
                    help="[intent] change-intents.json 路径")
    ap.add_argument("--hunk-list", default=None,
                    help="[intent] hunk-list.json 路径（可选，启用交叉校验）")
    ap.add_argument("--pre-cluster", default=None,
                    help="[intent] pre-cluster-hints.json 路径（可选）")
    ap.add_argument("--fix", action="store_true",
                    help="自动修复可确定性修复的字段")
    ap.add_argument("--output", default=None,
                    help="校验报告输出路径")
    ap.add_argument("--design-md", default=None,
                    help="[attribution] design.md 路径（可选，启用 D-xx → US-xx 一致性校验）")
    args = ap.parse_args()

    if args.mode == "attribution":
        if not args.frag_dir or not args.config_dir:
            ap.error("--mode=attribution 需要 --frag-dir 和 --config-dir")

        schema = load_validation_schema(args.config_dir)
        print(f"[validate-attribution] Loaded schema: {len(schema['valid_pcodes'])} P-codes, "
              f"{len(schema['valid_rc_variants'])} variants", file=sys.stderr)

        # Parse design.md for D-xx → US-xx mapping if provided
        design_us_map = {}
        if args.design_md:
            design_us_map = parse_design_us_map(args.design_md)
            print(f"[validate-attribution] Parsed design.md: {len(design_us_map)} D-xx → US-xx mappings",
                  file=sys.stderr)

        results, summary = validate_all_attribution_fragments(
            args.frag_dir, schema, auto_fix=args.fix,
            design_us_map=design_us_map
        )

        output_path = args.output or os.path.join(
            os.path.dirname(args.frag_dir.rstrip("/")),
            "validation-report.json"
        )

        report = {"mode": "attribution", "summary": summary, "intents": results}

    elif args.mode == "intent":
        if not args.change_intents:
            ap.error("--mode=intent 需要 --change-intents")

        with open(args.change_intents, encoding="utf-8") as f:
            data = json.load(f)

        hunk_list = None
        if args.hunk_list:
            with open(args.hunk_list, encoding="utf-8") as f:
                hunk_list = json.load(f)

        pre_cluster = None
        if args.pre_cluster:
            with open(args.pre_cluster, encoding="utf-8") as f:
                pre_cluster = json.load(f)

        results, summary, validation = validate_change_intents_file(
            data, hunk_list, pre_cluster, auto_fix=args.fix
        )

        # 将规格要求的顶层 validation: {warnings[], auto_fixes[]} 写回 change-intents.json，
        # 与 references/subagent-intent.md 输出样例中的 "validation" 字段保持一致。
        data["validation"] = validation

        # 自动修复或写入 validation 字段后均需写回
        with open(args.change_intents, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        output_path = args.output or os.path.join(
            os.path.dirname(args.change_intents),
            "validation-report.json"
        )

        # 顶层同时提供规格化 warnings[] / auto_fixes[]（与 change-intents.json 里的 validation 一致）
        # 以及详细的 results/summary（供人工/主 Agent 调试定位）。
        report = {
            "mode": "intent",
            "summary": summary,
            "warnings": validation["warnings"],
            "auto_fixes": validation["auto_fixes"],
            "targets": results,
        }

    else:
        ap.error(f"未知 mode: {args.mode}")
        return 1

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # 打印摘要
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"SubAgent-{args.mode.title()} 输出校验报告", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    if args.mode == "attribution":
        print(f"总计: {summary['total_intents']} intents", file=sys.stderr)
    else:
        print(f"总计: {summary['total_targets']} 校验目标（CI + hunk + cross_check）", file=sys.stderr)

    print(f"通过: {summary['passed']}  失败: {summary['failed']}", file=sys.stderr)
    print(f"错误: {summary['total_errors']}  警告: {summary['total_warnings']}",
          file=sys.stderr)
    if args.fix:
        print(f"自动修复: {summary.get('total_auto_fixed', 0)}", file=sys.stderr)

    if summary["failed"] > 0:
        items = report.get("intents", report.get("targets", []))
        print(f"\n需要 SubAgent 重新执行的目标:", file=sys.stderr)
        for r in items:
            if r.get("error_count", 0) > 0:
                target_name = r.get("intent_id", r.get("target", "?"))
                print(f"  {target_name}: {r['error_count']} errors", file=sys.stderr)
                for v in r.get("violations", []):
                    if v.get("severity") == "error":
                        print(f"    [{v['rule']}] {v['message']}", file=sys.stderr)

    print(f"\n报告已写入: {output_path}", file=sys.stderr)

    return 1 if summary["failed"] > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())