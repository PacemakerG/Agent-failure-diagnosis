# 数据采集执行手册

本手册描述 Phase 1 数据采集的执行步骤。从 `req_id` / `fsd_url` 出发，依次完成 Observability API 查询、CLI 日志洗数、commit 提取、execution_trace 生成、远程校验、diff 生成、产物拷贝、Gate 1 校验。CLI 产物的数据结构与字段提取规则详见 `references/cli-schemas.md`。

## 数据源总览

| 数据源 | 获取内容 | 优先级 |
|---|---|---|
| 用户显式提供（`commits_file` / 内联 commits） | repo / branch / commit | 最高，覆盖所有其他来源 |
| CLI 日志洗数（`deep-ai-analysis`） | repo 列表 / branch / 阶段 commit（commit_markers）/ 阶段产物 | 仓库范围、branch、阶段产物的首要来源 |
| Observability API `/sessions` 响应 | `run_id` / `session_ids` / `developers` / `requirement_name` | `requirement_name` 的唯一来源 |
| Observability API 响应 `agcr_data_json` | AGCR 观测值（`agcr_overall` 等），仅用于展示 | 仅展示，不作为 commit 事实来源 |
| 本地 git + `fetch_diff.py` | diff 生成 / commit chain 提取 / commit 校验 | diff 和 commit chain 的实际执行工具 |

**关键约束**：不要从 `agcr_data_json` 读取或推断阶段代码 commit——其中的 commit 和仓库字段不置信。FSD 链接只用于提取需求 ID，不通过 FSD 查询分支绑定来补齐仓库或 commit。

## 执行流程总览

```text
req_id / fsd_url
  -> Step 1: 从 fsd_url 提取 req_id（若提供的是 fsd_url）
  -> Step 2: 查询 Observability API，获取 session_id / run_id / developers / requirement_name
  -> Step 3: 执行 CLI 日志洗数，产出 agcr.json / phases.json / commits.json / dag_*.json / *.md
  -> Step 4: 从 commit_markers 提取三版本候选，列出完整 commit 列表供用户确认
  -> Step 5: 生成 execution_trace.json（parse_execution_trace.py 三层融合）
  -> Step 6: 远程校验 branch / commit，读取 target_final_commit
  -> Step 7: 生成各 repo 的 b2o / os2f diff（fetch_diff.py）
  -> Step 8: 拷贝阶段产物到 artifacts/ 目录
  -> Step 9: 组装 repos-meta.json，执行 Gate 1 校验（缺失则阻塞并交互补充）
  -> 完成：产出 repos-meta.json + diffs/ + artifacts/，进入 Phase 2
```

---

## Step 1: 确定 req_id

若输入是 `fsd_url`，从中提取需求 ID（URL 路径中的数字部分）。若输入已经是 `req_id`，直接使用。`fsd_url` 不用于查询分支绑定或仓库信息。

## Step 2: 查询 Observability API

通过 HTTP API 查询 observability 数据，获取 `session_id` / `run_id` / `requirement_name` / `developers`。不要直接查数据库表。

API base URL：`http://yuanxi.adp.test.sankuai.com/api/v1/observability`

```bash
curl -s "http://yuanxi.adp.test.sankuai.com/api/v1/observability/sessions?requirement_id=${REQ_ID}" \
  [-H "swimlane: ${SWIMLANE}"] \
  | python3 -m json.tool
```

响应结构（`data` 字段内包含 session 记录）：

```json
{
  "code": 0,
  "data": {
    "requirement_id": "95019604",
    "run_id": "yx-xxx-...",
    "requirement_name": "全站推诊断&营销活动结合",
    "developers": "zhao",
    "session_ids": ["..."]
  },
  "success": true
}
```

若响应 `data` 为空或 `code != 0`，说明该需求无 observability 记录，需依赖 CLI 洗数或用户交互补充。

`requirement_name` 字段并非所有需求都返回——部分需求的响应中会缺少此字段。此时 `requirement_name` 留空，报告标头自动回退显示 `requirement_id`（`render_report.py` 已处理），不影响后续流程。

### agcr_data_json（仅展示用）

