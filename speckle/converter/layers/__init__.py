"""
Contains all Layer related classes and methods.
"""
import enum
import inspect
import math
from typing import List, Union
from specklepy.objects import Base
from specklepy.objects.geometry import Mesh, Point
import os
import time
from datetime import datetime

from osgeo import (  # # C:\Program Files\QGIS 3.20.2\apps\Python39\Lib\site-packages\osgeo
    gdal, osr)
from plugin_utils.helpers import findFeatColors, findOrCreatePath, removeSpecialCharacters
#from qgis._core import Qgis, QgsVectorLayer, QgsWkbTypes
from qgis.core import (Qgis, QgsProject, QgsRasterLayer, QgsPoint, 
                       QgsVectorLayer, QgsProject, QgsWkbTypes,
                       QgsLayerTree, QgsLayerTreeGroup, QgsLayerTreeNode, QgsLayerTreeLayer,
                       QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                       QgsFields, 
                       QgsSingleSymbolRenderer, QgsCategorizedSymbolRenderer,
                       QgsRendererCategory,
                       QgsSymbol, QgsUnitTypes)
from speckle.converter.geometry.point import pointToNative
from speckle.converter.layers.CRS import CRS
from speckle.converter.layers.Layer import VectorLayer, RasterLayer, Layer
from speckle.converter.layers.feature import featureToSpeckle, rasterFeatureToSpeckle, featureToNative, cadFeatureToNative, bimFeatureToNative 
from speckle.converter.layers.utils import colorFromSpeckle, colorFromSpeckle, getLayerGeomType, getLayerAttributes, tryCreateGroup, trySaveCRS, validateAttributeName
from speckle.logging import logger
from speckle.converter.geometry.mesh import constructMesh, writeMeshToShp

from speckle.converter.layers.symbology import vectorRendererToNative, rasterRendererToNative, rendererToSpeckle

from PyQt5.QtGui import QColor
import numpy as np

from ui.logger import logToUser

GEOM_LINE_TYPES = ["Objects.Geometry.Line", "Objects.Geometry.Polyline", "Objects.Geometry.Curve", "Objects.Geometry.Arc", "Objects.Geometry.Circle", "Objects.Geometry.Ellipse", "Objects.Geometry.Polycurve"]


def getAllLayers(tree: QgsLayerTree, parent: QgsLayerTreeNode = None):
    try:
        if parent is None:
            parent = tree 
        
        if isinstance(parent, QgsLayerTreeLayer): 
            return [parent.layer()] 
        
        elif isinstance(parent, QgsLayerTreeGroup): 
            children = parent.children()
            layers = []
            for node in children:            
                if tree.isLayer(node):
                    if isinstance(node.layer(), QgsVectorLayer) or isinstance(node.layer(), QgsRasterLayer): 
                        layers.append(node.layer())
                    continue
                if tree.isGroup(node):
                    for lyr in getAllLayers(tree, node):
                        if isinstance(lyr, QgsVectorLayer) or isinstance(lyr, QgsRasterLayer): 
                            layers.append(lyr) 
                    #layers.extend( [ lyr for lyr in getAllLayers(tree, node) if isinstance(lyr.layer(), QgsVectorLayer) or isinstance(lyr.layer(), QgsRasterLayer) ] )
        return layers
    
    except Exception as e:
        logToUser(e, level = 2, func = inspect.stack()[0][3])
        return [parent] 

def getLayers(plugin, bySelection = False ) -> List[ Union[QgsLayerTreeLayer, QgsLayerTreeNode]]:
    """Gets a list of all layers in the given QgsLayerTree"""
    
    layers = []
    try:
        #print("___ get layers list ___")
        self = plugin.dockwidget
        if bySelection is True: # by selection 
            selected_layers = plugin.iface.layerTreeView().selectedNodes()
            layers = []
            
            for item in selected_layers:
                root = self.dataStorage.project.layerTreeRoot()
                layers.extend(getAllLayers(root, item))

        else: # from project data 
            project = plugin.qgis_project
            #all_layers_ids = [l.id() for l in project.mapLayers().values()]
            for item in plugin.dataStorage.current_layers:
                try: 
                    id = item[1].id()
                except:
                    logToUser(f'Saved layer not found: "{item[0]}"', level = 1, func = inspect.stack()[0][3])
                    continue
                found = 0
                for l in project.mapLayers().values():
                    if id == l.id():
                        layers.append(l)
                        found += 1
                        break 
                if found == 0: 
                    logToUser(f'Saved layer not found: "{item[0]}"', level = 1, func = inspect.stack()[0][3])
        
        r'''
        children = parent.children()
        for node in children:
            #print(node)
            if tree.isLayer(node):
                #print(node)
                if isinstance(node.layer(), QgsVectorLayer) or isinstance(node.layer(), QgsRasterLayer): layers.append(node)
                continue
            if tree.isGroup(node):
                for lyr in getLayers(tree, node):
                    if isinstance(lyr.layer(), QgsVectorLayer) or isinstance(lyr.layer(), QgsRasterLayer): layers.append(lyr) 
                #layers.extend( [ lyr for lyr in getLayers(tree, node) if isinstance(lyr.layer(), QgsVectorLayer) or isinstance(lyr.layer(), QgsRasterLayer) ] )
        '''
        return layers
    except Exception as e:
        logToUser(e, level = 2, func = inspect.stack()[0][3], plugin = plugin.dockwidget)
        return layers 


