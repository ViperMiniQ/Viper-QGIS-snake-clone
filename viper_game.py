from qgis.core import (
    QgsTask, 
    QgsVectorLayer, 
    QgsFeature, 
    QgsGeometry, 
    QgsPointXY, 
    QgsSpatialIndex
)

from time import sleep
import random


class ViperMain(QgsTask):
    def __init__(
        self, 
        btn_up,
        btn_down,
        btn_left,
        btn_right,
        btn_pause, 
        play_area_layer: QgsVectorLayer,
        snake_layer: QgsVectorLayer,
        food_layer: QgsVectorLayer,
        snake_width: int = 25, 
        refresh_rate: float = 0.25, 
        time_limit: float = 60,
        prepare_food: bool = True
    ):
        """
        :param prepare_food: if True, the food points are generated in advance, otherwise they are generated on the fly
        :param time_limit: play time in seconds
        :param refresh_rate: refresh rate in seconds
        :param snake_width: width of the snake part in meters
        """
        super().__init__(f'Viper - time limit: {time_limit if time_limit else "N/A"} s')
        
        self.pause = False
        self.direction_lock = False
        self.snake_bit_itself = False
        
        self.snake_parts = 3
        
        self.snake_width = snake_width
        self.refresh_rate = refresh_rate
        self.time_limit = time_limit
        
        self.snake_layer = snake_layer
        self.food_layer = food_layer
        self.play_area_layer = play_area_layer
        
        self.snake_direction = 'right'
        
        self.play_area_feature = next(self.play_area_layer.getFeatures())
        self.play_area_feature_extent = self.play_area_feature.geometry().boundingBox()
        
        center = self.play_area_feature.geometry().pointOnSurface()
        
        self.center_x = center.asPoint().x()
        self.center_y = center.asPoint().y()

        self.snake_head_x = self.center_x # - self.snake_width * (self.snake_parts + 1)
        self.snake_head_y = self.center_y
        
        self.snake_tail_x = 0
        self.snake_tail_y = 0
        
        self._generate_starting_snake(
            center.asPoint().x() - self.snake_width * self.snake_parts,  # offset starting position to the left of center
            center.asPoint().y()
        )
        
        btn_up.clicked.connect(lambda: self.change_snake_direction('up'))
        btn_down.clicked.connect(lambda: self.change_snake_direction('down'))
        btn_left.clicked.connect(lambda: self.change_snake_direction('left'))
        btn_right.clicked.connect(lambda: self.change_snake_direction('right'))
        btn_pause.clicked.connect(self.trigger_pause)
        
        self.food_feature = QgsFeature()
        self.prepared_food = None
        if prepare_food:
            self.prepare_food_points()
        
        self.current_snake_features = list(self.snake_layer.getFeatures())
        self.snake_layer_spatial_index = QgsSpatialIndex(self.snake_layer)
        self._refresh_all_layers()
        
    def _refresh_all_layers(self):
        self.play_area_layer.triggerRepaint()
        self.snake_layer.triggerRepaint()
        self.food_layer.triggerRepaint()
        
    def prepare_food_points(self):
        x_points = []
        y_points = []
        
        # ----------------- x ---------------->
        for x in range(1, int((self.play_area_feature_extent.xMaximum() - self.center_x) // self.snake_width), 1):
            x_points.append(self.center_x + x * self.snake_width)
        # <----------------- x -----------------
        for x in range(0, int((self.center_x - self.play_area_feature_extent.xMinimum()) // self.snake_width) + 1, 1):
            x_points.append(self.center_x - x * self.snake_width)
        
        for y in range(1, int((self.play_area_feature_extent.yMaximum() - self.center_y) // self.snake_width), 1):
            y_points.append(self.center_y + y * self.snake_width)
        for y in range(0, int((self.center_y - self.play_area_feature_extent.yMinimum()) // self.snake_width) + 1, 1):
            y_points.append(self.center_y - y * self.snake_width)
        
        # leave only points that are within the play area
        self.prepared_food = [(float(x), float(y)) for x in x_points for y in y_points if self.play_area_feature.geometry().intersects(QgsGeometry.fromPointXY(QgsPointXY(x, y)))]
        
    def _check_snake_intersects_food(self, food: QgsGeometry = None, head: bool = False):
        """
        Check if the snake intersects with the food.
        If head is set to True, then it only checks if the snake head intersects with the food.
        """
        # Due to some weird stuff going on with the contains method on different CRSs, the actual check is done by checking if the food centroid is within the snake head.
        # For example, contains works great on EPSG:3857, but not on EPSG:2180.
        if food is None:
            food = self.food_feature.geometry()
            
        if head:
            return self.current_snake_features[-1].geometry().contains(self.food_feature.geometry().centroid())
        
        for feature in self.current_snake_features:
            if feature.geometry().contains(self.food_feature.geometry().centroid()):
                return True
            
        return False
    
    def _check_snake_bit_itself(self):
        head = self.current_snake_features[-1].geometry()
        
        possible_intersections = self.snake_layer_spatial_index.intersects(head.boundingBox())
        
        if len(possible_intersections) <= 3:
            return False
        
        possible_intersections.remove(self.current_snake_features[-1].id())
        for feature_id in possible_intersections:
            if self.snake_layer.getFeature(feature_id).geometry().contains(head):
                return True
            
        return False
    
    def _check_snake_within_play_area(self):
        head = self.current_snake_features[-1].geometry()
        
        return self.play_area_feature.geometry().contains(head)
        
    def _generate_food(self):
        self.food_layer.dataProvider().truncate()
        
        if self.prepared_food is not None:
            # TODO food generation - there has to be a better way to do this, but it works and is relatively fast
            # it doesn't struggle with 10,000 items and I hope no one is going to create a bigger play area
            # no one has time to play that long anyway
            prepared_food = self.prepared_food.copy()  
            
            for feature in self.current_snake_features:
                geometry_centroid = feature.geometry().centroid().asPoint()
                prepared_food.remove((geometry_centroid.x() - self.snake_width / 2, geometry_centroid.y() - self.snake_width / 2))
        
            self.food_feature.setGeometry(self._get_snake_part_geometry(random.choice(prepared_food)))
            self.food_layer.dataProvider().addFeatures([self.food_feature])
            return
        
        while True:
            x = random.uniform(self.play_area_feature_extent.xMinimum(), self.play_area_feature_extent.xMaximum())
            y = random.uniform(self.play_area_feature_extent.yMinimum(), self.play_area_feature_extent.yMaximum())

            x = self.center_x % self.snake_width + x // self.snake_width * self.snake_width

            y = self.center_y % self.snake_width + y // self.snake_width * self.snake_width
            
            geometry = self._get_snake_part_geometry((x, y))
            self.food_feature.setGeometry(geometry)
            
            if self.play_area_feature.geometry().contains(geometry) and not self._check_snake_intersects_food():
                self.food_feature.setGeometry(geometry)
                self.food_layer.dataProvider().addFeatures([self.food_feature])
                break
        
    def trigger_pause(self):
        self.pause = not self.pause
        
    def _generate_starting_snake(self, start_x: float = 0, start_y: float = 0):
        for x in range(1, self.snake_parts + 1, 1):
            new_part = QgsFeature()
            
            new_part.setGeometry(self._get_snake_part_geometry((start_x + x * self.snake_width, start_y)))
            self.snake_layer.dataProvider().addFeatures([new_part])
        
    def _get_snake_part_geometry(self, xy: tuple):
        x_offset, y_offset = xy
        return QgsGeometry.fromPolygonXY([[
            QgsPointXY(x_offset, y_offset), 
            QgsPointXY(x_offset, self.snake_width + y_offset), 
            QgsPointXY(self.snake_width + x_offset, self.snake_width + y_offset), 
            QgsPointXY(self.snake_width + x_offset, y_offset)
        ]])
        
    def change_snake_direction(self, direction: str):
        if self.direction_lock:
            return
        
        self.direction_lock = True
        
        if self.snake_direction == 'up' and direction == 'down':
            return
        if self.snake_direction == 'down' and direction == 'up':
            return
        if self.snake_direction == 'left' and direction == 'right':
            return
        if self.snake_direction == 'right' and direction == 'left':
            return
        
        self.snake_direction = direction
    
    def _adjust_snake_head(self):
        if self.snake_direction == 'up': 
            self.snake_head_y += self.snake_width
            return
        if self.snake_direction == 'down':
            self.snake_head_y -= self.snake_width
            return
        if self.snake_direction == 'left':
            self.snake_head_x -= self.snake_width
            return
        if self.snake_direction == 'right':
            self.snake_head_x += self.snake_width
            return
    
    def _extend_snake(self):
        self._adjust_snake_head()
        self.direction_lock = False
        
        new_part = QgsFeature()
        new_part.setGeometry(self._get_snake_part_geometry((self.snake_head_x, self.snake_head_y)))
        
        success, features = self.snake_layer.dataProvider().addFeatures([new_part])
        feature = features[0]
        
        self.snake_layer_spatial_index.addFeature(feature)
        self.current_snake_features.append(feature)
        
    def _remove_snake_tail(self):
        tail = self.current_snake_features[0]
        self.snake_layer.dataProvider().deleteFeatures([tail.id()])
        self.snake_layer_spatial_index.deleteFeature(tail)
        self.current_snake_features.pop(0)
    
    def _move_snake(self):
        self._remove_snake_tail()
        self._extend_snake()
    
    def update_current_snake_features(self):
        self.current_snake_features = list(self.snake_layer.getFeatures())
    
    def run(self):
        # yes, the time limit won't be correct, it only takes into account the refresh rate
        # doesn't take into account the time it takes to execute the code within the loop
        # unless you are playing on a potato, it should be fine
        total = int(self.time_limit / self.refresh_rate)
        
        loops = 0
        
        self._generate_food()
        self.food_layer.triggerRepaint()
        
        sleep(1)  # give user some time to prepare, 1s is enough (?)
        
        while not self.isCanceled():    
            if self.pause:
                sleep(1)
                continue
        
            sleep(self.refresh_rate)
            
            if self._check_snake_intersects_food(head=True):
                self._extend_snake()
                self._generate_food()
                self.food_layer.triggerRepaint()
            else:
                self._move_snake()
            
            if self._check_snake_bit_itself():
                self.snake_bit_itself = True
                return True
            
            if not self._check_snake_within_play_area():
                return True
            
            self.snake_layer.triggerRepaint()
            
            if not self.time_limit:
                continue
            
            loops += 1
            
            if loops >= total:
                break
            
            self.setProgress(loops / total * 100)
            
        return True
    
    def finished(self, result):
        self._refresh_all_layers()
