#!/usr/bin/env python3
"""
Deterministic hunk splitter: parse diff files into hunk-list.json.

Reads one-shot-to-target-final.diff for each repo, splits into hunks
(preserving +/- prefixes in diff_content), applies exclusion rules,
and outputs hunk-list.json with correct old_start/new_start/removed_lines/
added_lines/before_code/after_code.

Usage:
  python3 split_hunks.py \
    --repos-meta  $OUTPUT_DIR/repos-meta.json \
    --run-dir     $OUTPUT_DIR \
    --output      $OUTPUT_DIR/hunks/hunk-list.json
"""
import argparse
import json
import os
import re
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
try:
    from filter_excluded_files import classify_file
    _HAS_FILTER = True
except ImportError:
    _HAS_FILTER = False
try:
    from symbol_extract import detect_lang, build_symbol_index
    _HAS_SYMBOL_EXTRACT = True
except ImportError:
    _HAS_SYMBOL_EXTRACT = False

RE_FILE_HEADER = re.compile(r'^diff --git "?a/(.+?)"? "?b/(.+?)"?$', re.MULTILINE)
RE_HUNK_HEADER = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')
RE_NEW_FILE = re.compile(r'^new file mode')
RE_DELETED_FILE = re.compile(r'^deleted file mode')
RE_BINARY = re.compile(r'^Binary files')


def _repo_to_prefix(repo_name):
    for suffix in ("_server", "_client", "_api", "_promo"):
        if repo_name.endswith(suffix):
            return suffix[1:]
    parts = repo_name.rsplit("_", 1)
    return parts[-1] if len(parts) > 1 else repo_name[:6]


def _fallback_symbol_hint(file_path):
    """兜底实现：语言不受支持 / symbol_extract 不可用 / 未命中任何符号时，
    退化为文件名，symbol_type 标记为 "file" 以便下游区分归属精度。"""
    basename = os.path.basename(file_path)
    name = basename.rsplit(".", 1)[0] if "." in basename else basename
    return name, name, "file"


def _build_file_symbol_index(file_block, file_path):
    """
    基于整个文件的 diff 内容（file_block，含该文件所有物理 hunk）构建
    "新文件视角行号 -> {method, class}" 的符号索引。

    实现说明：
      - diff 只包含被 unified diff 上下文覆盖到的行（默认前后各 3 行），
        本地仓库不保证在本脚本运行时仍然存在（clone 用后即删的兜底策略），
        因此不依赖读取完整源文件，只能基于 diff 文本本身重建行号序列。
      - 按"新文件"视角计算行号：context 行（前缀为空格）和新增行（+）
        都会出现在新文件中并占用行号；删除行（-）不占用新文件行号，跳过。
      - 序列可能是稀疏的（hunk 之间有未被 diff 覆盖的 gap），
        build_symbol_index 对此有已知的精度局限（见其 docstring），
        但仍显著优于"仅用文件名代替"的粗糙实现。

    返回：symbol_index dict（可能为空 dict，表示无法构建，调用方应回退到
    _fallback_symbol_hint）。
    """
    if not _HAS_SYMBOL_EXTRACT:
        return {}
    lang = detect_lang(file_path)
    if not lang:
        return {}

    numbered_lines = []
    for hunk_block in re.split(r'(?=^@@ )', file_block, flags=re.MULTILINE):
        hm = RE_HUNK_HEADER.match(hunk_block)
        if not hm:
            continue
        new_start = int(hm.group(3))
        cur_line_no = new_start
        for line in hunk_block.split("\n")[1:]:
            if line.startswith("-") and not line.startswith("---"):
                continue  # 删除行不占用新文件行号
            if line.startswith("+") and not line.startswith("+++"):
                numbered_lines.append((cur_line_no, line[1:]))
                cur_line_no += 1
            elif line.startswith(" "):
                numbered_lines.append((cur_line_no, line[1:]))
                cur_line_no += 1
            # 其余（如 "\ No newline at end of file"、空行）不占用行号

    if not numbered_lines:
        return {}
    numbered_lines.sort(key=lambda x: x[0])
    return build_symbol_index(numbered_lines, lang)


