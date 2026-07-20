#!/usr/bin/env python3
"""
Post-aggregation verification script.
Checks attribution-result.json against SKILL.md quality constraints.
Exit code 0 = all checks passed; non-zero = violations found.
Agent should run this after aggregate_stats.py and before render_report.py.

Verifies intent-level output format (intents[]).
Checks fields: first_cause_nature, attribution_direction, additional_tags.
Validates evidence_chain structure: 首因层(full) + 传导层 + 信号充足层(one-line).
Allows null upstream fields for signal-sufficient layers.
Checks before_vs_artifact in N5/N4 layers (逆向归因).
Validates problem_type against 37 types (P5-1~4, P4-1~14, P3-1~11, P2-1~5, P1-1~3; includes P4-14, P5-4, P3-11).

Usage:
  python3 verify_attribution.py --input /tmp/agcr-{run_id}/attribution-result.json
"""
import argparse
import json
import os
import sys


# Stage ordering for evidence chain completeness check
STAGE_ORDER = [
    "N5 编码计划", "N4 技术方案",
    "N3 需求澄清", "N2 现状梳理", "N1 项目初始化",
]

# P-code → full stage name mapping (normalize_intent() converts N4→P4)
P_TO_FULL = {
    "P5": "N5 编码计划", "P4": "N4 技术方案", "P3": "N3 需求澄清",
    "P2": "N2 现状梳理", "P1": "N1 项目初始化",
}

def _normalize_stage_for_verify(s):
    """Normalize stage to full name for comparison. Accepts P4, N4, 'N4 技术方案'."""
    if not s:
        return ""
    if s in STAGE_ORDER:
        return s
    if s in P_TO_FULL:
        return P_TO_FULL[s]
    # Try N-code prefix
    for full in STAGE_ORDER:
        if s == full.split()[0]:
            return full
    return s

# Stages that should have upstream comparison in evidence_chain
UPSTREAM_MAP = {
    "N5 编码计划": "N4 技术方案",
    "N4 技术方案": "N3 需求澄清",
    "N3 需求澄清": "N2 现状梳理",
    "N2 现状梳理": "N1 项目初始化",
}

# Valid problem types (37 types: P5-1~4, P4-1~14, P3-1~11, P2-1~5, P1-1~3)
VALID_PROBLEM_TYPES = set()
for p, max_n in [("P5", 4), ("P4", 14), ("P3", 11), ("P2", 5), ("P1", 3)]:
    for i in range(1, max_n + 1):
        VALID_PROBLEM_TYPES.add(f"{p}-{i}")

VALID_ROOT_CAUSES = {"R1", "R2", "R3", "R4", "R5", None}
VALID_CONFIDENCE = {"high", "medium", "low"}
VALID_DIFF_NATURE = {"corrective", "additive", "subtractive", "refining"}
VALID_FIRST_CAUSE_NATURE = {"product_defect", "ai_deviation", "upstream_propagation", "prd_quality"}
VALID_ATTRIBUTION_DIRECTION = {"artifact_defect", "ai_execution", None}

# Stages where before_vs_artifact is mandatory
BEFORE_VS_ARTIFACT_STAGES = {"N5 编码计划", "N4 技术方案"}


class CheckResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.warnings = 0
        self.failures = []
        self.warns = []

    def ok(self, msg):
        self.passed += 1

    def fail(self, msg):
        self.failed += 1
        self.failures.append(msg)

    def warn(self, msg):
        self.warnings += 1
        self.warns.append(msg)

    def exit_code(self):
        return 0 if self.failed == 0 else 1

    def report(self):
        lines = []
        lines.append(f"=== Verification Report ===")
        lines.append(f"Passed: {self.passed}  Failed: {self.failed}  Warnings: {self.warnings}")
        if self.failures:
            lines.append("\nFAILURES:")
            for f in self.failures:
                lines.append(f"  [FAIL] {f}")
        if self.warns:
            lines.append("\nWARNINGS:")
            for w in self.warns:
                lines.append(f"  [WARN] {w}")
        if self.failed == 0 and self.warnings == 0:
            lines.append("\nAll checks passed!")
        return "\n".join(lines)