`agcr_data_json` 仅用于 AGCR 观测值展示（`agcr_overall` 等），其中的 commit 和仓库字段不置信，不作为 commit 事实来源。

```json
{
  "agcr_overall": 95.0,
  "latest_commit": "target-or-latest-observed-commit",
  "history": [
    {
      "commit_time": "2026-06-03T14:38:07+08:00",
      "commit_hash": "975e6da2b438cf9b92d376860f497eae74aacf5e",
      "agcr_overall": 100.0
    }
  ],
  "repos": [
    {
      "repo": "repo-name",
      "branch": "feature/94842225-xxx",
      "base_commit": "...",
      "tdd_commit": "...",
      "cr_commit": "...",
      "itest_commit": "...",
      "lines_total": 120,
      "lines_by_tdd": 80,
      "lines_by_cr": 20,
      "lines_by_itest": 20
    }
  ]
}
```

也兼容历史或回放数据中直接提供 `one_shot_commit` / `c0` / `c_tdd` 的形态。`lines_total` / `lines_by_tdd` / `lines_by_cr` / `lines_by_itest` 只表示采纳率统计口径，不能作为 commit 是否存在的证据。

## Step 3: 执行 CLI 日志洗数

通过 `deep-ai-analysis` CLI（v0.3.1+）从 CC 日志提取仓库、分支、commit 和阶段产物。这是仓库范围、branch、阶段产物的首要来源。

```bash
deep-ai-analysis export-requirement \
  --requirement-id ${REQ_ID} \
  --output-dir ${OUTPUT_DIR}/cli-washing
```

产物目录结构：

```text
${OUTPUT_DIR}/cli-washing/
├── {session_id}/          # 每个会话一个子目录
│   ├── agcr.json          # 会话级 AGCR 数组（含 repo/branch/commit_markers/shot_ratio）
│   ├── phases.json        # 阶段划分（phase_name/start_time/end_time/skills）
│   ├── commits.json       # commit 列表（session_id/command/message/repo/commit_id/branch）
│   ├── dag.json           # DAG 图
│   ├── dag_*.json         # 各阶段 DAG
│   └── *.md               # 阶段产物文档
└── agcr-{req_id}.json     # 需求级汇总（tdd/itest shot_ratio）
```

agcr.json 结构、commit 版本提取规则、short hash → full hash 映射、阶段 commit 计数详见 `references/cli-schemas.md`。

## Step 4: 提取并确认 commit 三版本

从 agcr.json 的 `commit_markers` 提取每个 repo 的三版本 commit 作为初始候选。`base_commit`（分支基线）和 `target_final_commit`（远程分支最新 head）由系统自动提取，无需用户确认。只有 `one_shot_commit` 需要用户确认——因为 `commit_markers` 的 tdd 标记受日志完整性和阶段划分影响最大，日志中 coding 阶段最后一个 AI 提交可能因日志不完整或阶段划分偏差而遗漏。

提取规则和 short hash → full hash 映射详见 `references/cli-schemas.md`。

### 4.1 列出 commit 供用户确认

对每个 repo，从 `agcr.json` 的 `result.commits[]` 提取完整 commit 列表，标注 `commit_markers` 的初步判定，同时展示每个 commit 的 `shot_ratio`（采纳率）和代码行数（`commit_lines→final_lines`），以及 `result.summary` 的 AGCR 汇总统计。这些采纳率数据帮助用户判断 tdd 标记是否合理——例如 shot_ratio 过低的 commit 不太可能是 AI 首轮编码的最终输出。`base` 和 `final` 标记自动采用，仅 `tdd`（one-shot）候选项需用户确认。多仓库时在同一个输出块中依次列出所有 repo 的 commit 列表，供用户一次性批量确认：

