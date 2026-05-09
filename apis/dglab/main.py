import yaml
import random
import math
import aiohttp
import asyncio
from typing import List, Optional, Tuple

from .. import api

SEGMENTS = [
    (0, 0),      # 0%
    (1, 25),     # 1-2%
    (3, 60),     # 3-4%
    (5, 85),     # 5-7%
    (8, 105),    # 8-9%
    (10, 115),   # 10-14%
    (15, 125),   # 15-19%
    (20, 132),   # 20-29%
    (30, 138),   # 30-39%
    (40, 142),   # 40-49%
    (50, 145),   # 50-59%
    (60, 147),   # 60-74%
    (75, 148.5), # 75-89%
    (90, 149),   # 90-100%
    (101, 150),  # 超过100%
]

class DynamicSegment:
    """动态乘数计算器 - 分段函数（强度上限150）"""
    def __init__(self, segments: Optional[List[Tuple[float, float]]] = None, max_strength: int = 150):
        self.max_strength = max_strength
        if segments is None or len(segments) == 0:
            self.strength_segments = SEGMENTS.copy()
        else:
            self.strength_segments = sorted([(float(s[0]), float(s[1])) for s in segments], key=lambda x: x[0])
            if len(self.strength_segments) <= 10:
                print(f"[乘数器] 分段详情: {self.strength_segments}")

    def get_strength(self, percentage: float) -> int:
        if percentage <= 0:
            return 0
        for i, (threshold, strength) in enumerate(self.strength_segments):
            if percentage < threshold:
                if i == 0:
                    return min(int(strength), self.max_strength)
                prev_strength = self.strength_segments[i - 1][1]
                return min(int(prev_strength), self.max_strength)
        return min(int(self.strength_segments[-1][1]), self.max_strength)

    def get_Segment(self, percentage: float) -> float:
        strength = self.get_strength(percentage)
        if percentage <= 0:
            return 0.0
        return strength / percentage

    def calculate_strength(self, percentage: float) -> int:
        return self.get_strength(percentage)