def verify(data, cr):
    """Run all verification checks (intent-level)."""

    # 1. AGCR <= 1.0
    agcr = data.get("calculated_agcr", {}).get("agcr")
    if agcr is not None:
        if agcr <= 1.0:
            cr.ok(f"AGCR <= 1.0 (value={agcr:.4f})")
        else:
            cr.fail(f"AGCR > 1.0 (value={agcr:.4f}) — formula may be wrong")
    else:
        cr.fail("AGCR is null — base-to-target-final.diff is required (subagent-diff.md marks it as 必需). Check that the diff subagent generated base-to-target-final.diff for all repos.")

    # 1b. abandonment_rate <= 1.0
    abn = data.get("calculated_agcr", {}).get("abandonment_rate")
    if abn is not None:
        if abn <= 1.0:
            cr.ok(f"abandonment_rate <= 1.0 (value={abn:.4f})")
        else:
            cr.fail(f"abandonment_rate > 1.0 (value={abn:.4f}) — clamping may have failed")
    else:
        cr.warn("abandonment_rate is null (possibly empty diff)")

    # 2. Check intents[] exists (primary data structure)
    intents = data.get("intents", [])
    if not intents:
        cr.fail("intents[] is empty or missing (requires intent-level attribution)")
    else:
        cr.ok(f"intents[] has {len(intents)} entries")

    # 2b. Check hunks[] still exists (for metadata reference)
    hunks = data.get("hunks", [])
    if not hunks:
        cr.warn("hunks[] is empty (hunk-level metadata may be missing)")
    else:
        cr.ok(f"hunks[] has {len(hunks)} entries")

    # 3. Each intent has required fields
    required_intent_fields = [
        "intent_id", "diff_nature", "first_cause_stage",
        "problem_type", "root_cause", "confidence",
        "evidence_chain", "direct_cause", "propagation_path",
        "hunk_ids",
    ]
    for intent in intents:
        iid = intent.get("intent_id", "?")
        for field in required_intent_fields:
            val = intent.get(field)
            # root_cause allows null (P1-3 external input)
            if field == "root_cause" and val is None:
                continue
            # hunk_ids allows empty list but key must exist
            if field == "hunk_ids" and val is not None and isinstance(val, list):
                continue
            if not val and val != 0:
                cr.fail(f"{iid}: missing required field '{field}'")

    # 4. problem_type is valid (35 types)
    for intent in intents:
        iid = intent.get("intent_id", "?")
        pt = intent.get("problem_type", "")
        if pt and pt not in VALID_PROBLEM_TYPES:
            cr.fail(f"{iid}: invalid problem_type '{pt}' (must be one of 35 valid types)")
        elif pt:
            cr.ok(f"{iid}: problem_type={pt}")

    # 5. root_cause is valid (R1-R5 or null for P1-3)
    for intent in intents:
        iid = intent.get("intent_id", "?")
        rc = intent.get("root_cause")
        if rc not in VALID_ROOT_CAUSES:
            cr.fail(f"{iid}: invalid root_cause '{rc}' (must be R1-R5 or null for P1-3)")

    # 6. confidence is valid
    for intent in intents:
        iid = intent.get("intent_id", "?")
        conf = intent.get("confidence", "")
        if conf and conf not in VALID_CONFIDENCE:
            cr.fail(f"{iid}: invalid confidence '{conf}'")

    # 7. diff_nature is valid
    for intent in intents:
        iid = intent.get("intent_id", "?")
        dn = intent.get("diff_nature", "")
        if dn and dn not in VALID_DIFF_NATURE:
            cr.fail(f"{iid}: invalid diff_nature '{dn}' (must be corrective/additive/subtractive/refining)")

    # 8. first_cause_nature is valid
    for intent in intents:
        iid = intent.get("intent_id", "?")
        fcn = intent.get("first_cause_nature", "")
        if fcn and fcn not in VALID_FIRST_CAUSE_NATURE:
            cr.fail(f"{iid}: invalid first_cause_nature '{fcn}'")

    # 9. attribution_direction is valid
    for intent in intents:
        iid = intent.get("intent_id", "?")
        ad = intent.get("attribution_direction")
        if ad and ad not in VALID_ATTRIBUTION_DIRECTION:
            cr.fail(f"{iid}: invalid attribution_direction '{ad}'")

    # 10. Evidence chain completeness and structure (首因层 + 传导层 + 信号充足层)
    VALID_STAGE_NAMES = set(STAGE_ORDER)
    for intent in intents:
        iid = intent.get("intent_id", "?")
        chain = intent.get("evidence_chain", [])
        if not chain:
            cr.fail(f"{iid}: evidence_chain is empty")
            continue

        chain_stages = [s.get("stage", "") for s in chain]
        # Normalize first_cause_stage: P4 → "N4 技术方案" for comparison
        first_cause_raw = intent.get("first_cause_stage", "")
        first_cause = _normalize_stage_for_verify(first_cause_raw)

        # 10a. Check stage names use standard full names
        for s in chain_stages:
            s_norm = _normalize_stage_for_verify(s)
            if s and s_norm not in VALID_STAGE_NAMES:
                cr.fail(f"{iid}: non-standard stage name '{s}' in evidence_chain")

        if not first_cause_raw:
            cr.fail(f"{iid}: first_cause_stage is empty")
            continue

        # 10b. Check first_cause_stage uses standard full name (accept P-code too)
        if first_cause not in VALID_STAGE_NAMES:
            cr.fail(f"{iid}: first_cause_stage '{first_cause_raw}' is not a standard name")

        # 10c. Check N5 is present (must start from N5)
        if "N5 编码计划" not in chain_stages:
            cr.fail(f"{iid}: evidence_chain missing N5 编码计划 (must start from N5)")
            continue

        # 10d. Check no skipping between N5 and first_cause
        try:
            n5_idx = STAGE_ORDER.index("N5 编码计划")
            fc_idx = STAGE_ORDER.index(first_cause)
        except ValueError:
            cr.warn(f"{iid}: first_cause_stage '{first_cause_raw}' not in known stages")
            continue

        expected_stages = STAGE_ORDER[n5_idx:fc_idx + 1]
        missing_stages = [s for s in expected_stages if s not in chain_stages]
        if missing_stages:
            cr.fail(f"{iid}: evidence_chain missing stages: {missing_stages}")
        else:
            cr.ok(f"{iid}: evidence_chain complete (N5→{first_cause})")

    # 11. Evidence chain record fields
    for intent in intents:
        iid = intent.get("intent_id", "?")
        first_cause = intent.get("first_cause_stage", "")
        chain = intent.get("evidence_chain", [])

        for step in chain:
            stage = step.get("stage", "?")

            # finding is always required
            if not step.get("finding"):
                cr.fail(f"{iid} [{stage}]: finding is empty")

            # 首因层: must have full fields
            if stage == first_cause:
                if not step.get("artifact"):
                    cr.warn(f"{iid} [{stage}]: artifact field is empty (首因层 should have artifact)")
                if not step.get("upstream_artifact"):
                    cr.fail(f"{iid} [{stage}]: missing upstream_artifact (mandatory for 首因层)")
                if not step.get("upstream_finding"):
                    cr.fail(f"{iid} [{stage}]: missing upstream_finding (mandatory for 首因层)")
                if not step.get("artifact_snippet"):
                    cr.fail(f"{iid} [{stage}]: missing artifact_snippet (首因层 must quote evidence)")

            # 信号充足层 (穿透终止层): upstream fields should be null
            # Detect by finding containing "信号充足"
            elif step.get("finding", "").startswith("信号充足"):
                if step.get("upstream_artifact") is not None:
                    cr.warn(f"{iid} [{stage}]: 信号充足层 should have null upstream_artifact")
                if step.get("upstream_finding") is not None:
                    cr.warn(f"{iid} [{stage}]: 信号充足层 should have null upstream_finding")

            # 传导层: should have upstream fields pointing to 首因层
            elif stage != first_cause and stage != "N1 项目初始化":
                if not step.get("upstream_artifact"):
                    cr.fail(f"{iid} [{stage}]: missing upstream_artifact (required for 传导层)")
                if not step.get("upstream_finding"):
                    cr.fail(f"{iid} [{stage}]: missing upstream_finding (required for 传导层)")

    # 12. before_vs_artifact in N5/N4 layers (逆向归因)
    for intent in intents:
        iid = intent.get("intent_id", "?")
        chain = intent.get("evidence_chain", [])
        for step in chain:
            stage = step.get("stage", "")
            if stage in BEFORE_VS_ARTIFACT_STAGES:
                bva = step.get("before_vs_artifact")
                if bva is None:
                    # Check if this is a 信号充足层 (no before_vs_artifact needed)
                    if not step.get("finding", "").startswith("信号充足"):
                        cr.fail(f"{iid} [{stage}]: missing before_vs_artifact (required for N5/N4 layers in 逆向归因)")

    # 13. Required extra fields on each intent
    required_extra_fields = [
        "propagation_path", "knowledge_check",
        "artifact_manifestation", "root_cause_verdict",
    ]
    for intent in intents:
        iid = intent.get("intent_id", "?")
        for field in required_extra_fields:
            if not intent.get(field):
                if field == "propagation_path":
                    cr.fail(f"{iid}: missing required field '{field}'")
                else:
                    cr.warn(f"{iid}: missing recommended field '{field}'")

    # 14. hunk_ids is non-empty for non-excluded intents
    for intent in intents:
        iid = intent.get("intent_id", "?")
        hunk_ids = intent.get("hunk_ids", [])
        if not hunk_ids:
            cr.warn(f"{iid}: hunk_ids is empty (intent has no associated hunks)")

    # 15. FeatureChange aggregated_attribution exists
    for fc in data.get("feature_changes", []):
        agg = fc.get("aggregated_attribution", {})
        if not agg:
            cr.warn(f"{fc.get('feature_change_id', '?')}: missing aggregated_attribution")
        elif not agg.get("primary_category"):
            cr.warn(f"{fc.get('feature_change_id', '?')}: aggregated_attribution.primary_category is empty")

    # 16. Excluded hunks have exclude_reason
    excluded = [h for h in data.get("hunks", []) if h.get("excluded")]
    valid_reasons = {
        "whitespace", "auto_import", "auto_generated",
        "test_file", "doc_only", "config_only", "merge_master",
    }
    for h in excluded:
        reason = h.get("exclude_reason")
        if not reason:
            cr.fail(f"{h.get('hunk_id', '?')}: excluded but no exclude_reason")
        elif reason not in valid_reasons:
            hid = h.get('hunk_id', h.get('file', '?'))
            cr.warn(f"{hid}: unknown exclude_reason '{reason}'")

    # 17. outputs fields populated (after S3 upload)
    outputs = data.get("outputs", {})
    if not outputs.get("report_html_s3_url"):
        cr.warn("outputs.report_html_s3_url is empty (S3 upload may not have run yet)")
    if not outputs.get("result_json_s3_url"):
        cr.warn("outputs.result_json_s3_url is empty (S3 upload may not have run yet)")

    # 18. render_report.py compatibility: repos[] has commit fields
    for r in data.get("repos", []):
        if not r.get("base_commit"):
            cr.warn(f"repos[]: {r.get('repo', '?')} missing base_commit")
        if not r.get("one_shot_commit"):
            cr.warn(f"repos[]: {r.get('repo', '?')} missing one_shot_commit")
        if not r.get("target_final_commit"):
            cr.warn(f"repos[]: {r.get('repo', '?')} missing target_final_commit")

    # 19. diff_overview populated with commit counts
    diff_ov = data.get("diff_overview", [])
    if not diff_ov:
        cr.warn("diff_overview is empty (render_report.py will show placeholder rows)")
    else:
        for ov in diff_ov:
            repo = ov.get("repo", "?")
            if "b2o_commits" not in ov:
                cr.warn(f"diff_overview[{repo}] missing b2o_commits (AI 编码 commit 数)")
            if "os2f_commits" not in ov:
                cr.warn(f"diff_overview[{repo}] missing os2f_commits (人工修改 commit 数)")
            if ov.get("os2f_commits") is None:
                cr.warn(f"diff_overview[{repo}] os2f_commits is null (commit-chain.json may be missing)")

    # 20. propagation_chain populated
    if not data.get("propagation_chain"):
        cr.warn("propagation_chain is empty")

    # 21. recommendations populated
    if not data.get("recommendations"):
        cr.warn("recommendations is empty")

    # 22. Summary has by_diff_nature and by_attribution_direction
    summary = data.get("summary", {})
    if not summary.get("by_diff_nature"):
        cr.warn("summary.by_diff_nature is empty")
    if not summary.get("by_attribution_direction"):
        cr.warn("summary.by_attribution_direction is empty")

    # 23. intent_groups populated (replaces hunk_groups)
    if not data.get("intent_groups"):
        cr.warn("intent_groups is empty (render_report.py §6 will show placeholder)")

    # 24. change_intent_groups field completeness
    ci_groups = data.get("change_intent_groups", [])
    if not ci_groups:
        cr.fail("change_intent_groups is empty (render_report.py §5 will show placeholder)")
    else:
        for ci in ci_groups:
            ci_id = ci.get("intent_id", "?")
            # evidence_chain non-empty
            if not ci.get("evidence_chain"):
                cr.fail(f"{ci_id}: change_intent_groups evidence_chain is empty")
            else:
                # artifact field non-empty in evidence_chain
                for step in ci["evidence_chain"]:
                    if not step.get("artifact"):
                        cr.fail(f"{ci_id} [{step.get('stage', '?')}]: artifact is empty in evidence_chain")
            # direct_cause non-empty
            if not ci.get("direct_cause"):
                cr.fail(f"{ci_id}: direct_cause is empty in change_intent_groups")
            # propagation_path non-empty
            if not ci.get("propagation_path"):
                cr.fail(f"{ci_id}: propagation_path is empty in change_intent_groups")
            # intent_description non-empty
            if not ci.get("intent_description"):
                cr.fail(f"{ci_id}: intent_description is empty in change_intent_groups")

    # 25. CI-ORPHAN should not exist
    for ci in ci_groups:
        if ci.get("intent_id") == "CI-ORPHAN":
            cr.fail("CI-ORPHAN exists — some hunks were not clustered into any Change Intent")

    # 26. key_findings structure validation
    kf = data.get("key_findings", [])
    if not kf:
        cr.fail("key_findings is empty")
    elif not isinstance(kf, list):
        cr.fail(f"key_findings should be list, got {type(kf).__name__}")
    else:
        for i, f in enumerate(kf):
            if not isinstance(f, dict):
                cr.fail(f"key_findings[{i}] is not a dict (got {type(f).__name__})")
            else:
                text = f.get("finding", "") or f.get("title", "")
                if not text:
                    cr.fail(f"key_findings[{i}]: both 'finding' and 'title' are empty")
                priority = f.get("priority", "") or f.get("severity", "")
                if not priority:
                    cr.warn(f"key_findings[{i}]: both 'priority' and 'severity' are empty")

    # 27. diff_overview hunk_count and commit counts
    for ov in data.get("diff_overview", []):
        repo_name = ov.get("repo", "?")
        if ov.get("hunk_count", 0) == 0:
            cr.warn(f"diff_overview[{repo_name}]: hunk_count is 0")
        if ov.get("b2o_commits") is None:
            cr.warn(f"diff_overview[{repo_name}]: b2o_commits is null (AI coding commit count missing)")
        if ov.get("os2f_commits") is None:
            cr.warn(f"diff_overview[{repo_name}]: os2f_commits is null (human modification commit count missing)")
        # Check commit detail lists for render_report.py r_repo_commit_details()
        if not ov.get("ai_commits"):
            cr.warn(f"diff_overview[{repo_name}]: ai_commits is empty (commit list won't render)")
        if not ov.get("human_commits"):
            cr.warn(f"diff_overview[{repo_name}]: human_commits is empty (commit list won't render)")


def main():
    ap = argparse.ArgumentParser(description="Verify attribution-result.json quality")
    ap.add_argument("--input", required=True, help="attribution-result.json path")
    args = ap.parse_args()

    with open(args.input, encoding="utf-8") as f:
        data = json.load(f)

    cr = CheckResult()
    verify(data, cr)
    report = cr.report()
    print(report)

    # Write report to file for Agent to read
    report_path = args.input.replace(".json", ".verify.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    sys.exit(cr.exit_code())


if __name__ == "__main__":
    raise SystemExit(main())
