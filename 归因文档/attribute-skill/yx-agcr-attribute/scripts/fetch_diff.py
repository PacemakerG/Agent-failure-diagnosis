#!/usr/bin/env python3
"""
fetch_diff.py — 生成两个 commit 之间的 git diff。

策略（详见 references/diff-strategy.md）：
  1. 本地优先：若 --local-path 存在且两个 commit 均在本地 → 直接 git diff
  2. 完整 clone 兜底：从远程完整 clone 仓库后 diff，完成后清理临时目录

用法：
  python3 fetch_diff.py \
    --repo    {repo_name}      \
    --from    {sha}            \
    --to      {sha}            \
    --output  {path}.diff      \
    [--local-path /abs/path/to/local/repo]  \
    [--group  wm]              \
    [--provider-out /tmp/provider.txt]

退出码：
  0  成功
  1  两种方式均失败（commit 不存在 / 网络故障）
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile


# ── 测试文件过滤 ─────────────────────────────────────────────────────────────
# 对应 SKILL.md「测试文件排除规则」：diff 生成后按文件路径剔除测试代码，
# 再写入 .diff 文件。覆盖 Java/Kotlin/Groovy/JS/TS/Go/Python/Rust 等常见测试命名。
TEST_FILE_PATTERNS = [
    # Java / Kotlin
    r'.*Test\.java$', r'.*Test\.kt$',
    r'.*Tests\.java$', r'.*Tests\.kt$',
    r'.*TestUtil\.java$', r'.*TestUtils\.java$', r'.*TestFixture\.java$',
    # Groovy (Spock) — 美团 Java 栈常见
    r'.*Spec\.groovy$', r'.*SpockSpec\.groovy$',
    r'.*Test\.groovy$', r'.*Tests\.groovy$',
    # 测试目录（按 POSIX 路径段匹配，忽略大小写）
    r'.*/src/test/.*', r'.*/src/it/.*', r'.*/src/integration-test/.*',
    r'.*/test/resources/.*', r'.*/src/test/groovy/.*',
    # Mock / fixture（仅测试目录下）
    r'.*/src/test/.*/.*Mock.*\.java$',
    # JS / TS
    r'.*\.test\.(js|ts|jsx|tsx)$', r'.*\.spec\.(js|ts)$',
    # Go / Python / Rust
    r'.*_test\.go$', r'.*_test\.py$', r'.*test_.*\.py$',
    r'.*\.test\.rs$', r'.*\.spec\.rs$',
    # pytest / jest 配置目录
    r'.*/__tests__/.*', r'.*/__fixtures__/.*', r'.*/__mocks__/.*',
]
_TEST_RE = re.compile('|'.join(TEST_FILE_PATTERNS))


def is_test_file(path):
    if not path:
        return False
    return bool(_TEST_RE.match(path))


def filter_test_files(diff_text):
    """按 diff --git 边界切分，整段剔除测试文件，保留其余文件内容与 hunk 顺序。"""
    out = []
    removed = []
    # 在每个 "diff --git" 前切分，保留分隔符
    parts = re.split(r'(?=^diff --git )', diff_text, flags=re.MULTILINE)
    for part in parts:
        if not part.strip():
            continue
        m = re.match(r'diff --git "?a/(.+?)"? "?b/(.+?)"?$', part, re.MULTILINE)
        if m:
            path = m.group(2)
            if is_test_file(path):
                removed.append(path)
                continue
        out.append(part)
    return ''.join(out), removed


# ── 工具函数 ─────────────────────────────────────────────────────────────────

def run(cmd, **kwargs):
    return subprocess.run(cmd, **kwargs)


def commit_exists_locally(repo_path, sha):
    """检查 commit 是否存在于本地 repo。"""
    r = run(["git", "-C", repo_path, "cat-file", "-e", sha],
            capture_output=True)
    return r.returncode == 0


def write_diff_local(repo_path, from_commit, to_commit, output):
    """用本地 repo 生成 diff。返回 (ok, raw_text)。"""
    r = run(["git", "-C", repo_path, "diff", from_commit, to_commit],
            capture_output=True, text=True)
    return r.returncode == 0, r.stdout


def resolve_remote_url(repo, group):
    """
    按优先级推导 SSH remote URL：
      1. repo search {repo}
      2. repo info --group {wm|wbqa|shopdiy} --repo {repo}
      3. 兜底构造：ssh://git@git.sankuai.com/{group}/{repo}.git
    """
    # 1. repo search
    r = run(["repo", "search", repo], capture_output=True, text=True)
    if r.returncode == 0:
        url = _extract_ssh_url(r.stdout)
        if url:
            return url

    # 2. repo info（依次尝试各 group）
    groups = [group] if group else ["wm", "wbqa", "shopdiy"]
    for g in groups:
        r = run(["repo", "info", "--group", g, "--repo", repo],
                capture_output=True, text=True)
        if r.returncode == 0:
            url = _extract_ssh_url(r.stdout)
            if url:
                # shopdiy 的实际 domain 是 git.dianpingoa.com
                if g == "shopdiy":
                    url = url.replace("git.sankuai.com", "git.dianpingoa.com")
                return url

    # 3. 兜底
    g = group or "wm"
    return "ssh://git@git.sankuai.com/{}/{}.git".format(g, repo)


def _extract_ssh_url(text):
    for line in text.splitlines():
        if "repository_ssh_url" in line and ":" in line:
            # 形如 `repository_ssh_url: "ssh://git@.../repo.git"` —— split 后去掉首尾引号
            url = line.split(":", 1)[-1].strip().strip('"').strip("'")
            if url:
                return url
    return None


def write_diff_clone(repo, from_commit, to_commit, output, group):
    """
    通过完整 clone 生成 diff：
      - 从远程完整 clone 仓库（保留完整 git 历史和对象）
      - diff 后清理临时目录
      - 完整 clone 保证 GitNexus PDG 分析所需的 git 对象完整性
    """
    remote_url = resolve_remote_url(repo, group)
    print("[fetch_diff] full clone from {}".format(remote_url), file=sys.stderr)

    tmpdir = tempfile.mkdtemp(prefix="agcr-clone-{}-".format(repo))
    try:
        r = run(["git", "clone", "-q", remote_url, tmpdir],
                capture_output=True, text=True)
        if r.returncode != 0:
            print("[fetch_diff] ERROR: clone failed: {}".format(r.stderr.strip()),
                  file=sys.stderr)
            return False, ""

        r = run(["git", "-C", tmpdir, "diff", from_commit, to_commit],
                capture_output=True, text=True)
        if r.returncode != 0:
            print("[fetch_diff] ERROR: diff failed for {}..{}".format(
                from_commit[:12], to_commit[:12]), file=sys.stderr)
            return False, ""
        return True, r.stdout
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── 主逻辑 ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate git diff between two commits.")
    parser.add_argument("--repo",         required=True,  help="repo 名称")
    parser.add_argument("--from",         required=True,  dest="from_commit", help="起始 commit SHA")
    parser.add_argument("--to",           required=True,  dest="to_commit",   help="目标 commit SHA")
    parser.add_argument("--output",       required=True,  help="输出 diff 文件路径")
    parser.add_argument("--local-path",   default=None,   help="本地 repo 绝对路径（优先使用）")
    parser.add_argument("--group",        default=None,   help="代码平台 group（wm / wbqa / shopdiy）")
    parser.add_argument("--provider-out", default=None,   help="将实际使用的 provider 名写入该文件")
    parser.add_argument("--filter-tests", dest="filter_tests", action="store_true",
                        default=True,
                        help="生成 diff 后按 SKILL.md 测试文件排除规则过滤（默认开启）")
    parser.add_argument("--no-filter-tests", dest="filter_tests", action="store_false",
                        help="关闭测试文件过滤，保留 raw diff")
    args = parser.parse_args()

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)

    provider = None
    raw_diff = ""

    # ── 策略 1：本地 repo ────────────────────────────────────────────────────
    if args.local_path and os.path.isdir(os.path.join(args.local_path, ".git")):
        if (commit_exists_locally(args.local_path, args.from_commit) and
                commit_exists_locally(args.local_path, args.to_commit)):
            ok, raw_diff = write_diff_local(args.local_path, args.from_commit,
                                            args.to_commit, args.output)
            if ok:
                provider = "local_git"
                print("[fetch_diff] local_git  {}..{}".format(
                    args.from_commit[:12], args.to_commit[:12]))
        else:
            print("[fetch_diff] local commit(s) missing, fallback to full clone",
                  file=sys.stderr)
    elif args.local_path:
        print("[fetch_diff] local path not a git repo: {}, fallback".format(args.local_path),
              file=sys.stderr)

    # ── 策略 2：完整 clone ─────────────────────────────────────────────────
    if provider is None:
        ok, raw_diff = write_diff_clone(args.repo, args.from_commit, args.to_commit,
                                        args.output, args.group)
        if ok:
            provider = "git_full_clone"
            print("[fetch_diff] git_full_clone  {}..{}".format(
                args.from_commit[:12], args.to_commit[:12]))
        else:
            print("[fetch_diff] FAILED: both local and full clone failed", file=sys.stderr)
            sys.exit(1)

    # ── 测试文件过滤 ─────────────────────────────────────────────────────────
    final_diff = raw_diff
    removed = []
    if args.filter_tests and raw_diff:
        final_diff, removed = filter_test_files(raw_diff)
        if removed:
            print("[fetch_diff] filtered {} test file(s):".format(len(removed)),
                  file=sys.stderr)
            for p in removed[:20]:
                print("[fetch_diff]   - {}".format(p), file=sys.stderr)
            if len(removed) > 20:
                print("[fetch_diff]   ... and {} more".format(len(removed) - 20),
                      file=sys.stderr)

    with open(args.output, "w") as f:
        f.write(final_diff)

    if args.provider_out:
        with open(args.provider_out, "w") as f:
            f.write(provider)


if __name__ == "__main__":
    main()
