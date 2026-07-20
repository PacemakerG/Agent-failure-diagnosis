#!/usr/bin/env python3
"""
write_attribution_db.py — Step 12 DB 写入脚本 (intent-level)

用法:
  # Step 12.1: 写入 Run 汇总行
  python3 write_attribution_db.py run \
    --result-json /tmp/agcr-{run_id}/attribution-result.json \
    --config-dir $SKILL_DIR/config \
    --base-url http://yuanxi.adp.test.sankuai.com/api/v1/observability

  # Step 12.2: 批量写入 Intent 明细（暂时禁用）
  python3 write_attribution_db.py intents \
    --result-json /tmp/agcr-{run_id}/attribution-result.json \
    --run-result-id 12345 \
    --config-dir $SKILL_DIR/config \
    --base-url http://yuanxi.adp.test.sankuai.com/api/v1/observability

注意: intent/hunk 粒度的 DB 写入暂时禁用，cmd_intents 为 no-op。
      build_intents_body 代码保留以便后续恢复。

输出: JSON 到 stdout，错误信息到 stderr。
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error


def load_config(config_dir):
    """加载 config/problem-types.json，提取标签映射。

    root_cause_variant 标签直接从 problem-types.json 的
    attribution_stages[].problem_types[].root_cause_variants[].sub_type → description
    提取，不再依赖独立的 p_sub_labels.json 文件。
    """
    pt_path = os.path.join(config_dir, "problem-types.json")
    with open(pt_path, encoding="utf-8") as f:
        cfg = json.load(f)

    issue_labels = {t["id"]: t["label"] for t in cfg.get("surface_issue_types", [])}
    r_root_cause_labels = {
        k: v["label"] if isinstance(v, dict) else v
        for k, v in cfg.get("root_causes", {}).items()
    }
    problem_type_labels = {}
    root_cause_variant_labels = {}
    for st in cfg.get("attribution_stages", []):
        for pt in st.get("problem_types", []):
            problem_type_labels[pt["id"]] = pt["label"]
            for rcv in pt.get("root_cause_variants", []):
                sub_type = rcv.get("sub_type", "")
                desc = rcv.get("description", "")
                if sub_type and desc:
                    root_cause_variant_labels[sub_type] = desc

    return issue_labels, r_root_cause_labels, problem_type_labels, root_cause_variant_labels


def fmt_pct(v):
    if v is None:
        return None
    try:
        return str(round(float(v) * 100, 1)) + "%"
    except (TypeError, ValueError):
        return None


def build_run_body(result_json_path, config_dir):
    """Step 12.1: 构建 Run 汇总行请求体 (intent-level)"""
    with open(result_json_path) as f:
        r = json.load(f)

    issue_labels, _, _, _ = load_config(config_dir)

    # Stats from intents[]
    intents = r.get("intents", [])
    stage_counts = {}
    issue_counts = {}
    for intent in intents:
        stage = intent.get("first_cause_stage")
        if stage:
            stage_counts[stage] = stage_counts.get(stage, 0) + 1
        issue_id = intent.get("surface_issue_type", "OTHER") or "OTHER"
        issue_label = issue_labels.get(issue_id, issue_id)
        issue_counts[issue_label] = issue_counts.get(issue_label, 0) + 1

    top_stage = max(stage_counts, key=stage_counts.get) if stage_counts else None
    top_issue_label = max(issue_counts, key=issue_counts.get) if issue_counts else None

    intent_count = len(intents)
    # Hunk-level stats still from hunks[]
    hunk_count = sum(1 for h in r.get("hunks", []) if not h.get("excluded"))
    excluded_count = sum(1 for h in r.get("hunks", []) if h.get("excluded"))

    agcr = r.get("calculated_agcr") or {}
    abandonment_val = agcr.get("abandonment_rate")
    raw_val = agcr.get("agcr")
    adjusted_val = agcr.get("adjusted_agcr")

    body = {
        "requirementId": r["requirement_id"],
        "runId": r["run_id"],
        "requirementName": r.get("requirement_name", ""),
        "developers": r.get("developers", ""),
        "agcrRaw": fmt_pct(raw_val),
        "agcrAdjusted": fmt_pct(adjusted_val),
        "abandonmentRate": fmt_pct(abandonment_val),
        "agcrObserved": fmt_pct(agcr.get("agcr_observed")),
        "agcrConsistency": agcr.get("agcr_consistency"),
        "repoCount": len(r.get("repos", [])),
        "intentCount": intent_count,
        "hunkCount": hunk_count,
        "excludedHunkCount": excluded_count,
        "topAttributionStage": top_stage,
        "topIssueTypeLabel": top_issue_label,
        "reportHtmlUrl": r.get("outputs", {}).get("report_html_s3_url"),
        "resultJsonUrl": r.get("outputs", {}).get("result_json_s3_url"),
        "repos": json.dumps(r.get("repos", []), ensure_ascii=False),
        "featureChanges": json.dumps(r.get("feature_changes", []), ensure_ascii=False),
        "stageDist": json.dumps(stage_counts, ensure_ascii=False),
        "issueTypeDist": json.dumps(issue_counts, ensure_ascii=False),
        "evidenceGaps": json.dumps(r.get("evidence_gaps", []), ensure_ascii=False),
        "keyFindings": json.dumps(r.get("key_findings", []), ensure_ascii=False),
    }
    return body


def build_intents_body(result_json_path, run_result_id, config_dir):
    """Step 12.2: 构建 Intent 明细请求体

    Writes intent-level details.
    Each intent includes attribution results + associated hunk_ids.
    """
    with open(result_json_path) as f:
        r = json.load(f)

    issue_labels, r_root_cause_labels, problem_type_labels, rcv_labels = load_config(config_dir)
    conf_map = {"high": "HIGH", "medium": "MEDIUM", "low": "LOW"}

    intents = []
    for intent in r.get("intents", []):
        pt = intent.get("problem_type", "")
        rc_variant = intent.get("root_cause_variant", "")
        r_cause = intent.get("root_cause", "")
        issue_id = intent.get("surface_issue_type", "") or "OTHER"

        at = {
            "surface_issue_type": issue_id,
            "surface_issue_type_label": issue_labels.get(issue_id, issue_id),
            "problem_type": pt,
            "problem_type_label": problem_type_labels.get(pt, ""),
            "root_cause": r_cause,
            "root_cause_label": r_root_cause_labels.get(r_cause, "") if r_cause else "",
            "root_cause_variant": rc_variant,
            "root_cause_variant_label": rcv_labels.get(rc_variant, ""),
            # Additional attribution fields
            "first_cause_nature": intent.get("first_cause_nature", ""),
            "attribution_direction": intent.get("attribution_direction", ""),
            "diff_nature": intent.get("diff_nature", ""),
            "additional_tags": intent.get("additional_tags", []),
        }

        # Build hunk summary from hunk_ids
        hunk_ids = intent.get("hunk_ids", [])
        all_hunks = {h.get("hunk_id"): h for h in r.get("hunks", [])}
        hunk_summary = []
        for hid in hunk_ids:
            h = all_hunks.get(hid, {})
            hunk_summary.append({
                "hunk_id": hid,
                "repo": h.get("repo", ""),
                "file": h.get("file") or h.get("file_path", ""),
                "removed_lines": h.get("removed_lines", 0),
                "added_lines": h.get("added_lines", 0),
            })

        impact = intent.get("impact", {})

        intents.append({
            "requirementId": r["requirement_id"],
            "runId": r["run_id"],
            "intentId": intent.get("intent_id", ""),
            "intentLabel": intent.get("intent_label", ""),
            "diffNature": intent.get("diff_nature", ""),
            "hunkIds": json.dumps(hunk_ids, ensure_ascii=False),
            "hunkCount": len(hunk_ids),
            "hunkSummary": json.dumps(hunk_summary, ensure_ascii=False),
            "attributionType": json.dumps(at, ensure_ascii=False),
            "attributionStage": intent.get("first_cause_stage"),
            "attributionSkill": intent.get("first_cause_skill"),
            "firstCauseNature": intent.get("first_cause_nature"),
            "attributionDirection": intent.get("attribution_direction"),
            "improvementPriority": conf_map.get(
                str(intent.get("confidence", "low")).lower(), "LOW"
            ),
            "directCause": intent.get("direct_cause"),
            "recommendation": intent.get("recommendation"),
            "featureChangeId": intent.get("feature_change_id"),
            "evidenceChain": json.dumps(intent.get("evidence_chain", []), ensure_ascii=False),
            "propagationPath": intent.get("propagation_path"),
            "downstreamPropagation": intent.get("downstream_propagation"),
            "knowledgeCheck": intent.get("knowledge_check"),
            "artifactManifestation": intent.get("artifact_manifestation"),
            "rootCauseVerdict": intent.get("root_cause_verdict"),
            "rootCauseEvidence": intent.get("root_cause_evidence"),
            "additionalTags": json.dumps(intent.get("additional_tags", []), ensure_ascii=False),
            "evidenceMissingStages": json.dumps(
                intent.get("evidence_missing_stages", []), ensure_ascii=False
            ),
            "totalRemovedLines": impact.get("total_removed_lines", 0),
            "totalAddedLines": impact.get("total_added_lines", 0),
            "abandonmentImpact": impact.get("abandonment_impact"),
            "agcrImpact": impact.get("agcr_impact"),
            "impact": json.dumps(impact, ensure_ascii=False),
        })

    return {"runResultId": run_result_id, "intents": intents}


def post_json(url, body):
    """POST JSON 并返回响应 dict"""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        return {"code": -1, "msg": str(e)}
    except Exception as e:
        return {"code": -1, "msg": str(e)}


def cmd_run(args):
    body = build_run_body(args.result_json, args.config_dir)
    url = f"{args.base_url}/agcr-attribution-run"
    if args.dry_run:
        print(json.dumps(body, ensure_ascii=False))
        return 0
    resp = post_json(url, body)
    print(json.dumps(resp, ensure_ascii=False))
    code = resp.get("code", -1)
    if code != 0:
        print(
            f"[Step 12] ERROR: POST /agcr-attribution-run 返回 code={code}：{json.dumps(resp, ensure_ascii=False)}",
            file=sys.stderr,
        )
        return 1
    run_result_id = resp.get("data", {}).get("runResultId")
    print(f"[Step 12] Run 汇总写入成功，runResultId={run_result_id}", file=sys.stderr)
    return 0


def cmd_intents(args):
    """Step 12.2: 批量写入 Intent 明细（暂时禁用）

    intent/hunk 粒度的 DB 写入暂时跳过。
    build_intents_body 代码保留，后续恢复时取消注释即可。
    """
    print('{"code": 0, "msg": "intent/hunk DB write temporarily disabled"}')
    print(
        f"[Step 12] Intent 明细写入已跳过（暂时禁用），runResultId={args.run_result_id}",
        file=sys.stderr,
    )
    return 0

    # ---- 以下为原始逻辑，暂时禁用，恢复时取消注释 ----
    # body = build_intents_body(args.result_json, args.run_result_id, args.config_dir)
    # url = f"{args.base_url}/agcr-attribution-intents"
    # if args.dry_run:
    #     print(json.dumps(body, ensure_ascii=False))
    #     return 0
    # resp = post_json(url, body)
    # print(json.dumps(resp, ensure_ascii=False))
    # code = resp.get("code", -1)
    # if code != 0:
    #     print(
    #         f"[Step 12] ERROR: POST /agcr-attribution-intents 返回 code={code}：{json.dumps(resp, ensure_ascii=False)}",
    #         file=sys.stderr,
    #     )
    #     return 1
    # inserted = resp.get("data", {}).get("inserted", 0)
    # print(
    #     f"[Step 12] Intent 明细写入成功，runResultId={args.run_result_id}，inserted={inserted}",
    #     file=sys.stderr,
    # )
    # return 0


def main():
    parser = argparse.ArgumentParser(description="Step 12 DB 写入脚本 (intent-level)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Step 12.1: 写入 Run 汇总行")
    p_run.add_argument("--result-json", required=True, help="attribution-result.json 路径")
    p_run.add_argument("--config-dir", required=True, help="config 目录路径")
    p_run.add_argument("--base-url", required=True, help="API base URL")
    p_run.add_argument("--dry-run", action="store_true", help="仅输出请求体，不发送")
    p_run.set_defaults(func=cmd_run)

    p_intents = sub.add_parser("intents", help="Step 12.2: 批量写入 Intent 明细")
    p_intents.add_argument("--result-json", required=True, help="attribution-result.json 路径")
    p_intents.add_argument("--run-result-id", required=True, type=int, help="Run 汇总行 ID")
    p_intents.add_argument("--config-dir", required=True, help="config 目录路径")
    p_intents.add_argument("--base-url", required=True, help="API base URL")
    p_intents.add_argument("--dry-run", action="store_true", help="仅输出请求体，不发送")
    p_intents.set_defaults(func=cmd_intents)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