def convertSelectedLayers(layers: List[Union[QgsVectorLayer, QgsRasterLayer]], selectedLayerIndex: List[int], selectedLayerNames: List[str], projectCRS: QgsCoordinateReferenceSystem, plugin) -> List[Union[VectorLayer, RasterLayer]]:
    """Converts the current selected layers to Speckle"""
    result = []
    try:
        project: QgsProject = plugin.qgis_project

        for i, layer in enumerate(layers):

            if plugin.dataStorage.savedTransforms is not None:
                for item in plugin.dataStorage.savedTransforms:
                    layer_name = item.split("  ->  ")[0].split(" (\'")[0]
                    transform_name = item.split("  ->  ")[1].lower()

                    # check all the conditions for transform 
                    if isinstance(layer, QgsVectorLayer) and layer.name() == layer_name and "extrude" in transform_name and "polygon" in transform_name:
                        if plugin.dataStorage.project.crs().isGeographic():
                            logToUser("Extrusion cannot be applied when the project CRS is set to Geographic type", level = 1, plugin = plugin.dockwidget)

                        attribute = None
                        if " (\'" in item:
                            attribute = item.split(" (\'")[1].split("\') ")[0]
                        if (attribute is None or str(attribute) not in layer.fields().names()) and "ignore" in transform_name:
                            logToUser("Attribute for extrusion not found, extrusion will not be applied", level = 1, plugin = plugin.dockwidget)
                            return None
                        
            
            result.append(layerToSpeckle(layer, projectCRS, plugin))
        
        return result
    except Exception as e:
        logToUser(e, level = 2, func = inspect.stack()[0][3], plugin = plugin.dockwidget)
        return []


def layerToSpeckle(selectedLayer: Union[QgsVectorLayer, QgsRasterLayer], projectCRS: QgsCoordinateReferenceSystem, plugin) -> VectorLayer or RasterLayer: #now the input is QgsVectorLayer instead of qgis._core.QgsLayerTreeLayer
    """Converts a given QGIS Layer to Speckle"""
    try:
        project: QgsProject = plugin.qgis_project
        layerName = selectedLayer.name()
        #except: layerName = layer.sourceName()
        #try: selectedLayer = selectedLayer.layer()
        #except: pass 
        crs = selectedLayer.crs()
        #units = "m"
        units_proj = plugin.dataStorage.currentUnits
        units_layer = QgsUnitTypes.encodeUnit(crs.mapUnits())
        #plugin.dataStorage.currentUnits = units_proj 

        if crs.isGeographic(): units_layer = "m" ## specklepy.logging.exceptions.SpeckleException: SpeckleException: Could not understand what unit degrees is referring to. Please enter a valid unit (eg ['mm', 'cm', 'm', 'in', 'ft', 'yd', 'mi']). 
        layerObjs = []
        # Convert CRS to speckle, use the projectCRS
        print(projectCRS.toWkt())
        speckleReprojectedCrs = CRS(name=projectCRS.authid(), wkt=projectCRS.toWkt(), units=units_proj) 
        layerCRS = CRS(name=crs.authid(), wkt=crs.toWkt(), units=units_layer) 
        
        renderer = selectedLayer.renderer()
        layerRenderer = rendererToSpeckle(renderer) 
        
        if isinstance(selectedLayer, QgsVectorLayer):

            fieldnames = [] #[str(field.name()) for field in selectedLayer.fields()]
            attributes = Base()
            for field in selectedLayer.fields():
                fieldnames.append(str(field.name()))
                corrected = validateAttributeName(str(field.name()), [])
                attribute_type = field.type()
                r'''
                all_types = [
                    (1, "bool"), 
                    (2, "int"),
                    (6, "decimal"),
                    (8, "map"),
                    (9, "int_list"),
                    (10, "string"),
                    (11, "string_list"),
                    (12, "binary"),
                    (14, "date"),
                    (15, "time"),
                    (16, "date_time") 
                ]
                for att_type in all_types:
                    if attribute_type == att_type[0]:
                        attribute_type = att_type[1]
                '''
                attributes[corrected] = attribute_type

            # write feature attributes
            for f in selectedLayer.getFeatures():
                b = featureToSpeckle(fieldnames, f, crs, projectCRS, project, selectedLayer, plugin.dataStorage)
                layerObjs.append(b)
            # Convert layer to speckle
            layerBase = VectorLayer(units = units_proj, name=layerName, crs=speckleReprojectedCrs, elements=layerObjs, attributes = attributes, type="VectorLayer", geomType=getLayerGeomType(selectedLayer))
            layerBase.type="VectorLayer"
            layerBase.renderer = layerRenderer
            layerBase.applicationId = selectedLayer.id()
            #print(layerBase.features)
            return layerBase

        if isinstance(selectedLayer, QgsRasterLayer):
            # write feature attributes
            b = rasterFeatureToSpeckle(selectedLayer, projectCRS, project, plugin.dataStorage)
            layerObjs.append(b)
            # Convert layer to speckle
            layerBase = RasterLayer(units = units_proj, name=layerName, crs=speckleReprojectedCrs, rasterCrs=layerCRS, elements=layerObjs, type="RasterLayer")
            layerBase.type="RasterLayer"
            layerBase.renderer = layerRenderer
            layerBase.applicationId = selectedLayer.id()
            return layerBase
    except Exception as e:
        logToUser(e, level = 2, func = inspect.stack()[0][3], plugin = plugin.dockwidget)
        return  


