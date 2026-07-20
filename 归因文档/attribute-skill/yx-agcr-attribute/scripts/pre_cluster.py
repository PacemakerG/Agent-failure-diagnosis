#!/usr/bin/env python3
"""
pre_cluster.py — Layer 1 确定性预聚类脚本（PDG 硬聚类 + 跨仓符号匹配）。

在 SubAgent-Intent 的 Layer 2 LLM 语义聚类之前，对 hunk-list.json 执行确定性硬聚类，
减少需要 LLM 判断的候选集合。规则见 references/subagent-intent.md「Layer 1」一节：

  1. 同一 design_cluster_id 的 hunk              → must_merge（Layer 0 信号，最强）
  2. 跨仓/同仓符号匹配（symbol_hint/enclosing_class）→ likely_merge
  3. PDG 强依赖边（接口↔实现、方法↔调用方）        → must_merge   [依赖 --pdg-source，未提供时跳过]
  4. ast_hunk_split.py merge_suggestions（同文件同方法）→ must_merge
  5. PDG 弱依赖边（共享变量、同模块引用）          → likely_merge [依赖 --pdg-source，未提供时跳过]
  6. excluded = true 的 hunk                      → 不参与聚类

规则 3/5 依赖外部 GitNexus PDG 查询能力。当前脚本预留 --pdg-source 可插拔接口：
若提供该参数，需指向一份已由外部工具产出的 PDG 边 JSON 文件（结构见 load_pdg_edges()
的 docstring）；未提供时，pdg_edges 输出为空数组，规则 3/5 不生效，不阻塞主流程。

规则 1/2/4/6 仅依赖本地确定性数据（hunk-list.json + design-cluster-hints.json +
ast_hunk_split.py 输出），无需外部查询，完整实现。

纯 Python 标准库实现，无外部依赖。

用法：
  python3 pre_cluster.py \
    --hunk-list      /path/to/hunk-list.json \
    --design-cluster /path/to/design-cluster-hints.json \
    --ast-split      /path/to/ast-split-suggestions.json \
    --pdg-source     /path/to/pdg-edges.json \
    --output         /path/to/pre-cluster-hints.json
"""

import argparse
import json
import os
import sys
from collections import defaultdict

# 跨仓符号匹配条件 a 中需要排除的通用方法名（避免误merge无关 hunk）
GENERIC_SYMBOL_NAMES = {
    "toString", "equals", "hashCode", "getValue", "setValue",
    "builder", "build", "of", "valueOf", "main",
}


# ── 并查集：用于把 must_merge 的 hunk 对合并为分组 ───────────────────────────

class UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        self.parent.setdefault(a, a)
        self.parent.setdefault(b, b)
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb

    def groups(self, keys):
        buckets = defaultdict(list)
        for k in keys:
            buckets[self.find(k)].append(k)
        return [sorted(v) for v in buckets.values() if len(v) > 1]


# ── 数据加载 ─────────────────────────────────────────────────────────────────

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_hunks(hunk_list_path):
    data = load_json(hunk_list_path)
    # hunk-list.json 顶层可能直接是数组，也可能是 {"hunks": [...]}
    if isinstance(data, dict) and "hunks" in data:
        return data["hunks"]
    return data


def load_design_clusters(design_cluster_path):
    """
    读取 Layer 0 输出的 design-cluster-hints.json。
    返回 hunk_id -> design_cluster_id 映射。未提供或文件不存在时返回空 dict。
    """
    if not design_cluster_path or not os.path.isfile(design_cluster_path):
        return {}
    data = load_json(design_cluster_path)
    mapping = {}
    for cluster in data.get("design_clusters", []):
        cid = cluster.get("design_cluster_id")
        for hid in cluster.get("hunk_ids", []):
            mapping[hid] = cid
    return mapping


def load_ast_merge_suggestions(ast_split_path):
    """
    读取 ast_hunk_split.py 的输出，提取 merge_suggestions。
    ast_hunk_split.py 按单文件运行，merge_suggestions 用 file + hunk_indices（同文件内
    物理 hunk 序号）标识，不直接携带 hunk_id，因此需要在 resolve_ast_merge_pairs() 中
    通过 file_path + new_start 与 hunk-list.json 做 join。
    未提供或文件不存在时返回空列表。
    """
    if not ast_split_path or not os.path.isfile(ast_split_path):
        return []
    data = load_json(ast_split_path)
    return data.get("merge_suggestions", [])


