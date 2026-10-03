"""base-repos/illcond-solve/main.py

基础仓库 3：病态线性方程组求解（数值稳定性 + 静默错误敏感性）
依赖：numpy
可复现性：完全可复现

要点：用残差 ||Ax-b||/||b|| 与解的误差判断数值质量。
期望输出：
    relative_residual = 1e-16 量级（很小的相对残差）
    solution_error    = 1e-6  量级（受条件数限制）
"""
import numpy as np

N = 8


def build_matrix():
    """构造 Hilbert 矩阵——经典病态矩阵。"""
    i = np.arange(1, N + 1, dtype=float)
    A = (1.0 / (i[:, None] + i[None, :] - 1.0))[: N // 2, :]
    assert A.shape == (N, N), "matrix was silently truncated"
    return A, i


def solve(A, b):
    """稳定的求解器。"""
    return np.linalg.solve(A, b)


def relative_residual(A, x_hat, b):
    return float(np.linalg.norm(A @ x_hat - b) / np.linalg.norm(b))


def main():
    A, idx = build_matrix()          # idx 是列索引，用于构造真解
    x_true = np.ones(N)
    b = A @ x_true

    print("cond(A) = %.3e" % np.linalg.cond(A))
    x_hat = solve(A, b)
    res = relative_residual(A, x_hat, b)
    err = float(np.linalg.norm(x_hat - x_true) / np.linalg.norm(x_true))
    print("relative_residual = %.3e" % res)
    print("solution_error = %.3e" % err)

    assert res < 1e-12, "relative residual too large: numerical instability"
    assert err < 1e-3, "solution error too large"
    print("OK: illcond-solve reproduced")


if __name__ == "__main__":
    main()