def layerToNative(layer: Union[Layer, VectorLayer, RasterLayer], streamBranch: str, plugin) -> Union[QgsVectorLayer, QgsRasterLayer, None]:
    try:
        project: QgsProject = plugin.qgis_project
        #plugin.dataStorage.currentCRS = project.crs()
        plugin.dataStorage.currentUnits = layer.crs.units 
        if plugin.dataStorage.currentUnits is None or plugin.dataStorage.currentUnits == 'degrees': 
            plugin.dataStorage.currentUnits = 'm'

        if layer.type is None:
            # Handle this case
            return
        
        if layer.type.endswith("VectorLayer"):
            vectorLayerToNative(layer, streamBranch, plugin)
            return 
        
        elif layer.type.endswith("RasterLayer"):
            rasterLayerToNative(layer, streamBranch, plugin)
            return 
        
        return None
    except Exception as e:
        logToUser(e, level = 2, func = inspect.stack()[0][3], plugin = plugin.dockwidget)
        return  


def bimLayerToNative(layerContentList: List[Base], layerName: str, streamBranch: str, plugin):
    print("01______BIM layer to native")
    try:
        project: QgsProject = plugin.qgis_project
        print(layerName)

        geom_meshes = []
        layer_meshes = None

        #filter speckle objects by type within each layer, create sub-layer for each type (points, lines, polygons, mesh?)
        for geom in layerContentList:
            if geom.speckle_type =='Objects.Geometry.Mesh':
                geom_meshes.append(geom)
            else:
                try: 
                    if geom.displayValue: geom_meshes.append(geom)
                except:
                    try: 
                        if geom["@displayValue"]: geom_meshes.append(geom)
                    except:
                        try: 
                            if geom.displayMesh: geom_meshes.append(geom)
                        except: pass
            
            #if geom.speckle_type == 'Objects.BuiltElements.Alignment':

        
        if len(geom_meshes)>0: layer_meshes = bimVectorLayerToNative(geom_meshes, layerName, "Mesh", streamBranch, plugin)

        return True
    
    except Exception as e:
        logToUser(e, level = 2, func = inspect.stack()[0][3], plugin = plugin.dockwidget)
        return  

def bimVectorLayerToNative(geomList: List[Base], layerName_old: str, geomType: str, streamBranch: str, plugin): 
    print("02_________BIM vector layer to native_____")
    try: 
        project: QgsProject = plugin.qgis_project
        print(layerName_old)

        layerName = layerName_old[:50]
        layerName = removeSpecialCharacters(layerName) 
        #layerName = removeSpecialCharacters(layerName_old)[:30]
        print(layerName)

        #get Project CRS, use it by default for the new received layer
        vl = None
        layerName = layerName + "_" + geomType
        print(layerName)

        #find ID of the layer with a matching name in the "latest" group 
        #newName = f'{streamBranch}_{layerName}'
        
        if "mesh" in geomType.lower(): geomType = "MultiPolygonZ"
        
        newFields = getLayerAttributes(geomList)
        print("___________Layer fields_____________")
        print(newFields.toList())
                
        plugin.dockwidget.addBimLayerToGroup.emit(geomType, layerName, streamBranch, newFields, geomList)
        return 
    except Exception as e:
        logToUser(e, level = 2, func = inspect.stack()[0][3], plugin = plugin.dockwidget)
        return  


