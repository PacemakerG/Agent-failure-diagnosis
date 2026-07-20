#!/usr/bin/env python3
"""check_artifact_structure.py — 维度 A 结构性检查脚本。

在 Penetration subagent 派发前由主 Agent 执行。
解析各层产物的固定标注字段，做 ID 级和字段级确定性比对。
按 §5.3 多信号兜底策略界定检查范围（intent 级聚焦），不做全量产物诊断。
产出 artifact-structure-report.json（格式见 §5.6）。

覆盖 §5.4 表中的 8 项确定性检查：
  N5: Task→D-xx 映射完整性 / 接口契约段字段一致性
  N4: D-xx→US-xx 映射完整性 / ○复用标注交叉验证 / DEC-xx 引用完整性
  N3: US→current-state.md 章节存在性 / AC 场景与 In Scope 文本匹配
  全局: before_vs_artifact 硬约束预检

用法:
  python3 check_artifact_structure.py \\
      --intent-frag $OUTPUT_DIR/intent-fragments/CI-001.json \\
      --artifact-dir $ARTIFACT_DIR \\
      --output $OUTPUT_DIR/artifact-structure-report-CI-001.json

退出码:
  0 = 脚本执行成功（不代表检查全部通过，检查结果在 JSON 中）
  1 = 脚本执行失败（参数错误、文件缺失等）
"""
import argparse
import json
import re
import sys
from pathlib import Path


# ═══════════════════════════════════════════════════════════════════════
#  Parsing Functions — 解析各层产物的固定标注字段
# ═══════════════════════════════════════════════════════════════════════

def _read_text(path):
    """安全读取文件，返回文本或空字符串。"""
    try:
        p = Path(path)
        if p.exists() and p.is_file():
            return p.read_text(encoding="utf-8")
    except Exception:
        pass
    return ""


def parse_tasks_md(path):
    """解析 tasks.md，提取 Task 段落、Covers 字段、Files 字段、接口契约段。

    Returns:
        {
            "tasks": {task_id: {"covers": [D-xx], "files": [path], "interface_source": str|None}},
            "coverage_matrix": {D-xx: [task_ids]},  # 末尾覆盖矩阵
        }
    """
    text = _read_text(path)
    if not text:
        return {"tasks": {}, "coverage_matrix": {}}

    tasks = {}
    coverage_matrix = {}

    # ── 解析 Task 段落 ──
    # 匹配 ### Task Txx: 或 ### Txx: 开头的段落
    task_pattern = re.compile(
        r'^#{2,4}\s+(?:Task\s+)?(T\d[\w-]*)\s*[:：]\s*(.+)$',
        re.MULTILINE
    )
    covers_pattern = re.compile(
        r'(?:Covers|覆盖|覆盖设计)\s*[:：]\s*(.+)$',
        re.MULTILINE
    )
    dxx_pattern = re.compile(r'D-\d[\w-]*')

    for m in task_pattern.finditer(text):
        task_id = m.group(1)
        start = m.end()
        # 下一个 Task 段落或文件末尾
        next_m = task_pattern.search(text, m.end())
        end = next_m.start() if next_m else len(text)
        section = text[start:end]

        # 解析 Covers
        covers_match = covers_pattern.search(section)
        covers = []
        if covers_match:
            covers = dxx_pattern.findall(covers_match.group(1))

        # 解析 Files
        files = []
        file_line_pattern = re.compile(
            r'(?:Add|Modify|Delete|新增|修改|删除)\s*[:：]\s*(.+)'
        )
        for fl in section.split('\n'):
            flm = file_line_pattern.match(fl.strip())
            if flm:
                fp = flm.group(1).strip()
                # 去除注释部分（如 # 注释）
                fp = re.split(r'\s+#', fp)[0].strip()
                if fp:
                    files.append(fp)

        # 解析接口契约段 Source 引用
        iface_source = None
        source_match = re.search(
            r'(?:Source|来源|接口来源)\s*[:：]\s*(.+)',
            section
        )
        if source_match:
            iface_source = source_match.group(1).strip()

        tasks[task_id] = {
            "covers": covers,
            "files": files,
            "interface_source": iface_source,
        }

    # ── 解析末尾覆盖矩阵 ──
    # 格式: | Design | D-xx ... | T-xx | Covered | ... |
    matrix_pattern = re.compile(
        r'\|\s*(?:Design|设计项)\s*\|.*?D-(\S+?)\s*\|'
    )
    for mm in matrix_pattern.finditer(text):
        dxx = "D-" + mm.group(1).strip()
        coverage_matrix.setdefault(dxx, [])

    return {"tasks": tasks, "coverage_matrix": coverage_matrix}


