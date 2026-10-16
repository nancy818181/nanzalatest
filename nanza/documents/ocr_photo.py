"""Prepare photographed documents for OCR without changing the original file."""
from __future__ import annotations


def variants(image):
    """Perspective-correct a large paper region, flatten shadows and suppress long table rules.

    The original image remains an OCR candidate: paper detection can be ambiguous.
    """
    import cv2
    import numpy as np
    from PIL import Image

    rgb=np.asarray(image.convert("RGB"))
    scale=min(1.0,800/max(rgb.shape[:2]))
    small=cv2.resize(rgb,None,fx=scale,fy=scale,interpolation=cv2.INTER_AREA)
    hsv=cv2.cvtColor(small,cv2.COLOR_RGB2HSV)
    mask=cv2.inRange(hsv,np.array([0,0,80]),np.array([179,70,255]))
    mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((15,15),np.uint8))
    contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    prepared=rgb
    if contours:
        hull=cv2.convexHull(max(contours,key=cv2.contourArea))
        quad=cv2.approxPolyDP(hull,.035*cv2.arcLength(hull,True),True)
        area=cv2.contourArea(quad)
        if len(quad)==4 and area>=small.shape[0]*small.shape[1]*.5:
            points=quad.reshape(4,2).astype("float32")/scale
            sums=points.sum(axis=1);diff=np.diff(points,axis=1).ravel()
            ordered=points[[np.argmin(sums),np.argmin(diff),np.argmax(sums),np.argmax(diff)]]
            if len(np.unique(ordered,axis=0))==4:
                width=int(max(np.linalg.norm(ordered[0]-ordered[1]),np.linalg.norm(ordered[3]-ordered[2])))
                height=int(max(np.linalg.norm(ordered[0]-ordered[3]),np.linalg.norm(ordered[1]-ordered[2])))
                if min(width,height)>=150:
                    target=np.array([[0,0],[width-1,0],[width-1,height-1],[0,height-1]],dtype="float32")
                    prepared=cv2.warpPerspective(rgb,cv2.getPerspectiveTransform(ordered,target),(width,height))
    gray=cv2.cvtColor(prepared,cv2.COLOR_RGB2GRAY)
    background=cv2.GaussianBlur(gray,(0,0),max(10,min(75,gray.shape[1]/40)))
    normal=cv2.divide(gray,np.maximum(background,1),scale=255)
    binary=cv2.adaptiveThreshold(normal,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY,31,15)
    ink=255-binary
    horizontal=cv2.morphologyEx(ink,cv2.MORPH_OPEN,np.ones((1,max(40,gray.shape[1]//10)),np.uint8))
    vertical=cv2.morphologyEx(ink,cv2.MORPH_OPEN,np.ones((max(40,gray.shape[0]//10),1),np.uint8))
    clean=cv2.add(binary,cv2.bitwise_or(horizontal,vertical))
    return [Image.fromarray(normal),Image.fromarray(clean)]