```text
【commit 三版本确认 — 共 2 个仓库】

--- repo: vas_server  branch: feature/95101048-xxx ---

  AGCR 汇总：valid=4, skip=0, ≥95%=2, 50~95%=2, <50%=0, avg_discard=5%

  CLI 洗数 commit 列表（共 4 条）：

    #  short_hash  date              subject                              lines   shot   markers
    1  a1b2c3d4    2026-06-03 10:00  feat: init project structure         30→28   93%    [base]
    2  f7e6d5c4    2026-06-03 14:00  feat: implement gift service         120→98  82%    [tdd] ← one-shot 候选
    3  b8c7d6e5    2026-06-03 16:00  fix: handle edge case               8→3     38%    [skip]
    4  1a2b3c4d    2026-06-04 09:00  refactor: code review adjustments    15→15   100%   [final]

  自动提取：base=a1b2c3d4, final=1a2b3c4d
  one_shot 候选：f7e6d5c4(第2条, shot=82%) ← 请确认

--- repo: vas_web  branch: feature/95101048-xxx ---

  AGCR 汇总：valid=3, skip=0, ≥95%=1, 50~95%=2, <50%=0, avg_discard=8%

  CLI 洗数 commit 列表（共 3 条）：

    #  short_hash  date              subject                              lines   shot   markers
    1  9z8y7x6w    2026-06-03 10:00  chore: scaffold                      12→12   100%   [base]
    2  1u2v3w4x    2026-06-03 13:00  feat: add gift page                  85→60   71%    [tdd] ← one-shot 候选
    3  7y6x5w4v    2026-06-04 09:00  fix: review feedback                 10→8    80%    [final]

  自动提取：base=9z8y7x6w, final=7y6x5w4v
  one_shot 候选：1u2v3w4x(第2条, shot=71%) ← 请确认

---

请确认 one_shot_commit（AI 首轮完整实现后的 commit），回复方式：
  - 全部正确：回复"全部确认"
  - 修正某个仓库：回复"vas_server: 第3条"或"vas_web: b8c7d6e5"（序号或 hash 均可）
  - 某仓库 AI 未生成代码：回复"vas_web: AI未生成代码"
    系统将设置该仓库 one_shot_commit = base_commit（AGCR=null，仍执行 hunk 归因）
```

用户确认后，以用户确认的值为准，覆盖 `commit_markers` 的初步判定。若用户通过 `commits_file` 或内联 commits 显式提供了 commit hash，则跳过确认流程，直接使用用户提供的值。

### 4.2 commit 事实来源优先级

| 内部归因字段 | 优先级 1（最可靠） | 优先级 2 | 优先级 3（兜底） | 含义 |
|---|---|---|---|---|
| `base_commit` | 用户显式提供 | CLI 洗数（commit_markers.base） | 远程分支第一个 commit 的 parent | 拉分支时的起点 commit |
| `one_shot_commit` | 用户确认 | CLI 洗数（commit_markers.tdd） | Gate 1 交互补充 | AI 首轮完整实现后的代码版本 |
| `target_final_commit` | 用户显式提供 | 代码平台远程分支最新 head | — | 上线或最新版本 commit |

### 4.3 base_commit 兜底

当 CLI 洗数和用户输入均未提供时，`base_commit` 是 feature 分支第一个 commit 的 parent：

```bash
# 1. 获取 feature 分支第一个 commit（时间最早的 commit）
# 2. 用 git log 获取其 parent
git log --format=%P -1 "{first_commit_sha}"
```

### 4.4 one_shot_commit 识别说明

CLI 洗数通过 `commit_markers` 中标记为 `"tdd"` 的 commit 识别 one-shot 边界，不依赖 `agcr_data_json` 中的别名字段。`cr_commit` / `itest_commit` 只作为阶段辅助边界，不作为主分析 diff 的 one-shot 边界。

由于日志不完整或阶段划分偏差，`tdd` 标记可能不准确。因此 Step 4.1 要求用户确认 one-shot 边界，而非静默接受 CLI 判定。

### 4.5 target_final_commit 读取

优先使用用户显式提供的 commit hash（通过 `commits_file` 或内联 commits 覆盖）。用户未提供时，从代码平台读取远程分支最新 head commit，标记 `target_final_kind=remote_branch_head`。若远程分支不存在或代码平台无法读取 commit，必须阻塞；不能用 `agcr_data_json` 中的任何 commit 字段代替。

### 4.6 特殊场景：AI 未生成代码