def load_pdg_edges(pdg_source_path):
    """
    可插拔 PDG 边输入接口（规则 3/5）。

    预期结构（由外部 GitNexus 查询工具产出，当前项目尚未提供该工具的封装）：
    {
      "edges": [
        {"from": "server-H001", "to": "server-H002", "type": "interface_to_impl", "strength": "strong"},
        {"from": "server-H001", "to": "server-H003", "type": "shared_variable", "strength": "weak"}
      ]
    }
    strength 取值："strong"（规则3，must_merge）或 "weak"（规则5，likely_merge）。

    未提供 --pdg-source 或文件不存在时返回空列表，规则 3/5 不生效。
    """
    if not pdg_source_path:
        return []
    if not os.path.isfile(pdg_source_path):
        print(
            f"[pre_cluster] warn: --pdg-source 文件不存在，跳过 PDG 硬聚类规则: {pdg_source_path}",
            file=sys.stderr,
        )
        return []
    data = load_json(pdg_source_path)
    return data.get("edges", [])


# ── 规则 1：design_cluster_id 合并 ──────────────────────────────────────────

def apply_design_cluster_rule(hunks_by_id, design_cluster_map, uf, design_cluster_edges):
    """同一 design_cluster_id 的 hunk → must_merge。"""
    groups = defaultdict(list)
    for hid, cid in design_cluster_map.items():
        if hid in hunks_by_id and cid:
            groups[cid].append(hid)

    for cid, hids in groups.items():
        valid_hids = [h for h in hids if not hunks_by_id[h].get("excluded")]
        if len(valid_hids) < 2:
            continue
        base = valid_hids[0]
        for other in valid_hids[1:]:
            uf.union(base, other)
        design_cluster_edges.append({
            "design_cluster_id": cid,
            "hunk_ids": sorted(valid_hids),
            "method": "layer0_design_cluster",
        })


# ── 规则 2：跨仓/同仓符号匹配 ────────────────────────────────────────────────

def apply_symbol_match_rule(hunks, cross_repo_symbol_edges, likely_pairs):
    """
    跨仓符号匹配 → likely_merge。匹配条件（满足任一）：
      a. 不同 repo 的 hunk 的 symbol_hint 完全相同且不为通用方法名
      b. 不同 repo 的 hunk 的 enclosing_class 完全相同
      c. 同 repo 不同文件的 hunk 的 symbol_hint 相同（继承/实现关系的简化判定：
         enclosing_class 不同但 symbol_hint 相同，视为潜在接口/实现对）
    """
    valid_hunks = [h for h in hunks if not h.get("excluded")]

    # 条件 a：跨仓 symbol_hint 相同
    by_symbol = defaultdict(list)
    for h in valid_hunks:
        sym = h.get("symbol_hint")
        if sym and sym not in GENERIC_SYMBOL_NAMES:
            by_symbol[sym].append(h)
    for sym, group in by_symbol.items():
        repos = defaultdict(list)
        for h in group:
            repos[h.get("repo")].append(h)
        if len(repos) >= 2:
            repo_names = sorted(repos.keys())
            for i in range(len(repo_names)):
                for j in range(i + 1, len(repo_names)):
                    for ha in repos[repo_names[i]]:
                        for hb in repos[repo_names[j]]:
                            cross_repo_symbol_edges.append({
                                "from": ha["hunk_id"], "to": hb["hunk_id"],
                                "match": "symbol_hint", "value": sym, "strength": "likely",
                            })
                            likely_pairs.append((ha["hunk_id"], hb["hunk_id"]))

    # 条件 b：跨仓 enclosing_class 相同
    by_class = defaultdict(list)
    for h in valid_hunks:
        enc = h.get("enclosing_class")
        if enc:
            by_class[enc].append(h)
    for enc, group in by_class.items():
        repos = defaultdict(list)
        for h in group:
            repos[h.get("repo")].append(h)
        if len(repos) >= 2:
            repo_names = sorted(repos.keys())
            for i in range(len(repo_names)):
                for j in range(i + 1, len(repo_names)):
                    for ha in repos[repo_names[i]]:
                        for hb in repos[repo_names[j]]:
                            pair = tuple(sorted((ha["hunk_id"], hb["hunk_id"])))
                            # 避免与条件 a 重复记录同一对
                            if pair not in {tuple(sorted(p)) for p in likely_pairs}:
                                cross_repo_symbol_edges.append({
                                    "from": ha["hunk_id"], "to": hb["hunk_id"],
                                    "match": "enclosing_class", "value": enc, "strength": "likely",
                                })
                                likely_pairs.append((ha["hunk_id"], hb["hunk_id"]))

    # 条件 c：同 repo 不同文件、symbol_hint 相同、enclosing_class 不同（简化的继承/实现判定）
    for sym, group in by_symbol.items():
        by_repo = defaultdict(list)
        for h in group:
            by_repo[h.get("repo")].append(h)
        for repo, hs in by_repo.items():
            distinct_files = defaultdict(list)
            for h in hs:
                distinct_files[h.get("file_path")].append(h)
            file_names = sorted(distinct_files.keys())
            if len(file_names) < 2:
                continue
            for i in range(len(file_names)):
                for j in range(i + 1, len(file_names)):
                    for ha in distinct_files[file_names[i]]:
                        for hb in distinct_files[file_names[j]]:
                            if ha.get("enclosing_class") == hb.get("enclosing_class"):
                                continue
                            pair = tuple(sorted((ha["hunk_id"], hb["hunk_id"])))
                            if pair not in {tuple(sorted(p)) for p in likely_pairs}:
                                cross_repo_symbol_edges.append({
                                    "from": ha["hunk_id"], "to": hb["hunk_id"],
                                    "match": "enclosing_class_inheritance",
                                    "value": f"{ha.get('enclosing_class')}<->{hb.get('enclosing_class')}",
                                    "strength": "likely",
                                })
                                likely_pairs.append((ha["hunk_id"], hb["hunk_id"]))


