#!/usr/bin/env python3
"""
symbol_extract.py — 共享符号提取模块：语言识别 + 方法签名 / 类型声明正则。

被 ast_hunk_split.py（方法级 split/merge 建议）和 split_hunks.py（symbol_hint /
enclosing_class 回填）共同复用，避免正则重复定义、口径不一致。

纯 Python 标准库实现，无外部依赖。
"""

import os
import re

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


def detect_lang(file_path):
    """根据文件扩展名检测语言。返回语言名字符串或 None。"""
    _, ext = os.path.splitext(file_path)
    return LANG_BY_EXT.get(ext.lower())


# ── 方法签名正则 ──────────────────────────────────────────────────────────────
# 每种语言一组正则，匹配一行代码（+ / - / 空格前缀已去掉后）中的方法/函数签名行。
# 设计原则：只匹配行的前缀部分，允许修饰符、注解、返回类型等前缀灵活组合。

_JAVA_KW = ('public|private|protected|internal|open|override|final|'
            'static|abstract|synchronized|native|sealed|companion|'
            'lateinit|inline|suspend|operator|infix|tailrec|default')
_JAVA_METHOD_RE = re.compile(
    r'^\s*(?:@\w+(?:\([^)]*\))?\s*)*'            # 注解（可选）
    r'(?:(?:' + _JAVA_KW + r')\s+)*'              # 修饰符（可选，可多个）
    r'(?:@\w+(?:\([^)]*\))?\s*)*'                # 更多注解
    r'(?:fun\s+)?'                                # Kotlin fun 关键字（可选）
    r'(?:[A-Za-z_][\w<>\[\],?.\s]*?\s+)?'         # 返回类型（泛型/数组/可空，可选——构造方法无返回类型）
    r'([A-Za-z_]\w*)\s*'                          # 方法名 (group 1)
    r'\([^)]*\)'                                  # 参数列表
    r'(?:\s*:\s*[\w<>\[\]?]+)?'                   # Kotlin 返回类型（可选）
    r'(?:\s*throws\s+[\w,\s.]+)?'                 # Java throws（可选）
    r'\s*\{?\s*$'                                 # 可选的 { 或行尾
)

_GO_FUNC_RE = re.compile(
    r'^\s*func\s+'
    r'(?:\([^)]*\)\s*)?'                          # 接收者（可选）
    r'([A-Za-z_]\w*)\s*'                          # 函数名 (group 1)
    r'\([^)]*\)'                                  # 参数列表
    r'(?:\s*[\w<>\[\]*.(),\s]*?)?'                # 返回类型（可选）
    r'\s*\{?\s*$'
)

_PY_FUNC_RE = re.compile(
    r'^\s*(?:@\w+(?:\([^)]*\))?\s*)*'
    r'def\s+'
    r'([A-Za-z_]\w*)\s*'                          # 函数名 (group 1)
    r'\([^)]*\)'
    r'\s*(?:->\s*[\w.\[\],\s]+?)?\s*'             # 返回类型（Python 3，可选）
    r':\s*$'                                      # 冒号结尾
)

_TS_METHOD_RE = re.compile(
    r'^\s*(?:(?:public|private|protected|static|async|override|readonly|get|set|abstract)\s+)*'
    r'(?:function\s+)?'
    r'([A-Za-z_$][\w$]*)\s*'
    r'\([^)]*\)'
    r'(?:\s*:\s*[\w<>\[\],?|.{}()\s]+?)?'
    r'\s*\{?\s*$'
)

_TS_ARROW_RE = re.compile(
    r'^\s*(?:public|private|protected|static|readonly|async)?\s*'
    r'([A-Za-z_$][\w$]*)\s*'
    r'=\s*\([^)]*\)\s*(?::\s*[\w<>\[\],?|.{}\s]+?)?\s*=>\s*\{?\s*$'
)