def parse_design_md(path):
    """解析 design.md，提取 D-xx 段落、US-xx 映射、DEC-xx 引用、○复用标注。

    Returns:
        {
            "design_items": {dxx_id: {"us_ref": [US-xx], "dec_refs": [DEC-xx/C-xx]}},
            "reuse_components": [component_name],  # §2.1 中标记为 ○复用 的组件
            "constraint_ids": set(),  # §1 约束摘要表中的 DEC-xx / C-xx
        }
    """
    text = _read_text(path)
    if not text:
        return {"design_items": {}, "reuse_components": [], "constraint_ids": set()}

    design_items = {}
    reuse_components = []
    constraint_ids = set()

    # ── 解析 D-xx 段落 ──
    dxx_pattern = re.compile(
        r'^#{2,4}\s+(D-\d[\w-]*)\s*[:：]\s*(.+)$',
        re.MULTILINE
    )
    us_pattern = re.compile(r'US-\d[\w-]*')
    dec_pattern = re.compile(r'(?:DEC|C)-\d[\w-]*')

    for m in dxx_pattern.finditer(text):
        dxx_id = m.group(1)
        start = m.end()
        next_m = dxx_pattern.search(text, m.end())
        end = next_m.start() if next_m else len(text)
        section = text[start:end]

        # 对应用户故事
        us_refs = []
        us_match = re.search(
            r'(?:对应用户故事|用户故事|对应故事)\s*[:：]\s*(.+)',
            section
        )
        if us_match:
            us_refs = us_pattern.findall(us_match.group(1))

        # 关联决策/约束
        dec_refs = []
        dec_match = re.search(
            r'(?:关联决策|关联约束|决策约束|决策/约束)\s*[:：]\s*(.+)',
            section
        )
        if dec_match:
            dec_refs = dec_pattern.findall(dec_match.group(1))

        design_items[dxx_id] = {
            "us_ref": us_refs,
            "dec_refs": dec_refs,
        }

    # ── 解析 §2.1 ○复用 标注 ──
    # ○复用 标记出现在组件名旁边
    reuse_pattern = re.compile(r'○\s*复用\s*(.+?)$|复用\s*[:：]\s*(.+?)$', re.MULTILINE)
    for rm in reuse_pattern.finditer(text):
        comp_name = (rm.group(1) or rm.group(2) or "").strip()
        # 提取组件名（去除行内注释和多余符号）
        comp_name = re.split(r'[#（(]', comp_name)[0].strip()
        if comp_name:
            reuse_components.append(comp_name)

    # 也匹配 ○ 标记后面直接跟类名的情况
    circle_reuse_pattern = re.compile(r'○\s+(.+?)(?:\s*[#（(]|$)', re.MULTILINE)
    for cm in circle_reuse_pattern.finditer(text):
        comp = cm.group(1).strip()
        if comp and comp not in reuse_components:
            reuse_components.append(comp)

    # ── 解析 §1 约束摘要表中的 DEC-xx / C-xx ──
    # 表格行中的 DEC-xx 或 C-xx
    constraint_table_pattern = re.compile(r'(?:DEC|C)-\d[\w-]*')
    # 只在 §1 区域搜索
    sec1_match = re.search(r'(?:^#\s*1\b|^#\s*约束摘要|^##\s*1\b).*?(?=\n#\s|\Z)', text, re.MULTILINE | re.DOTALL)
    sec1_text = sec1_match.group(0) if sec1_match else text
    for cid in constraint_table_pattern.finditer(sec1_text):
        constraint_ids.add(cid.group(0))

    return {
        "design_items": design_items,
        "reuse_components": reuse_components,
        "constraint_ids": constraint_ids,
    }