def addBimMainThread(plugin, geomType, layerName, streamBranch, newFields, geomList):
    try: 
        project: QgsProject = plugin.dataStorage.project

        
        newName = f'{streamBranch.split("_")[len(streamBranch.split("_"))-1]}_{layerName}'
        newName_shp = f'{streamBranch.split("_")[len(streamBranch.split("_"))-1]}/{layerName}'


        ###########################################
        dummy = None 
        root = project.layerTreeRoot()
        plugin.dataStorage.all_layers = getAllLayers(root)
        if plugin.dataStorage.all_layers is not None: 
            if len(plugin.dataStorage.all_layers) == 0:
                dummy = QgsVectorLayer("Point?crs=EPSG:4326", "", "memory") # do something to distinguish: stream_id_latest_name
                crs = QgsCoordinateReferenceSystem(4326)
                dummy.setCrs(crs)
                project.addMapLayer(dummy, True)
        #################################################

        
        crs = project.crs() #QgsCoordinateReferenceSystem.fromWkt(layer.crs.wkt)
        plugin.dataStorage.currentUnits = QgsUnitTypes.encodeUnit(crs.mapUnits())
        if plugin.dataStorage.currentUnits is None or plugin.dataStorage.currentUnits == 'degrees': 
            plugin.dataStorage.currentUnits = 'm'

        if crs.isGeographic is True: 
            logToUser(f"Project CRS is set to Geographic type, and objects in linear units might not be received correctly", level = 1, func = inspect.stack()[0][3])

        p = os.path.expandvars(r'%LOCALAPPDATA%') + "\\Temp\\Speckle_QGIS_temp\\" + datetime.now().strftime("%Y-%m-%d %H-%M")
        findOrCreatePath(p)
        path = p
        #logToUser(f"BIM layers can only be received in an existing saved project. Layer {layerName} will be ignored", level = 1, func = inspect.stack()[0][3])

        path_bim = path + "/Layers_Speckle/BIM_layers/" + streamBranch+ "/" + layerName + "/" #arcpy.env.workspace + "\\" #

        findOrCreatePath(path_bim)
        print(path_bim)

        shp = writeMeshToShp(geomList, path_bim + newName_shp)
        if shp is None: return 
        print("____ meshes saved___")
        print(shp)

        vl_shp = QgsVectorLayer( shp + ".shp", newName, "ogr") # do something to distinguish: stream_id_latest_name
        vl = QgsVectorLayer( geomType+ "?crs=" + crs.authid(), newName, "memory") # do something to distinguish: stream_id_latest_name
        vl.setCrs(crs)
        project.addMapLayer(vl, False)

        pr = vl.dataProvider()
        vl.startEditing()

        # add Layer attribute fields
        pr.addAttributes(newFields)
        vl.updateFields()

        # create list of Features (fets) and list of Layer fields (fields)
        #attrs = QgsFields()
        fets = []
        fetIds = []
        fetColors = []
        
        for i,f in enumerate(geomList[:]): 
            try:
                exist_feat: None = None
                for n, shape in enumerate(vl_shp.getFeatures()):
                    #print(shape["speckle_id"])
                    if shape["speckle_id"] == f.id:
                        exist_feat = vl_shp.getFeature(n)
                        break
                if exist_feat is None: 
                    logToUser(f"Feature skipped due to invalid geometry", level = 2, func = inspect.stack()[0][3])
                    continue 

                new_feat = bimFeatureToNative(exist_feat, f, vl.fields(), crs, path_bim)
                if new_feat is not None and new_feat != "": 
                    fetColors = findFeatColors(fetColors, f)
                    fets.append(new_feat)
                    vl.addFeature(new_feat)
                    fetIds.append(f.id)
                else:
                    logToUser(f"Feature skipped due to invalid geometry", level = 2, func = inspect.stack()[0][3])
            except Exception as e: print(e)
        
        vl.updateExtents()
        vl.commitChanges()
        
        layerGroup = tryCreateGroup(project, streamBranch)
        layerGroup.addLayer(vl)
        print(vl)

        
        try: 
            ################################### RENDERER 3D ###########################################
            #rend3d = QgsVectorLayer3DRenderer() # https://qgis.org/pyqgis/3.16/3d/QgsVectorLayer3DRenderer.html?highlight=layer3drenderer#module-QgsVectorLayer3DRenderer

            plugin_dir = os.path.dirname(__file__)
            renderer3d = os.path.join(plugin_dir, 'renderer3d.qml')
            print(renderer3d)

            vl.loadNamedStyle(renderer3d)
            vl.triggerRepaint()
        except: pass 
        
        try:
            ################################### RENDERER ###########################################
            # only set up renderer if the layer is just created
            attribute = 'Speckle_ID'
            categories = []
            for i in range(len(fets)):
                material = fetColors[i]
                color = colorFromSpeckle(material)

                symbol = QgsSymbol.defaultSymbol(QgsWkbTypes.geometryType(QgsWkbTypes.parseType(geomType)))
                symbol.setColor(color)
                categories.append(QgsRendererCategory(fetIds[i], symbol, fetIds[i], True) )  
            # create empty category for all other values
            symbol2 = symbol.clone()
            symbol2.setColor(QColor.fromRgb(245,245,245))
            cat = QgsRendererCategory()
            cat.setSymbol(symbol2)
            cat.setLabel('Other')
            categories.append(cat)        
            rendererNew = QgsCategorizedSymbolRenderer(attribute, categories)
        except Exception as e: print(e)

        try: vl.setRenderer(rendererNew)
        except: pass

        
        try: project.removeMapLayer(dummy)
        except: pass
        
    except Exception as e:
        logToUser(e, level = 2, func = inspect.stack()[0][3], plugin = plugin.dockwidget)
        

