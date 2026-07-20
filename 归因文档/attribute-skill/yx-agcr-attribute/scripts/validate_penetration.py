#!/usr/bin/env python3
"""validate_penetration.py — SubAgent-Penetration 产出校验脚本。

校验 penetration-result-{CI-xxx}.json 的字段完整性和一致性。
不通过时返回 exit code 1，主 Agent 应要求 SubAgent-Penetration 重新执行。

用法:
  python3 validate_penetration.py \\
      --frag-dir $OUTPUT_DIR/penetration-results \\
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
VALID_NATURES = {"product_defect", "ai_deviation", "prd_quality", "upstream_propagation"}
VALID_DEFECT_CATEGORIES = {"existence", "correctness", "completeness", "execution_deviation"}
VALID_DIMENSIONS = {"A", "B"}
STAGE_LAYERS = {"N5": "N5", "N4": "N4", "N3": "N3", "N2": "N2", "N1": "N1"}


class ValidationError:
    def __init__(self, severity, field, message, fixable=False):
        self.severity = severity  # "error" or "warning"
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


def validate_fragment(frag_path, config):
    """Validate a single penetration-result JSON file."""
    errors = []
    fixes = []

    with open(frag_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    intent_id = data.get("intent_id", "")
    filename = Path(frag_path).name

    # ─── Required top-level fields ────────────────────────────────────────────
    required_fields = [
        "intent_id", "first_cause_stage", "first_cause_nature",
        "first_cause_rationale", "penetration_chain",
        "checked_layers", "termination_reason"
    ]
    for field in required_fields:
        if field not in data or data[field] is None:
            errors.append(ValidationError("error", field, f"{field} is missing or null"))

    # ─── first_cause_stage validation ────────────────────────────────────────
    stage = data.get("first_cause_stage", "")
    if stage and stage not in VALID_STAGES:
        errors.append(ValidationError("error", "first_cause_stage",
            f"Invalid stage '{stage}', must be one of {VALID_STAGES}"))

    # ─── first_cause_nature validation ────────────────────────────────────────
    nature = data.get("first_cause_nature", "")
    if nature and nature not in VALID_NATURES:
        errors.append(ValidationError("error", "first_cause_nature",
            f"Invalid nature '{nature}', must be one of {VALID_NATURES}"))

    # ─── first_cause_nature vs before_vs_artifact hard gate (§2.1) ────────────
    # before_vs_artifact=consistent 意味着 AI 忠实遵循了产物，此时首因性质
    # 不可能为 ai_deviation，必须是 product_defect（产物本身有缺陷）
    chain = data.get("penetration_chain", [])
    if chain and stage:
        first_layer = None
        for layer_data in chain:
            if layer_data.get("layer") == stage:
                first_layer = layer_data
                break

        if first_layer:
            bva = first_layer.get("before_vs_artifact")
            if bva == "consistent" and nature == "ai_deviation":
                errors.append(ValidationError("error", "first_cause_nature",
                    f"before_vs_artifact='consistent' but first_cause_nature='ai_deviation' — "
                    f"AI followed the artifact, so the issue must be in the artifact itself (product_defect)"))
            # 正向校验: consistent → nature 应为 product_defect
            if bva == "consistent" and nature and nature != "product_defect" and nature != "upstream_propagation":
                errors.append(ValidationError("error", "first_cause_nature",
                    f"before_vs_artifact='consistent' but first_cause_nature='{nature}' — "
                    f"when AI followed the artifact, nature must be 'product_defect' or 'upstream_propagation'"))

    # ─── penetration_chain validation ─────────────────────────────────────────
    if not chain:
        errors.append(ValidationError("error", "penetration_chain",
            "penetration_chain is empty or missing"))
    else:
        for i, layer_data in enumerate(chain):
            layer = layer_data.get("layer", "")
            layer_prefix = f"penetration_chain[{i}] ({layer})"

            # Required per-layer fields
            if not layer:
                errors.append(ValidationError("error", f"{layer_prefix}.layer",
                    f"layer field is missing at index {i}"))

            if "has_problem" not in layer_data:
                errors.append(ValidationError("error", f"{layer_prefix}.has_problem",
                    f"has_problem is missing"))

            if not layer_data.get("finding"):
                errors.append(ValidationError("warning", f"{layer_prefix}.finding",
                    f"finding is empty"))

            # N5/N4 layers must have before_vs_artifact
            if layer in ("N5", "N4"):
                bva = layer_data.get("before_vs_artifact")
                if not bva:
                    errors.append(ValidationError("error", f"{layer_prefix}.before_vs_artifact",
                        f"before_vs_artifact is required for {layer} layer"))

            # First cause layer (has_problem=true, problem_nature != upstream_propagation)
            # must have defect_detail
            is_first_cause = (layer == stage and
                             layer_data.get("has_problem") and
                             layer_data.get("problem_nature") != "upstream_propagation")
            if is_first_cause:
                dd = layer_data.get("defect_detail")
                if not dd:
                    errors.append(ValidationError("error", f"{layer_prefix}.defect_detail",
                        "First cause layer must have defect_detail"))
                else:
                    # Validate defect_detail fields
                    if "failed_dimension" not in dd or dd["failed_dimension"] not in VALID_DIMENSIONS:
                        errors.append(ValidationError("error",
                            f"{layer_prefix}.defect_detail.failed_dimension",
                            f"failed_dimension must be one of {VALID_DIMENSIONS}"))

                    dc = dd.get("defect_category", "")
                    if dc and dc not in VALID_DEFECT_CATEGORIES:
                        errors.append(ValidationError("error",
                            f"{layer_prefix}.defect_detail.defect_category",
                            f"defect_category '{dc}' must be one of {VALID_DEFECT_CATEGORIES}"))

                    if not dd.get("defective_items"):
                        errors.append(ValidationError("warning",
                            f"{layer_prefix}.defect_detail.defective_items",
                            "defective_items is empty"))

    # ─── checked_layers consistency ───────────────────────────────────────────
    checked = data.get("checked_layers", [])
    if chain and checked:
        chain_layers = [l.get("layer") for l in chain]
        if checked != chain_layers:
            errors.append(ValidationError("warning", "checked_layers",
                f"checked_layers {checked} != chain layers {chain_layers}"))

    # ─── Auto-fixable issues ──────────────────────────────────────────────────
    # If checked_layers is missing but chain exists, auto-fill
    if not checked and chain:
        checked = [l.get("layer", "") for l in chain]
        data["checked_layers"] = checked
        fixes.append("Auto-filled checked_layers from penetration_chain")
        errors.append(ValidationError("warning", "checked_layers",
            "Auto-filled checked_layers from penetration_chain", fixable=True))

    # Write fixes if --fix
    if fixes:
        with open(frag_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    return errors, fixes


def main():
    parser = argparse.ArgumentParser(
        description="SubAgent-Penetration 产出校验脚本"
    )
    parser.add_argument("--frag-dir", required=True, help="penetration-results 目录路径")
    parser.add_argument("--config-dir", required=True, help="config 目录路径")
    parser.add_argument("--fix", action="store_true", help="自动修复可修复的问题")
    args = parser.parse_args()

    # Load config for stage validation
    config_path = Path(args.config_dir) / "problem-types.json"
    config = {}
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

    # Find all penetration-result files
    frag_pattern = str(Path(args.frag_dir) / "penetration-result-*.json")
    frag_files = sorted(glob.glob(frag_pattern))

    if not frag_files:
        # Try single file mode
        single_file = Path(args.frag_dir)
        if single_file.is_file() and single_file.suffix == ".json":
            frag_files = [str(single_file)]

    if not frag_files:
        print(json.dumps({
            "status": "warning",
            "message": f"No penetration-result files found in {args.frag_dir}"
        }, ensure_ascii=False))
        return

    all_errors = []
    all_fixes = []
    has_blocking = False

    for frag_path in frag_files:
        errors, fixes = validate_fragment(frag_path, config)
        blocking = [e for e in errors if e.severity == "error"]

        if blocking:
            has_blocking = True

        all_errors.extend([{**e.to_dict(), "file": frag_path} for e in errors])
        all_fixes.extend(fixes)

    # Output report
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
