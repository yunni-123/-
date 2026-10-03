# -*- coding: utf-8 -*-
"""缺陷注入工具：把基础仓库复制成"有已知缺陷"的变体仓库。

用法：
    python inject_defect.py --repo sinusoid-fit --defect no_seed --out ../variants
    python inject_defect.py --list
    python inject_defect.py --all            # 每个基础仓库 x 所有适用缺陷

每个变体仓库会写入 defect.json，记录注入的缺陷与期望的根因标签。
期望根因标签（root_cause）是后面计算"根因定位准确率"的标准答案。
"""
import argparse
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)          # 仓库根目录（tools 的上一级）
BASE = os.path.join(ROOT, "base-repos")

# ---------------------------------------------------------------------------
# 缺陷定义
#   rule: 通用规则（所有适用仓库都用）
#   rule_by_repo: 按仓库分支的规则（用于不同仓库写法不同的替换）
#   要求：替换必须精确命中，命中数必须等于 expect，否则中止（避免静默失配）
# ---------------------------------------------------------------------------
DEFECTS = {
    "no_seed": {
        "root_cause": "随机性未固定",
        "explain": "移除了随机种子，导致每次运行结果不同（不可复现）",
        "rule": [],
        "rule_by_repo": {
            "sinusoid-fit": [
                # 保留 rng 对象，但去掉固定种子 -> 每次运行不同（真正的不可复现）
                (r"rng = np\.random\.default_rng\(20261001\)",
                 "rng = np.random.default_rng()", 1),
            ],
            "linreg-pipeline": [
                (r"rng = np\.random\.default_rng\(SEED\)",
                 "rng = np.random.default_rng()", 1),
            ],
        },
        "obs": "多次运行同一仓库，关键输出数值不稳定",
    },
    "data_leakage": {
        "root_cause": "数据泄漏（目标泄漏特征）",
        "explain": "构造了一个与目标强相关的'本不该有'的特征，并在全量数据（含测试集）上做特征选择，"
                   "该特征把测试集信息带进模型，test_r2 被抬到不合理的水平",
        "rule": [],
        "rule_by_repo": {
            "linreg-pipeline": [
                (r"    return X, y\n",
                 "    # 注入目标泄漏特征：由目标 y 派生（本不该作为特征出现）\n"
                 "    X[:, N_FEATURES - 1] = y + rng.normal(0.0, 0.05, size=N_SAMPLES)\n"
                 "    return X, y\n",
                 1),
                (r"    cols = select_features\(X_train, y_train\)\n",
                 "    cols = select_features(X, y)   # 错误：用了全量数据选特征\n",
                 1),
            ],
        },
        "obs": "test_r2 超出合理性上界（>0.90），触发断言",
    },
    "unit_confusion": {
        "root_cause": "单位换算错误",
        "explain": "把 km 直接当成 m 使用，距离小了 1000 倍，导致结果偏差",
        "rule": [],
        "rule_by_repo": {
            "units-pipeline": [
                (r"^(\s*)return value \* TO_METER\[unit\][^\n]*\n",
                 r"\1return float(value)\n", 1),
            ],
        },
        "obs": "distance_m / path_loss 与合理量级相差约 1000 倍",
    },
    "numerical_instability": {
        "root_cause": "数值不稳定",
        "explain": "用正规方程（A^T A）求解病态方程组，条件数被平方，残差与解误差显著变大",
        "rule": [],
        "rule_by_repo": {
            "illcond-solve": [
                (r"    return np\.linalg\.solve\(A, b\)\n",
                 "    return np.linalg.solve(A.T @ A, A.T @ b)\n", 1),
            ],
        },
        "obs": "solution_error / relative_residual 远大于基线（1e-16 -> 1e-10 量级）",
    },
    "env_cuda": {
        "root_cause": "环境不匹配",
        "explain": "声明依赖 CUDA/GPU，但环境无 GPU，运行期报错",
        "rule": [],
        "extra": "cuda_header",
        "obs": "运行时报 CUDA/GPU 相关错误",
    },
    "silent_truncation": {
        "root_cause": "静默截断",
        "explain": "对数组做了静默切片截断，形状仍然合法但数值错误（不报错）",
        "rule": [],
        "rule_by_repo": {
            "sinusoid-fit": [
                (r"    t = np\.arange\(n\) / fs\n",
                 "    t = (np.arange(n) / fs)[: n // 2]\n", 1),
                (r"    y = y \+ rng\.normal\(0\.0, 0\.15, size=n\)\n",
                 "    y = y + rng.normal(0.0, 0.15, size=n)[: n // 2]\n", 1),
            ],
            "illcond-solve": [
                (r"    A = 1\.0 / \(i\[:, None\] \+ i\[None, :\] - 1\.0\)\n",
                 "    A = (1.0 / (i[:, None] + i[None, :] - 1.0))[: N // 2, :]\n", 1),
                (r"    return A, i\n",
                 "    assert A.shape == (N, N), \"matrix was silently truncated\"\n"
                 "    return A, i\n", 1),
            ],
        },
        "obs": "输出数值与基线偏离，但不抛异常",
    },
    "dep_typo": {
        "root_cause": "依赖版本问题",
        "explain": "requirements 中写入不存在的版本，环境构建必然失败",
        "rule": [],
        "extra": "bad_requirement",
        "obs": "依赖解析/安装阶段直接失败",
    },
}

