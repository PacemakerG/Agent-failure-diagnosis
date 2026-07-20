#!/usr/bin/env python3
"""
ast_hunk_split.py — 确定性预处理脚本，为 LLM Hunk 切分提供硬约束建议。

解析 unified diff 文件，按 AST 方法签名边界生成三类建议：
  1. split_suggestions: 单个物理 hunk 跨 2+ 方法签名 → 拆分点 + 方法名
  2. merge_suggestions: 相邻物理 hunk 同属一方法且间隙 ≤ 3 行 → 合并
  3. oversized_warnings: 物理 hunk 变更行数 > max-lines → 警告

支持语言：Java, Kotlin, Go, Python, TypeScript, JavaScript
纯 Python 标准库实现，无外部依赖。

用法：
  python3 ast_hunk_split.py \
    --diff     /path/to/repo-one-shot-to-target-final.diff \
    --max-lines 80 \
    --output   /path/to/ast-split-suggestions.json
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict

# ── 语言识别 ─────────────────────────────────────────────────────────────────

LANG_BY_EXT = {
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".go": "go",
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mts": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
}

SUPPORTED_LANGS = {"java", "kotlin", "go", "python", "typescript", "javascript"}

# ── 方法签名正则 ──────────────────────────────────────────────────────────────
# 每种语言一组正则，匹配新增行（+ 前缀去掉后）中的方法/函数签名行。
# 设计原则：只匹配行的前缀部分，允许修饰符、注解、返回类型等前缀灵活组合。

# Java / Kotlin 方法签名
# [修饰符] [注解] [返回类型] 方法名(参数列表) [throws ...] {
# Kotlin: [修饰符] fun 方法名(参数列表) [: 返回类型] {
_JAVA_KW = ('public|private|protected|internal|open|override|final|'
            'static|abstract|synchronized|native|sealed|companion|'
            'lateinit|inline|suspend|operator|infix|tailrec|default')
_JAVA_METHOD_RE = re.compile(
    r'^\s*(?:@\w+(?:\([^)]*\))?\s*)*'           # 注解（可选）
    r'(?:(?:' + _JAVA_KW + r')\s+)*'              # 修饰符（可选，可多个）
    r'(?:@\w+(?:\([^)]*\))?\s*)*'               # 更多注解
    r'(?:fun\s+)?'                               # Kotlin fun 关键字（可选）
    r'(?:[A-Za-z_][\w<>\[\],?.\s]*?\s+)?'        # 返回类型（泛型/数组/可空，可选——构造方法无返回类型）
    r'([A-Za-z_]\w*)\s*'                         # 方法名 (group 1)
    r'\([^)]*\)'                                 # 参数列表
    r'(?:\s*:\s*[\w<>\[\]?]+)?'                  # Kotlin 返回类型（可选）
    r'(?:\s*throws\s+[\w,\s.]+)?'                # Java throws（可选）
    r'\s*\{?\s*$'                                # 可选的 { 或行尾
)

# Go 函数签名
# func [receiver.] MethodName(参数) [返回类型] {
_GO_FUNC_RE = re.compile(
    r'^\s*func\s+'
    r'(?:\([^)]*\)\s*)?'                         # 接收者（可选）
    r'([A-Za-z_]\w*)\s*'                         # 函数名 (group 1)
    r'\([^)]*\)'                                 # 参数列表
    r'(?:\s*[\w<>\[\]*.(),\s]*?)?'              # 返回类型（可选）
    r'\s*\{?\s*$'
)

# Python 函数签名
# [装饰器] def func_name(参数):
_PY_FUNC_RE = re.compile(
    r'^\s*(?:@\w+(?:\([^)]*\))?\s*)*'
    r'def\s+'
    r'([A-Za-z_]\w*)\s*'                         # 函数名 (group 1)
    r'\([^)]*\)'
    r'\s*(?:->\s*[\w.\[\],\s]+?)?\s*'            # 返回类型（Python 3，可选）
    r':\s*$'                                     # 冒号结尾
)

# TypeScript / JavaScript 函数签名
# [修饰符] [async] function funcName(参数) [: Type] {
# 或 [修饰符] funcName(参数) [: Type] {   （类方法，无 function 关键字）
_TS_METHOD_RE = re.compile(
    r'^\s*(?:(?:public|private|protected|static|async|override|readonly|get|set|abstract)\s+)*'
    r'(?:function\s+)?'
    r'([A-Za-z_$][\w$]*)\s*'
    r'\([^)]*\)'
    r'(?:\s*:\s*[\w<>\[\],?|.{}()\s]+?)?'
    r'\s*\{?\s*$'
)

# TypeScript / JavaScript 箭头函数赋值
# [修饰符] propName = (参数) => {
_TS_ARROW_RE = re.compile(
    r'^\s*(?:public|private|protected|static|readonly|async)?\s*'
    r'([A-Za-z_$][\w$]*)\s*'
    r'=\s*\([^)]*\)\s*(?::\s*[\w<>\[\],?|.{}\s]+?)?\s*=>\s*\{?\s*$'
)

LANG_PATTERNS = {
    "java": [_JAVA_METHOD_RE],
    "kotlin": [_JAVA_METHOD_RE],  # Kotlin 复用 Java 正则（含 fun 关键字处理）
    "go": [_GO_FUNC_RE],
    "python": [_PY_FUNC_RE],
    "typescript": [_TS_METHOD_RE, _TS_ARROW_RE],
    "javascript": [_TS_METHOD_RE, _TS_ARROW_RE],
}

# ── Diff 解析 ─────────────────────────────────────────────────────────────────

RE_DIFF_HEADER = re.compile(r'^diff --git "?a/(.+?)"? "?b/(.+?)"?\s*$')
RE_HUNK_HEADER = re.compile(
    r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$'
)


def detect_lang(file_path):
    """根据文件扩展名检测语言。返回语言名字符串或 None。"""
    _, ext = os.path.splitext(file_path)
    return LANG_BY_EXT.get(ext.lower())


def parse_diff(diff_content):
    """
    解析 unified diff 内容，返回文件级结构。

    返回: [
        {
            "old_path": "a/foo.java",
            "new_path": "b/foo.java",
            "lang": "java",
            "hunks": [
                {
                    "old_start": 10, "old_count": 5,
                    "new_start": 10, "new_count": 8,
                    "changed_lines": 6,  # + 和 - 行数之和
                    "new_lines_text": ["line1", "line2", ...],  # 新增/保留行（+ 和 空格前缀去掉）
                    "added_line_numbers": [10, 11, 12, ...],  # 新文件中的行号
                },
                ...
            ],
        },
        ...
    ]
    """
    files = []
    current_file = None
    current_hunk = None

    for line in diff_content.splitlines():
        # 文件头
        m = RE_DIFF_HEADER.match(line)
        if m:
            if current_hunk and current_file:
                current_file["hunks"].append(current_hunk)
                current_hunk = None
            if current_file:
                files.append(current_file)
            old_path = m.group(1)
            new_path = m.group(2)
            lang = detect_lang(new_path)
            current_file = {
                "old_path": old_path,
                "new_path": new_path,
                "lang": lang,
                "hunks": [],
            }
            current_hunk = None
            continue

        # hunk 头 @@ -old,count +new,count @@ context
        m = RE_HUNK_HEADER.match(line)
        if m:
            if current_hunk and current_file:
                current_file["hunks"].append(current_hunk)
            old_start = int(m.group(1))
            old_count = int(m.group(2)) if m.group(2) else 1
            new_start = int(m.group(3))
            new_count = int(m.group(4)) if m.group(4) else 1
            current_hunk = {
                "old_start": old_start,
                "old_count": old_count,
                "new_start": new_start,
                "new_count": new_count,
                "changed_lines": 0,
                "new_lines_text": [],
                "added_line_numbers": [],
                "added_lines_with_num": [],  # [(new_line_num, text), ...] 仅 + 行
                "context_lines_with_num": [],  # [(new_line_num, text), ...] 仅空格行
            }
            continue

        if current_hunk is None:
            continue

        # diff 内容行
        if line.startswith("+++") or line.startswith("---"):
            # 文件路径行，跳过
            continue
        elif line.startswith("+"):
            # 新增行
            text = line[1:]
            new_line_num = current_hunk["new_start"] + len(current_hunk["new_lines_text"])
            current_hunk["changed_lines"] += 1
            current_hunk["new_lines_text"].append(text)
            current_hunk["added_line_numbers"].append(new_line_num)
            current_hunk["added_lines_with_num"].append((new_line_num, text))
        elif line.startswith("-"):
            # 删除行
            current_hunk["changed_lines"] += 1
            # 删除行不算入 new_lines_text（它不在新文件中）
        elif line.startswith(" "):
            # 上下文行（保留行）
            text = line[1:]
            new_line_num = current_hunk["new_start"] + len(current_hunk["new_lines_text"])
            current_hunk["new_lines_text"].append(text)
            current_hunk["context_lines_with_num"].append((new_line_num, text))
        # 跳过 \ No newline at end of file 等

    # 收尾
    if current_hunk and current_file:
        current_file["hunks"].append(current_hunk)
    if current_file:
        files.append(current_file)

    return files


# ── 方法签名检测 ──────────────────────────────────────────────────────────────

def detect_methods_in_hunk(hunk, lang):
    """
    检测一个物理 hunk 中包含的方法签名。
    返回: [{"method_name": "foo", "line_number": 42, "line_text": "..."}, ...]
    按行号排序。
    """
    if lang not in SUPPORTED_LANGS:
        return []

    patterns = LANG_PATTERNS.get(lang, [])
    if not patterns:
        return []

    methods = []
    # 检查所有新增行和上下文行
    all_lines = hunk["added_lines_with_num"] + hunk["context_lines_with_num"]
    all_lines.sort(key=lambda x: x[0])

    for line_num, text in all_lines:
        stripped = text.lstrip()
        # 排除以语句关键字开头的行（不是方法定义）
        if re.match(r'(return|if|for|while|switch|catch|try|finally|throw|throws|new|super|this|else|elif|with|match|case|when|do|yield|break|continue|assert|await)\b', stripped):
            continue
        for pat in patterns:
            m = pat.match(text)
            if m:
                method_name = m.group(1)
                # 过滤掉控制流关键字误匹配
                if method_name in ("if", "for", "while", "switch", "catch",
                                   "return", "new", "class", "interface",
                                   "enum", "struct", "try", "finally",
                                   "elif", "else", "with", "match", "case",
                                   "when", "do", "throw", "throws"):
                    continue
                methods.append({
                    "method_name": method_name,
                    "line_number": line_num,
                    "line_text": text.strip(),
                })
                break  # 一行只匹配一个模式

    return methods


# ── 建议生成 ──────────────────────────────────────────────────────────────────

def generate_split_suggestions(file_entry):
    """
    生成 split 建议：单个物理 hunk 跨 2+ 方法签名时，输出拆分点。

    返回: [
        {
            "file": "b/foo.java",
            "hunk_index": 0,
            "old_start": 10, "old_count": 5,
            "new_start": 10, "new_count": 20,
            "methods": ["methodA", "methodB"],
            "split_points": [
                {"line_number": 25, "method_name": "methodB", "reason": "method_boundary"},
            ],
        },
        ...
    ]
    """
    lang = file_entry["lang"]
    if lang not in SUPPORTED_LANGS:
        return []

    suggestions = []
    for idx, hunk in enumerate(file_entry["hunks"]):
        methods = detect_methods_in_hunk(hunk, lang)
        if len(methods) < 2:
            continue

        # 拆分点：从第二个方法开始，每个方法签名行就是一个拆分点
        split_points = []
        for m in methods[1:]:
            split_points.append({
                "line_number": m["line_number"],
                "method_name": m["method_name"],
                "reason": "method_boundary",
            })

        suggestions.append({
            "file": file_entry["new_path"],
            "hunk_index": idx,
            "old_start": hunk["old_start"],
            "old_count": hunk["old_count"],
            "new_start": hunk["new_start"],
            "new_count": hunk["new_count"],
            "methods": [m["method_name"] for m in methods],
            "method_details": methods,
            "split_points": split_points,
        })

    return suggestions


def generate_merge_suggestions(file_entry, max_gap=3):
    """
    生成 merge 建议：相邻物理 hunk 同属一方法且间隙 ≤ 3 行时合并。

    返回: [
        {
            "file": "b/foo.java",
            "hunk_indices": [0, 1],
            "method": "methodA",
            "gap_lines": 2,
            "reason": "same_method_adjacent",
            "hunks": [
                {"index": 0, "new_start": 10, "new_count": 5},
                {"index": 1, "new_start": 18, "new_count": 3},
            ],
        },
        ...
    ]
    """
    lang = file_entry["lang"]
    if lang not in SUPPORTED_LANGS:
        return []

    hunks = file_entry["hunks"]
    if len(hunks) < 2:
        return []

    suggestions = []
    for i in range(len(hunks) - 1):
        hunk_a = hunks[i]
        hunk_b = hunks[i + 1]

        # 计算间隙：hunk_b 的 new_start - (hunk_a 的 new_start + new_count)
        a_end = hunk_a["new_start"] + hunk_a["new_count"]
        gap = hunk_b["new_start"] - a_end

        if gap < 0 or gap > max_gap:
            continue

        # 检测两个 hunk 的方法
        methods_a = detect_methods_in_hunk(hunk_a, lang)
        methods_b = detect_methods_in_hunk(hunk_b, lang)

        # 判断是否同属一方法：
        # 1. 两个 hunk 各自只检测到 1 个方法，且方法名相同
        # 2. 或一个 hunk 没检测到方法但另一个有，且间隙 ≤ 3（可能是同一方法内的连续改动）
        # 3. 或两个 hunk 检测到的方法集合有交集

        names_a = {m["method_name"] for m in methods_a}
        names_b = {m["method_name"] for m in methods_b}
        common = names_a & names_b

        merge_method = None
        reason = None

        if common:
            merge_method = next(iter(common))
            reason = "same_method_adjacent"
        elif len(names_a) == 1 and len(names_b) == 0 and gap <= max_gap:
            # hunk_b 在 hunk_a 的方法内（无新方法签名）
            merge_method = next(iter(names_a))
            reason = "same_method_continuation"
        elif len(names_b) == 1 and len(names_a) == 0 and gap <= max_gap:
            merge_method = next(iter(names_b))
            reason = "same_method_continuation"
        elif len(names_a) == 0 and len(names_b) == 0 and gap <= max_gap:
            # 两个 hunk 都没检测到方法签名，但间隙很小，可能是类字段/顶层代码的连续改动
            merge_method = None
            reason = "adjacent_no_method_small_gap"

        if merge_method or reason:
            suggestions.append({
                "file": file_entry["new_path"],
                "hunk_indices": [i, i + 1],
                "method": merge_method,
                "gap_lines": gap,
                "reason": reason,
                "hunks": [
                    {
                        "index": i,
                        "new_start": hunk_a["new_start"],
                        "new_count": hunk_a["new_count"],
                    },
                    {
                        "index": i + 1,
                        "new_start": hunk_b["new_start"],
                        "new_count": hunk_b["new_count"],
                    },
                ],
            })

    return suggestions


def generate_oversized_warnings(file_entry, max_lines):
    """
    生成 oversized 警告：物理 hunk 变更行数 > max_lines。

    返回: [
        {
            "file": "b/foo.java",
            "hunk_index": 0,
            "old_start": 10, "old_count": 5,
            "new_start": 10, "new_count": 90,
            "changed_lines": 95,
            "max_lines": 80,
            "has_split_suggestion": false,
        },
        ...
    ]
    """
    warnings = []
    for idx, hunk in enumerate(file_entry["hunks"]):
        if hunk["changed_lines"] > max_lines:
            warnings.append({
                "file": file_entry["new_path"],
                "hunk_index": idx,
                "old_start": hunk["old_start"],
                "old_count": hunk["old_count"],
                "new_start": hunk["new_start"],
                "new_count": hunk["new_count"],
                "changed_lines": hunk["changed_lines"],
                "max_lines": max_lines,
            })

    return warnings


# ── 主流程 ────────────────────────────────────────────────────────────────────

def analyze_diff(diff_path, max_lines=80):
    """
    分析 diff 文件，生成 split/merge/oversized 三类建议。
    返回完整的结果字典。
    """
    with open(diff_path, "r", encoding="utf-8", errors="replace") as f:
        diff_content = f.read()

    files = parse_diff(diff_content)

    all_splits = []
    all_merges = []
    all_oversized = []
    file_summaries = []

    for file_entry in files:
        lang = file_entry["lang"]
        new_path = file_entry["new_path"]

        # 统计信息
        hunk_count = len(file_entry["hunks"])
        supported = lang in SUPPORTED_LANGS

        file_summaries.append({
            "file": new_path,
            "lang": lang,
            "supported": supported,
            "hunk_count": hunk_count,
        })

        if not supported:
            continue

        splits = generate_split_suggestions(file_entry)
        merges = generate_merge_suggestions(file_entry)
        oversized = generate_oversized_warnings(file_entry, max_lines)

        # 给 oversized 补充 has_split_suggestion 标记
        split_hunk_indices = {s["hunk_index"] for s in splits}
        for w in oversized:
            w["has_split_suggestion"] = w["hunk_index"] in split_hunk_indices

        all_splits.extend(splits)
        all_merges.extend(merges)
        all_oversized.extend(oversized)

    result = {
        "diff_file": os.path.basename(diff_path),
        "max_lines": max_lines,
        "summary": {
            "total_files": len(files),
            "supported_files": sum(1 for f in file_summaries if f["supported"]),
            "total_hunks": sum(f["hunk_count"] for f in file_summaries),
            "split_count": len(all_splits),
            "merge_count": len(all_merges),
            "oversized_count": len(all_oversized),
        },
        "file_summaries": file_summaries,
        "split_suggestions": all_splits,
        "merge_suggestions": all_merges,
        "oversized_warnings": all_oversized,
    }

    return result


def main():
    parser = argparse.ArgumentParser(
        description="AST-based hunk split suggestions for AGCR attribution analysis."
    )
    parser.add_argument(
        "--diff", required=True,
        help="Path to the unified diff file to analyze."
    )
    parser.add_argument(
        "--max-lines", type=int, default=80,
        help="Maximum changed lines per hunk before oversized warning (default: 80)."
    )
    parser.add_argument(
        "--output", required=True,
        help="Path to the output JSON file."
    )
    args = parser.parse_args()

    if not os.path.isfile(args.diff):
        print(f"Error: diff file not found: {args.diff}", file=sys.stderr)
        sys.exit(1)

    result = analyze_diff(args.diff, args.max_lines)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    s = result["summary"]
    print(
        f"ast_hunk_split: {s['total_files']} files, {s['total_hunks']} hunks, "
        f"{s['split_count']} splits, {s['merge_count']} merges, "
        f"{s['oversized_count']} oversized → {args.output}"
    )


if __name__ == "__main__":
    main()
