---
name: yx-agcr-attribution
description: AI 生成代码采纳率归因分析。基于三步分步归因架构（逐层穿透定位首因层 → 决策树选择问题类型 → 根因子变体判定）+ 三层 Change Intent 聚类 + evidence_type/structure_type 确定性推导，对 AI 生成代码在交付过程中被人工修改/删除的部分进行全链路归因。当用户提到"采纳率归因""代码归因""AI代码质量分析"时激活。
---

# AI 生成代码采纳率归因分析

## 1. 概述

本 Skill 对 AI 辅助研发流程中，AI 首轮生成代码在最终交付版本中被修改/删除的代码进行逆向归因分析，定位问题根因到元析研发流水线的具体阶段（N5→N1）。

核心设计：三步分步归因架构（Penetration → Typing → RootCause，三个独立 SubAgent 串行）+ 三层 Change Intent 聚类 + evidence_type/structure_type 由 `normalize_hunks.py` 确定性推导。全量归因（不跳过 refining），逆向归因（before-side ↔ artifact + after-side ↔ artifact 双重对比）。

## 2. 输入模式

| 模式 | 输入 | 适用场景 |
|---|---|---|
| 常规模式 | `req_id` 或 `fsd_url` | 从 observability + CLI 日志洗数获取完整上下文 |
| 手动模式 | `commits_file` + 可选 `artifact_paths` | 用户显式提供 commit 和产物 |

可选参数：`run_id`、`agcr_value`、`swimlane`。

## 3. 版本语义

| 版本 | 含义 | 来源 |
|---|---|---|
| `base_commit` | 拉分支时的代码基线 | CLI 洗数 / 用户显式提供 |
| `one_shot_commit` | AI 首轮完整实现后的代码版本 | CLI 洗数 / 用户显式提供 |
| `target_final_commit` | 上线或最新版本 commit | CLI 洗数 / 远程代码平台 / 用户显式提供 |

主分析 diff：`one_shot_commit..target_final_commit`。**diff 的 before 侧 = AI 原始代码，after 侧 = 人工修正后代码。**

## 4. 执行流程

执行前读取 `config/problem-types.json`（35 种问题类型 + 16 种表象类型 + R1-R5 根因体系 + 各阶段决策树）。

### Phase 1：初始化与数据收集

```bash
# 1. Observability API — 查询 session 数据（run_id / session_ids / developers / requirement_name）
curl -s "http://yuanxi.adp.test.sankuai.com/api/v1/observability/sessions?requirement_id=$REQ_ID" > session.json
# sessions 响应包含 requirement_name（部分需求可能缺失，此时留空，报告标头自动回退显示 requirement_id）

# 2. CLI 日志洗数
deep-ai-analysis export-requirement --requirement-id "$REQ_ID" --output "$OUTPUT_DIR/log-washing-result.json"

# 3. 从 agcr.json 提取 commit_markers → base/one_shot/target_final
python3 -c "
import json; d=json.load(open('$OUTPUT_DIR/log-washing-result.json'))
cm=d.get('agcr',{}).get('commit_markers',{})
print(json.dumps({'base':cm.get('base',''),'one_shot':cm.get('tdd',''),'final':cm.get('final','')}))
"

# 4. 生成 execution_trace.json（三层融合：phases.json + commits.json + dag_*.json）
python3 "$SCRIPT_DIR/parse_execution_trace.py" \
  --log-washing "$OUTPUT_DIR/log-washing-result.json" \
  --output "$OUTPUT_DIR/artifacts/execution_trace.json"

# 5. 组装 repos-meta.json（含 requirement_name，从 session.json 提取），执行 Gate 1 校验（repo + commit 完整性）
# Gate 1 失败 → 交互式补充流程（要求用户提供 commits_file 或 artifact_paths）
```

Gate 1 通过后并行派发 SubAgent-Diff（N repos，≤3 并行）和 SubAgent-Artifact（1 个），总计 ≤4 并行。SubAgent-Diff 完成后提取 commit author MIS 写入 `repos-meta.json`。

完整数据采集规格详见 `references/data-collection.md`。SubAgent-Diff / SubAgent-Artifact 详见对应参考文件。

### Phase 2a：Hunk 切分 + 聚类

