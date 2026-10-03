#!/usr/bin/env python3
"""repro-agent-bench · MCP 工具服务器（stdio，JSON-RPC 2.0，零第三方依赖）

五个工具（对应 06-项目执行手册 §3.1）：
  1. inspect_repo   — 仓库结构 / 入口 / 依赖解析 / 目标数值
  2. build_env      — 依赖可解析性校验（dep_typo 的唯一检出途径）
  3. run_repo       — 运行 main.py（可多次，供随机性检测）
  4. compare_numbers— 数值相对误差比对
  5. diagnose       — 证据 → 根因标签 + 置信度 + 修复建议（确定性规则表）

协议：MCP over stdio（newline-delimited JSON-RPC 2.0）。
启动：python3 mcp_server.py   （由 AGH `mcp add --stdio` 拉起）
"""
import importlib.metadata
import json
import os
import re
import subprocess
import sys
import time

BENCH_ROOT = os.environ.get("REPRO_BENCH_ROOT", "/root/repro-agent-bench")
OBSERVATIONS = os.path.join(BENCH_ROOT, "observations.csv")
PYTHON = os.environ.get("REPRO_PYTHON", "/usr/bin/python3")
RUN_TIMEOUT = int(os.environ.get("REPRO_RUN_TIMEOUT", "120"))

# ---------------------------------------------------------------- 数据表 --

# 根因判定规则表（签名 → 标签），顺序即优先级。diagnose 依此裁决。
RULES = [
    ("env_unresolvable", "依赖版本问题", 0.95,
     "requirements.txt 存在无法解析/安装的依赖项；程序可能侥幸跑通但环境不完整"),
    ("runs_inconsistent", "随机性未固定", 0.90,
     "两次独立运行的输出不一致 → 存在未固定种子的随机源；用 np.random.default_rng(seed) 固定"),
    ("sig:CUDA|GPU backend", "环境不匹配", 0.95,
     "代码要求 GPU/CUDA 后端但环境无 → 添加回退到 CPU 的实现或声明环境前置条件"),
    ("sig:relative residual too large", "数值不稳定", 0.90,
     "病态系统直接求解放大舍入误差 → 改用对称正定分解 / Cholesky / 预条件迭代"),
    ("sig:suspiciously high R2", "数据泄漏（目标泄漏特征）", 0.90,
     "由目标派生的特征在全量数据上做选择 → 先划分、再在训练集上拟合/选择"),
    ("sig:distance out of plausible range", "单位换算错误", 0.90,
     "物理量单位不一致导致结果超出合理范围 → 统一 SI 单位并在断言处写明量纲检查"),
    ("sig:silently truncated", "静默截断", 0.90,
     "对数组做静默切片且形状校验未覆盖 → 在截断后加形状/长度一致性断言"),
    ("numeric_deviation", "未知（静默数值偏离）", 0.55,
     "退出码 0 但关键数值偏离期望 → 需人工核对数据生成与参数；置信度低于 0.7 阈值，按『未知』上报"),
]

REPRO_OK = "可复现（无缺陷）"


def load_observations():
    """observations.csv → {variant_name: row}，只读一次。含 key_outputs。"""
    import csv
    rows = {}
    try:
        with open(OBSERVATIONS, encoding="utf-8-sig", newline="") as fh:
            for rec in csv.DictReader(fh):
                name = rec.get("variant")
                if not name:
                    continue
                raw_outputs = rec.get("key_outputs", "")
                try:
                    key_outputs = json.loads(raw_outputs) if raw_outputs else {}
                except json.JSONDecodeError:
                    key_outputs = {}
                rows[name] = {
                    "repo": rec.get("repo"), "defect": rec.get("defect"),
                    "expected_root_cause": rec.get("expected_root_cause"),
                    "expected_reproducible": rec.get("expected_reproducible"),
                    "exit_code": rec.get("exit_code"),
                    "deterministic": rec.get("deterministic"),
                    "key_outputs": key_outputs,
                }
    except FileNotFoundError:
        pass
    return rows


OBS = load_observations()

# ---------------------------------------------------------------- 工具实现 --