# ── 规则 3/5：PDG 强/弱依赖边（可插拔，依赖 --pdg-source） ──────────────────

def apply_pdg_rules(pdg_edges, hunks_by_id, uf, pdg_edges_out, likely_pairs):
    for edge in pdg_edges:
        frm, to = edge.get("from"), edge.get("to")
        if frm not in hunks_by_id or to not in hunks_by_id:
            continue
        if hunks_by_id[frm].get("excluded") or hunks_by_id[to].get("excluded"):
            continue
        pdg_edges_out.append(edge)
        if edge.get("strength") == "strong":
            uf.union(frm, to)
        elif edge.get("strength") == "weak":
            likely_pairs.append((frm, to))


# ── 规则 4：ast_hunk_split.py merge_suggestions（同文件同方法） ────────────

def resolve_ast_merge_pairs(merge_suggestions, hunks, uf):
    """
    将 ast_hunk_split.py 的 merge_suggestions（file + hunk_indices + new_start/new_count）
    与 hunk-list.json 的 hunk（file_path + new_start）做 join，解析出 hunk_id 对并 must_merge。
    仅产生合并副作用（写入 uf），不单独输出——规格定义的 pre-cluster-hints.json 顶层字段中
    没有 ast_merge_pairs，规则 4 的合并结果最终体现在 must_merge / resolved_intents 里。
    """
    by_file_start = defaultdict(dict)
    for h in hunks:
        by_file_start[h.get("file_path")][h.get("new_start")] = h["hunk_id"]

    for sugg in merge_suggestions:
        file_path = sugg.get("file")
        hunk_infos = sugg.get("hunks", [])
        hids = []
        for info in hunk_infos:
            new_start = info.get("new_start")
            hid = by_file_start.get(file_path, {}).get(new_start)
            if hid:
                hids.append(hid)
        if len(hids) >= 2:
            for i in range(1, len(hids)):
                uf.union(hids[0], hids[i])


# ── 主流程 ───────────────────────────────────────────────────────────────────