若某 repo 的 AI 未生成代码（`one_shot_commit = base_commit`），该 repo 的 AGCR 为 null，不参与采纳率计算，但仍需分析 one-shot→final diff 中的 hunk 归因。此场景在 Step 4.1 确认表中通过用户回复"AI未生成代码"触发。

若 CLI 洗数完全未产出某 repo 的 commit 列表（`result.commits[]` 为空或 agcr.json 缺失），Step 4.1 无法列出确认表，转入 Gate 1 交互式补充流程。

## Step 5: 生成 execution_trace.json

调用 `parse_execution_trace.py`，从 phases.json + commits.json + dag_*.json 三层融合生成 `execution_trace.json`，写入 `$OUTPUT_DIR/artifacts/`。

```bash
python3 "$SCRIPT_DIR/parse_execution_trace.py" \
  --cli-washing-dir "$OUTPUT_DIR/cli-washing/{session_id}" \
  --output "$OUTPUT_DIR/artifacts/execution_trace.json"
```

三层融合策略、输出格式、回退策略详见 `references/cli-schemas.md`。

## Step 6: 远程校验 branch 和 commit

本 Skill 分析的是远程仓库状态。commit 事实来源是远程代码平台（美团 Code 平台），不能把本地工作区的未提交改动、分支名、本地 `git log` 当作 commit 事实来源。

### branch 校验

每个 repo 必须确定一个 `target_branch`，用于限定"这些变化发生在当前分支中"：

1. 必须使用 CLI 洗数结果中每仓 `branch`；CLI 缺失时必须阻塞，要求用户通过 `commits_file` 补充。
2. 不能读取或使用本地 repo 当前 checkout 分支作为替代。

若远程分支不存在或代码平台无法证明 commit 属于该分支，必须阻塞。

### commit 校验

```bash
# 读取远程分支最新 head commit（获取 target_final_commit）
git ls-remote --heads {remote_url} {branch}

# commit 校验（本地 repo 存在时）
git -C {local_path} cat-file -e {commit_hash}
```

`fetch_diff.py` 在完整 clone 后也可用于 commit 校验——clone 成功即表示远程仓库可达，`git diff` 成功即表示两个 commit 均存在。远程分支 head commit 即为 `target_final_commit`。

## Step 7: 生成 diff

Diff 生成通过确定性脚本 `scripts/fetch_diff.py` 完成。仓库克隆使用完整 clone，不做 sparse fetch（GitNexus PDG 分析需要完整的 git 历史和对象）。

```bash
python3 "$SCRIPT_DIR/fetch_diff.py" \
  --repo {repo} \
  --from {from_commit} \
  --to {to_commit} \
  --output {output_path}.diff \
  [--local-path /abs/path/to/local/repo] \
  [--group wm]
```

`fetch_diff.py` 有两种策略：

1. **本地优先**：若本地存在该 repo 的 `.git` 目录且两个 commit 均可达，直接 `git diff` 生成。此方式仅使用本地 repo 作为 diff 引擎，commit 来源仍然是远程仓库（commit SHA 由 observability 或用户提供，不是从本地分支推断）。
2. **完整 clone 兜底**：本地 repo 不存在或 commit 不可达时，从远程完整 clone 仓库后 `git diff`，完成后清理临时目录。

两种策略都保证 diff 基于 commit SHA 之间的客观差异，不依赖本地工作区状态。

## Step 8: 拷贝阶段产物

将 CLI 产出目录中的 `.md` 文件拷贝到 `$OUTPUT_DIR/artifacts/` 目录。缺失产物不阻塞分析，后续在归因报告中记录为证据缺口。

## Step 9: 组装 repos-meta.json 并执行 Gate 1 校验

将所有仓库的元数据和 commit 信息汇总写入 `repos-meta.json`。repos-meta.json 结构详见 `references/cli-schemas.md`。

组装完成后执行 Gate 1 校验。Gate 1 检测到数据缺失时，不立即终止，而是向用户输出缺失明细和补充格式示例，等待用户通过 `commits_file`（补充 commit/branch）或 `artifact_paths`（补充阶段产物路径）补充。用户补充后重新执行 Gate 1 校验，通过则继续后续流程。

