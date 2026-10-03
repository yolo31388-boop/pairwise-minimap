"""小地图雷达系统 - 存在bug"""
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
        self.explored_areas: set = set()

    def update_position(self, obj: MapObject) -> tuple[float, float]:
        """更新物体在小地图上的位置 - BUG: 只做简单缩放不做旋转"""
        # BUG: 不做旋转，玩家转身后小地图不跟着转
        world_x, world_y = obj.position
        # 简单缩放
        map_x = (world_x - self.player_position[0]) / self.world_size * self.width + self.width / 2
        map_y = (world_y - self.player_position[1]) / self.world_size * self.height + self.height / 2
        return (map_x, map_y)

    def update_icon(self, obj: MapObject) -> dict:
        """更新图标 - BUG: 只做位置不做方向"""
        # BUG: 不做方向，所有图标都朝上
        pos = self.update_position(obj)
        return {
            "position": pos,
            "type": obj.icon_type,
            "size": obj.size,
            "rotation": 0.0,  # BUG: 不使用obj.direction
        }

    def calculate_visibility(self, obj: MapObject) -> bool:
        """计算可见性 - BUG: 只做圆形不做扇形"""
        # BUG: 只做圆形视野，不做扇形
        dx = obj.position[0] - self.player_position[0]
        dy = obj.position[1] - self.player_position[1]
        dist = (dx * dx + dy * dy) ** 0.5
        # BUG: 不做扇形，不做遮挡
        return dist < self.world_size / 2

    def update_quest_marker(self, marker: QuestMarker) -> dict:
        """更新任务标记 - BUG: 只做位置不做距离"""
        # BUG: 不做距离计算
        return {
            "position": marker.position,
            "name": marker.name,
            "completed": marker.completed,
            "distance": 0.0,  # BUG: 不计算距离
        }

    def set_zoom_level(self, level: float):
        """设置缩放 - BUG: 不做限制"""
        # BUG: 不做缩放限制
        self.zoom_level = level

    def get_render_data(self) -> dict:
        """获取渲染数据"""
        icons = []
        for obj in self.objects.values():
            if obj.visible and self.calculate_visibility(obj):
                icons.append(self.update_icon(obj))
        quests = []
        for marker in self.quest_markers.values():
            quests.append(self.update_quest_marker(marker))
        return {
            "icons": icons,
            "quests": quests,
            "player_pos": self.player_position,
            "zoom": self.zoom_level,
        }
