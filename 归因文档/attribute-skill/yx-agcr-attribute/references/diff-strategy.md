# Diff 生成策略

## 优先级

1. **本地仓库优先**：若 `--local-path` 指定的本地仓库路径存在且包含目标 commit，直接使用 `git diff` 生成
2. **完整 clone 兜底**：本地仓库不存在或不含目标 commit 时，从远程完整 clone 仓库后生成 diff。使用完整 clone 而非 sparse fetch，以保证 GitNexus PDG 分析所需的 git 对象完整性

## 本地 diff 生成

```bash
cd {local_repo_path}
git diff {from_commit}..{to_commit} -- {file_filter}
```

## 远程 diff 生成（fetch_diff.py）

`fetch_diff.py` 封装了远程代码平台 compare API，支持：
- 指定 repo、from/to commit
- 输出到指定文件路径
- 自动处理分页（大 diff 场景）
- 失败时输出明确错误信息

## 测试文件排除

生成的 diff 文件在写入前必须按文件路径过滤掉测试文件（详见 SubAgent-Diff 规格）。过滤按 `diff --git a/... b/...` 行识别文件边界，整段剔除命中文件。

## 特殊 diff header 处理

| 情况 | 处理方式 |
|---|---|
| `rename from / rename to` | 以 `rename to` 的新路径作为文件标识 |
| `new file mode` | 整个文件的 `+` 行进入统计 |
| `deleted file mode` | 跳过 |
| `Binary files ... differ` | 跳过 |
| `\ No newline at end of file` | 跳过该行 |
| `copy from / copy to` | 以 `copy to` 的新路径作为文件标识 |