```bash
# Step 5: 确定性 Hunk 切分
python3 "$SCRIPT_DIR/split_hunks.py" \
  --diff-file "$OUTPUT_DIR/diffs/{repo}/{repo}-one-shot-to-target-final.diff" \
  --repo "$REPO" \
  --output "$OUTPUT_DIR/hunks/hunk-list.json"

# Step 5.2b: AST 方法签名检测
python3 "$SCRIPT_DIR/ast_hunk_split.py" \
  --diff-file "$OUTPUT_DIR/diffs/{repo}/{repo}-one-shot-to-target-final.diff" \
  --repo "$REPO" \
  --output "$OUTPUT_DIR/hunks/ast-split-suggestions.json"

# Layer 0: D-xx 设计项预聚类（主 Agent 解析 tasks.md，生成 design-cluster-hints.json）
# tasks.md 不存在时跳过此步

# Layer 1: 确定性预聚类
python3 "$SCRIPT_DIR/pre_cluster.py" \
  --hunk-list "$OUTPUT_DIR/hunks/hunk-list.json" \
  --design-cluster "$OUTPUT_DIR/hunks/design-cluster-hints.json" \
  --ast-split "$OUTPUT_DIR/hunks/ast-split-suggestions.json" \
  --output "$OUTPUT_DIR/hunks/pre-cluster-hints.json"
```

完成后并行派发 SubAgent-AGCR（独立计算 AGCR）和 SubAgent-Intent（Layer 2 LLM 语义聚类 + before-side 提取 + diff_nature 判定）。

Gate 校验（`validate_subagent_output.py --mode intent`）通过后执行 `normalize_hunks.py` 完成确定性推导（evidence_type / structure_type / first_cause_skill / attribution_direction / surface_issue_type）。详见 `references/subagent-intent.md` 和 `references/derivation-rules.md`。

### Phase 2b：三步归因

按 intent 分批派发三步归因（≤4 并行），**三个独立 SubAgent 串行执行**：

```bash
# Step 0.5: 维度 A 结构性检查（脚本化模式 §5.7）
python3 "$SCRIPT_DIR/check_artifact_structure.py" \
  --artifacts-dir "$OUTPUT_DIR/artifacts" \
  --intent-list "$OUTPUT_DIR/hunks/change-intents.json" \
  --output "$OUTPUT_DIR/artifact-structure-report.json"
# 产出 artifact-structure-report.json，供 SubAgent-Penetration 逐层读取结构性检查结果

# Step 1: SubAgent-Penetration — 逐层穿透定位首因层
# 派发 SubAgent，输入 intent-list.json + artifacts(N1-N5) + artifact-structure-report.json
# SubAgent 先读取脚本结构性检查结果，再做语义检查（§5.7 脚本化模式）
# 输出: penetration-result.json (first_cause_stage + evidence_chain per layer)
# 规格: references/subagent-penetration.md

# Step 2a: SubAgent-Typing — 决策树选择问题类型
# 派发 SubAgent，输入 first_cause_stage + penetration_evidence_brief
# SubAgent 通过 navigate_decision_tree.py 与决策树脚本交互（答 yes/no）
# 输出: typing-result.json (problem_type + typing_evidence_detail)
# 规格: references/subagent-typing.md

# Step 2b: SubAgent-RootCause — 根因子变体判定
# 派发 SubAgent，输入 problem_type + typing_evidence_detail + execution_trace + change-intents.json（继承 cluster_confidence）
# 输出: intent-fragments/CI-xxx.json (root_cause + complete evidence_chain + confidence from cluster_confidence)
# 规格: references/subagent-rootcause.md
```

Gate 校验（`validate_subagent_output.py --mode attribution --design-md "$OUTPUT_DIR/artifacts/design.md"`）通过后执行 `normalize_hunks.py` 归一化。`--design-md` 启用 D-xx → US-xx 一致性校验，交叉检查 evidence_chain 中引用的用户故事是否匹配 design.md 的「对应用户故事」字段。

### Phase 3：汇聚与输出