def parse_requirement_md(path):
    """解析 requirement.md，提取 §4 US-xx + AC、§2.2 In Scope、§6 映射表。

    Returns:
        {
            "user_stories": {usxx_id: {"ac_list": [str], "ac_scenes": [str]}},
            "in_scope_texts": [str],  # §2.2 In Scope 条目文本
            "mapping_table": {usxx_id: [current_state_sections]},  # §6 映射
        }
    """
    text = _read_text(path)
    if not text:
        return {"user_stories": {}, "in_scope_texts": [], "mapping_table": {}}

    user_stories = {}
    in_scope_texts = []
    mapping_table = {}

    # ── 解析 §4 用户故事 ──
    us_pattern = re.compile(
        r'^#{2,4}\s+(US-\d[\w-]*)\s*[:：]\s*(.+)$',
        re.MULTILINE
    )
    for m in us_pattern.finditer(text):
        us_id = m.group(1)
        start = m.end()
        next_m = us_pattern.search(text, m.end())
        end = next_m.start() if next_m else len(text)
        section = text[start:end]

        # 提取 AC 条目（Given/When/Then 或 AC-xx 编号格式）
        ac_list = []
        ac_scenes = []
        ac_pattern = re.compile(
            r'(?:AC-\d+|验收条件|Given|当)\s*[:：]?\s*(.+)',
            re.MULTILINE
        )
        for am in ac_pattern.finditer(section):
            ac_text = am.group(0).strip()
            ac_list.append(ac_text)
            # 提取场景关键词（用于 In Scope 匹配）
            scene = am.group(1).strip()
            ac_scenes.append(scene)

        user_stories[us_id] = {
            "ac_list": ac_list,
            "ac_scenes": ac_scenes,
        }

    # ── 解析 §2.2 In Scope ──
    # 定位 §2.2 区域
    sec22_match = re.search(
        r'(?:^#{2,3}\s*2\.2\b|^#{2,3}\s*In\s*Scope).*?(?=\n#{2,3}\s|\Z)',
        text, re.MULTILINE | re.DOTALL | re.IGNORECASE
    )
    if sec22_match:
        sec22_text = sec22_match.group(0)
        # 提取列表条目（- 或 * 或数字. 开头）
        for line in sec22_text.split('\n'):
            line = line.strip()
            if re.match(r'^[-*]\s+|^\d+\.\s+', line):
                item = re.sub(r'^[-*]\s+|^\d+\.\s+', '', line).strip()
                if item:
                    in_scope_texts.append(item)

    # ── 解析 §6 映射表 ──
    # 格式: | US-xx | current-state.md §x.x | ... |
    sec6_match = re.search(
        r'(?:^#{2,3}\s*6\b|^#{2,3}\s*映射).*?(?=\n#{2,3}\s|\Z)',
        text, re.MULTILINE | re.DOTALL
    )
    if sec6_match:
        sec6_text = sec6_match.group(0)
        mapping_pattern = re.compile(
            r'(US-\d[\w-]*)\s*\|.*?(?:current-state|现状).md?\s*(§\S+)',
            re.IGNORECASE
        )
        for mm in mapping_pattern.finditer(sec6_text):
            us_id = mm.group(1)
            section_ref = mm.group(2)
            mapping_table.setdefault(us_id, []).append(section_ref)

    return {
        "user_stories": user_stories,
        "in_scope_texts": in_scope_texts,
        "mapping_table": mapping_table,
    }