### Gate 1 阻塞条件

- CLI 日志洗数结果中无法解析 repo 列表，且用户未通过 `commits_file` / 内联 commits 补充
- CLI 日志洗数失败或无法解析 repo 级 commit 列表，且用户未通过 `commits_file` / 内联 commits 补充
- 任一 repo 缺少 `branch`（CLI 洗数结果无且用户未补充）
- 用户未确认 `base_commit` / `one_shot_commit`（Step 4 确认流程未完成或 CLI 洗数未产出 commit 列表）
- 任一 repo 缺少远程代码读取来源
- commit 值为空字符串、纯空白、`~`、`TBD`、`unknown`、`null`
- 试图使用 `agcr_data_json` 中的 commit 字段代替 CLI 洗数结果或 repo 粒度阶段 commit

### Gate 1 阻塞输出格式

```text
【采纳率归因阻塞 — 可交互补充】

原因：缺少仓库上下文或 AGCR 代码版本 commit 输入

缺失明细：
- {repo}: branch={值或缺失}, base_commit={值或缺失}, one_shot_commit={值或缺失}, target_final_commit={值或缺失}

请通过 commits_file 或内联 commits 补充缺失字段（格式见下方 commits_file 补充格式，target_final_commit 可不填，系统自动从代码平台读取）。

若阶段产物也缺失，请通过 artifact_paths 补充阶段产物路径（格式：{ "阶段名": "本地路径或目录" }）。

补充方式：将 YAML 保存为文件后传入 commits_file={文件路径}，或直接内联传入。阶段产物路径可通过 artifact_paths={JSON文件路径} 或内联 JSON 补充。

本次未执行 diff / 问题分类 / 归因分析。等待用户补充后重试。
```

### commits_file 补充格式

当 CLI 洗数结果缺失时，允许用户通过 `commits_file` 或内联 commits 补充缺失字段。用户传入的 commits 与 CLI 洗数结果按字段级合并，同字段以用户传入为准；合并后仍须通过 Gate 1 校验。

完整格式（observability 无数据时，用户需提供全部字段）：

```yaml
commits:
  - repo: vas_server
    branch: feature/95101048-xxx
    base_commit: a1b2c3d4e5f6789
    one_shot_commit: f7e6d5c4b3a2918
    target_final_commit: 1a2b3c4d5e6f789  # 不提供则从代码平台远程分支最新 head 读取
  - repo: vas_web
    branch: feature/95101048-xxx
    base_commit: 9z8y7x6w5v4u321
    one_shot_commit: 1u2v3w4x5y6z789
    target_final_commit: 7y6x5w4v3u2t109
```

`repo` 可以是仓库名或 repo slug。若 CLI 洗数结果有 repo 列表，用户传入的 repo 必须能与之匹配；若 CLI 洗数和 observability 均无 repo 信息，以用户传入的 repo 列表为准。

### developers 字段来源规范

`developers` 字段表示参与代码修改的**实际开发人**（commit author），不是元析执行人。提取优先级：

1. **commit_chain（首选）**：SubAgent-Diff 完成后，主 Agent 从各 repo 的 `commit-chain.json` 中提取全部 commit 的 `author_email`，取 `@` 前缀作为 MIS，去重后逗号连接写入 `commit_developers` 和 `developers`，`developer_source` 标记为 `commit_chain`
2. **Observability API 兜底**：若 commit-chain.json 不存在或无 author 信息，从 Observability API 的 CC 日志 `user_mis` 字段获取，写入 `developers`，`developer_source` 标记为 `observability`。注意此值是**元析执行人**（触发 AI 编码的人），不一定等于后续人工修改代码的开发人

`commit_developers` 字段仅在从 commit chain 成功提取时存在，用于下游区分来源。`aggregate_stats.py` 优先使用 `commit_developers`，缺失时 fallback 到 `developers`。报告中展示时标注来源（"来自 commit" vs "来自 Observability"）。

排除规则：过滤掉 email 前缀为 `noreply`、`git`、`merge` 等非人工 MIS。
