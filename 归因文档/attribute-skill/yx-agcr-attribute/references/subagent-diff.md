# SubAgent-Diff 规格

## 职责

对单个 repo 执行远程 commit 校验（Gate 2/3）+ diff 生成 + commit chain 提取。

## 主 Agent 传入参数

```json
{
  "repo": "vas_server",
  "target_branch": "feature/xxx",
  "base_commit": "abc1234",
  "one_shot_commit": "def5678",
  "target_final_commit": "ghi9012"
}
```

## 输出文件（写入 `$OUTPUT_DIR/diffs/{repo}/`）

- `{repo}-one-shot-to-target-final.diff`（必需，后续 Hunk 切分主数据源）
- `{repo}-base-to-one-shot.diff`（必需，AGCR 计算数据源）
- `{repo}-base-to-target-final.diff`（必需，AGCR 最终分子计算数据源，失败阻塞）
- `commit-chain.json`

## Gate 2 — commit 存在性校验

对每个 repo 校验 base_commit / one_shot_commit / target_final_commit 都存在于远程 repo。通过 `fetch_diff.py` 完整 clone 后 `git diff` 验证（clone 成功即仓库可达，diff 成功即 commit 存在）。任一 commit 不存在或 clone 失败，输出阻塞信息并停止。

## Gate 3 — 分支归属与顺序校验

校验：远程 target_branch 存在；base_commit → one_shot_commit → target_final_commit 顺序线性成立，且都在 target_branch 可达历史中。

## diff 生成

通过 `fetch_diff.py` 生成 diff，生成后应用测试文件排除规则。

测试文件排除规则（适用于全部三个 diff）：
- `*Test.java` / `*Tests.java` / `*Test.kt`（Java/Kotlin 测试类）
- `src/test/` / `src/it/` / `src/integration-test/` 目录下全部文件
- `*.test.js` / `*.test.ts` / `*.spec.js` / `*.spec.ts` / `*_test.go` / `test_*.py` / `*_test.py`
- `__tests__/` / `__fixtures__/` / `__mocks__/` 目录

过滤方式：按 `diff --git a/... b/...` 行识别文件边界，整段剔除命中文件。

必需 diff 生成命令：
```bash
python3 "$SCRIPT_DIR/fetch_diff.py" \
  --repo {repo} --from {one_shot_commit} --to {target_final_commit} \
  --output $OUTPUT_DIR/diffs/{repo}/{repo}-one-shot-to-target-final.diff \
  --local-path {local_repo_path} --group {group}

python3 "$SCRIPT_DIR/fetch_diff.py" \
  --repo {repo} --from {base_commit} --to {one_shot_commit} \
  --output $OUTPUT_DIR/diffs/{repo}/{repo}-base-to-one-shot.diff \
  --local-path {local_repo_path} --group {group}

python3 "$SCRIPT_DIR/fetch_diff.py" \
  --repo {repo} --from {base_commit} --to {target_final_commit} \
  --output $OUTPUT_DIR/diffs/{repo}/{repo}-base-to-target-final.diff \
  --local-path {local_repo_path} --group {group}
```

## commit chain 提取

从本地 repo（或完整 clone 后的仓库）提取 one_shot_commit..target_final_commit 范围内的提交链，用于 Step 5.6 source_commits 关联和**开发人 MIS 提取**。

```bash
git -C {local_path} log --format='%H|%an|%ae|%cn|%ce|%cI|%s' \
  {one_shot_commit}..{target_final_commit}
```

若本地 repo 不存在，`fetch_diff.py` 完整 clone 后在临时目录中执行同样的 `git log` 命令。

输出写入 `$OUTPUT_DIR/diffs/{repo}/commit-chain.json`，结构为 commit 数组：

```json
[
  {
    "sha": "f6f87a5...",
    "message": "[FIX-1234] 修复满赠逻辑",
    "author_name": "zhangsan",
    "author_email": "zhangsan@meituan.com",
    "committer_name": "zhangsan",
    "committer_email": "zhangsan@meituan.com",
    "timestamp": "2026-06-03T14:38:07+08:00"
  }
]
```

**必须包含 `author_name` 和 `author_email` 字段**。主 Agent 在 Step 2.4 组装 repos-meta.json 时，从各 repo 的 commit-chain.json 中提取去重后的 commit author MIS（从 author_email 的 `@` 前缀提取），写入 `repos-meta.json` 的 `commit_developers` 字段。`git log` 的 `%an` / `%ae` 格式符直接提供 author 信息，无需额外查询。

## 返回摘要

```json
{
  "status": "success|blocked",
  "repo": "vas_server",
  "target_final_commit": "ghi9012",
  "diff_files": {
    "one_shot_to_final": "{path}",
    "base_to_one_shot": "{path}",
    "base_to_final": "{path}"
  },
  "commit_chain_path": "{path}",
  "block_reason": null
}
```

status 为 `blocked` 时记录该 repo 的 evidence_gap，跳过该 repo，其余 repo 继续。