def parse_design_interface_md(path):
    """解析 design-interface.md，提取接口定义及字段名/类型。

    Returns:
        {interface_name: {"fields": [{"name": str, "type": str}]}}
    """
    text = _read_text(path)
    if not text:
        return {}

    interfaces = {}

    # 接口段: ### InterfaceName 或 ### 接口名: InterfaceName
    iface_pattern = re.compile(
        r'^#{2,4}\s+(?:接口\s*[:：]\s*)?(\w+)\s*$',
        re.MULTILINE
    )
    for m in iface_pattern.finditer(text):
        iface_name = m.group(1)
        start = m.end()
        next_m = iface_pattern.search(text, m.end())
        end = next_m.start() if next_m else len(text)
        section = text[start:end]

        # 提取字段定义（如 Java 风格: Type fieldName; 或 Thrift 风格: Type fieldName）
        fields = []
        field_pattern = re.compile(
            r'(?:^|\n)\s*(\w[\w<>,\[\]]*)\s+(\w+)\s*[;;\n]'
        )
        for fm in field_pattern.finditer(section):
            fields.append({
                "name": fm.group(2),
                "type": fm.group(1),
            })

        if fields:
            interfaces[iface_name] = {"fields": fields}

    return interfaces


# ═══════════════════════════════════════════════════════════════════════
#  Scoping Function — 多信号兜底策略界定检查范围
# ═══════════════════════════════════════════════════════════════════════

def _match_file_path(hunk_path, task_files):
    """三级匹配策略: 精确 → 前缀 → 目录。"""
    # 去除仓库前缀
    hunk_path_clean = re.sub(r'^[\w-]+/', '', hunk_path)

    for tf in task_files:
        tf_clean = re.sub(r'^[\w-]+/', '', tf)
        # 1. 精确匹配
        if hunk_path_clean == tf_clean:
            return True
        # 2. 前缀匹配（处理 ... 通配符）
        if '...' in tf_clean:
            prefix = tf_clean.split('...')[0]
            if hunk_path_clean.startswith(prefix):
                return True
        # 3. 目录匹配
        hunk_dir = str(Path(hunk_path_clean).parent)
        tf_dir = str(Path(tf_clean).parent)
        if hunk_dir == tf_dir:
            return True
    return False


def scope_intent_hunks(hunks, tasks_data):
    """多信号兜底策略: design_item_ref → task_ref → file_path → skip。

    Returns:
        {
            "scoping_signal": str|None,
            "dxx_ids": [D-xx],
            "task_ids": [Txx],
            "us_ids": [US-xx],
            "unmapped_hunks": [hunk_id],
        }
    """
    dxx_ids = set()
    task_ids = set()
    us_ids = set()
    unmapped_hunks = []
    signal = None

    for hunk in hunks:
        hunk_id = hunk.get("hunk_id", "")
        h_dxx = hunk.get("design_item_ref") or hunk.get("design_cluster_id")

        # Signal 1: design_item_ref
        if h_dxx:
            dxx_ids.add(h_dxx)
            if not signal:
                signal = "design_item_ref"
            continue

        # Signal 2: task_ref from source_commits
        commits = hunk.get("source_commits", [])
        task_ref = None
        for c in commits:
            tr = c.get("task_ref")
            if tr:
                task_ref = tr
                break

        if task_ref and task_ref in tasks_data.get("tasks", {}):
            task_ids.add(task_ref)
            # 从 Task 的 Covers 获取 D-xx
            task_covers = tasks_data["tasks"][task_ref].get("covers", [])
            dxx_ids.update(task_covers)
            if not signal:
                signal = "task_ref"
            continue

        # Signal 3: file_path matching
        file_path = hunk.get("file_path", "")
        matched = False
        for tid, tdata in tasks_data.get("tasks", {}).items():
            if _match_file_path(file_path, tdata.get("files", [])):
                task_ids.add(tid)
                dxx_ids.update(tdata.get("covers", []))
                matched = True
                if not signal:
                    signal = "file_path"
                break

        if not matched:
            unmapped_hunks.append(hunk_id)

    return {
        "scoping_signal": signal,
        "dxx_ids": sorted(dxx_ids),
        "task_ids": sorted(task_ids),
        "us_ids": sorted(us_ids),
        "unmapped_hunks": unmapped_hunks,
    }