def cadLayerToNative(layerContentList:Base, layerName: str, streamBranch: str, plugin) -> List[QgsVectorLayer or None]:
    print("02_________ CAD vector layer to native_____")
    try:
        project: QgsProject = plugin.qgis_project

        geom_points = []
        geom_polylines = []
        geom_meshes = []

        layer_points = None
        layer_polylines = None
        #filter speckle objects by type within each layer, create sub-layer for each type (points, lines, polygons, mesh?)
        for geom in layerContentList:
            #print(geom)
            if geom.speckle_type == "Objects.Geometry.Point": 
                geom_points.append(geom)
            if geom.speckle_type == "Objects.Geometry.Line" or geom.speckle_type == "Objects.Geometry.Polyline" or geom.speckle_type == "Objects.Geometry.Curve" or geom.speckle_type == "Objects.Geometry.Arc" or geom.speckle_type == "Objects.Geometry.Circle" or geom.speckle_type == "Objects.Geometry.Ellipse" or geom.speckle_type == "Objects.Geometry.Polycurve":
                geom_polylines.append(geom)
            try:
                if geom.speckle_type.endswith(".ModelCurve") and geom["baseCurve"].speckle_type in GEOM_LINE_TYPES:
                    geom_polylines.append(geom["baseCurve"])
                if geom["baseLine"].speckle_type in GEOM_LINE_TYPES:
                    geom_polylines.append(geom["baseLine"])
            except: pass
        
        if len(geom_points)>0: layer_points = cadVectorLayerToNative(geom_points, layerName, "Points", streamBranch, plugin)
        if len(geom_polylines)>0: layer_polylines = cadVectorLayerToNative(geom_polylines, layerName, "Polylines", streamBranch, plugin)
        #print(layerName)
        #print(layer_points)
        #print(layer_polylines)
        return [layer_points, layer_polylines]
    except Exception as e:
        logToUser(e, level = 2, func = inspect.stack()[0][3], plugin = plugin.dockwidget)
        return []

def cadVectorLayerToNative(geomList: List[Base], layerName: str, geomType: str, streamBranch: str, plugin) -> QgsVectorLayer: 
    print("___________cadVectorLayerToNative")
    try:
        project: QgsProject = plugin.qgis_project

        #get Project CRS, use it by default for the new received layer
        vl = None

        layerName = removeSpecialCharacters(layerName) 

        layerName = layerName + "_" + geomType
        print(layerName)

        newName = f'{streamBranch.split("_")[len(streamBranch.split("_"))-1]}/{layerName}'

        if geomType == "Points": geomType = "PointZ"
        elif geomType == "Polylines": geomType = "LineStringZ"

        
        newFields = getLayerAttributes(geomList)
        print(newFields.toList())
        print(geomList)
        
        plugin.dockwidget.addCadLayerToGroup.emit(geomType, newName, streamBranch, newFields, geomList)
        return 
    except Exception as e:
        logToUser(e, level = 2, func = inspect.stack()[0][3], plugin = plugin.dockwidget)
        return  
    
