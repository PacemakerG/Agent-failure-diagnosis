# attribution-report.html 占位符说明

本文件描述 `attribution-report.html` 模板中所有 `{{placeholder}}` 的填充规则。
所有占位符均由 `scripts/render_report.py` 的 `main()` 函数确定性生成（读取 `attribution-result.json` + `problem-types.json`），**不是**由 LLM 在 Step 10 手写替换。执行归因流程时，Step 10 只需调用 `render_report.py`，不需要人工按本文件逐条替换。

本文件的作用是：当需要修改 `render_report.py` 的渲染逻辑，或需要排查报告某个区块渲染错误时，作为占位符 ↔ 渲染函数 ↔ 数据字段的对照速查表。**如实反映 `render_report.py` 当前实现**，两者必须保持一致；修改渲染函数后必须同步更新本文件。

## 通用规则

- 所有文本类字段统一通过 `esc()`（`html.escape(str(s), quote=True)`）做 HTML 转义，避免破坏页面结构。
- 未匹配到数据的占位符，`main()` 结尾会用正则 `\{\{[a-zA-Z0-9_]+\}\}` 扫描模板中残留的占位符并统一替换为 `-`，因此新增占位符时若忘记在 `repl` 字典中赋值，不会报错，只会静默显示为 `-`（排查空白区块时需留意这一点）。
- 空表格 / 空列表的兜底文案由各渲染函数各自实现，常见的是 `<tr><td colspan="N" class="empty">暂无数据</td></tr>` 或 `<div class="empty-state">暂无数据</div>`，具体见下文各函数说明。

---

## 阶段名称映射（STAGE_MAP / STAGE_ORDER）

`render_report.py` 内部用 `STAGE_MAP` 把 SKILL.md 中的阶段编码（P5-P1，以及 SubAgent 输出中可能出现的 N5-N1 前缀）统一映射为中文展示名，`normalize_stage()` / `normalize_stage_short()` 是实际调用的转换函数：

| 阶段编码（P 前缀或 N 前缀） | 报告展示名称 |
|---|---|
| `P5` / `N5` | N5 编码计划 |
| `P4` / `N4` | N4 技术方案 |
| `P3` / `N3` | N3 需求澄清 |
| `P2` / `N2` | N2 现状梳理 |
| `P1` / `N1` | N1 项目初始化 |

`STAGE_ORDER`（用于排序展示，从后往前）：`N6 代码生成` → `N5 编码计划` → `N4 技术方案` → `N3 需求澄清` → `N2 现状梳理` → `N1 项目初始化` → `测试并行链路`。

注意：`N6 代码生成`和`测试并行链路`不在 `STAGE_MAP` 的转换范围内（不存在对应 P-code），只在 `STAGE_ORDER` 排序表中出现，代表数据中可能直接携带的原始阶段字符串。

---

## 问题类型 / 根因展示规则

- 问题类型展示由 `_display_pc(pc, label, maps)` 统一处理：若 `pc` 是全大写下划线格式的英文 SIT ID（如 `FUNC_LOGIC_ERROR`），只展示中文 `label`；若 `pc` 是 `P5-1` 这种编码格式，展示为 `"P5-1 {label}"`。
- 根因展示统一为 `"{root_cause} {root_cause_label}"` 形式（如 `R3 模型推理`），标签来源优先取 CI 自带的 `root_cause_label`，否则回退查 `problem-types.json` 的 `maps["rc_label"]`。
- `first_cause_nature` 中文映射（`FCN_LABEL`，用于 CI 卡片 meta 区）：`product_defect`→产物缺陷，`design_quality`→设计质量缺陷，`ai_deviation`→AI 执行偏差，`upstream_propagation`→上游传导，`prd_quality`→PRD 质量。
- `attribution_direction` 中文映射（`ATTR_DIR_LABEL` / `DIR_LABEL`）：`artifact_defect`→产物缺陷，`ai_execution`→AI 执行偏差（AI 执行偏差）。
- `diff_nature` 中文映射（`DN_LABEL`）：`corrective`→修正类，`additive`→补充类，`subtractive`→删除类，`refining`→精炼类；对应描述文案见 `DN_DESC`。