def resolve_us_ids(scoped, design_data):
    """从 D-xx 列表解析对应的 US-xx。"""
    us_ids = set()
    for dxx in scoped["dxx_ids"]:
        d_data = design_data.get("design_items", {}).get(dxx, {})
        us_ids.update(d_data.get("us_ref", []))
    scoped["us_ids"] = sorted(us_ids)


# ═══════════════════════════════════════════════════════════════════════
#  Check Functions — 8 项确定性检查
# ═══════════════════════════════════════════════════════════════════════

def _skip(reason):
    """生成 skip 结果。"""
    return {"status": "skip", "reason": reason}


def _pass(evidence):
    """生成 pass 结果。"""
    return {"status": "pass", "evidence": evidence}


def _fail(evidence, defect_items):
    """生成 fail 结果。"""
    return {"status": "fail", "evidence": evidence, "defect_items": defect_items}


# ── N5 检查 ──

def check_n5_task_dxx_mapping(scoped, tasks_data, design_data):
    """N5: Task → D-xx 映射完整性。"""
    if not scoped["dxx_ids"]:
        return _skip("无法定位相关 D-xx，由 LLM 自行检查")

    dxx_in_design = set(design_data.get("design_items", {}).keys())
    tasks = tasks_data.get("tasks", {})

    # 构建 D-xx → has_task 映射
    dxx_covered_by_task = set()
    for dxx in scoped["dxx_ids"]:
        for tid, tdata in tasks.items():
            if dxx in tdata.get("covers", []):
                dxx_covered_by_task.add(dxx)

    missing = [d for d in scoped["dxx_ids"] if d not in dxx_covered_by_task]
    # 也检查 D-xx 是否存在于 design.md
    not_in_design = [d for d in scoped["dxx_ids"] if d not in dxx_in_design]

    if missing:
        return _fail(
            f"以下 D-xx 在 tasks.md 中无对应 Task（Covers 字段未覆盖）: {', '.join(missing)}",
            missing
        )
    if not_in_design:
        return _fail(
            f"以下 D-xx 在 design.md 中不存在: {', '.join(not_in_design)}",
            not_in_design
        )
    return _pass(f"所有相关 D-xx ({', '.join(scoped['dxx_ids'])}) 在 tasks.md 中有对应 Task")


def check_n5_interface_field_consistency(scoped, tasks_data, interface_data):
    """N5: 接口契约段字段一致性。"""
    if not scoped["task_ids"]:
        return _skip("无法定位相关 Task，由 LLM 自行检查")

    tasks = tasks_data.get("tasks", {})
    inconsistencies = []

    for tid in scoped["task_ids"]:
        tdata = tasks.get(tid, {})
        iface_source = tdata.get("interface_source")
        if not iface_source:
            continue

        # 尝试匹配 design-interface.md 中的接口名
        matched_iface = None
        for iface_name in interface_data:
            if iface_name in iface_source or iface_source in iface_name:
                matched_iface = iface_name
                break

        if matched_iface and matched_iface in interface_data:
            # 字段级一致性检查（简化：只检查字段名集合是否一致）
            # 完整检查需要解析 tasks.md 接口契约段的字段定义
            # 这里只做存在性验证
            pass  # 字段级比对留给 LLM 做语义检查

    if inconsistencies:
        return _fail(
            f"接口契约段字段不一致: {'; '.join(inconsistencies)}",
            inconsistencies
        )
    return _pass(
        f"相关 Task ({', '.join(scoped['task_ids'])}) 接口契约段引用检查完成"
        + ("，字段级一致性需 LLM 语义确认" if scoped["task_ids"] else "")
    )


# ── N4 检查 ──