LANG_METHOD_PATTERNS = {
    "java": [_JAVA_METHOD_RE],
    "kotlin": [_JAVA_METHOD_RE],  # Kotlin 复用 Java 正则（含 fun 关键字处理）
    "go": [_GO_FUNC_RE],
    "python": [_PY_FUNC_RE],
    "typescript": [_TS_METHOD_RE, _TS_ARROW_RE],
    "javascript": [_TS_METHOD_RE, _TS_ARROW_RE],
}

_CONTROL_FLOW_KEYWORDS = (
    "if", "for", "while", "switch", "catch", "return", "new", "class",
    "interface", "enum", "struct", "try", "finally", "elif", "else",
    "with", "match", "case", "when", "do", "throw", "throws",
)

_STATEMENT_PREFIX_RE = re.compile(
    r'^(return|if|for|while|switch|catch|try|finally|throw|throws|new|'
    r'super|this|else|elif|with|match|case|when|do|yield|break|continue|'
    r'assert|await)\b'
)

# 纯注解行（如 @ExtensionImpl(name = "...", bizCode = {"..."})）：整行只是一个
# 注解调用，后面没有跟随方法签名。_JAVA_METHOD_RE 的注解前缀部分是可选的，
# 若不做这层过滤，容易把注解参数里的片段误当成"返回类型 + 方法名"匹配掉
# （尤其当注解参数包含花括号/嵌套引号时）。判断依据：整行掐头（前导 @ 注解）
# 去尾后，剩余内容为空，说明该行纯粹是注解，不含方法签名。
_LEADING_ANNOTATION_RE = re.compile(r'^\s*(?:@\w+(?:\([^)]*\))?\s*)+$')


def match_method_name(line_text, lang):
    """
    尝试用给定语言的方法签名正则匹配一行代码（前缀已去掉 +/-/空格）。
    返回方法名字符串，或 None（不匹配 / 是控制流关键字误匹配 / 纯注解行）。
    """
    patterns = LANG_METHOD_PATTERNS.get(lang)
    if not patterns:
        return None
    stripped = line_text.lstrip()
    if _STATEMENT_PREFIX_RE.match(stripped):
        return None
    if lang in ("java", "kotlin") and _LEADING_ANNOTATION_RE.match(line_text):
        return None
    for pat in patterns:
        m = pat.match(line_text)
        if m:
            name = m.group(1)
            if name in _CONTROL_FLOW_KEYWORDS:
                continue
            return name
    return None


# ── 类型声明（类/接口/枚举/结构体）正则 ───────────────────────────────────────
# 用于确定 enclosing_class：识别一行是否是类型声明行，提取类型名。

# Java / Kotlin: [修饰符] class|interface|enum|object Name [<T>] [extends/implements ...] {
_JAVA_TYPE_RE = re.compile(
    r'^\s*(?:@\w+(?:\([^)]*\))?\s*)*'
    r'(?:(?:' + _JAVA_KW + r')\s+)*'
    r'(?:class|interface|enum|object|annotation\s+class|data\s+class)\s+'
    r'([A-Za-z_]\w*)'
)

# Go: type Name struct|interface {
_GO_TYPE_RE = re.compile(
    r'^\s*type\s+([A-Za-z_]\w*)\s+(?:struct|interface)\b'
)

# Python: class Name[(Base, ...)]:
_PY_TYPE_RE = re.compile(
    r'^\s*class\s+([A-Za-z_]\w*)'
)

# TypeScript / JavaScript: [export] [default] [abstract] class|interface Name
_TS_TYPE_RE = re.compile(
    r'^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?'
    r'(?:class|interface)\s+([A-Za-z_$][\w$]*)'
)

LANG_TYPE_PATTERNS = {
    "java": [_JAVA_TYPE_RE],
    "kotlin": [_JAVA_TYPE_RE],
    "go": [_GO_TYPE_RE],
    "python": [_PY_TYPE_RE],
    "typescript": [_TS_TYPE_RE],
    "javascript": [_TS_TYPE_RE],
}