**渲染脚本消费的核心数据结构**：`attribution-result.json` 中的 `change_intent_groups`（若为空则回退读取 `hunk_groups`，这是历史字段名兼容）是 CI（修改意图）级归因数据的唯一来源，绝大多数 §3-§7 的占位符都遍历这个数组聚合生成。单个 CI 对象的关键字段：`intent_id`、`intent_description`、`diff_nature`、`first_cause_stage`、`p_category` / `p_category_label`、`root_cause` / `root_cause_label`、`root_cause_variant`、`first_cause_nature`、`attribution_direction`、`propagation_path`、`additional_tags`、`dominant_confidence`、`evidence_type`、`cluster_method`、`impact`（含 `abandonment_impact`/`agcr_impact`/`gap_impact`/`total_removed_lines`/`total_added_lines`）、`evidence_chain`、`direct_cause`、`recommendation`、`hunks`（该 CI 下的原始 hunk 列表）、`hunk_count`。

---

## 页面骨架占位符（`<head>` / Header / TOC 之外的公共区）

| 占位符 | 渲染函数 | 填充内容 |
|---|---|---|
| `{{requirement_name}}` | `main()` 直接取值 | 需求名称：`data.requirement_name`，缺失时回退 `requirement_id`，再缺失填 `-`。出现在 `<title>`、Header `<h1>` 徽标、Header meta 行、§1 表格 |
| `{{requirement_id}}` | `main()` 直接取值 | `data.requirement_id`，缺失填 `-`。出现在 Header meta 行、§1 表格 |
| `{{developers}}` | `main()` 直接取值 | 开发人员：`data.developers`（缺失填 `-`），并根据 `data.developer_source` 追加来源徽标（`commit_chain`/`source_commits`→绿色"来自 commit"；`observability`→橙色"来自 Observability（执行人）"；`repos_meta`→灰色"来自 repos-meta"）；若 `meta_developers` 与 `developers` 不同且来源为 commit 类，额外注明执行人 |
| `{{generated_at}}` | `main()` 直接取值 | **渲染脚本执行时的系统时间**，由 `datetime.now().strftime("%Y-%m-%d %H:%M:%S +0800")` 生成，不读取历史时间戳 |
| `{{run_id}}` | `main()` 直接取值 | `data.run_id`，缺失填 `-`。出现在 Header meta 行、§1 表格 |
| `{{empty_diff_notice}}` | `main()` 直接取值 | `data.empty_diff_notice` 非空时包裹为 `<div class="direct-cause-box">...</div>`，否则为空字符串 |
| `{{repo_count}}` / `{{hunk_count}}` / `{{ci_count}}` / `{{top_issue_type}}` / `{{top_stage}}` / `{{confidence_summary}}` | `r_summary_cards()` | 顶部 6 张统计卡：仓库数（`len(data.repos)`）、有效 Hunk 数（排除 `excluded=true` 后的 `data.hunks` 长度）、CI 数（`len(change_intent_groups)`）、Top 问题类型（CI 级 `p_category` 出现频次最高的一项，经 `_display_pc` 转中文）、Top 首因层（CI 级 `first_cause_stage` 出现频次最高，转中文全称）、置信度摘要（格式 `高置信度数/CI总数`，如 `12/19`） |
| `{{executive_summary}}` | `r_executive_summary()` | 摘要区多段 `<p>`：① 仓库数/有效Hunk数/CI数概览；② AGCR 数值及废弃率（`calculated_agcr` 为空时显示"AGCR 数据缺失"）；③ CI 级出现频次最高的根因；④ CI 级出现频次最高的首因阶段及占比；⑤ Diff 性质分布（各类型 CI 数量，按数量降序用顿号连接）；⑥ 置信度分布（高/中/低数量及高置信度占比） |

---

## §1 基本信息

| 占位符 | 渲染函数 | 填充内容 |
|---|---|---|
| `{{commit_source}}` | `r_commit_source()` | `data.commit_source` 字段值；缺失时根据 `data.hunks[].source` 是否含 `sdk_log`/`cc_log` 拼接 `sdk_log_washing`/`cc_log_analysis`；都没有则填 `-` |
| `{{gate_status}}` | `r_gate_status()` | 读取 `data.gate_check`（含 `missing`/`invalid`/`branch_errors` 三个列表）。为空或三个列表均空 → 绿色"✅ Gate 校验通过"；否则红色徽标列出各类问题数量 |

