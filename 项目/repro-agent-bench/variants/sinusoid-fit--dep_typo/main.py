"""base-repos/sinusoid-fit/main.py

基础仓库 1：正弦信号拟合
依赖：numpy
可复现性：完全可复现（固定了随机种子）

期望输出（作为"目标结果"）：
    amplitude = 3.0xxx
    frequency = 2.5xxx
"""
import numpy as np


def generate_signal(n=400, fs=100.0):
    """生成带噪声的正弦信号。"""
    rng = np.random.default_rng(20261001)
    t = np.arange(n) / fs
    amplitude, frequency, phase = 3.0, 2.5, 0.4
    y = amplitude * np.sin(2 * np.pi * frequency * t + phase)
    y = y + rng.normal(0.0, 0.15, size=n)
    return t, y


def fit_sinusoid(t, y, f0=2.5):
    """用最小二乘拟合正弦的幅值与频率（在 f0 附近做细搜索）。"""
    best = None
    for f in np.linspace(f0 - 0.3, f0 + 0.3, 601):
        basis = np.column_stack([np.sin(2 * np.pi * f * t), np.cos(2 * np.pi * f * t)])
        coef, res, *_ = np.linalg.lstsq(basis, y, rcond=None)
        rss = float(np.sum((y - basis @ coef) ** 2))
        if best is None or rss < best[0]:
            best = (rss, f, coef)
    rss, f, coef = best
    amplitude = float(np.hypot(coef[0], coef[1]))
    return amplitude, f


def main():
    t, y = generate_signal()
    amplitude, frequency = fit_sinusoid(t, y)
    print("amplitude = %.4f" % amplitude)
    print("frequency = %.4f" % frequency)
    assert abs(amplitude - 3.0) < 0.1, "amplitude out of range"
    assert abs(frequency - 2.5) < 0.05, "frequency out of range"
    print("OK: sinusoid-fit reproduced")


if __name__ == "__main__":
    main()