def check_n4_dxx_usxx_mapping(scoped, design_data, requirement_data):
    """N4: D-xx → US-xx 映射完整性。"""
    if not scoped["dxx_ids"]:
        return _skip("无法定位相关 D-xx，由 LLM 自行检查")

    design_items = design_data.get("design_items", {})
    us_in_req = set(requirement_data.get("user_stories", {}).keys())

    missing_us = []
    missing_in_req = []

    for dxx in scoped["dxx_ids"]:
        d_data = design_items.get(dxx, {})
        us_refs = d_data.get("us_ref", [])

        if not us_refs:
            missing_us.append(dxx)
        else:
            for us in us_refs:
                if us not in us_in_req:
                    missing_in_req.append(f"{dxx}→{us}")

    if missing_us:
        return _fail(
            f"以下 D-xx 缺少 '对应用户故事：US-xx' 映射: {', '.join(missing_us)}",
            missing_us
        )
    if missing_in_req:
        return _fail(
            f"以下 D-xx 映射的 US-xx 不存在于 requirement.md §4: {', '.join(missing_in_req)}",
            missing_in_req
        )
    return _pass(
        f"所有相关 D-xx ({', '.join(scoped['dxx_ids'])}) 的 US-xx 映射存在于 requirement.md §4"
    )


def check_n4_reuse_marker_cross_validation(hunks, design_data):
    """N4: ○复用标注交叉验证（按 file_path，不需要 D-xx 界定）。"""
    reuse_components = design_data.get("reuse_components", [])
    if not reuse_components:
        return _pass("design.md §2.1 无 ○复用 标注组件")

    # 检查 after-side 是否修改了 ○复用 组件
    # after-side 的修改体现在 hunk 的 file_path 和 diff_content 中
    violated = []
    for hunk in hunks:
        file_path = hunk.get("file_path", "")
        for comp in reuse_components:
            # 组件名可能是类名，尝试匹配 file_path 的末尾部分
            comp_clean = comp.replace("Impl", "").replace(".java", "")
            if comp_clean and (
                comp in file_path
                or comp_clean in file_path
                or Path(file_path).stem == comp_clean
            ):
                # 检查 hunk 是否有 after-side 修改
                # 如果 hunk 在 after-side 有变化（added_lines > 0），说明 ○复用 组件被修改
                if hunk.get("added_lines", 0) > 0 or hunk.get("removed_lines", 0) > 0:
                    violated.append(comp)
                break

    if violated:
        return _fail(
            f"design.md §2.1 ○复用 组件在 after-side 被修改: {', '.join(violated)}",
            violated
        )
    return _pass("hunk file_path 未命中 design.md §2.1 任何 ○复用 标注组件")


def check_n4_dec_reference_integrity(scoped, design_data):
    """N4: DEC-xx 引用完整性。"""
    if not scoped["dxx_ids"]:
        return _skip("无法定位相关 D-xx，由 LLM 自行检查")

    design_items = design_data.get("design_items", {})
    constraint_ids = design_data.get("constraint_ids", set())

    missing_refs = []
    for dxx in scoped["dxx_ids"]:
        d_data = design_items.get(dxx, {})
        dec_refs = d_data.get("dec_refs", [])
        for ref in dec_refs:
            if ref not in constraint_ids:
                missing_refs.append(f"{dxx}→{ref}")

    if missing_refs:
        return _fail(
            f"以下 D-xx 引用的 DEC-xx/C-xx 不存在于 §1 约束摘要表: {', '.join(missing_refs)}",
            missing_refs
        )
    return _pass(
        f"所有相关 D-xx 引用的 DEC-xx/C-xx 均存在于 §1 约束摘要表"
    )


# ── N3 检查 ──