def addCadMainThread(plugin, geomType, newName, streamBranch, newFields, geomList ):
    try:
        project: QgsProject = plugin.dataStorage.project

        ###########################################
        dummy = None 
        root = project.layerTreeRoot()
        plugin.dataStorage.all_layers = getAllLayers(root)
        if plugin.dataStorage.all_layers is not None: 
            if len(plugin.dataStorage.all_layers) == 0:
                dummy = QgsVectorLayer("Point?crs=EPSG:4326", "", "memory") # do something to distinguish: stream_id_latest_name
                crs = QgsCoordinateReferenceSystem(4326)
                dummy.setCrs(crs)
                project.addMapLayer(dummy, True)
        #################################################

        crs = project.crs() #QgsCoordinateReferenceSystem.fromWkt(layer.crs.wkt)
        plugin.dataStorage.currentUnits = QgsUnitTypes.encodeUnit(crs.mapUnits())
        if plugin.dataStorage.currentUnits is None or plugin.dataStorage.currentUnits == 'degrees': 
            plugin.dataStorage.currentUnits = 'm'
        #authid = trySaveCRS(crs, streamBranch)

        if crs.isGeographic is True: 
            logToUser(f"Project CRS is set to Geographic type, and objects in linear units might not be received correctly", level = 1, func = inspect.stack()[0][3])

        
        vl = QgsVectorLayer( geomType+ "?crs=" + crs.authid() , newName, "memory") # do something to distinguish: stream_id_latest_name
        vl.setCrs(crs)
        project.addMapLayer(vl, False)

        pr = vl.dataProvider()
        vl.startEditing()
        
        
        # create list of Features (fets) and list of Layer fields (fields)
        attrs = QgsFields()
        fets = []
        fetIds = []
        fetColors = []
        for f in geomList[:]: 
            new_feat = cadFeatureToNative(f, newFields, plugin.dataStorage)
            # update attrs for the next feature (if more fields were added from previous feature)

            print("________cad feature to add") 
            if new_feat is not None and new_feat != "": 
                fets.append(new_feat)
                for a in newFields.toList(): 
                    attrs.append(a) 
                
                pr.addAttributes(newFields) # add new attributes from the current object
                fetIds.append(f.id)
                fetColors = findFeatColors(fetColors, f)
            else:
                logToUser(f"Feature skipped due to invalid geometry", level = 2, func = inspect.stack()[0][3])

        
        # add Layer attribute fields
        pr.addAttributes(newFields)
        vl.updateFields()

        #pr = vl.dataProvider()
        pr.addFeatures(fets)
        vl.updateExtents()
        vl.commitChanges()
        layerGroup = tryCreateGroup(project, streamBranch)
        layerGroup.addLayer(vl)

        ################################### RENDERER ###########################################
        # only set up renderer if the layer is just created
        attribute = 'Speckle_ID'
        categories = []
        for i in range(len(fets)):
            rgb = fetColors[i]
            if rgb:
                r = (rgb & 0xFF0000) >> 16
                g = (rgb & 0xFF00) >> 8
                b = rgb & 0xFF 
                color = QColor.fromRgb(r, g, b)
            else: color = QColor.fromRgb(0,0,0)

            symbol = QgsSymbol.defaultSymbol(QgsWkbTypes.geometryType(QgsWkbTypes.parseType(geomType)))
            symbol.setColor(color)
            categories.append(QgsRendererCategory(fetIds[i], symbol, fetIds[i], True) )  
        # create empty category for all other values
        symbol2 = symbol.clone()
        symbol2.setColor(QColor.fromRgb(0,0,0))
        cat = QgsRendererCategory()
        cat.setSymbol(symbol2)
        cat.setLabel('Other')
        categories.append(cat)        
        rendererNew = QgsCategorizedSymbolRenderer(attribute, categories)

        try: vl.setRenderer(rendererNew)
        except: pass

        try: 
            ################################### RENDERER 3D ###########################################
            #rend3d = QgsVectorLayer3DRenderer() # https://qgis.org/pyqgis/3.16/3d/QgsVectorLayer3DRenderer.html?highlight=layer3drenderer#module-QgsVectorLayer3DRenderer

            plugin_dir = os.path.dirname(__file__)
            renderer3d = os.path.join(plugin_dir, 'renderer3d.qml')
            print(renderer3d)

            vl.loadNamedStyle(renderer3d)
            vl.triggerRepaint()
        except: pass 

        try: project.removeMapLayer(dummy)
        except: pass
        
    except Exception as e:
        logToUser(e, level = 2, func = inspect.stack()[0][3], plugin = plugin.dockwidget)
          

def vectorLayerToNative(layer: Layer or VectorLayer, streamBranch: str, plugin):
    try:
        project: QgsProject = plugin.qgis_project
        layerName = removeSpecialCharacters(layer.name) 

        #find ID of the layer with a matching name in the "latest" group 
        newName = f'{streamBranch.split("_")[len(streamBranch.split("_"))-1]}_{layerName}'

        # particularly if the layer comes from ArcGIS
        geomType = layer.geomType # for ArcGIS: Polygon, Point, Polyline, Multipoint, MultiPatch
        if geomType =="Point": geomType = "Point"
        elif geomType =="Polygon": geomType = "Multipolygon"
        elif geomType =="Polyline": geomType = "MultiLineString"
        elif geomType =="Multipoint": geomType = "Point"
        elif geomType == 'MultiPatch': geomType = "Polygon"
        
        fets = []
        newFields = getLayerAttributes(layer.features)
        for f in layer.features: 
            new_feat = featureToNative(f, newFields, plugin.dataStorage)
            if new_feat is not None and new_feat != "": fets.append(new_feat)
            else:
                logToUser(f"Feature skipped due to invalid geometry", level = 2, func = inspect.stack()[0][3])
        
        plugin.dockwidget.addLayerToGroup.emit(geomType, newName, streamBranch, layer.crs.wkt, layer, newFields, fets)
        return 
    
    except Exception as e:
        logToUser(e, level = 2, func = inspect.stack()[0][3], plugin = plugin.dockwidget)
        return  
    