# 哪些缺陷适用于哪个基础仓库
APPLICABLE = {
    "sinusoid-fit": ["no_seed", "silent_truncation", "env_cuda", "dep_typo"],
    "linreg-pipeline": ["no_seed", "data_leakage", "env_cuda", "dep_typo"],
    "illcond-solve": ["numerical_instability", "silent_truncation", "env_cuda", "dep_typo"],
    "units-pipeline": ["unit_confusion", "env_cuda", "dep_typo"],
}

CUDA_HEADER = '''import numpy as np

try:
    import cupy as cp          # [ENV] 需要 GPU/CUDA
    _xp = cp
except Exception as exc:       # noqa: BLE001
    raise RuntimeError(
        "CUDA/GPU backend is required but not available: %s" % exc
    ) from exc

'''
BAD_REQUIREMENT = "numpy==1.24\nnonexistent-package-xyz==99.99.99\n"


def apply_rules(text, rules, repo):
    """按规则做替换；命中数不符则抛错，避免静默失配。"""
    for pattern, repl, expect in rules:
        new, count = re.subn(pattern, repl, text, flags=re.MULTILINE)
        if count != expect:
            raise SystemExit(
                "注入失败：仓库 %s 中正则未按预期命中（期望 %d 次，实际 %d 次）\n"
                "  正则: %s" % (repo, expect, count, pattern)
            )
        text = new
    return text


def inject(repo, defect, out_root, force=False):
    src = os.path.join(BASE, repo)
    if not os.path.isdir(src):
        raise SystemExit("基础仓库不存在: %s" % src)

    spec = DEFECTS[defect]
    dst = os.path.join(out_root, "%s--%s" % (repo, defect))
    if os.path.exists(dst):
        if not force:
            raise SystemExit("目标已存在（加 --force 覆盖）: %s" % dst)
        shutil.rmtree(dst)
    shutil.copytree(src, dst)

    main_py = os.path.join(dst, "main.py")
    with open(main_py, encoding="utf-8") as f:
        text = f.read()
    rules = spec.get("rule", [])
    by_repo = spec.get("rule_by_repo", {})
    if repo in by_repo:
        rules = rules + by_repo[repo]
    if not rules and not spec.get("extra"):
        raise SystemExit("缺陷 %s 对仓库 %s 没有可用规则" % (defect, repo))
    text = apply_rules(text, rules, repo)

    extra = spec.get("extra")
    if extra == "cuda_header":
        text = CUDA_HEADER + text
    with open(main_py, "w", encoding="utf-8") as f:
        f.write(text)

    if extra == "bad_requirement":
        with open(os.path.join(dst, "requirements.txt"), "w", encoding="utf-8") as f:
            f.write(BAD_REQUIREMENT)

    meta = {
        "repo": repo,
        "defect": defect,
        "root_cause": spec["root_cause"],
        "explain": spec["explain"],
        "expected_observation": spec["obs"],
        "reproducible": False,
    }
    with open(os.path.join(dst, "defect.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo")
    ap.add_argument("--defect")
    ap.add_argument("--out", default=os.path.join(ROOT, "variants"))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if args.list:
        print("基础仓库与适用缺陷：")
        for r, ds in APPLICABLE.items():
            print("  %-18s %s" % (r, ", ".join(ds)))
        print("\n缺陷与期望根因：")
        for k, v in DEFECTS.items():
            print("  %-22s -> %s" % (k, v["root_cause"]))
        return

    if not os.path.isdir(args.out):
        os.makedirs(args.out, exist_ok=True)

    if args.all:
        n = 0
        for repo, defects in APPLICABLE.items():
            for d in defects:
                path = inject(repo, d, args.out, args.force)
                print("生成:", os.path.basename(path))
                n += 1
        # 同时放入"完好"的对照组
        for repo in APPLICABLE:
            dst = os.path.join(args.out, "%s--pristine" % repo)
            if os.path.exists(dst):
                shutil.rmtree(dst)
            shutil.copytree(os.path.join(BASE, repo), dst)
            with open(os.path.join(dst, "defect.json"), "w", encoding="utf-8") as f:
                json.dump({"repo": repo, "defect": "pristine",
                           "root_cause": "无缺陷（对照组）",
                           "explain": "完好仓库，应当判定为可复现",
                           "reproducible": True}, f, ensure_ascii=False, indent=2)
            print("生成:", os.path.basename(dst))
            n += 1
        print("\n共生成 %d 个变体仓库于 %s" % (n, args.out))
        return

    if not args.repo or not args.defect:
        ap.error("需要 --repo 与 --defect，或使用 --all / --list")
    print("生成:", inject(args.repo, args.defect, args.out, args.force))


if __name__ == "__main__":
    main()