（`{{requirement_id}}`、`{{requirement_name}}`、`{{developers}}`、`{{run_id}}` 同时用于本节表格，见上表）

---

## §2 代码版本与 Diff 概览

| 占位符 | 渲染函数 | 填充内容 |
|---|---|---|
| `{{repo_diff_rows}}` | `r_repo_diff_rows()` | 每个 `data.repos[]` 一行：仓库名、分支、base/one-shot/final commit 短哈希（one_shot 缺失显示 `N/A`）、AI 编码 commit 数徽标（来自 `diff_overview[].b2o_commits`）、人工修改 commit 数徽标（`os2f_commits`）、该仓库有效 Hunk 数、变更摘要（`repos[].change_summary`）。无仓库数据时填一行 `colspan=9` 的"暂无数据" |
| `{{repo_diff_note}}` | `r_repo_diff_note()` | 附加说明：若某仓库有效 Hunk 数为 0 且 one_shot_commit == target_final_commit，注明"AI 生成代码即为最终版本，无人工修改"；若为 0 但 commit 不同，注明"人工修改未生成有效 Hunk（排除后为 0）" |
| `{{repo_commit_details}}` | `r_repo_commit_details()` | 每个仓库一个可折叠 `<details>`，展示该仓库 AI 编码阶段（base→one-shot）和人工修改阶段（one-shot→final）的完整 commit 列表（sha/message/date/shot_ratio 或 author）。数据来自 `diff_overview[].ai_commits` / `.human_commits`；两者都为空的仓库不生成 details |

---

## §3 计算采纳率（AGCR）

| 占位符 | 渲染函数 | 填充内容 |
|---|---|---|
| `{{agcr_metric_cards}}` | `r_agcr_metric_cards()` | 5 张全局指标卡：AGCR、废弃率、One-shot 行数、废弃行数、最终版总行数，数据来自 `data.calculated_agcr`（含 `agcr`/`abandonment_rate`/`grand_total.{one_shot_lines,removed_lines,final_lines}`）。`calculated_agcr.agcr` 为 `None` 时 5 张卡全部显示 N/A / 0 |
| `{{per_repo_rows}}` | `r_per_repo_rows()` | 按仓库统计表格行，数据源 `calculated_agcr.per_repo[]`：仓库名、one-shot/final commit 短哈希、有效 Hunk 数、one-shot 行数、废弃行数、最终行数、AGCR（行级，按阈值 ≥0.7 绿/≥0.4 黄/<0.4 红着色）、废弃率、备注（`clamped=true` 时注明"removed 含预存在代码删除，已钳制"）。`per_repo` 为空时回退遍历 `data.repos[]` 只显示 commit 信息，其余列填 N/A |
| `{{per_ci_table}}` | `r_per_ci_table()` | 按 CI 粒度统计表格：每个 CI 一行（CI ID、描述、Hunk 数、废弃行数、新增行数、废弃影响率、AGCR 影响率、AGCR 缺口占比），末尾追加"合计"行与"1-AGCR（参照值）"对比行。CI 为空时返回 `暂无 CI 粒度数据` 提示 |
| `{{agcr_formula_note}}` | `r_agcr_formula_note()` | AGCR 与废弃率的计算公式说明文字，以及当前数值复述；`calculated_agcr.agcr` 为空时改为显示数据缺失警告框 |

---

## §4 问题分布

