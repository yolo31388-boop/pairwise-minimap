"""小地图雷达系统"""
from dataclasses import dataclass, field
import math
from typing import Optional


@dataclass
class MapObject:
    id: int
    position: tuple[float, float]  # 世界坐标
    icon_type: str  # player, enemy, npc, quest, item
    direction: float = 0.0  # 朝向角度
    size: float = 1.0
    visible: bool = True


@dataclass
class QuestMarker:
    id: int
    position: tuple[float, float]
    name: str
    completed: bool = False
    distance: float = 0.0


@dataclass
class Wall:
    """遮挡物（线段），用于视野遮挡计算"""
    x1: float
    y1: float
    x2: float
    y2: float


class Minimap:
    MIN_ZOOM = 0.1
    MAX_ZOOM = 10.0
    VIEW_ANGLE = math.radians(120.0)  # 扇形视野张角
    ZOOM_LERP = 0.2   # 缩放动画插值系数
    ICON_LERP = 0.3   # 图标移动动画插值系数
    FOG_CELL = 50.0   # 战争迷雾格子边长（世界单位）

    # 渲染层级：地形在最底，玩家在最顶
    LAYERS = {
        "terrain": 0,
        "item": 1,
        "npc": 2,
        "quest": 3,
        "enemy": 4,
        "player": 5,
    }

    def __init__(self, width: int = 200, height: int = 200, world_size: float = 1000.0):
        self.width = width
        self.height = height
        self.world_size = world_size
        self.player_position: tuple[float, float] = (0, 0)
        self.player_direction: float = 0.0
        self.objects: dict[int, MapObject] = {}
        self.quest_markers: dict[int, QuestMarker] = {}
        self.zoom_level: float = 1.0          # 当前缩放（动画插值后的值）
        self.target_zoom_level: float = 1.0   # 目标缩放
        self.explored_areas: set = set()      # 战争迷雾：已探索的格子
        self.walls: list[Wall] = []
        self._icon_positions: dict[int, tuple[float, float]] = {}  # 图标动画缓存

    # ---------- 位置更新：旋转 + 裁剪 + 层级 ----------

    def update_position(self, obj: MapObject) -> tuple[float, float]:
        """世界坐标 -> 小地图坐标，随玩家朝向旋转，越界坐标保留在地图外供裁剪"""
        dx = obj.position[0] - self.player_position[0]
        dy = obj.position[1] - self.player_position[1]
        # 按玩家朝向反向旋转，使小地图始终"玩家朝向上方"
        cos_a = math.cos(-self.player_direction)
        sin_a = math.sin(-self.player_direction)
        rx = dx * cos_a - dy * sin_a
        ry = dx * sin_a + dy * cos_a
        # 世界坐标 -> 小地图像素，应用缩放
        scale = self.zoom_level
        map_x = rx / self.world_size * self.width * scale + self.width / 2
        map_y = ry / self.world_size * self.height * scale + self.height / 2
        return (map_x, map_y)

    def is_on_map(self, pos: tuple[float, float]) -> bool:
        """裁剪判断：坐标是否落在小地图范围内"""
        return 0 <= pos[0] <= self.width and 0 <= pos[1] <= self.height

    def get_layer(self, icon_type: str) -> int:
        """渲染层级，地形和单位分层"""
        return self.LAYERS.get(icon_type, 1)

    # ---------- 图标更新：方向 + 大小缩放 + 动画 ----------

    def update_icon(self, obj: MapObject) -> dict:
        """更新图标：位置（带移动动画）、朝向、按距离缩放大小"""
        target = self.update_position(obj)
        # 移动动画：从上一帧位置向目标位置插值，避免跳变
        prev = self._icon_positions.get(obj.id)
        if prev is None:
            smoothed = target
        else:
            smoothed = (
                prev[0] + (target[0] - prev[0]) * self.ICON_LERP,
                prev[1] + (target[1] - prev[1]) * self.ICON_LERP,
            )
        self._icon_positions[obj.id] = smoothed

        # 大小缩放：近大远小，再乘缩放级别
        dist = self._distance_to_player(obj.position)
        distance_factor = 1.0 / (1.0 + dist / (self.world_size / 4))
        size = obj.size * distance_factor * self.zoom_level

        return {
            "position": smoothed,
            "target_position": target,
            "type": obj.icon_type,
            "size": size,
            "rotation": obj.direction,  # 图标朝向跟随物体朝向
            "layer": self.get_layer(obj.icon_type),
            "on_map": self.is_on_map(target),
        }

    # ---------- 视野：扇形 + 遮挡 + 战争迷雾 ----------

    def calculate_visibility(self, obj: MapObject) -> bool:
        """扇形视野 + 墙体遮挡"""
        dx = obj.position[0] - self.player_position[0]
        dy = obj.position[1] - self.player_position[1]
        dist = (dx * dx + dy * dy) ** 0.5
        if dist > self.world_size / 2:
            return False
        if dist > 1e-9:
            # 扇形：目标方向与玩家朝向的夹角必须在视野张角内
            angle_to_obj = math.atan2(dy, dx)
            diff = self._angle_diff(angle_to_obj, self.player_direction)
            if abs(diff) > self.VIEW_ANGLE / 2:
                return False
        # 遮挡：玩家到目标的连线被墙挡住则不可见
        if self._is_occluded(self.player_position, obj.position):
            return False
        return True

    def _is_occluded(self, a: tuple[float, float], b: tuple[float, float]) -> bool:
        for wall in self.walls:
            if self._segments_intersect(a, b, (wall.x1, wall.y1), (wall.x2, wall.y2)):
                return True
        return False

    @staticmethod
    def _segments_intersect(p1, p2, p3, p4) -> bool:
        def cross(o, a, b):
            return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

        d1 = cross(p3, p4, p1)
        d2 = cross(p3, p4, p2)
        d3 = cross(p1, p2, p3)
        d4 = cross(p1, p2, p4)
        return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))

    @staticmethod
    def _angle_diff(a: float, b: float) -> float:
        diff = (a - b) % (2 * math.pi)
        if diff > math.pi:
            diff -= 2 * math.pi
        return diff

    def update_explored(self):
        """战争迷雾：把玩家视野范围内的格子标记为已探索"""
        px, py = self.player_position
        view = self.world_size / 2
        x0 = int((px - view) // self.FOG_CELL)
        x1 = int((px + view) // self.FOG_CELL)
        y0 = int((py - view) // self.FOG_CELL)
        y1 = int((py + view) // self.FOG_CELL)
        for gx in range(x0, x1 + 1):
            for gy in range(y0, y1 + 1):
                cx = (gx + 0.5) * self.FOG_CELL
                cy = (gy + 0.5) * self.FOG_CELL
                if (cx - px) ** 2 + (cy - py) ** 2 <= view * view:
                    self.explored_areas.add((gx, gy))

    def fog_state(self, position: tuple[float, float]) -> str:
        """visible=当前可见 / explored=探索过但不可见（迷雾） / hidden=未探索"""
        gx = int(position[0] // self.FOG_CELL)
        gy = int(position[1] // self.FOG_CELL)
        if (gx, gy) in self.explored_areas:
            return "explored"
        return "hidden"

    # ---------- 任务标记：距离 + 箭头指引 + 完成状态 ----------

    def update_quest_marker(self, marker: QuestMarker) -> dict:
        """更新任务标记：距离、出界箭头指引、完成状态"""
        marker.distance = self._distance_to_player(marker.position)
        pos = self.update_position(marker)
        on_map = self.is_on_map(pos)

        arrow = None
        if not on_map and not marker.completed:
            # 箭头指引：把标记钳制到地图边缘，并给出指向角度
            cx, cy = self.width / 2, self.height / 2
            dx, dy = pos[0] - cx, pos[1] - cy
            angle = math.atan2(dy, dx)
            margin = 10
            # 与矩形边界的交点
            scale = min(
                (cx - margin) / abs(dx) if dx else float("inf"),
                (cy - margin) / abs(dy) if dy else float("inf"),
            )
            arrow = {
                "position": (cx + dx * scale, cy + dy * scale),
                "angle": angle,
            }

        return {
            "position": pos,
            "name": marker.name,
            "completed": marker.completed,
            "distance": marker.distance,
            "on_map": on_map,
            "arrow": arrow,
            # 已完成的标记不再显示
            "visible": not marker.completed,
        }

    # ---------- 缩放：细节层级 + 限制 + 动画 ----------

    def set_zoom_level(self, level: float):
        """设置缩放：钳制到 [MIN_ZOOM, MAX_ZOOM]，动画在 update() 中插值"""
        self.target_zoom_level = max(self.MIN_ZOOM, min(self.MAX_ZOOM, level))
        self.zoom_level = max(self.MIN_ZOOM, min(self.MAX_ZOOM, self.zoom_level))

    def update(self):
        """每帧调用：缩放动画插值"""
        self.zoom_level += (self.target_zoom_level - self.zoom_level) * self.ZOOM_LERP
        self.zoom_level = max(self.MIN_ZOOM, min(self.MAX_ZOOM, self.zoom_level))

    def get_detail_level(self) -> str:
        """细节层级（LOD）：放大后使用高分辨率地图"""
        if self.zoom_level >= 4.0:
            return "high"
        if self.zoom_level >= 2.0:
            return "medium"
        return "low"

    # ---------- 渲染数据 ----------

    def _distance_to_player(self, position: tuple[float, float]) -> float:
        dx = position[0] - self.player_position[0]
        dy = position[1] - self.player_position[1]
        return (dx * dx + dy * dy) ** 0.5

    def get_render_data(self) -> dict:
        """获取渲染数据：图标裁剪 + 按层级排序 + 战争迷雾"""
        self.update_explored()
        icons = []
        for obj in self.objects.values():
            if not obj.visible or not self.calculate_visibility(obj):
                continue
            icon = self.update_icon(obj)
            if not icon["on_map"]:
                continue  # 裁剪：地图外的不渲染
            icons.append(icon)
        # 层级：地形在下，单位在上
        icons.sort(key=lambda i: i["layer"])

        quests = []
        for marker in self.quest_markers.values():
            data = self.update_quest_marker(marker)
            if data["visible"]:
                quests.append(data)

        return {
            "icons": icons,
            "quests": quests,
            "player_pos": self.player_position,
            "zoom": self.zoom_level,
            "detail_level": self.get_detail_level(),
            "explored": set(self.explored_areas),
        }
