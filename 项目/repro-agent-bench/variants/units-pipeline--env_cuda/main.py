import numpy as np

try:
    import cupy as cp          # [ENV] 需要 GPU/CUDA
    _xp = cp
except Exception as exc:       # noqa: BLE001
    raise RuntimeError(
        "CUDA/GPU backend is required but not available: %s" % exc
    ) from exc

"""base-repos/units-pipeline/main.py

基础仓库 4：物理量单位传递（信号传播损耗）
依赖：numpy
可复现性：完全可复现

约定：代码内部**一律用国际单位制（米）**，只在输入输出边界做换算。
所有带单位的输入都存在 units 字段里，读取时必须按声明单位换算成米。

期望输出：
    received_power_dbm 在合理范围内（约 -60 dBm 量级）
    distance_m 与声明单位一致
"""
import json
import os

import numpy as np

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")

# 单位 -> 换算成米的系数
TO_METER = {"m": 1.0, "km": 1000.0, "cm": 0.01, "mm": 0.001}
TO_HZ = {"Hz": 1.0, "kHz": 1e3, "MHz": 1e6, "GHz": 1e9}


def to_meters(value, unit):
    """[UNIT_CONV] 按声明单位把长度换算成米。"""
    return value * TO_METER[unit]


def to_hz(value, unit):
    """[UNIT_CONV] 按声明单位把频率换算成赫兹。"""
    return value * TO_HZ[unit]


def path_loss_db(distance_m, freq_hz):
    """自由空间路径损耗（Friis）。"""
    c = 299792458.0
    return 20.0 * np.log10(distance_m) + 20.0 * np.log10(freq_hz) + 20.0 * np.log10(4 * np.pi / c)


def main():
    with open(DATA, encoding="utf-8") as f:
        cfg = json.load(f)

    distance_m = to_meters(cfg["distance"]["value"], cfg["distance"]["unit"])
    freq_hz = to_hz(cfg["frequency"]["value"], cfg["frequency"]["unit"])
    tx_power_dbm = cfg["tx_power_dbm"]

    loss = path_loss_db(distance_m, freq_hz)
    rx_power_dbm = tx_power_dbm - loss

    print("distance_m = %.1f" % distance_m)
    print("frequency_hz = %.3e" % freq_hz)
    print("path_loss_db = %.2f" % loss)
    print("received_power_dbm = %.2f" % rx_power_dbm)

    assert 100.0 < distance_m < 1e6, "distance out of plausible range (unit error?)"
    assert -120.0 < rx_power_dbm < 0.0, "received power out of plausible range"
    print("OK: units-pipeline reproduced")


if __name__ == "__main__":
    main()