def addVectorMainThread(plugin, geomType, newName, streamBranch, wkt, layer, newFields, fets):
    try:
        project: QgsProject = plugin.dataStorage.project

        ###########################################
        dummy = None 
        root = project.layerTreeRoot()
        plugin.dataStorage.all_layers = getAllLayers(root)
        if plugin.dataStorage.all_layers is not None: 
            if len(plugin.dataStorage.all_layers) == 0:
                dummy = QgsVectorLayer("Point?crs=EPSG:4326", "", "memory") # do something to distinguish: stream_id_latest_name
                crs = QgsCoordinateReferenceSystem(4326)
                dummy.setCrs(crs)
                project.addMapLayer(dummy, True)
        #################################################

        crs = QgsCoordinateReferenceSystem.fromWkt(wkt) #moved up, because CRS of existing layer needs to be rewritten
        srsid = trySaveCRS(crs, streamBranch)
        crs_new = QgsCoordinateReferenceSystem.fromSrsId(srsid)
        authid = crs_new.authid()
        
        vl = None
        vl = QgsVectorLayer(geomType + "?crs=" + authid, newName, "memory") # do something to distinguish: stream_id_latest_name
        vl.setCrs(crs)
        project.addMapLayer(vl, False)

        pr = vl.dataProvider()
        #vl.setCrs(crs)
        vl.startEditing()
        #print(vl.crs())

        # add Layer attribute fields
        pr.addAttributes(newFields.toList())
        vl.updateFields()

        pr.addFeatures(fets)
        vl.updateExtents()
        vl.commitChanges()
        
        layerGroup = tryCreateGroup(project, streamBranch)

        layerGroup.addLayer(vl)

        rendererNew = vectorRendererToNative(layer, newFields)
        if rendererNew is None:
            symbol = QgsSymbol.defaultSymbol(QgsWkbTypes.geometryType(QgsWkbTypes.parseType(geomType)))
            rendererNew = QgsSingleSymbolRenderer(symbol)
        
        
        #time.sleep(3)
        try: vl.setRenderer(rendererNew)
        except: pass

        try: 
            ################################### RENDERER 3D ###########################################
            #rend3d = QgsVectorLayer3DRenderer() # https://qgis.org/pyqgis/3.16/3d/QgsVectorLayer3DRenderer.html?highlight=layer3drenderer#module-QgsVectorLayer3DRenderer

            plugin_dir = os.path.dirname(__file__)
            renderer3d = os.path.join(plugin_dir, 'renderer3d.qml')
            print(renderer3d)

            vl.loadNamedStyle(renderer3d)
            vl.triggerRepaint()
        except: pass 

        try: project.removeMapLayer(dummy)
        except: pass

    except Exception as e:
        logToUser(e, level = 2, func = inspect.stack()[0][3], plugin = plugin.dockwidget)
          
    
def rasterLayerToNative(layer: RasterLayer, streamBranch: str, plugin):
    try:
        project = plugin.qgis_project
        layerName = removeSpecialCharacters(layer.name) + "_Speckle"

        newName = f'{streamBranch.split("_")[len(streamBranch.split("_"))-1]}_{layerName}'

        plugin.dockwidget.addRasterLayerToGroup.emit(layerName, newName, streamBranch, layer)
        
        return 
    except Exception as e:
        logToUser(e, level = 2, func = inspect.stack()[0][3], plugin = plugin.dockwidget)
        return  