def t_inspect_repo(repo_path: str) -> str:
    """检查仓库结构、入口、依赖与目标数值。返回 JSON 字符串。"""
    repo = os.path.abspath(repo_path)
    if not os.path.isdir(repo):
        return json.dumps({"ok": False, "error": f"目录不存在: {repo}"}, ensure_ascii=False)

    files = []
    for root, _dirs, names in os.walk(repo):
        depth = os.path.relpath(root, repo).count(os.sep)
        if depth > 2:
            continue
        for n in names:
            files.append(os.path.relpath(os.path.join(root, n), repo))

    deps = []
    req_file = os.path.join(repo, "requirements.txt")
    if os.path.exists(req_file):
        for line in open(req_file, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#"):
                m = re.match(r"([A-Za-z0-9_.\-]+)\s*(==|>=|<=|~=|!=)?\s*([\d.]+)?", line)
                if m:
                    deps.append({"spec": line, "package": m.group(1),
                                 "op": m.group(2) or "", "version": m.group(3) or ""})

    # 目标数值：从 main.py 头部 docstring 抽 "期望输出" 段落
    target = []
    main_py = os.path.join(repo, "main.py")
    if os.path.exists(main_py):
        src = open(main_py, encoding="utf-8").read()
        m = re.search(r"期望输出[^:]*:\n((?:\s{4,}\S.*\n?)+)", src)
        if m:
            target = [l.strip() for l in m.group(1).splitlines() if l.strip()]

    # 基准登记：若该目录是某个 variant，取其期望根因 + 同仓 pristine 基线（期望数值）
    variant_name = os.path.basename(repo.rstrip("/"))
    obs = OBS.get(variant_name)
    repo_name = obs["repo"] if obs else None
    baseline = OBS.get(f"{repo_name}--pristine") if repo_name else None

    # 注意：bench_row 仅保留目录名与仓库名（模型从输入路径已可知），
    # 不返回 expected_root_cause / expected_reproducible —— 那是判官（judge）数据，
    # 工具不得主动把答案递给 Agent（否则根因定位指标失真）。
    bench_info = None
    if obs:
        bench_info = {"repo": obs["repo"], "variant": variant_name, "in_bench": True}

    return json.dumps({
        "ok": True, "repo_path": repo, "files": sorted(files),
        "entry": "main.py" if os.path.exists(main_py) else None,
        "requirements": deps,
        "target_outputs": target,
        "in_bench": obs is not None,
        "bench_info": bench_info,
        "expected_key_values": baseline.get("key_outputs") if baseline else None,
        "note": "expected_key_values 来自同仓 pristine 基线（论文宣称的期望结果），"
                "供 compare_numbers 比对；pristine 自身该字段即自身期望。"
                "工具不提供期望根因标签——根因须由你基于证据推理。",
    }, ensure_ascii=False)


def _dist_version(pkg: str):
    try:
        return importlib.metadata.version(pkg)
    except importlib.metadata.PackageNotFoundError:
        return None


def _spec_satisfied(pkg: str, op: str, want: str, have: str) -> bool:
    if not op or not want or not have:
        return True
    def key(v):
        return tuple(int(x) for x in re.findall(r"\d+", v)[:4])
    a, b = key(have), key(want)
    return {"==": a == b, ">=": a >= b, "<=": a <= b, "~=": a[:2] == b[:2] and a >= b,
            "!=": a != b}.get(op, True)


def t_build_env(repo_path: str) -> str:
    """校验 requirements.txt 中每项依赖是否可解析（importlib.metadata）。"""
    repo = os.path.abspath(repo_path)
    req_file = os.path.join(repo, "requirements.txt")
    if not os.path.exists(req_file):
        return json.dumps({"ok": True, "requirements": [], "all_resolvable": True,
                           "note": "无 requirements.txt"}, ensure_ascii=False)
    results, all_ok = [], True
    for line in open(req_file, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"([A-Za-z0-9_.\-]+)\s*(==|>=|<=|~=|!=)?\s*([\d.]+)?", line)
        pkg, op, want = (m.group(1), m.group(2) or "", m.group(3) or "") if m else (line, "", "")
        have = _dist_version(pkg)
        if have is None:
            status, detail = "unresolvable", f"系统中找不到 {pkg}（pip 不可解析）"
            all_ok = False
        elif not _spec_satisfied(pkg, op, want, have):
            status, detail = "version_mismatch", f"需要 {pkg}{op}{want}，实际 {have}"
            all_ok = False
        else:
            status, detail = "ok", f"{pkg} {have} 满足 {line}"
        results.append({"spec": line, "package": pkg, "status": status,
                       "installed": have, "detail": detail})
    return json.dumps({"ok": True, "repo_path": repo, "requirements": results,
                       "all_resolvable": all_ok}, ensure_ascii=False)


_KEY_RE = re.compile(r"^(\w+)\s*=\s*([0-9eE+.\-]+)$", re.M)


def _parse_key_values(stdout: str) -> dict:
    return {k: v for k, v in _KEY_RE.findall(stdout)}


def t_run_repo(repo_path: str, runs: int = 2) -> str:
    """在仓库内运行 python3 main.py 共 runs 次，返回每次的退出码/输出/耗时。"""
    repo = os.path.abspath(repo_path)
    main_py = os.path.join(repo, "main.py")
    if not os.path.exists(main_py):
        return json.dumps({"ok": False, "error": "未找到 main.py"}, ensure_ascii=False)
    runs = max(1, min(int(runs), 5))
    results = []
    for i in range(runs):
        t0 = time.monotonic()
        try:
            p = subprocess.run([PYTHON, "main.py"], cwd=repo, capture_output=True,
                               text=True, timeout=RUN_TIMEOUT)
            rc, out, err, timeout = p.returncode, p.stdout, p.stderr, False
        except subprocess.TimeoutExpired as e:
            rc = None
            out = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
            err = (e.stderr or b"").decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
            timeout = True
        results.append({
            "run": i + 1, "exit_code": rc, "timeout": timeout,
            "elapsed_ms": round((time.monotonic() - t0) * 1000),
            "stdout_head": out[:400], "stderr_head": err[:400],
            "key_values": _parse_key_values(out) if rc == 0 else {},
        })
    outs = [json.dumps(r["key_values"], sort_keys=True) for r in results]
    consistent = len(set(outs)) <= 1 and all(r["exit_code"] == results[0]["exit_code"] for r in results)
    return json.dumps({"ok": True, "repo_path": repo, "runs": results,
                       "consistent": consistent,
                       "note": "consistent=False 表示两次运行结果/退出码不一致（随机性信号）"},
                      ensure_ascii=False)


def t_compare_numbers(actual, expected, rel_tol: float = 1e-3) -> str:
    """数值比对：相对误差与阈值判定。"""
    try:
        a, e = float(actual), float(expected)
    except (TypeError, ValueError):
        same = str(actual).strip() == str(expected).strip()
        return json.dumps({"ok": True, "exact_match": same, "note": "非数值，按字符串全等比较"},
                          ensure_ascii=False)
    if e == 0:
        return json.dumps({"ok": True, "diff": abs(a), "rel_error": None,
                           "within_tol": abs(a) < 1e-12}, ensure_ascii=False)
    rel = abs(a - e) / abs(e)
    return json.dumps({"ok": True, "actual": a, "expected": e,
                       "rel_error": round(rel, 8), "rel_tol": rel_tol,
                       "within_tol": rel <= rel_tol}, ensure_ascii=False)


def t_get_source(repo_path: str) -> str:
    """读取被诊断仓库内 main.py 的完整源码（带行号）。供第6步构造最小修复。纯只读。"""
    repo = os.path.abspath(repo_path)
    main_py = os.path.join(repo, "main.py")
    if not os.path.exists(main_py):
        return json.dumps({"ok": False, "error": "未找到 main.py"}, ensure_ascii=False)
    lines = open(main_py, encoding="utf-8").readlines()
    numbered = "".join(f"{i+1:>4}  {l}" for i, l in enumerate(lines))
    return json.dumps({"ok": True, "repo_path": repo, "lines": len(lines),
                       "source": numbered}, ensure_ascii=False)


def t_get_source(repo_path: str) -> str:
    """读取被诊断仓库 main.py 完整源码（带行号）。第6步构造最小修复用。纯只读。"""
    repo = os.path.abspath(repo_path)
    main_py = os.path.join(repo, "main.py")
    if not os.path.exists(main_py):
        return json.dumps({"ok": False, "error": "未找到 main.py"}, ensure_ascii=False)
    lines = open(main_py, encoding="utf-8").readlines()
    numbered = "".join(f"{i+1:>4}  {l}" for i, l in enumerate(lines))
    return json.dumps({"ok": True, "repo_path": repo, "lines": len(lines),
                       "source": numbered}, ensure_ascii=False)


def t_verify_fix(repo_path: str, fixed_main_py: str, runs: int = 2) -> str:
    """第 6 步修复验证：把修复后的 main.py 在 /tmp 沙箱副本中运行（原仓库保持只读）。

    返回每次运行的退出码/关键数值/耗时、一致性，以及与 pristine 基线期望值的比对。
    """
    import shutil, tempfile
    repo = os.path.abspath(repo_path)
    if not os.path.exists(os.path.join(repo, "main.py")):
        return json.dumps({"ok": False, "error": "未找到 main.py"}, ensure_ascii=False)
    runs = max(1, min(int(runs), 5))
    tmp = tempfile.mkdtemp(prefix="repro-verify-")
    try:
        shutil.copytree(repo, tmp + "/repo", dirs_exist_ok=True)
        with open(tmp + "/repo/main.py", "w", encoding="utf-8") as f:
            f.write(fixed_main_py)
        results = []
        for i in range(runs):
            t0 = time.monotonic()
            try:
                p = subprocess.run([PYTHON, "main.py"], cwd=tmp + "/repo",
                                   capture_output=True, text=True, timeout=RUN_TIMEOUT)
                rc, out, err, timeout = p.returncode, p.stdout, p.stderr, False
            except subprocess.TimeoutExpired as e:
                rc = None
                out = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
                err = (e.stderr or b"").decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
                timeout = True
            results.append({
                "run": i + 1, "exit_code": rc, "timeout": timeout,
                "elapsed_ms": round((time.monotonic() - t0) * 1000),
                "stdout_head": out[:400], "stderr_head": err[:400],
                "key_values": _parse_key_values(out) if rc == 0 else {},
            })
        outs = [json.dumps(r["key_values"], sort_keys=True) for r in results]
        consistent = len(set(outs)) <= 1 and all(
            r["exit_code"] == results[0]["exit_code"] for r in results)
        # 与 pristine 基线期望比对
        variant_name = os.path.basename(repo.rstrip("/"))
        obs = OBS.get(variant_name)
        baseline = OBS.get(f"{obs['repo']}--pristine") if obs else None
        expected = baseline.get("key_outputs") if baseline else None
        match = None
        if expected and results[0].get("key_values"):
            ok_all = True
            for k, ev in expected.items():
                cmp = _cmp_kv(results[0]["key_values"].get(k), ev)
                if not cmp.get("within_tol", False) and not cmp.get("exact_match", False):
                    ok_all = False
            match = {"expected": expected, "actual": results[0]["key_values"],
                     "all_within_tol": ok_all}
        return json.dumps({
            "ok": True, "sandbox": tmp, "note": "原仓库未被修改；验证在 /tmp 副本中进行",
            "runs": results, "consistent": consistent,
            "fix_verified": bool(consistent and all(r["exit_code"] == 0 for r in results)
                                 and (match is None or match["all_within_tol"])),
            "vs_baseline": match,
        }, ensure_ascii=False)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _cmp_kv(actual, expected):
    try:
        a, e = float(actual), float(expected)
    except (TypeError, ValueError):
        return {"exact_match": str(actual).strip() == str(expected).strip()}
    if e == 0:
        return {"within_tol": abs(a) < 1e-12, "rel_error": None}
    rel = abs(a - e) / abs(e)
    return {"within_tol": rel <= 1e-3, "rel_error": round(rel, 8)}


def t_diagnose(evidence_json: str) -> str:
    """证据包(JSON 字符串) → 根因标签 + 置信度 + 修复建议。

    evidence_json 期望字段（缺失按空处理）:
      build_env: {all_resolvable, requirements:[...]}
      run:       {consistent, runs:[{exit_code, stderr_head, key_values}]}
      compare:   单个 {within_tol} 或 多个比对的列表（任一项超差即视为偏离信号）
    """
    try:
        ev = json.loads(evidence_json) if isinstance(evidence_json, str) else dict(evidence_json or {})
    except json.JSONDecodeError:
        return json.dumps({"ok": False, "error": "evidence 不是合法 JSON"}, ensure_ascii=False)
    be, ru = ev.get("build_env") or {}, ev.get("run") or {}
    raw_cp = ev.get("compare") or {}
    cp_list = raw_cp if isinstance(raw_cp, list) else [raw_cp]
    any_out_of_tol = any(c.get("within_tol") is False for c in cp_list if isinstance(c, dict))
    stderr_all = " ".join(r.get("stderr_head", "") for r in ru.get("runs", []))
    exit_codes = [r.get("exit_code") for r in ru.get("runs", [])]

    # ── 守卫：证据不完整时不得判定"可复现"，必须按『未知』上报并给出 ok=False ──
    # 理由：把"字段缺失"当作"检查通过"会把证据缺失误判为无缺陷（沉默误判）；
    #       此处显式拒绝，要求调用方补齐证据。证据齐全的正常路径不受影响。
    _missing = []
    if not be:
        _missing.append("build_env")
    if not ru:
        _missing.append("run")
    if not raw_cp:
        _missing.append("compare")
    if _missing:
        return json.dumps({
            "ok": False,
            "root_cause": "未知",
            "confidence": 0.0,
            "reported_as_unknown": True,
            "error": "证据不完整，缺少: " + ", ".join(_missing),
            "fix_suggestion": "请依次补齐 build_env / run / compare 三类证据后再调用 diagnose；"
                              "证据缺失时不得判定为『可复现』。",
            "evidence_points": [],
        }, ensure_ascii=False)

    for kind, label, conf, fix in RULES:
        hit = False
        if kind == "env_unresolvable":
            hit = (not be.get("all_resolvable", True))
        elif kind == "runs_inconsistent":
            hit = (ru.get("consistent") is False)
        elif kind.startswith("sig:"):
            pat = re.escape(kind[4:])
            hit = re.search(pat, stderr_all, re.I) is not None
        elif kind == "numeric_deviation":
            hit = (all(c == 0 for c in exit_codes if c is not None) and any_out_of_tol)
        if hit:
            pts = []
            if kind == "env_unresolvable":
                pts = [q["detail"] for q in be.get("requirements", []) if q.get("status") != "ok"]
            elif kind == "runs_inconsistent":
                pts = [f"两次运行 key_values/exit_code 不一致: {exit_codes}"]
            elif kind.startswith("sig:"):
                pts = [stderr_all.strip()[:200]]
            elif kind == "numeric_deviation":
                bad = [c for c in cp_list if isinstance(c, dict) and c.get("within_tol") is False]
                pts = [f"退出码 0 但 {len(bad)} 项数值超差: "
                       + "; ".join(f"{c.get('actual')} vs {c.get('expected')}" for c in bad)]
            return json.dumps({
                "ok": True, "root_cause": label, "confidence": conf,
                "reported_as_unknown": conf < 0.7,
                "fix_suggestion": fix, "evidence_points": pts,
                "tried_alternatives": "按规则表优先级从上到下逐条匹配；命中即返回",
            }, ensure_ascii=False)

    # 全部干净
    clean = (be.get("all_resolvable", True)
             and ru.get("consistent", True)
             and all(c == 0 for c in exit_codes if c is not None)
             and not any_out_of_tol)
    if clean:
        return json.dumps({"ok": True, "root_cause": REPRO_OK, "confidence": 0.90,
                           "reported_as_unknown": False,
                           "fix_suggestion": "无需修复；建议保留本次观测作为基线",
                           "evidence_points": ["环境可解析、运行一致且成功、数值在容差内"]},
                          ensure_ascii=False)
    return json.dumps({"ok": True, "root_cause": "未知", "confidence": 0.30,
                       "reported_as_unknown": True,
                       "fix_suggestion": "证据不足以下结论，建议人工审查",
                       "evidence_points": [json.dumps(ev, ensure_ascii=False)[:300]]},
                      ensure_ascii=False)


TOOLS = [
    {
        "name": "inspect_repo",
        "description": "读取科研计算仓库的结构、入口、依赖(requirements.txt)与目标数值；若目录在基准集内还返回其登记信息。纯只读。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {"repo_path": {"type": "string", "description": "仓库目录绝对路径"}},
            "required": ["repo_path"],
        },
        "fn": t_inspect_repo,
    },
    {
        "name": "build_env",
        "description": "校验 requirements.txt 每项依赖在系统中是否可解析（含版本约束）。这是检出『依赖版本问题』类缺陷的唯一途径——此类缺陷主程序照常运行、无任何输出异常。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {"repo_path": {"type": "string"}},
            "required": ["repo_path"],
        },
        "fn": t_build_env,
    },
    {
        "name": "run_repo",
        "description": "在仓库内运行 python3 main.py 共 runs 次（默认2，供随机性检测），返回每次的退出码/输出/耗时与一致性判定。不修改仓库文件；对基准仓库而言结果确定性执行、无副作用。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string"},
                "runs": {"type": "integer", "minimum": 1, "maximum": 5, "default": 2},
            },
            "required": ["repo_path"],
        },
        "fn": t_run_repo,
    },
    {
        "name": "compare_numbers",
        "description": "比对实际数值与期望值：相对误差 + 容差判定（默认 1e-3）。用于『没报错但数值不对』的静默缺陷。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "actual": {"type": "string", "description": "实际值（数值字符串）"},
                "expected": {"type": "string", "description": "期望值（数值字符串）"},
                "rel_tol": {"type": "number", "default": 0.001},
            },
            "required": ["actual", "expected"],
        },
        "fn": t_compare_numbers,
    },
    {
        "name": "diagnose",
        "description": "把前几个工具的证据（build_env/run/compare 结果）汇总为根因裁决：返回 root_cause 标签 + 置信度 + 修复建议。规则表按优先级匹配，置信度<0.7 一律上报『未知』。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "evidence_json": {
                    "type": "string",
                    "description": "JSON 字符串：{\"build_env\":..., \"run\":..., \"compare\":...}（tools/call 的原始结果可直接拼接）",
                }
            },
            "required": ["evidence_json"],
        },
        "fn": t_diagnose,
    },
    {
        "name": "get_source",
        "description": "读取被诊断仓库 main.py 的完整源码（带行号）。第6步构造最小修复时用；不要凭记忆或推断改代码。纯只读。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {"repo_path": {"type": "string"}},
            "required": ["repo_path"],
        },
        "fn": t_get_source,
    },
    {
        "name": "verify_fix",
        "description": "第6步修复验证：把修复后的 main.py 写入 /tmp 沙箱副本运行（原仓库保持只读），返回运行结果、一致性，以及与 pristine 基线期望值的比对。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "被诊断仓库目录"},
                "fixed_main_py": {"type": "string", "description": "修复后的 main.py 完整内容"},
                "runs": {"type": "integer", "minimum": 1, "maximum": 5, "default": 2},
            },
            "required": ["repo_path", "fixed_main_py"],
        },
        "fn": t_verify_fix,
    },
]