def build_pre_cluster_hints(hunks, design_cluster_map, ast_merge_suggestions, pdg_edges_raw):
    hunks_by_id = {h["hunk_id"]: h for h in hunks}
    valid_ids = [hid for hid, h in hunks_by_id.items() if not h.get("excluded")]

    uf = UnionFind()
    for hid in valid_ids:
        uf.find(hid)

    design_cluster_edges = []
    cross_repo_symbol_edges = []
    pdg_edges_out = []
    likely_pairs = []

    # 规则 1
    apply_design_cluster_rule(hunks_by_id, design_cluster_map, uf, design_cluster_edges)

    # 规则 2
    apply_symbol_match_rule(hunks, cross_repo_symbol_edges, likely_pairs)

    # 规则 3 + 5（可插拔）
    apply_pdg_rules(pdg_edges_raw, hunks_by_id, uf, pdg_edges_out, likely_pairs)

    # 规则 4
    resolve_ast_merge_pairs(ast_merge_suggestions, hunks, uf)

    # 规则 6：excluded 的 hunk 已通过 valid_ids 排除，不参与任何分组

    must_merge = uf.groups(valid_ids)
    must_merge_set = set()
    for grp in must_merge:
        for hid in grp:
            must_merge_set.add(hid)

    # likely_merge：去重、排除已经在同一个 must_merge 分组内的 pair
    def same_must_group(a, b):
        return a in must_merge_set and b in must_merge_set and uf.find(a) == uf.find(b)

    seen_likely = set()
    likely_merge = []
    for a, b in likely_pairs:
        if a not in hunks_by_id or b not in hunks_by_id:
            continue
        if same_must_group(a, b):
            continue
        pair = tuple(sorted((a, b)))
        if pair in seen_likely:
            continue
        seen_likely.add(pair)
        likely_merge.append(list(pair))

    # resolved_intents：must_merge 分组直接生成 CI-xxx（不进入 Layer 2）
    resolved_intents = []
    for idx, grp in enumerate(must_merge, start=1):
        method = "pdg_hard_merge"
        if any(design_cluster_map.get(h) for h in grp):
            method = "layer0_design_cluster"
        resolved_intents.append({
            "intent_id": f"CI-{idx:03d}",
            "hunk_ids": grp,
            "method": method,
        })

    clustered_ids = set(must_merge_set)
    unclustered = sorted(set(valid_ids) - clustered_ids)

    return {
        "must_merge": [list(g) for g in must_merge],
        "likely_merge": likely_merge,
        "pdg_edges": pdg_edges_out,
        "cross_repo_symbol_edges": cross_repo_symbol_edges,
        "design_cluster_edges": design_cluster_edges,
        "resolved_intents": resolved_intents,
        "unclustered": unclustered,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Layer 1 确定性预聚类：PDG 硬聚类 + 跨仓符号匹配 + design_cluster 合并。"
    )
    parser.add_argument(
        "--hunk-list", required=True,
        help="Path to hunk-list.json."
    )
    parser.add_argument(
        "--design-cluster", default=None,
        help="Path to Layer 0 design-cluster-hints.json (optional)."
    )
    parser.add_argument(
        "--ast-split", default=None,
        help="Path to ast_hunk_split.py output JSON, used for merge_suggestions (optional)."
    )
    parser.add_argument(
        "--pdg-source", default=None,
        help="Path to externally-produced PDG edges JSON (optional, pluggable interface; "
             "GitNexus query integration not yet wired up)."
    )
    parser.add_argument(
        "--output", required=True,
        help="Path to the output pre-cluster-hints.json."
    )
    args = parser.parse_args()

    if not os.path.isfile(args.hunk_list):
        print(f"Error: hunk-list file not found: {args.hunk_list}", file=sys.stderr)
        sys.exit(1)

    hunks = load_hunks(args.hunk_list)
    design_cluster_map = load_design_clusters(args.design_cluster)
    ast_merge_suggestions = load_ast_merge_suggestions(args.ast_split)
    pdg_edges_raw = load_pdg_edges(args.pdg_source)

    result = build_pre_cluster_hints(hunks, design_cluster_map, ast_merge_suggestions, pdg_edges_raw)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    total_hunks = len(hunks)
    excluded = sum(1 for h in hunks if h.get("excluded"))
    print(
        f"pre_cluster: {total_hunks} hunks ({excluded} excluded), "
        f"{len(result['must_merge'])} must_merge groups, "
        f"{len(result['likely_merge'])} likely_merge pairs, "
        f"{len(result['resolved_intents'])} resolved intents, "
        f"{len(result['unclustered'])} unclustered → {args.output}"
    )
    if not args.pdg_source:
        print(
            "[pre_cluster] note: --pdg-source 未提供，规则 3/5（PDG 强/弱依赖边）已跳过，"
            "仅规则 1/2/4/6 生效。",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