| 占位符 | 渲染函数 | 填充内容 |
|---|---|---|
| `{{problem_legends}}` | `r_problem_legends()` | 三个图例框拼接：① 问题类型图例（仅展示实际出现在 `change_intent_groups`/`intent_groups` 中的 `p_category`/`problem_type`，来自 `problem-types.json` 的 `pc_label`）；② 根因图例（仅展示实际出现的 `root_cause`）；③ Diff 性质图例（固定展示 corrective/additive/subtractive/refining 四种及其 `DN_DESC` 描述） |
| `{{stage_problem_grid}}` | `r_stage_problem_grid()` | 4.1 首因层 × 问题类型网格卡片：按 `STAGE_ORDER` 顺序为每个出现过的阶段生成一张卡片，卡片内按数量降序列出该阶段下各问题类型的迷你进度条（颜色循环使用 7 色调色板）。数据源：CI 级 `first_cause_stage` × `p_category` 二维计数。无数据时返回 `<div class="empty-state">暂无数据</div>` |
| `{{diff_nature_bars}}` | `r_diff_nature_bars()` | 4.2 Diff 性质分布条形图，按 CI 计数，四色映射（corrective=c1紫蓝、subtractive=c6粉、additive=c5绿、refining=c4蓝），按数量降序排列 |
| `{{attribution_direction_bars}}` | `r_attribution_direction_bars()` | 4.3 归因方向分布条形图，按 CI 计数，区分 `artifact_defect`（产物缺陷）与 `ai_execution`（AI 执行偏差），条形图下方附两者的定义说明文字 |

---

## §5 归因明细（按修改意图 CI 粒度）

| 占位符 | 渲染函数 | 填充内容 |
|---|---|---|
| `{{ci_intro_text}}` | `r_ci_intro_text()` | 一句话说明本节内容：CI 总数、有效 Hunk 总数、聚合维度和交互方式的固定模板文案 |
| `{{filter_bar}}` | `r_filter_bar()` | 筛选工具条：首因阶段/问题类型/根因/Diff 性质四组按钮，其中首因阶段与问题类型联动（`window._stagePtypeMap` 内嵌 JS 对象控制级联显示）。按钮的可选值均从实际数据中去重收集，不是写死的枚举 |
| `{{ci_cards}}` | `r_ci_cards()` | 核心区块：为每个 CI 生成一张 `.ci-card` 卡片（见下方"CI 卡片结构"）。若 `change_intent_groups` 为空但存在有效 hunk，会退化为按 `first_cause_stage × p_category` 对原始 hunk 分组的"回退模式"卡片（`intent_id` 形如 `CI-001`，`cluster_method="legacy_fallback"`，描述前缀 `[回退模式]`）。两者都为空时返回 `暂无归因明细数据` |

### CI 卡片结构（`_build_ci_card()`）

每张 `.ci-card` 携带 `data-stage`/`data-ptype`/`data-rcause`/`data-dnature` 四个 data 属性供前端筛选脚本使用，结构如下：

- **Header**（`.ci-card-header`，点击可折叠）：CI ID（`.ci-id`）+ 修改意图描述（`.ci-desc`，单行省略）+ 标签组（`.ci-tags`：diff_nature 徽标、问题类型徽标、根因徽标、置信度徽标"高/中/低"、Hunk 数徽标）
- **Body**（`.ci-card-body`，展开后显示）：
  - `.ci-desc-full`：完整意图描述（不省略）
  - `.ci-meta`：4 列指标网格 —— 首因阶段、问题类型、根因、置信度，以及有值才展示的首因性质/归因方向/根因变体，末尾固定展示废弃行数、新增行数
  - 附加标签行（`additional_tags` 非空时展示）
  - `.ci-impact-row`：废弃影响率 / AGCR 影响率 / AGCR 缺口占比三项数值（来自 `impact` 字段，缺失显示 N/A 灰徽标）
  - 传导路径（`propagation_path` 非空时由 `_render_propagation_path()` 渲染，保留 `→` 链路格式）
  - derivation-hint 小字：证据类型 + 聚类方法（`legacy_fallback`/`orphan_fallback` 不展示聚类方法）
  - 直接原因框（`direct_cause`，取 CI 自身字段，缺失时回退取首个 hunk 的 `direct_cause`，再回退取 `data._ci_direct_cause_map`）
  - CI 级证据链（`evidence_chain`，每步展示阶段名/产物名/finding/`before_vs_artifact` 一致性徽标（仅 N5/N4 层）/可折叠产物片段 `artifact_snippet`/上游追溯块 `upstream_artifact`+`upstream_finding`+`upstream_snippet`）
  - 改进建议框（`recommendation`）
  - 可折叠的 Hunk 归因明细列表（`<details>`，标题显示 Hunk 数量），内部为每个 hunk 调用 `_build_hunk_item()` 渲染