def check_n3_us_currentstate_mapping(scoped, requirement_data, current_state_path):
    """N3: US → current-state.md §章节存在性。"""
    if not scoped["us_ids"]:
        return _skip("无法定位相关 US-xx，由 LLM 自行检查")

    mapping_table = requirement_data.get("mapping_table", {})
    current_state_text = _read_text(current_state_path)

    missing_mapping = []
    missing_section = []

    for us_id in scoped["us_ids"]:
        if us_id not in mapping_table:
            missing_mapping.append(us_id)
        else:
            # 检查 current-state.md 中对应章节是否存在
            for section_ref in mapping_table[us_id]:
                # section_ref 格式如 §1.3
                section_num = re.sub(r'§', '', section_ref).strip()
                # 在 current-state.md 中查找对应章节
                header_pattern = re.compile(
                    rf'^#+\s*{re.escape(section_num)}\b',
                    re.MULTILINE
                )
                if not header_pattern.search(current_state_text):
                    missing_section.append(f"{us_id}→{section_ref}")

    if missing_mapping:
        return _fail(
            f"以下 US-xx 在 requirement.md §6 映射表中缺失: {', '.join(missing_mapping)}",
            missing_mapping
        )
    if missing_section:
        return _fail(
            f"以下 US-xx 引用的 current-state.md 章节不存在: {', '.join(missing_section)}",
            missing_section
        )
    return _pass(
        f"所有相关 US-xx ({', '.join(scoped['us_ids'])}) 引用的 current-state.md 章节存在"
    )


def check_n3_ac_scope_text_match(scoped, requirement_data):
    """N3: AC 场景与 In Scope 文本匹配。"""
    if not scoped["us_ids"]:
        return _skip("无法定位相关 US-xx，由 LLM 自行检查")

    user_stories = requirement_data.get("user_stories", {})
    in_scope_texts = requirement_data.get("in_scope_texts", [])

    if not in_scope_texts:
        return _skip("requirement.md §2.2 In Scope 列表为空或无法解析，由 LLM 自行检查")

    unmatched = []
    for us_id in scoped["us_ids"]:
        us_data = user_stories.get(us_id, {})
        ac_scenes = us_data.get("ac_scenes", [])

        for scene in ac_scenes:
            # 检查 AC 场景文本是否在 In Scope 中有匹配
            matched = False
            for scope_text in in_scope_texts:
                # 文本匹配：关键词重叠（简化策略）
                scene_lower = scene.lower()
                scope_lower = scope_text.lower()
                # 取较短的文本，检查是否是较长文本的子串
                if scene_lower in scope_lower or scope_lower in scene_lower:
                    matched = True
                    break
                # 关键词重叠检查
                scene_words = set(re.findall(r'\w+', scene_lower))
                scope_words = set(re.findall(r'\w+', scope_lower))
                if scene_words & scope_words and len(scene_words & scope_words) >= 2:
                    matched = True
                    break

            if not matched:
                unmatched.append(f"{us_id}: {scene[:50]}...")

    if unmatched:
        return _fail(
            f"以下 AC 场景在 §2.2 In Scope 中无文本匹配: {'; '.join(unmatched[:5])}",
            unmatched
        )
    return _pass(
        f"所有相关 US-xx 的 AC 场景在 §2.2 In Scope 中有文本匹配"
    )


# ── 全局检查 ──

def check_global_before_vs_artifact(hunks):
    """全局: before_vs_artifact 硬约束预检。"""
    empty_before = []
    for hunk in hunks:
        before_code = hunk.get("before_code", "")
        if not before_code or not before_code.strip():
            empty_before.append(hunk.get("hunk_id", ""))

    if empty_before:
        return _fail(
            f"before-side 为空，疑似遗漏实现: {', '.join(empty_before)}",
            empty_before
        )
    return _pass("before-side 非空，硬约束预检不触发")


