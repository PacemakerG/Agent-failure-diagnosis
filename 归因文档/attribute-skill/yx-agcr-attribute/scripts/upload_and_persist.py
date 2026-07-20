#!/usr/bin/env python3
"""upload_and_persist.py — Phase 3 上传报告到 S3 + 归因结果落库。

对标 yx-l3-eval 的 report_and_persist.py：合成一个进程，
S3 URL 通过 Python 变量在上传和落库之间传递，主 Agent 只需一行调用。

合并三个步骤：
  1. S3 上传 HTML + JSON
  2. URL 回填到 attribution-result.json.outputs
  3. 调用 write_attribution_db.py 写入 DB（Run 汇总；Intent 明细暂时禁用）

用法:
  python3 upload_and_persist.py \\
      --result-json $OUTPUT_DIR/attribution-result.json \\
      --html-path $OUTPUT_DIR/attribution-report.html \\
      --config-dir $SKILL_DIR/config \\
      --base-url http://yuanxi.adp.test.sankuai.com/api/v1/observability \\
      --upload-script ~/.claude/skills/yx-s3plus-upload/scripts/upload_to_s3plus.py \\
      --env test \\
      [--dry-run]
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_UPLOAD = str(Path.home() / ".claude/skills/yx-s3plus-upload/scripts/upload_to_s3plus.py")
DEFAULT_API_BASE = "http://yuanxi.adp.test.sankuai.com/api/v1/observability"


def upload_to_s3(file_path, object_name, upload_script, env, content_type=None):
    """调用 upload_to_s3plus.py 上传单个文件，返回 S3 access URL。"""
    cmd = [
        "python3", upload_script,
        "--file", file_path,
        "--env", env,
        "--object-name", object_name,
    ]
    if content_type:
        cmd += ["--content-type", content_type]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip().splitlines()[-1]
    return None


def upload_reports(result_json_path, html_path, run_id, upload_script, env):
    """上传 HTML 报告 + JSON 结果到 S3Plus，返回 (html_url, json_url)。"""
    today = datetime.date.today().isoformat()
    s3_prefix = "agcr-attribution"

    # 从 result JSON 读取 requirement_id / run_id
    with open(result_json_path, "r", encoding="utf-8") as f:
        r = json.load(f)
    req_id = r.get("requirement_id", "unknown")
    rid = r.get("run_id", run_id or "unknown")

    html_url = None
    json_url = None

    # 上传 HTML
    if os.path.exists(html_path):
        html_obj = f"{s3_prefix}/{req_id}/{rid}/attribution-report.html"
        html_url = upload_to_s3(
            html_path, html_obj, upload_script, env, "text/html; charset=utf-8"
        )
        if html_url:
            print(f"[S3] HTML: {html_url}")
        else:
            print(f"[S3] HTML 上传失败", file=sys.stderr)
    else:
        print(f"[S3] HTML 文件不存在: {html_path}", file=sys.stderr)

    # 上传 JSON
    json_obj = f"{s3_prefix}/{req_id}/{rid}/attribution-result.json"
    json_url = upload_to_s3(
        result_json_path, json_obj, upload_script, env, "application/json"
    )
    if json_url:
        print(f"[S3] JSON: {json_url}")
    else:
        print(f"[S3] JSON 上传失败", file=sys.stderr)

    return html_url, json_url


def backfill_s3_urls(result_json_path, html_url, json_url):
    """将 S3 URL 回填到 attribution-result.json 的 outputs 字段。"""
    with open(result_json_path, "r", encoding="utf-8") as f:
        r = json.load(f)

    if "outputs" not in r:
        r["outputs"] = {}

    r["outputs"]["report_html_s3_url"] = html_url or ""
    r["outputs"]["result_json_s3_url"] = json_url or ""

    with open(result_json_path, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=2)


def persist_to_db(result_json_path, config_dir, api_base):
    """调用已有的 write_attribution_db.py 逻辑写入 DB（Run 汇总；Intent 明细暂时禁用）。"""
    script_dir = Path(__file__).parent

    # Step 1: 写入 Run 汇总行
    run_cmd = [
        "python3", str(script_dir / "write_attribution_db.py"), "run",
        "--result-json", result_json_path,
        "--config-dir", config_dir,
        "--base-url", api_base,
    ]
    run_result = subprocess.run(run_cmd, capture_output=True, text=True)
    print(f"[DB] Run 汇总: {run_result.stdout[:100]}")
    if run_result.returncode != 0:
        print(f"[DB] Run 汇总写入失败: {run_result.stderr[-200:]}", file=sys.stderr)
        return None

    # 从输出提取 runResultId
    try:
        resp = json.loads(run_result.stdout.strip().splitlines()[-1])
        run_result_id = resp.get("data", {}).get("runResultId")
    except (json.JSONDecodeError, IndexError):
        print(f"[DB] 无法解析 runResultId", file=sys.stderr)
        return None

    if not run_result_id:
        print(f"[DB] runResultId 为空", file=sys.stderr)
        return None

    # Step 2: 写入 Intent 明细（暂时禁用，cmd_intents 已为 no-op）
    # 恢复时取消下方注释即可，write_attribution_db.py 的 cmd_intents 也需同步恢复。
    # intents_cmd = [
    #     "python3", str(script_dir / "write_attribution_db.py"), "intents",
    #     "--result-json", result_json_path,
    #     "--run-result-id", str(run_result_id),
    #     "--config-dir", config_dir,
    #     "--base-url", api_base,
    # ]
    # intents_result = subprocess.run(intents_cmd, capture_output=True, text=True)
    # print(f"[DB] Intent 明细: {intents_result.stdout[:100]}")
    # if intents_result.returncode != 0:
    #     print(f"[DB] Intent 明细写入失败: {intents_result.stderr[-200:]}", file=sys.stderr)

    print(f"[DB] Intent 明细写入已跳过（暂时禁用）")
    return run_result_id


def main():
    ap = argparse.ArgumentParser(description="Phase 3 上传 S3 + 归因结果落库")
    ap.add_argument("--result-json", required=True, help="attribution-result.json 路径")
    ap.add_argument("--html-path", required=True, help="attribution-report.html 路径")
    ap.add_argument("--config-dir", required=True, help="config 目录路径")
    ap.add_argument("--base-url", default=DEFAULT_API_BASE, help="API base URL")
    ap.add_argument("--upload-script", default=DEFAULT_UPLOAD, help="upload_to_s3plus.py 路径")
    ap.add_argument("--env", default="test", help="S3 环境")
    ap.add_argument("--dry-run", action="store_true", help="仅上传不落库")
    args = ap.parse_args()

    # 1. 上传 S3
    html_url, json_url = upload_reports(
        args.result_json, args.html_path, None, args.upload_script, args.env
    )

    # 2. 回填 URL 到 attribution-result.json
    backfill_s3_urls(args.result_json, html_url, json_url)
    print("[backfill] S3 URLs written to attribution-result.json.outputs")

    if args.dry_run:
        print("--dry-run: 跳过 DB 写入")
        return

    # 3. 写入 DB
    run_result_id = persist_to_db(args.result_json, args.config_dir, args.base_url)

    print(
        f"\n完成：HTML({'ok' if html_url else '失败'}) + "
        f"JSON({'ok' if json_url else '失败'}) 上传 S3，"
        f"DB 落库 runResultId={run_result_id}"
    )
    if html_url:
        print(f"报告地址: {html_url}")


if __name__ == "__main__":
    main()