### 单 Hunk 卡片结构（`_build_hunk_item()`）

- Header：Hunk ID + 标签组（归因方向徽标、`consistency` 一致性徽标、置信度徽标）
- 行数指标行：废弃行数（红）/新增行数（绿）+ 文件位置（`file:new_start`，仅取 basename）
- 变更摘要（`change_summary`）
- Before/After 代码对比块（双栏，优先取 `before_code`/`after_code` 字段，缺失时从 `diff_content` 按 `+`/`-` 行提取兜底）
- 可折叠证据链（hunk 自身的 `evidence_chain`，比 CI 级证据链更简略，不含 snippet/上游追溯）

---

## §6 排除 Hunk 汇总

| 占位符 | 渲染函数 | 填充内容 |
|---|---|---|
| `{{excluded_hunk_summary}}` | `r_excluded_hunks()` | 两个子表格：6.1 按排除原因（遍历固定排除原因枚举 `whitespace`/`auto_import`/`auto_generated`/`test_file`/`doc_only`/`config_only`，仅展示 `data.excluded_hunks_by_reason` 中数量>0 的项，末尾加合计行）；6.2 按仓库分布（仅展示存在排除 Hunk 的仓库，同时显示该仓库有效 Hunk 数对比）。均无排除时两表格显示"无排除 Hunk" |

---

## §7 改进建议

| 占位符 | 渲染函数 | 填充内容 |
|---|---|---|
| `{{key_findings_items}}` | `r_key_findings()` | 遍历 `data.key_findings[]`，每条渲染为 `.kf-item`：优先级徽标（兼容 `priority`/`severity` 两种字段名，`severity` 经 `SEVERITY_TO_PRIORITY` 映射为大写）+ 标题文本（`finding` 或 `title`）+ 关联 hunks/FCs 数量小字 + 描述小字（`description`）。`key_findings` 为空返回 `<div class="empty">暂无数据</div>` |
| `{{recommendation_items}}` | `r_recommendations()` | 遍历 `data.recommendations[]`，按 `priority` 分组为 HIGH/MEDIUM/LOW 三组（默认 LOW），每组渲染为可点击展开/折叠的 `.rec-group`，组内每条建议为 `.rec-item`（纯文本 `text` 字段）。空列表分组不渲染；`recommendations` 整体为空返回 `暂无数据` |

---

## §8 证据缺口

| 占位符 | 渲染函数 | 填充内容 |
|---|---|---|
| `{{evidence_gap_content}}` | `r_evidence_gaps()` | 遍历 `data.evidence_gaps[]`，每条一行表格：阶段（`stage`）、缺口描述（`gap`）、影响（`impact`）、补充建议（`suggestion`）。空列表时返回提示"✅ 本次分析无证据缺口" |

---

## §9 产物读取情况

| 占位符 | 渲染函数 | 填充内容 |
|---|---|---|
| `{{artifact_summary_rows}}` | `r_artifact_summary()` | 基于内置完整产物注册表 `FULL_REGISTRY`（15 项，覆盖技术方案/编码计划/需求澄清/现状梳理/项目初始化/全链路六个阶段，含"Session JSONL（ai-trace）"）逐项渲染，与 `data.artifact_summary[]` 按 `(stage, artifact_name)` 匹配；未匹配到的注册表项显示"缺失"+"数据中无此产物记录"。数据中存在但不在注册表内的额外产物会追加在表格末尾。表格首行为汇总行：已读取/缺失数量 + 覆盖率百分比。相同阶段的行用 `rowspan` 合并阶段列 |

---

## 维护说明

- 新增/删除模板中的 `{{xxx}}` 占位符时，必须同步修改 `render_report.py` 的 `main()` 中 `repl` 字典，并更新本文件对应表格行。
- 若某占位符的生成逻辑发生变化（如新增字段来源、调整兜底文案），应同步更新本文件中该占位符的"填充内容"描述，保持文档与代码一致，避免文档失真。
- 本文件不描述 CSS 类名的样式细节（颜色/间距等），仅描述数据到 HTML 结构的映射逻辑；样式细节请直接查看 `attribution-report.html` 的 `<style>` 块。