def _derive_symbol_hint(file_path, symbol_index, lookup_line):
    """
    优先用 symbol_index（基于 diff 内容解析出的真实方法名/类名）在
    lookup_line 行号处查表；查不到（该行之前没有任何方法/类声明可见，例如
    hunk 出现在文件开头的 import 区域）时回退到文件名兜底。

    lookup_line 必须是 hunk 中"第一个真正变更行"的新文件行号
    （见 _parse_hunk_block 的 first_change_new_line），而不是 hunk 的
    new_start —— new_start 只是 unified diff 上下文窗口起点，常常落在
    上一个方法的尾部或方法间空行上（此时 method/class 均为 None），
    用它查表会系统性地丢失方法级归属、错误退化为类级或文件级。

    返回 (symbol_hint, enclosing_class, symbol_type)：
      - 命中方法名：symbol_type="method"，enclosing_class 为其外围类名
        （若无外围类，如顶层函数，则退化为方法名本身，保持字段非空）。
      - 只命中类名（hunk 落在类体内但不在任何方法体内，如字段声明/静态
        初始化块）：symbol_type="class"，symbol_hint 和 enclosing_class
        均为该类名。
      - 均未命中：回退到文件名，symbol_type="file"。
    """
    if symbol_index:
        entry = symbol_index.get(lookup_line)
        if entry is None:
            # 精确行号未命中（理论上不常发生，因 lookup_line 必然是 diff 中
            # 出现过的行），做一次向前最近邻查找作为兜底。
            candidates = [ln for ln in symbol_index if ln <= lookup_line]
            if candidates:
                entry = symbol_index[max(candidates)]
        if entry:
            method_name = entry.get("method")
            class_name = entry.get("class")
            if method_name:
                return method_name, (class_name or method_name), "method"
            if class_name:
                return class_name, class_name, "class"
    return _fallback_symbol_hint(file_path)


def _parse_hunk_block(hunk_block):
    hm = RE_HUNK_HEADER.match(hunk_block)
    if not hm:
        return None
    old_start = int(hm.group(1))
    old_lines = int(hm.group(2)) if hm.group(2) else 1
    new_start = int(hm.group(3))
    new_lines = int(hm.group(4)) if hm.group(4) else 1
    lines = hunk_block.split("\n")
    diff_content_parts = [lines[0]]
    before_parts = []
    after_parts = []
    removed = 0
    added = 0
    # 计算"新文件视角"下第一个真正变更行（+/- 行）所在的行号，而不是
    # hunk 的 new_start——new_start 只是 unified diff 上下文窗口的起点
    # （默认含前 3 行未改动 context），若直接用它去查符号索引，很容易落在
    # 上一个方法的尾部或方法间的空行上，导致归属到错误的（甚至是 None 的）
    # 方法/类。first_change_new_line 才是真正应该归属的位置。
    cur_new_line = new_start
    first_change_new_line = None
    for line in lines[1:]:
        if not line:
            continue
        diff_content_parts.append(line)
        if line.startswith("-") and not line.startswith("---"):
            before_parts.append(line[1:])
            removed += 1
            if first_change_new_line is None:
                # 删除行不占用新文件行号，其"归属位置"取当前光标处
                # （即紧邻的新文件行号，等价于该删除发生的插入点）。
                first_change_new_line = cur_new_line
            continue
        if line.startswith("+") and not line.startswith("+++"):
            after_parts.append(line[1:])
            added += 1
            if first_change_new_line is None:
                first_change_new_line = cur_new_line
            cur_new_line += 1
        elif line.startswith(" "):
            cur_new_line += 1
    if first_change_new_line is None:
        first_change_new_line = new_start
    return {
        "old_start": old_start, "old_lines": old_lines,
        "new_start": new_start, "new_lines": new_lines,
        "first_change_new_line": first_change_new_line,
        "removed_lines": removed, "added_lines": added,
        "diff_content": "\n".join(diff_content_parts),
        "before_code": "\n".join(before_parts).strip(),
        "after_code": "\n".join(after_parts).strip(),
    }


def _determine_change_type(file_block):
    for line in file_block.split("\n"):
        if RE_NEW_FILE.match(line):
            return "add"
        if RE_DELETED_FILE.match(line):
            return "delete"
        if RE_BINARY.match(line):
            return "binary"
    return "modify"