def match_type_name(line_text, lang):
    """
    尝试用给定语言的类型声明正则匹配一行代码。
    返回类型名字符串（类/接口/枚举/结构体名），或 None。
    """
    patterns = LANG_TYPE_PATTERNS.get(lang)
    if not patterns:
        return None
    for pat in patterns:
        m = pat.match(line_text)
        if m:
            return m.group(1)
    return None


# ── 缩进层级（用于 Python 判断类体范围结束） ──────────────────────────────────

def _leading_spaces(line_text):
    return len(line_text) - len(line_text.lstrip(" \t"))


def build_symbol_index(numbered_lines, lang):
    """
    扫描一段代码的行序列，构建：
      line_no(1-based, 按调用方传入的实际行号) -> {"method": ..., "class": ...}

    numbered_lines: [(line_no, text), ...] 按 line_no 升序排列的序列。
        - 支持"连续"序列（如完整文件的每一行都传入）；
        - 也支持"稀疏"序列（如 unified diff 中只有 hunk 覆盖到的行，
          行号之间可能有未出现的 gap ——例如被折叠的未改动区域）。
          稀疏场景下，跨越 gap 的花括号计数/缩进层级判断可能不完全精确
          （无法感知 gap 内的 { } 或缩进变化），这是基于 diff 文本而非
          完整源文件的已知局限，但仍显著优于"仅用文件名"的粗糙实现。

    返回：line_no -> {"method": 最近方法名 or None, "class": 最近外围类名 or None}

    规则（简化版，非真 AST，基于正则 + 缩进/花括号计数的启发式）：
      - Java/Kotlin/Go/TS/JS：用花括号计数判断类体/方法体的结束边界。
      - Python：用缩进层级判断类体/方法体的结束边界。
    """
    index = {}
    if lang not in SUPPORTED_LANGS:
        return index

    is_brace_lang = lang in ("java", "kotlin", "go", "typescript", "javascript")

    if is_brace_lang:
        # 用一个栈追踪 (class_name, brace_depth_when_entered) 的嵌套关系，
        # 以及当前方法名 + 方法体入口时的 brace_depth。
        class_stack = []  # [(name, depth_when_entered)]
        method_name = None
        method_depth = None
        depth = 0
        for line_no, raw_line in numbered_lines:
            type_name = match_type_name(raw_line, lang)
            if type_name:
                class_stack.append((type_name, depth))

            if method_name is None:
                m_name = match_method_name(raw_line, lang)
                if m_name:
                    method_name = m_name
                    method_depth = depth

            index[line_no] = {
                "method": method_name,
                "class": class_stack[-1][0] if class_stack else None,
            }

            depth += raw_line.count("{") - raw_line.count("}")

            if method_name is not None and method_depth is not None and depth <= method_depth:
                method_name = None
                method_depth = None
            while class_stack and depth <= class_stack[-1][1]:
                class_stack.pop()

    else:
        # Python：用缩进层级判断代码块归属
        class_stack = []  # [(name, indent_of_class_line)]
        method_name = None
        method_indent = None
        for line_no, raw_line in numbered_lines:
            stripped = raw_line.strip()
            if stripped == "" or stripped.startswith("#"):
                index[line_no] = {
                    "method": method_name,
                    "class": class_stack[-1][0] if class_stack else None,
                }
                continue

            indent = _leading_spaces(raw_line)

            while class_stack and indent <= class_stack[-1][1]:
                class_stack.pop()
            if method_name is not None and method_indent is not None and indent <= method_indent:
                method_name = None
                method_indent = None

            type_name = match_type_name(raw_line, lang)
            if type_name:
                class_stack.append((type_name, indent))

            if method_name is None:
                m_name = match_method_name(raw_line, lang)
                if m_name:
                    method_name = m_name
                    method_indent = indent

            index[line_no] = {
                "method": method_name,
                "class": class_stack[-1][0] if class_stack else None,
            }

    return index
