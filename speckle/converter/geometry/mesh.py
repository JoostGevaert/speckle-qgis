import math
from typing import List
from specklepy.objects.geometry import Mesh, Point
from specklepy.objects.other import RenderMaterial

import shapefile
from shapefile import TRIANGLE_STRIP, TRIANGLE_FAN
from speckle.converter.geometry.point import pointToNative
from speckle.converter.layers.symbology import featureColorfromNativeRenderer
from speckle.converter.layers.utils import get_scale_factor
from speckle.logging import logger
from qgis.core import (
    Qgis, QgsPoint, QgsPointXY, QgsMultiPolygon, QgsPolygon, QgsLineString, QgsFeature, QgsVectorLayer
    )
from panda3d.core import Triangulator

def meshToNative(meshes: List[Mesh]) -> QgsMultiPolygon:
    multiPolygon = QgsMultiPolygon()
    for mesh in meshes:
        parts_list = deconstructSpeckleMesh(mesh)
        for part in parts_list: 
            polygon = QgsPolygon()
            pts = [Point(x=pt[0], y=pt[1], z=pt[2], units="m") for pt in part]
            pts.append(pts[0])
            boundary = QgsLineString([pointToNative(pt) for pt in pts])
            polygon.setExteriorRing(boundary)

            if polygon is not None:
                multiPolygon.addGeometry(polygon)
    return multiPolygon
    
def writeMeshToShp(meshes: List[Mesh], path: str):
    """Converts a Speckle Mesh to QgsGeometry"""
    print("06___________________Mesh to Native")
    #print(meshes)
    #print(mesh.units)
    w = shapefile.Writer(path) 
    w.field('speckle_id', 'C')

    shapes = []
    for geom in meshes:

        if geom.speckle_type =='Objects.Geometry.Mesh' and isinstance(geom, Mesh):
            mesh = geom
            w = fill_mesh_parts(w, mesh, geom.id)
        else:
            try: 
                if geom.displayValue and isinstance(geom.displayValue, Mesh): 
                    mesh = geom.displayValue
                    w = fill_mesh_parts(w, mesh, geom.id)
                elif geom.displayValue and isinstance(geom.displayValue, List): 
                    for part in geom.displayValue:
                        if isinstance(part, Mesh): 
                            mesh = part
                            w = fill_mesh_parts(w, mesh, geom.id)
            except: 
                try: 
                    if geom["@displayValue"] and isinstance(geom["@displayValue"], Mesh): 
                        mesh = geom["@displayValue"]
                        w = fill_mesh_parts(w, mesh, geom.id)
                    elif geom["@displayValue"] and isinstance(geom["@displayValue"], List): 
                        for part in geom["@displayValue"]:
                            if isinstance(part, Mesh): 
                                mesh = part
                                w = fill_mesh_parts(w, mesh, geom.id)
                except:
                    try: 
                        if geom.displayMesh and isinstance(geom.displayMesh, Mesh): 
                            mesh = geom.displayMesh
                            w = fill_mesh_parts(w, mesh, geom.id)
                        elif geom.displayMesh and isinstance(geom.displayMesh, List): 
                            for part in geom.displayMesh:
                                if isinstance(part, Mesh): 
                                    mesh = part
                                    w = fill_mesh_parts(w, mesh, geom.id)
                    except: pass
    w.close()
    return path

def fill_mesh_parts(w: shapefile.Writer, mesh: Mesh, geom_id: str):
    
    try:
        #print(len(mesh.faces))
        if len(mesh.faces) % 4 == 0 and (mesh.faces[0] == 0 or mesh.faces[0] == 3):
            parts_list, types_list = deconstructTriangleMesh(mesh) 
            w.multipatch(parts_list, partTypes=types_list ) # one type for each part
            w.record(geom_id)
        else: 
            logger.logToUser("Received mesh type is not supported", Qgis.Warning)
            #print("not triangulated mesh")

    except Exception as e: pass #; print(e)
    #print("mesh part written")
    return w

def deconstructSpeckleMesh(mesh: Mesh):
    
    scale = get_scale_factor(mesh.units)
    parts_list = []
    types_list = []

    count = 0 # sequence of vertex (not of flat coord list) 
    for f in mesh.faces: # real number of loops will be at least 3 times less 
        try:
            vertices = mesh.faces[count]
            if mesh.faces[count] == 0: vertices = 3
            
            face = []
            for i in range(vertices):
                index_faces = count + 1 + i 
                index_vertices = mesh.faces[index_faces]*3
                face.append([ scale * mesh.vertices[index_vertices], scale * mesh.vertices[index_vertices+1], scale * mesh.vertices[index_vertices+2] ]) 

            parts_list.append(face)
            count += vertices + 1
        except: break # when out of range 

    return parts_list

