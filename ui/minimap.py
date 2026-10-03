"""小地图雷达系统"""
import math
from dataclasses import dataclass, field
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


# 渲染层级：地形在最底，单位在上
LAYER_ORDER = {
    "terrain": 0,
    "item": 1,
    "npc": 2,
    "enemy": 3,
    "player": 4,
    "quest": 5,
}

MIN_ZOOM = 0.1
MAX_ZOOM = 10.0
ZOOM_ANIM_SPEED = 5.0  # 每秒插值速率
ICON_ANIM_SPEED = 10.0  # 图标平滑移动速率
DEFAULT_FOV = math.pi * 2 / 3  # 扇形视野角 120°


class Minimap:
    def __init__(self, width: int = 200, height: int = 200, world_size: float = 1000.0):
        self.width = width
        self.height = height
        self.world_size = world_size
        self.player_position: tuple[float, float] = (0, 0)
        self.player_direction: float = 0.0
        self.objects: dict[int, MapObject] = {}
        self.quest_markers: dict[int, QuestMarker] = {}
        self.zoom_level: float = 1.0
        self.target_zoom: float = 1.0
        self.explored_areas: set = set()
        self.walls: list[tuple[float, float, float, float]] = []  # 遮挡线段
        self.fov: float = DEFAULT_FOV
        self.view_distance: float = world_size / 2
        self._icon_positions: dict[int, tuple[float, float]] = {}  # 动画用上一帧位置

    # ---------- 位置更新：旋转 + 裁剪 + 层级 ----------

    def update_position(self, obj: MapObject) -> tuple[float, float]:
        """世界坐标 -> 小地图坐标，随玩家朝向旋转，地图外不裁剪进边界"""
        dx = obj.position[0] - self.player_position[0]
        dy = obj.position[1] - self.player_position[1]
        # 按玩家朝向反向旋转，让玩家始终朝上
        cos_a = math.cos(-self.player_direction)
        sin_a = math.sin(-self.player_direction)
        rx = dx * cos_a - dy * sin_a
        ry = dx * sin_a + dy * cos_a
        scale = self.zoom_level
        map_x = rx / self.world_size * self.width * scale + self.width / 2
        map_y = ry / self.world_size * self.height * scale + self.height / 2
        return (map_x, map_y)

    def is_clipped(self, pos: tuple[float, float]) -> bool:
        """判断小地图坐标是否落在可视区域外（应被裁剪）"""
        return not (0 <= pos[0] <= self.width and 0 <= pos[1] <= self.height)

    def get_layer(self, obj: MapObject) -> int:
        """渲染层级：地形与单位分层"""
        return LAYER_ORDER.get(obj.icon_type, 1)

    # ---------- 图标更新：方向 + 大小缩放 + 动画 ----------

    def update_icon(self, obj: MapObject, dt: float = 1.0) -> dict:
        """更新图标：位置、朝向、随距离缩放的大小、平滑移动动画"""
        pos = self.update_position(obj)
        # 动画：从上一帧位置向目标位置插值，避免跳变
        prev = self._icon_positions.get(obj.id)
        if prev is not None and 0 < dt < 1:
            pos = (prev[0] + (pos[0] - prev[0]) * min(1.0, ICON_ANIM_SPEED * dt),
                   prev[1] + (pos[1] - prev[1]) * min(1.0, ICON_ANIM_SPEED * dt))
        self._icon_positions[obj.id] = pos
        # 大小随距离缩放：近大远小
        dist = math.hypot(obj.position[0] - self.player_position[0],
                          obj.position[1] - self.player_position[1])
        distance_factor = 1.0 / (1.0 + dist / (self.world_size / 4))
        size = obj.size * distance_factor * self.zoom_level
        return {
            "position": pos,
            "type": obj.icon_type,
            "size": size,
            "rotation": obj.direction,
            "layer": self.get_layer(obj),
            "clipped": self.is_clipped(pos),
        }

    # ---------- 视野：扇形 + 遮挡 + 战争迷雾 ----------

    def calculate_visibility(self, obj: MapObject) -> bool:
        """扇形视野 + 墙体遮挡；探索过的区域记入战争迷雾"""
        dx = obj.position[0] - self.player_position[0]
        dy = obj.position[1] - self.player_position[1]
        dist = math.hypot(dx, dy)
        if dist > self.view_distance:
            return False
        # 扇形：只在玩家朝向 ±fov/2 内可见
        if dist > 1e-9:
            angle = math.atan2(dy, dx)
            diff = (angle - self.player_direction + math.pi) % (2 * math.pi) - math.pi
            if abs(diff) > self.fov / 2:
                return False
        # 遮挡：视线被墙挡住则不可见
        if self._is_occluded(self.player_position, obj.position):
            return False
        # 战争迷雾：可见即标记为已探索
        self._mark_explored(obj.position)
        return True

    def _is_occluded(self, a: tuple[float, float], b: tuple[float, float]) -> bool:
        for (x1, y1, x2, y2) in self.walls:
            if _segments_intersect(a, b, (x1, y1), (x2, y2)):
                return True
        return False

    def _mark_explored(self, pos: tuple[float, float], cell: float = 50.0):
        self.explored_areas.add((int(pos[0] // cell), int(pos[1] // cell)))

    def is_explored(self, pos: tuple[float, float], cell: float = 50.0) -> bool:
        """战争迷雾：已探索区域亮，未探索区域暗"""
        return (int(pos[0] // cell), int(pos[1] // cell)) in self.explored_areas

    # ---------- 任务标记：距离 + 箭头指引 + 完成状态 ----------

    def update_quest_marker(self, marker: QuestMarker) -> dict:
        """任务标记：实时距离、出屏时箭头指引、完成后隐藏"""
        dx = marker.position[0] - self.player_position[0]
        dy = marker.position[1] - self.player_position[1]
        marker.distance = math.hypot(dx, dy)
        obj = MapObject(id=marker.id, position=marker.position, icon_type="quest")
        pos = self.update_position(obj)
        off_screen = self.is_clipped(pos)
        arrow = None
        if off_screen:
            # 箭头指引：指向任务方向的边缘位置与角度
            angle = math.atan2(dy, dx) - self.player_direction
            cx, cy = self.width / 2, self.height / 2
            radius = min(cx, cy) - 10
            arrow = {
                "position": (cx + radius * math.cos(angle), cy + radius * math.sin(angle)),
                "angle": angle,
            }
        return {
            "position": pos,
            "name": marker.name,
            "completed": marker.completed,
            "distance": marker.distance,
            "off_screen": off_screen,
            "arrow": arrow,
            "visible": not marker.completed,  # 已完成不再显示标记
        }

    # ---------- 缩放：细节层级 + 限制 + 动画 ----------

    def set_zoom_level(self, level: float):
        """设置缩放：限制在 [MIN_ZOOM, MAX_ZOOM]，动画平滑过渡"""
        clamped = max(MIN_ZOOM, min(MAX_ZOOM, level))
        self.target_zoom = clamped
        self.zoom_level = clamped

    def update_zoom(self, dt: float):
        """缩放动画：当前缩放向目标缩放平滑过渡"""
        diff = self.target_zoom - self.zoom_level
        step = diff * min(1.0, ZOOM_ANIM_SPEED * dt)
        self.zoom_level = max(MIN_ZOOM, min(MAX_ZOOM, self.zoom_level + step))

    def get_detail_level(self) -> int:
        """细节层级（LOD）：缩放越大加载越高分辨率的地图"""
        if self.zoom_level >= 4.0:
            return 3  # 高分辨率
        if self.zoom_level >= 2.0:
            return 2
        if self.zoom_level >= 1.0:
            return 1
        return 0  # 低分辨率

    # ---------- 渲染数据 ----------

    def get_render_data(self) -> dict:
        """获取渲染数据，图标按层级排序"""
        icons = []
        for obj in self.objects.values():
            if obj.visible and self.calculate_visibility(obj):
                icon = self.update_icon(obj)
                if not icon["clipped"]:
                    icons.append(icon)
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
            "explored": self.explored_areas,
        }


def _segments_intersect(a, b, c, d) -> bool:
    """判断线段 ab 与 cd 是否相交"""
    def cross(o, p, q):
        return (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0])
    d1 = cross(c, d, a)
    d2 = cross(c, d, b)
    d3 = cross(a, b, c)
    d4 = cross(a, b, d)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))