def addRasterMainThread(plugin, layerName, newName, streamBranch, layer):
    try: 
        project: QgsProject = plugin.dataStorage.project

        ###########################################
        dummy = None 
        root = project.layerTreeRoot()
        plugin.dataStorage.all_layers = getAllLayers(root)
        if plugin.dataStorage.all_layers is not None: 
            if len(plugin.dataStorage.all_layers) == 0:
                dummy = QgsVectorLayer("Point?crs=EPSG:4326", "", "memory") # do something to distinguish: stream_id_latest_name
                crs = QgsCoordinateReferenceSystem(4326)
                dummy.setCrs(crs)
                project.addMapLayer(dummy, True)
        #################################################

        ######################## testing, only for receiving layers #################
        source_folder = project.absolutePath()

        feat = layer.features[0]
        
        vl = None
        crs = QgsCoordinateReferenceSystem.fromWkt(layer.crs.wkt) #moved up, because CRS of existing layer needs to be rewritten
        # try, in case of older version "rasterCrs" will not exist 
        try: 
            crsRasterWkt = str(layer.rasterCrs.wkt)
            crsRaster = QgsCoordinateReferenceSystem.fromWkt(layer.rasterCrs.wkt) #moved up, because CRS of existing layer needs to be rewritten
        except: 
            crsRasterWkt = str(layer.crs.wkt)
            crsRaster = crs
            logToUser(f"Raster layer {layer.name} might have been sent from the older version of plugin. Try sending it again for more accurate results.", level = 1, func = inspect.stack()[0][3])
        
        srsid = trySaveCRS(crsRaster, streamBranch)
        crs_new = QgsCoordinateReferenceSystem.fromSrsId(srsid)
        authid = crs_new.authid()

        try:
            bandNames = feat.band_names
        except: 
            bandNames = feat["Band names"]
        bandValues = [feat["@(10000)" + name + "_values"] for name in bandNames]

        

        if(source_folder == ""):
            p = os.path.expandvars(r'%LOCALAPPDATA%') + "\\Temp\\Speckle_QGIS_temp\\" + datetime.now().strftime("%Y-%m-%d %H-%M")
            findOrCreatePath(p)
            source_folder = p
            logToUser(f"Project directory not found. Raster layers will be saved to \"{p}\".", level = 1, func = inspect.stack()[0][3], plugin = plugin.dockwidget)

        path_fn = source_folder + "/Layers_Speckle/raster_layers/" + streamBranch+ "/" 
        if not os.path.exists(path_fn): os.makedirs(path_fn)

        
        fn = path_fn + layerName + ".tif" #arcpy.env.workspace + "\\" #
        #fn = source_folder + '/' + newName.replace("/","_") + '.tif' #'_received_raster.tif'
        driver = gdal.GetDriverByName('GTiff')
        # create raster dataset
        try:
            ds = driver.Create(fn, xsize=feat.x_size, ysize=feat.y_size, bands=feat.band_count, eType=gdal.GDT_Float32)
        except: 
            ds = driver.Create(fn, xsize=feat["X pixels"], ysize=feat["Y pixels"], bands=feat["Band count"], eType=gdal.GDT_Float32)

        # Write data to raster band
        # No data issue: https://gis.stackexchange.com/questions/389587/qgis-set-raster-no-data-value
        
        try:
            b_count = int(feat.band_count) # from 2.14
        except:
            b_count = feat["Band count"]
        
        for i in range(b_count):
            rasterband = np.array(bandValues[i])
            try:
                rasterband = np.reshape(rasterband,(feat.y_size, feat.x_size))
            except:
                rasterband = np.reshape(rasterband,(feat["Y pixels"], feat["X pixels"]))

            band = ds.GetRasterBand(i+1) # https://pcjericks.github.io/py-gdalogr-cookbook/raster_layers.html
            
            # get noDataVal or use default
            try: 
                try:
                    noDataVal = float(feat.noDataValue)
                except:
                    noDataVal = float(feat["NoDataVal"][i]) # if value available
                try: band.SetNoDataValue(noDataVal)
                except: band.SetNoDataValue(float(noDataVal))
            except: pass

            band.WriteArray(rasterband) # or "rasterband.T"
        
        # create GDAL transformation in format [top-left x coord, cell width, 0, top-left y coord, 0, cell height]
        pt = None
        try:
            try:
                pt = QgsPoint(feat.x_origin, feat.y_origin, 0)
            except: 
                pt = QgsPoint(feat["X_min"], feat["Y_min"], 0)
        except: 
            try:
                displayVal = feat.displayValue
            except:
                displayVal = feat["displayValue"]
            if displayVal is not None:
                if isinstance(displayVal[0], Point): 
                    pt = pointToNative(displayVal[0], plugin.dataStorage)
                if isinstance(displayVal[0], Mesh): 
                    pt = QgsPoint(displayVal[0].vertices[0], displayVal[0].vertices[1])
        if pt is None:
            logToUser("Raster layer doesn't have the origin point", level = 2, func = inspect.stack()[0][3], plugin = plugin.dockwidget)
            return 
        
        xform = QgsCoordinateTransform(crs, crsRaster, project)
        pt.transform(xform)
        try:
            ds.SetGeoTransform([pt.x(), feat.x_resolution, 0, pt.y(), 0, feat.y_resolution])
        except:
            ds.SetGeoTransform([pt.x(), feat["X resolution"], 0, pt.y(), 0, feat["Y resolution"]])
        
        # create a spatial reference object
        ds.SetProjection(crsRasterWkt)
        # close the rater datasource by setting it equal to None
        ds = None

        raster_layer = QgsRasterLayer(fn, newName, 'gdal')
        project.addMapLayer(raster_layer, False)
        
        layerGroup = tryCreateGroup(project, streamBranch)
        layerGroup.addLayer(raster_layer)

        dataProvider = raster_layer.dataProvider()
        rendererNew = rasterRendererToNative(layer, dataProvider)

        try: raster_layer.setRenderer(rendererNew)
        except: pass


        try: project.removeMapLayer(dummy)
        except: pass

    except Exception as e:
        logToUser(e, level = 2, func = inspect.stack()[0][3], plugin = plugin.dockwidget)
          