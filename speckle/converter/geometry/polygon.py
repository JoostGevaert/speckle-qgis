""" This module contains all geometry conversion functionality To and From Speckle."""

import inspect
from qgis.core import Qgis, QgsGeometry, QgsPolygon, QgsPointXY, QgsPoint, QgsFeature, QgsVectorLayer

from typing import List, Sequence

from specklepy.objects.geometry import Point, Line, Polyline, Circle, Arc, Polycurve, Mesh 
from specklepy.objects import Base
from specklepy.objects.geometry import Point

from speckle.converter.geometry.mesh import meshPartsFromPolygon, constructMesh
from speckle.converter.geometry.polyline import (
    polylineToNative,
    unknownLineToSpeckle
)
from speckle.converter.geometry.utils import *
from speckle.logging import logger
import math

from panda3d.core import Triangulator

from PyQt5.QtGui import QColor

from ui.logger import logToUser

def polygonToSpeckleMesh(geom: QgsGeometry, feature: QgsFeature, layer: QgsVectorLayer):

    polygon = Base(units = "m")
    try: 

        vertices = []
        faces = [] 
        colors = []
        existing_vert = 0
        for p in geom.parts():
            boundary, voids = getPolyBoundaryVoids(p, feature, layer)
            polyBorder = speckleBoundaryToSpecklePts(boundary)
            voidsAsPts = []
            for v in voids:
                pts = speckleBoundaryToSpecklePts(v)
                voidsAsPts.append(pts)
            total_vert, vertices_x, faces_x, colors_x = meshPartsFromPolygon(polyBorder, voidsAsPts, existing_vert, feature, layer)

            existing_vert += total_vert
            vertices.extend(vertices_x)
            faces.extend(faces_x)
            colors.extend(colors_x)

        mesh = constructMesh(vertices, faces, colors)
        polygon.displayValue = [ mesh ] 
    except Exception as e:
        logToUser(e, level = 2, func = inspect.stack()[0][3])
    

    return polygon 

def polygonToSpeckle(geom: QgsGeometry, feature: QgsFeature, layer: QgsVectorLayer):
    """Converts a QgsPolygon to Speckle"""
    polygon = Base(units = "m")
    try:
        boundary, voids = getPolyBoundaryVoids(geom, feature, layer)
    
        polygon.boundary = boundary
        polygon.voids = voids
        polygon.displayValue = [ boundary ] + voids
        
        polyBorder = speckleBoundaryToSpecklePts(boundary)
        voidsAsPts = []
        for v in voids:
            pts = speckleBoundaryToSpecklePts(v)
            voidsAsPts.append(pts)

        total_vert, vertices, faces, colors = meshPartsFromPolygon(polyBorder, voidsAsPts, 0, feature, layer)

        mesh = constructMesh(vertices, faces, colors)
        polygon.displayValue = [ mesh ] 

        return polygon
    except Exception as e:
        logToUser("Some polygons might be invalid" + str(e), level = 1, func = inspect.stack()[0][3])
        return polygon 

    


def polygonToNative(poly: Base) -> QgsPolygon:
    """Converts a Speckle Polygon base object to QgsPolygon.
    This object must have a 'boundary' and 'voids' properties.
    Each being a Speckle Polyline and List of polylines respectively."""
    #print(polylineToNative(poly["boundary"]))
    
    polygon = QgsPolygon()
    try:
        try: # if it's indeed a polygon with QGIS properties
            polygon.setExteriorRing(polylineToNative(poly["boundary"]))
        except: return
        try:
            for void in poly["voids"]: 
                #print(polylineToNative(void))
                polygon.addInteriorRing(polylineToNative(void))
        except:pass
        #print(polygon)
        #print()

        #polygon = QgsPolygon(
        #    polylineToNative(poly["boundary"]),
        #    [polylineToNative(void) for void in poly["voids"]],
        #)
        return polygon
    except Exception as e:
        logToUser(e, level = 2, func = inspect.stack()[0][3])
        return polygon 

def getPolyBoundaryVoids(geom: QgsGeometry, feature: QgsFeature, layer: QgsVectorLayer):
    boundary = None
    voids: List[Union[None, Polyline, Arc, Line, Polycurve]] = []
    try: 
        pointList = []
        pt_iterator = []
        extRing = None
        try: 
            extRing = geom.exteriorRing()
            pt_iterator = extRing.vertices()
        except: 
            try:  
                extRing = geom.constGet().exteriorRing()
                pt_iterator = geom.vertices()
            except: 
                extRing = geom
                pt_iterator = geom.vertices()
        for pt in pt_iterator: pointList.append(pt) 
        if extRing is not None: 
            boundary = unknownLineToSpeckle(extRing, True, feature, layer)
        else: return boundary, voids

        try:
            for i in range(geom.numInteriorRings()):
                intRing = unknownLineToSpeckle(geom.interiorRing(i), True, feature, layer)
                #intRing = polylineFromVerticesToSpeckle(geom.interiorRing(i).vertices(), True, feature, layer)
                voids.append(intRing)
        except: 
            try:
                geom = geom.constGet()
                for i in range(geom.numInteriorRings()):
                    intRing = unknownLineToSpeckle(geom.interiorRing(i), True, feature, layer)
                    #intRing = polylineFromVerticesToSpeckle(geom.interiorRing(i).vertices(), True, feature, layer)
                    voids.append(intRing)
            except: pass     

        return boundary, voids
    
    except Exception as e:
        logToUser(e, level = 2, func = inspect.stack()[0][3])
        return None, None 
    