def _split_diff_file(diff_path, repo, prefix):
    if not os.path.isfile(diff_path):
        return []
    with open(diff_path, encoding="utf-8", errors="replace") as f:
        diff_text = f.read()
    if not diff_text.strip():
        return []
    file_blocks = re.split(r'(?=^diff --git )', diff_text, flags=re.MULTILINE)
    hunks = []
    counter = 0
    for file_block in file_blocks:
        if not file_block.strip():
            continue
        fm = RE_FILE_HEADER.match(file_block)
        if not fm:
            continue
        file_path = fm.group(2)
        change_type = _determine_change_type(file_block)
        excluded = False
        exclude_reason = None
        if _HAS_FILTER:
            excluded, exclude_reason, _ = classify_file(file_path, file_block)

        # 先对整个文件的 diff 内容扫描一次，构建"新文件行号 -> 方法名/类名"的
        # 符号索引，避免对每个 hunk 重复扫描（且必须基于整份 file_block 才能
        # 让跨 hunk 的类/方法声明正确覆盖后续 hunk 所在的行号）。
        symbol_index = _build_file_symbol_index(file_block, file_path)
        hunk_splits = re.split(r'(?=^@@ )', file_block, flags=re.MULTILINE)
        for hunk_block in hunk_splits:
            if not hunk_block.strip() or not RE_HUNK_HEADER.match(hunk_block):
                continue
            parsed = _parse_hunk_block(hunk_block)
            if not parsed:
                continue
            counter += 1
            sym, enc, sym_type = _derive_symbol_hint(
                file_path, symbol_index, parsed["first_change_new_line"]
            )
            hunks.append({
                "hunk_id": f"{prefix}-H{counter:03d}",
                "repo": repo,
                "file_path": file_path,
                "change_type": change_type,
                "diff_content": parsed["diff_content"],
                "symbol_hint": sym,
                "symbol_type": sym_type,
                "enclosing_class": enc,
                "source_commits": [],
                "ast_split_suggestion": {"split": False, "merge_with": None},
                "merge_suggestions": [],
                "design_item_ref": None,
                "excluded": excluded,
                "exclude_reason": exclude_reason if excluded else None,
                "old_start": parsed["old_start"],
                "old_lines": parsed["old_lines"],
                "new_start": parsed["new_start"],
                "new_lines": parsed["new_lines"],
                "removed_lines": parsed["removed_lines"],
                "added_lines": parsed["added_lines"],
                "before_code": parsed["before_code"],
                "after_code": parsed["after_code"],
            })
    return hunks


def split_hunks(repos_meta, run_dir):
    all_hunks = []
    for r in repos_meta.get("repos", []):
        repo = r["repo"]
        prefix = _repo_to_prefix(repo)
        diff_path = os.path.join(run_dir, "diffs", repo, f"{repo}-one-shot-to-target-final.diff")
        repo_hunks = _split_diff_file(diff_path, repo, prefix)
        all_hunks.extend(repo_hunks)
        total = len(repo_hunks)
        exc = sum(1 for h in repo_hunks if h["excluded"])
        print(f"[split_hunks] {repo}: {total} hunks ({total-exc} valid, {exc} excluded)", file=sys.stderr)
    return all_hunks


def main():
    ap = argparse.ArgumentParser(description="Deterministic hunk splitter")
    ap.add_argument("--repos-meta", required=True)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    with open(args.repos_meta, encoding="utf-8") as f:
        repos_meta = json.load(f)
    hunks = split_hunks(repos_meta, args.run_dir)
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(hunks, f, ensure_ascii=False, indent=2)
    total = len(hunks)
    exc = sum(1 for h in hunks if h["excluded"])
    valid = total - exc
    rm = sum(h["removed_lines"] for h in hunks if not h["excluded"])
    al = sum(h["added_lines"] for h in hunks if not h["excluded"])
    hb = sum(1 for h in hunks if not h["excluded"] and h["before_code"])
    ha = sum(1 for h in hunks if not h["excluded"] and h["after_code"])
    print(f"\n[split_hunks] Total: {total} hunks ({valid} valid, {exc} excluded)", file=sys.stderr)
    print(f"[split_hunks] removed={rm}, added={al}, before_code={hb}/{valid}, after_code={ha}/{valid}", file=sys.stderr)
    print(f"[split_hunks] Written to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