class DGLabShockApi(api.shockApiBase):
    ApiName = "DGLab"

    def __init__(self, pluginPath: str):
        self.BaseStrength = 0
        self._session: Optional[aiohttp.ClientSession] = None
        self._current_task: Optional[asyncio.Task] = None
        self._task_lock = asyncio.Lock()
        self._is_dying = False

        # 加载配置
        config = None
        try:
            with open(rf"{pluginPath}\\config.yaml", "r",encoding='utf-8') as f:
                config = yaml.load(f, Loader=yaml.FullLoader)
        except FileNotFoundError:
            print("[配置] config.yaml 不存在，使用默认配置")
        except Exception as e:
            print(f"[配置] 加载失败: {e}")

        # DGLab 原有配置项
        Segment_config = config.get("Segment", None) if config else None
        api_url = config.get("api_url", None) if config else None
        self.toAllDevices = config.get("toAllDevices", False) if config else False
        self.randomize_strength_range: List[int] = config.get("randomize_strength_range", [0, 0]) if config else [0, 0]

        # 初始化 client_id
        if not self.toAllDevices:
            import requests  # 仅初始化时同步调用
            try:
                rep = requests.get(f"{api_url}api/client/connect", timeout=3)
                if rep.status_code == 200:
                    self.client_id = rep.json().get("clientId")
                    print(f"[API连接] 成功连接到API self.client_id = {self.client_id}")
                else:
                    self.client_id = None
                    print(f"[API连接] 获取clientId失败，状态码: {rep.status_code}")
            except Exception as e:
                self.client_id = None
                print(f"[API连接] 初始化连接失败: {e}")
        else:
            self.client_id = "all"
            print(f"[API连接] 已设置为控制所有设备 self.client_id = {self.client_id}")

        # 强度 API 地址
        if config:
            self.api_url = api_url
            if self.client_id:
                self.strengthAPI = api_url + f"api/v2/game/{self.client_id}/strength"
            else:
                self.strengthAPI = None
            if Segment_config:
                segments = [(seg[0], seg[1]) for seg in Segment_config]
                self.mul_calc = DynamicSegment(segments=segments)
        else:
            self.mul_calc = DynamicSegment()

        # ========== 新增：渐降衰减配置 ==========
        decay_cfg = config.get("decay", {}) if config else {}
        self.decay_enabled = decay_cfg.get("enabled", False)          # 默认关闭，保持原有行为
        self.decay_interval = decay_cfg.get("interval", 0.5)
        self.decay_factor = decay_cfg.get("factor", 0.4)
        self.decay_min = decay_cfg.get("min_strength", 0)
        self._decay_min = self.decay_min

        print(f"[配置] Segment={Segment_config}")
        print(f"[配置] 衰减: enabled={self.decay_enabled}, interval={self.decay_interval}s, factor={self.decay_factor}")

        self._retry_count = 0

    # ---------- 基础异步工具 ----------
    async def _get_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        await self._cancel_current_task()
        if self._session and not self._session.closed:
            await self._session.close()

    async def _cancel_current_task(self):
        async with self._task_lock:
            if self._current_task and not self._current_task.done():
                self._current_task.cancel()
                try:
                    await self._current_task
                except asyncio.CancelledError:
                    pass
                self._current_task = None

    def setBaseStrength(self, strength: float):
        self.BaseStrength = strength
        # 动态提高衰减下限（基础强度不会因衰减而降低）
        if math.ceil(self.BaseStrength) > self._decay_min:
            self._decay_min = math.ceil(self.BaseStrength)

    def addBaseStrength(self, strength: float):
        self.setBaseStrength(self.BaseStrength + strength)

    # ---------- API 请求 ----------
    async def _sendApiRequest(self, strength: int, random_strength: int = 4):
        if not self.strengthAPI:
            print("[API错误] strengthAPI 未初始化")
            return

        session = await self._get_session()
        try:
            async with session.post(
                self.strengthAPI,
                json={"strength": {"set": strength}, "randomStrength": {"set": random_strength}},
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                js = await resp.json()
                if int(js.get("status")) != 1:
                    if self.client_id != "all" and js.get("message") == "ERR::GAME_NOT_FOUND":
                        await self._refresh_client_id()
                        if self._retry_count <= 3:
                            self._retry_count += 1
                            print(f"[API连接] 重试 {self._retry_count}/3...")
                            await self._sendApiRequest(strength, random_strength)
                        else:
                            print(f"[API错误] 已重试3次，仍然失败: {js}")
                            self._retry_count = 0
                    else:
                        print(f"[API错误] 请求失败: {js}")
                else:
                    self._retry_count = 0
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[API异常] {e}")

    async def _refresh_client_id(self):
        if self.toAllDevices:
            return
        session = await self._get_session()
        try:
            async with session.get(
                f"{self.api_url}api/client/connect",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    new_id = data.get("clientId")
                    if new_id:
                        self.client_id = new_id
                        self.strengthAPI = self.api_url + f"api/v2/game/{self.client_id}/strength"
                        print(f"[API连接] 成功刷新 client_id = {self.client_id}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[API刷新] 刷新 client_id 失败: {e}")

    # ---------- 电击序列执行 ----------
    async def _execute_fixed_sequence(self, strength: int, duration: float = 0.2):
        """原有固定时长电击序列"""
        try:
            await self._sendApiRequest(math.ceil(strength))
            await asyncio.sleep(duration)
            await self._sendApiRequest(math.ceil(self.BaseStrength), 0)
        except asyncio.CancelledError:
            # print("[取消] 电击序列被取消，发送停止指令")
            await self._sendApiRequest(math.ceil(self.BaseStrength), 0)
            raise

    async def _execute_decay_sequence(self, strength: int):
        """渐降式电击序列（新功能）"""
        current = strength
        try:
            while current > self._decay_min:
                await self._sendApiRequest(current)
                await asyncio.sleep(self.decay_interval)
                current = int(current * self.decay_factor)
            # 最后发送基础强度（归零）
            await self._sendApiRequest(math.ceil(self.BaseStrength), 0)
        except asyncio.CancelledError:
            # print("[取消] 渐降序列被取消，发送停止指令")
            await self._sendApiRequest(math.ceil(self.BaseStrength), 0)
            raise

    async def _run_shock_task(self, strength: int, duration: float = 0.2, is_dying: bool = False):
        """
        管理电击任务：取消旧任务，创建新任务。
        - 若 decay_enabled=True 且非死亡，使用渐降序列。
        - 否则使用固定时长序列。
        """
        if self._is_dying and not is_dying:
            return
        if is_dying:
            self._is_dying = True

        await self._cancel_current_task()

        async with self._task_lock:
            if is_dying:
                # 死亡始终使用固定长时电击
                self._current_task = asyncio.create_task(
                    self._execute_fixed_sequence(strength, duration)
                )
            else:
                if self.decay_enabled:
                    self._current_task = asyncio.create_task(
                        self._execute_decay_sequence(strength)
                    )
                else:
                    self._current_task = asyncio.create_task(
                        self._execute_fixed_sequence(strength, duration)
                    )

        try:
            await self._current_task
        except asyncio.CancelledError:
            pass
        finally:
            async with self._task_lock:
                if self._current_task and self._current_task.done():
                    self._current_task = None
            # 关键修复：死亡任务结束后重置标志
            if is_dying:
                self._is_dying = False

    # ---------- 公开接口 ----------
    async def onRestart(self):
        self.setBaseStrength(0)
        self._is_dying = False
        await self._run_shock_task(0)  # 安全停止当前电击

    async def onDamaged(self, hp: int, maxHp: int):
        if self._is_dying:
            return
        percentage = (hp / maxHp) * 100
        strength = self.mul_calc.calculate_strength(percentage) + random.randint(
            self.randomize_strength_range[0], self.randomize_strength_range[1]
        )
        print(f"Got {percentage:.1f}% damage! Strength: {strength}")
        await self._run_shock_task(strength, duration=0.2, is_dying=False)

    async def onDied(self):
        strength = self.mul_calc.calculate_strength(100) + self.BaseStrength + random.randint(
            self.randomize_strength_range[0], self.randomize_strength_range[1]
        )
        print(f"You died! Max strength applied for 9 seconds. Strength: {strength}")
        self.setBaseStrength(0)
        await self._run_shock_task(strength, duration=9.0, is_dying=True)