"""base-repos/linreg-pipeline/main.py

基础仓库 2：高维线性回归流水线（含数据划分、标准化与特征选择）
依赖：numpy
可复现性：完全可复现

为什么用高维设计：
    只有 4 个特征真正有信号，其余 16 个是纯噪声，而样本量不大（400）。
    在【全量数据】上做特征选择时，噪声特征会因"碰巧相关"而被选中；
    这些虚假相关在测试集上依然成立，于是 test_r2 被显著抬高。
    只在【训练集】上选特征则不会有这个假象。

正确顺序（关键）：
    划分 train/test -> 只用 train 统计 -> 只用 train 选特征 -> 评估 test

期望输出：
    test_r2 ≈ 0.7x（基线下限由断言保证）
"""
import numpy as np

N_SAMPLES = 400
N_FEATURES = 20
REAL_FEATURES = 4
SEED = 7
TOP_K = 6


def make_data(rng):
    X = rng.normal(0.0, 1.0, size=(N_SAMPLES, N_FEATURES))
    # 只有前 REAL_FEATURES 个特征真正有信号，其余全是纯噪声
    true_w = np.zeros(N_FEATURES)
    true_w[:REAL_FEATURES] = [2.0, -1.5, 0.8, 1.2]
    y = X @ true_w + rng.normal(0.0, 1.0, size=N_SAMPLES)
    # 注入目标泄漏特征：由目标 y 派生（本不该作为特征出现）
    X[:, N_FEATURES - 1] = y + rng.normal(0.0, 0.05, size=N_SAMPLES)
    return X, y


def split(X, y, test_ratio=0.3):
    """按索引切分（确定性），训练与测试互不重叠。"""
    n_test = int(round(len(y) * test_ratio))
    X_test, y_test = X[-n_test:], y[-n_test:]
    X_train, y_train = X[:-n_test], y[:-n_test]
    return X_train, y_train, X_test, y_test


def select_features(X_fit, y_fit, k=TOP_K):
    """按与目标的相关性选特征。传入的必须是【训练集】。"""
    corr = np.array([abs(np.corrcoef(X_fit[:, j], y_fit)[0, 1])
                     for j in range(X_fit.shape[1])])
    return np.argsort(-corr)[:k]


def standardize(X_fit, X_apply, cols):
    """只用 X_fit 的均值方差去变换两者。"""
    A, B = X_fit[:, cols], X_apply[:, cols]
    mu = A.mean(axis=0)
    sigma = A.std(axis=0)
    sigma[sigma == 0] = 1.0
    return (A - mu) / sigma, (B - mu) / sigma


def fit_predict(X_train, y_train, X_test):
    A = np.column_stack([np.ones(len(X_train)), X_train])
    w, *_ = np.linalg.lstsq(A, y_train, rcond=None)
    B = np.column_stack([np.ones(len(X_test)), X_test])
    return B @ w


def r2_score(y_true, y_pred):
    ss_res = float(np.sum((y_true - y_pred) ** 2))
    ss_tot = float(np.sum((y_true - y_true.mean()) ** 2))
    return 1.0 - ss_res / ss_tot


def main():
    rng = np.random.default_rng(SEED)
    X, y = make_data(rng)

    X_train, y_train, X_test, y_test = split(X, y)
    cols = select_features(X, y)   # 错误：用了全量数据选特征
    X_train_s, X_test_s = standardize(X_train, X_test, cols)
    y_pred = fit_predict(X_train_s, y_train, X_test_s)

    score = r2_score(y_test, y_pred)
    print("selected = %s" % ",".join(str(int(c)) for c in cols))
    print("test_r2 = %.4f" % score)

    # 合理性上界：指标高得离谱通常意味着流程有问题
    assert score < 0.90, "suspiciously high R2 (possible data leakage)"
    # 合理性下限：指标太低说明选特征或标准化没做对
    assert score > 0.70, "R2 too low: feature selection or scaling is wrong"
    print("OK: linreg-pipeline reproduced")


if __name__ == "__main__":
    main()