# ---------------------------------------------------------------- 协议层 --

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "repro-agent-bench-tools", "version": "1.0.0"}


def _result(id_, payload):
    return {"jsonrpc": "2.0", "id": id_, "result": payload}


def _error(id_, code, msg):
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": msg}}


def handle(req):
    method = req.get("method")
    rid = req.get("id")
    params = req.get("params") or {}

    if method == "initialize":
        return _result(rid, {
            "protocolVersion": params.get("protocolVersion", PROTOCOL_VERSION),
            "serverInfo": SERVER_INFO,
            "capabilities": {"tools": {"listChanged": False}},
        })
    if method in ("notifications/initialized", "notifications/cancelled",
                  "ping"):
        return None
    if method == "tools/list":
        tl = []
        for t in TOOLS:
            item = {"name": t["name"], "description": t["description"],
                    "inputSchema": t["inputSchema"]}
            if t.get("annotations"):
                item["annotations"] = t["annotations"]
            tl.append(item)
        return _result(rid, {"tools": tl})
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        tool = next((t for t in TOOLS if t["name"] == name), None)
        if tool is None:
            return _error(rid, -32602, f"unknown tool: {name}")
        try:
            out = tool["fn"](**args)
            return _result(rid, {"content": [{"type": "text", "text": out}],
                                 "isError": False})
        except TypeError as e:
            return _result(rid, {"content": [{"type": "text",
                                              "text": json.dumps({"ok": False, "error": f"参数错误: {e}"},
                                                                 ensure_ascii=False)}],
                                 "isError": True})
        except Exception as e:  # noqa: BLE001
            return _result(rid, {"content": [{"type": "text",
                                              "text": json.dumps({"ok": False, "error": str(e)},
                                                                 ensure_ascii=False)}],
                                 "isError": True})
    if method in ("resources/list", "prompts/list"):
        return _result(rid, {"resources": []} if method == "resources/list"
                       else {"prompts": []})
    return _error(rid, -32601, f"method not found: {method}")


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            sys.stderr.write(f"[mcp-server] bad line: {line[:120]}\n")
            continue
        resp = handle(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