```bash
# Step 9: 汇总统计 → attribution-result.json
python3 "$SCRIPT_DIR/aggregate_stats.py" \
  --run-dir "$OUTPUT_DIR" \
  --config-dir "$SCRIPT_DIR/../config" \
  --repos-meta "$OUTPUT_DIR/repos-meta.json" \
  --hunk-list "$OUTPUT_DIR/hunks/hunk-list.json" \
  --output "$OUTPUT_DIR/attribution-result.json"

# Gate 9: 聚合后校验
python3 "$SCRIPT_DIR/verify_attribution.py" --input "$OUTPUT_DIR/attribution-result.json"
# Gate 9 失败 → 阻塞，修正后重新校验

# Step 10: 渲染 HTML 报告
python3 "$SCRIPT_DIR/render_report.py" \
  --input "$OUTPUT_DIR/attribution-result.json" \
  --template "$SCRIPT_DIR/../templates/attribution-report.html" \
  --output "$OUTPUT_DIR/attribution-report.html" \
  --config-dir "$SCRIPT_DIR/../config"

# Gate 10: 渲染后校验（无未解析占位符、CI cards > 0、key_findings 非空）
# Gate 10 失败 → 阻塞上传

# Step 11+12: 上传 S3Plus + 写入 DB（合并为一步）
python3 "$SCRIPT_DIR/upload_and_persist.py" \
  --run-dir "$OUTPUT_DIR" \
  --repos-meta "$OUTPUT_DIR/repos-meta.json" \
  --html-path "$OUTPUT_DIR/attribution-report.html" \
  --result-json "$OUTPUT_DIR/attribution-result.json" \
  --bucket "agcr-attribution" \
  --s3-prefix "$REQ_ID/$RUN_ID"
# 支持 --dry-run 预览不实际写入
```

## 5. SubAgent 派发矩阵

| SubAgent | Phase | 并行上限 | 职责 | 参考文件 |
|---|---|---|---|---|
| SubAgent-Diff | 1 | 3 | 远程 commit 校验 + diff 生成 + merge_master 排除 | `references/subagent-diff.md` |
| SubAgent-Artifact | 1 | 1 | 阶段产物下载 | `references/subagent-artifact.md` |
| SubAgent-AGCR | 2a | 1 | AGCR 独立计算 | `references/subagent-agcr.md` |
| SubAgent-Intent | 2a | 1 | 三层聚类（Layer 2）+ before-side 提取 + diff_nature 判定 | `references/subagent-intent.md` |
| SubAgent-Penetration | 2b | 4 | 逐层穿透定位首因层 | `references/subagent-penetration.md` |
| SubAgent-Typing | 2b | 4 | 决策树选择问题类型 | `references/subagent-typing.md` |
| SubAgent-RootCause | 2b | 4 | 根因子变体判定 + evidence_chain 构造 | `references/subagent-rootcause.md` |

全局同时运行 SubAgent ≤ 4 个。Phase 2b 中三个 SubAgent 串行执行（Penetration → Typing → RootCause），1 intent = 1 串行链，intent 数 > 8 时分批。

## 6. 产物路径

```text
$OUTPUT_DIR/   # = $PWD/agcr-attribution/{requirement_id_or_run_id}/
  attribution-report.html
  attribution-result.json
  cc-logs/
  log-washing-result.json
  repos-meta.json
  hunks/
    hunk-list.json
    ast-split-suggestions.json
    design-cluster-hints.json
    pre-cluster-hints.json
    change-intents.json
  intent-fragments/
    CI-001.json               # SubAgent-RootCause 产出
    CI-002.json
  penetration-results/        # SubAgent-Penetration 产出
    CI-001.json
  artifact-structure-report.json  # check_artifact_structure.py 产出
  typing-results/             # SubAgent-Typing 产出
    CI-001.json
  artifacts/
    design.md
    requirement.md
    tasks.md
    current-state.md
    execution_trace.json       # 三层融合执行轨迹
  agcr-calc.json
  diffs/
    {repo}/
      {repo}-one-shot-to-target-final.diff
      {repo}-base-to-one-shot.diff
      commit-chain.json
```

S3Plus 上传路径：`agcr-attribution/{requirement_id_or_run_id}/{run_id}/attribution-report.html`

## 7. 确定性脚本清单

