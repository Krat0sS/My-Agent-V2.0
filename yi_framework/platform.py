# -*- coding: utf-8 -*-
"""
平台可达性模块 — 多设备感知

YiRuntime 的 d1_resource 维度使用此模块评估当前可用的平台资源，
而非从工具执行成功率推导（那是 d2_progress 的职责）。
"""

from dataclasses import dataclass


@dataclass
class PlatformReachability:
    """平台可达性状态"""
    windows: bool = True           # 本机 Windows
    linux_ssh: bool = False        # 远程 Linux（SSH）
    android_adb: bool = False      # Android（ADB）
    android_scrcpy: bool = False   # Android 屏幕镜像

    # 最大可能平台数（windows + linux + android）
    MAX_PLATFORMS = 3

    def score(self) -> float:
        """可达性分数 0.0-1.0

        分母为最大可能平台数（3），
        单平台场景下 score=0.33，全平台=1.0，断连会明显下降。
        """
        connected = sum([self.windows, self.linux_ssh, self.android_adb])
        return connected / self.MAX_PLATFORMS

    def available_platforms(self) -> list:
        """返回当前可用的平台名称列表"""
        platforms = []
        if self.windows:
            platforms.append("windows")
        if self.linux_ssh:
            platforms.append("linux")
        if self.android_adb:
            platforms.append("android")
        return platforms

    def is_platform_available(self, platform: str) -> bool:
        """检查指定平台是否可用

        Args:
            platform: "windows" / "linux" / "android" / "any"
        """
        if platform == "any":
            return True
        if platform == "windows":
            return self.windows
        if platform == "linux":
            return self.linux_ssh
        if platform == "android":
            return self.android_adb
        return True  # 未知平台默认可用