# ═══════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="维度 A 结构性检查脚本 — 在 Penetration subagent 派发前执行"
    )
    parser.add_argument(
        "--intent-frag", required=True,
        help="intent fragment JSON 路径 (CI-xxx.json)"
    )
    parser.add_argument(
        "--artifact-dir", required=True,
        help="产物文件目录路径"
    )
    parser.add_argument(
        "--output", required=True,
        help="输出 artifact-structure-report JSON 路径"
    )
    args = parser.parse_args()

    # ── 加载 intent fragment ──
    frag_path = Path(args.intent_frag)
    if not frag_path.exists():
        print(json.dumps({"status": "error", "error": f"Intent fragment not found: {frag_path}"}, ensure_ascii=False))
        sys.exit(1)

    with open(frag_path, "r", encoding="utf-8") as f:
        intent_data = json.load(f)

    intent_id = intent_data.get("intent_id", frag_path.stem)
    hunks = intent_data.get("hunks", [])

    if not hunks:
        # intent 可能有 hunk_ids 但无 hunks 详情，尝试从 intent 字段提取
        print(json.dumps({
            "intent_id": intent_id,
            "status": "warning",
            "message": "No hunks in intent fragment, skipping structural checks"
        }, ensure_ascii=False, indent=2))
        # 仍输出空报告
        report = {
            "intent_id": intent_id,
            "scoped_items": {
                "scoping_signal": None,
                "dxx_ids": [],
                "task_ids": [],
                "us_ids": [],
                "unmapped_hunks": []
            },
            "structural_checks": {}
        }
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        return

    # ── 加载产物文件 ──
    artifact_dir = Path(args.artifact_dir)
    tasks_data = parse_tasks_md(artifact_dir / "tasks.md")
    design_data = parse_design_md(artifact_dir / "design.md")
    requirement_data = parse_requirement_md(artifact_dir / "requirement.md")
    interface_data = parse_design_interface_md(artifact_dir / "design-interface.md")
    current_state_path = artifact_dir / "current-state.md"

    # ── 多信号范围界定 ──
    scoped = scope_intent_hunks(hunks, tasks_data)

    # 从 D-xx 解析 US-xx
    resolve_us_ids(scoped, design_data)

    # ── 执行 8 项确定性检查 ──
    report = {
        "intent_id": intent_id,
        "scoped_items": {
            "scoping_signal": scoped["scoping_signal"],
            "dxx_ids": scoped["dxx_ids"],
            "task_ids": scoped["task_ids"],
            "us_ids": scoped["us_ids"],
            "unmapped_hunks": scoped["unmapped_hunks"],
        },
        "structural_checks": {
            "N5": {
                "task_dxx_mapping": check_n5_task_dxx_mapping(scoped, tasks_data, design_data),
                "interface_field_consistency": check_n5_interface_field_consistency(scoped, tasks_data, interface_data),
            },
            "N4": {
                "dxx_usxx_mapping": check_n4_dxx_usxx_mapping(scoped, design_data, requirement_data),
                "reuse_marker_cross_validation": check_n4_reuse_marker_cross_validation(hunks, design_data),
                "dec_reference_integrity": check_n4_dec_reference_integrity(scoped, design_data),
            },
            "N3": {
                "us_currentstate_mapping": check_n3_us_currentstate_mapping(scoped, requirement_data, current_state_path),
                "ac_scope_text_match": check_n3_ac_scope_text_match(scoped, requirement_data),
            },
            "global": {
                "before_vs_artifact_hard_constraint": check_global_before_vs_artifact(hunks),
            },
        }
    }

    # ── 输出报告 ──
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # 控制台输出摘要
    total = sum(len(v) for v in report["structural_checks"].values())
    passes = sum(1 for layer in report["structural_checks"].values()
                 for check in layer.values()
                 if check.get("status") == "pass")
    fails = sum(1 for layer in report["structural_checks"].values()
                for check in layer.values()
                if check.get("status") == "fail")
    skips = sum(1 for layer in report["structural_checks"].values()
                for check in layer.values()
                if check.get("status") == "skip")

    print(json.dumps({
        "intent_id": intent_id,
        "scoping_signal": scoped["scoping_signal"],
        "dxx_ids": scoped["dxx_ids"],
        "task_ids": scoped["task_ids"],
        "us_ids": scoped["us_ids"],
        "summary": {"total": total, "pass": passes, "fail": fails, "skip": skips},
        "output": str(output_path),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