| 脚本 | 用途 | 调用时机 |
|---|---|---|
| `parse_execution_trace.py` | 三层融合执行轨迹（phases + commits + dag） | Phase 1 Step 4 |
| `split_hunks.py` | 确定性 Hunk 切分 | Phase 2 Step 5 |
| `ast_hunk_split.py` | AST 方法签名检测 | Phase 2 Step 5.2b |
| `pre_cluster.py` | Layer 1 确定性预聚类 | Phase 2a |
| `calc_agcr.py` | 从 diff 独立计算 AGCR | Phase 2a SubAgent-AGCR |
| `check_artifact_structure.py` | 维度 A 结构性检查（8 项确定性检查 + 多信号范围界定） | Phase 2b Step 0.5 |
| `navigate_decision_tree.py` | 决策树导航（SubAgent-Typing 交互） | Phase 2b Step 2a |
| `validate_penetration.py` | 穿透产出校验 | Phase 2b Step 1 后 |
| `validate_typing.py` | 类型产出校验 | Phase 2b Step 2a 后 |
| `normalize_hunks.py` | fragment 归一化 + 确定性推导（evidence_type / structure_type / first_cause_skill / attribution_direction / surface_issue_type） | Phase 2b Step 5.9 |
| `validate_subagent_output.py` | SubAgent 产出校验（intent / attribution 模式） | Gate 5.9a / Gate 5.9b |
| `aggregate_stats.py` | 汇聚统计 → attribution-result.json | Phase 3 Step 9 |
| `verify_attribution.py` | 验证 attribution-result.json 质量 | Phase 3 Gate 9 |
| `render_report.py` | 从 JSON + 模板渲染 HTML | Phase 3 Step 10 |
| `upload_and_persist.py` | 上传 S3Plus + 回填 URL + 写入 DB | Phase 3 Step 11+12 |
| `write_attribution_db.py` | 写入 DB（独立调用，upload_and_persist 内部调用） | Phase 3 Step 12 |

## 8. 关键约束

1. **commit 事实来源**：用户显式提供 > CLI 洗数 > base_commit 兜底。禁止从 `agcr_data_json` 读取 commit。
2. **逆向归因**：before-side ↔ artifact + after-side ↔ artifact 双重对比。N5/N4 层必须显式记录 before_vs_artifact。
3. **三步串行**：Phase 2b 中 Penetration → Typing → RootCause 严格串行，步骤间通过 evidence_brief 传递。
4. **全量归因**：所有 diff_nature 类型（含 refining）均进入完整三步归因路径。
5. **evidence_chain 完整性**：必须包含首因层 + 下游传导链 + 信号充足层确认。
6. **evidence_type / structure_type 禁止 LLM 自标注**：由 `normalize_hunks.py` 从 `problem_type` 映射确定性推导。
7. **HTML 报告由脚本生成**：`render_report.py` 确定性渲染，AI 不得手工拼接 HTML。
8. **Gate 校验阻塞**：脚本 exit code 1 则阻塞，不得跳过。
9. **CLI 依赖**：常规模式依赖 `deep-ai-analysis` CLI（v0.3.1+）。

## 9. 参考文件索引

| 文件 | 内容 |
|---|---|
| `references/subagent-diff.md` | SubAgent-Diff 完整规格 |
| `references/subagent-artifact.md` | SubAgent-Artifact 完整规格 |
| `references/subagent-agcr.md` | SubAgent-AGCR 完整规格 |
| `references/subagent-intent.md` | SubAgent-Intent 完整规格（三层聚类 + before-side 提取 + diff_nature 判定） |
| `references/subagent-penetration.md` | SubAgent-Penetration 完整规格（逐层穿透） |
| `references/subagent-typing.md` | SubAgent-Typing 完整规格（决策树导航 + 脚本交互） |
| `references/subagent-rootcause.md` | SubAgent-RootCause 完整规格（根因子判定 + evidence_chain 构造） |
| `references/derivation-rules.md` | evidence_type / structure_type / first_cause_skill / attribution_direction / surface_issue_type 推导规则 |
| `references/output-format.md` | Intent 归因完整输出格式（22+ 字段） |
| `references/data-collection.md` | 数据采集规格（Observability API、CLI 日志洗数、commit 优先级、Gate 流程） |
| `references/cli-schemas.md` | CLI 产物数据结构（agcr.json、commit 提取规则、execution_trace.json、repos-meta.json） |
| `references/diff-strategy.md` | Diff 生成策略 |
| `config/problem-types.json` | 问题类型完整枚举（35 种 + 16 种表象 + R1-R5 根因 + 决策树） |
| `templates/attribution-report.html` | HTML 报告模板 |