def deconstructTriangleMesh(mesh: Mesh):

    scale = get_scale_factor(mesh.units)
    parts_list = []
    types_list = []

    count = 0 # sequence of vertex (not of flat coord list) 
    for f in mesh.faces:
        try:
            if mesh.faces[count] == 0 or mesh.faces[count] == 3: # only handle triangles
                f1 = [ scale*mesh.vertices[mesh.faces[count+1]*3], scale*mesh.vertices[mesh.faces[count+1]*3+1], scale*mesh.vertices[mesh.faces[count+1]*3+2] ]
                f2 = [ scale*mesh.vertices[mesh.faces[(count+2)]*3], scale*mesh.vertices[mesh.faces[(count+2)]*3+1], scale*mesh.vertices[mesh.faces[(count+2)]*3+2] ]
                f3 = [ scale*mesh.vertices[mesh.faces[(count+3)]*3], scale*mesh.vertices[mesh.faces[(count+3)]*3+1], scale*mesh.vertices[mesh.faces[(count+3)]*3+2] ]
                parts_list.append([ f1, f2, f3 ])
                types_list.append(TRIANGLE_FAN)
                count += 4
            else: 
                count += mesh.faces[count+1]
                logger.logToUser("Received mesh type is only partially supported", Qgis.Warning)
        except: break

    return parts_list, types_list

def constructMesh(vertices, faces, colors):
    mesh = Mesh.create(vertices, faces, colors)
    mesh.units = "m"
    material = RenderMaterial()
    material.diffuse = colors[0]
    mesh.renderMaterial = material 
    return mesh

def meshPartsFromPolygon(polyBorder: List[Point], voidsAsPts: List[List[Point]], existing_vert: int, feature: QgsFeature, layer: QgsVectorLayer):
    
    vertices = []
    total_vertices = 0

    coef = 1
    maxPoints = 5000
    if len(polyBorder) >= maxPoints: coef = int(len(polyBorder)/maxPoints)
        
    if len(voidsAsPts) == 0: # only if there is a mesh with no voids and large amount of points
        for k, ptt in enumerate(polyBorder): #pointList:
            pt = polyBorder[k*coef]
            if k < maxPoints:
                if isinstance(pt, QgsPointXY):
                    pt = QgsPoint(pt)
                if isinstance(pt,Point):
                    pt = pointToNative(pt)
                x = pt.x()
                y = pt.y()
                z = 0 if math.isnan(pt.z()) else pt.z()
                vertices.extend([x, y, z])
                total_vertices += 1
            else: break

        ran = range(0, total_vertices)
        faces = [total_vertices]
        faces.extend([i + existing_vert for i in ran])
        # else: https://docs.panda3d.org/1.10/python/reference/panda3d.core.Triangulator
    else: # if there are voids 
        # if its a large polygon with voids to be triangualted, lower the coef even more:
        maxPoints = 100
        if len(polyBorder) >= maxPoints: coef = int(len(polyBorder)/maxPoints)

        trianglator = Triangulator()
        faces = []

        pt_count = 0
        # add extra middle point for border
        for k, ptt in enumerate(polyBorder): #pointList:
            pt = polyBorder[k*coef]
            if k < maxPoints:
                if pt_count < len(polyBorder)-1 and k < (maxPoints-1): 
                    pt2 = polyBorder[(k+1)*coef]
                else: pt2 = polyBorder[0]
                        
                trianglator.addPolygonVertex(trianglator.addVertex(pt.x, pt.y))
                vertices.extend([pt.x, pt.y, pt.z])
                trianglator.addPolygonVertex(trianglator.addVertex((pt.x+pt2.x)/2, (pt.y+pt2.y)/2))
                vertices.extend([(pt.x+pt2.x)/2, (pt.y+pt2.y)/2, (pt.z+pt2.z)/2])
                total_vertices += 2
                pt_count += 1
            else: break

        #add void points
        for pts in voidsAsPts:
            trianglator.beginHole()

            coefVoid = 1
            if len(pts) >= maxPoints: coefVoid = int(len(pts)/maxPoints)
            for k, ptt in enumerate(pts):
                pt = pts[k*coefVoid]
                if k < maxPoints:
                    trianglator.addHoleVertex(trianglator.addVertex(pt.x, pt.y))
                    vertices.extend([pt.x, pt.y, pt.z])
                    total_vertices += 1
                else: break
        
        trianglator.triangulate()
        i = 0
        #print(trianglator.getNumTriangles())
        while i < trianglator.getNumTriangles():
            tr = [trianglator.getTriangleV0(i),trianglator.getTriangleV1(i),trianglator.getTriangleV2(i)]
            faces.extend([3, tr[0] + existing_vert, tr[1] + existing_vert, tr[2] + existing_vert])
            i+=1
        ran = range(0, total_vertices)

    col = featureColorfromNativeRenderer(feature, layer)
    colors = [col for i in ran] # apply same color for all vertices

    return total_vertices, vertices, faces, colors