import os
import cv2
import json
import numpy as np
from pathlib import Path
from typing import List, Tuple, Dict, Any

def save_ply(filename: str, points: np.ndarray, colors: np.ndarray = None):
    with open(filename, 'w') as f:
        f.write("ply\n")
        f.write("format ascii 1.0\n")
        f.write(f"element vertex {len(points)}\n")
        f.write("property float x\n")
        f.write("property float y\n")
        f.write("property float z\n")
        if colors is not None:
            f.write("property uchar red\n")
            f.write("property uchar green\n")
            f.write("property uchar blue\n")
        f.write("end_header\n")
        for i in range(len(points)):
            p = points[i]
            if colors is not None:
                c = colors[i]
                f.write(f"{p[0]} {p[1]} {p[2]} {int(c[0])} {int(c[1])} {int(c[2])}\n")
            else:
                f.write(f"{p[0]} {p[1]} {p[2]}\n")

def run_two_view(frame1_path: Path, frame2_path: Path, output_dir: Path) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stats = {}
    
    img1 = cv2.imread(str(frame1_path))
    img2 = cv2.imread(str(frame2_path))
    
    gray1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
    gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)
    
    h, w = gray1.shape
    focal = max(h, w) # simple guess
    pp = (w/2.0, h/2.0)
    
    # Stage 1: SIFT
    sift = cv2.SIFT_create()
    kp1, des1 = sift.detectAndCompute(gray1, None)
    kp2, des2 = sift.detectAndCompute(gray2, None)
    
    stats['frame1_kps'] = len(kp1)
    stats['frame2_kps'] = len(kp2)
    
    # Feature visualization
    img_kps = cv2.drawKeypoints(img1, kp1, None, flags=cv2.DRAW_MATCHES_FLAGS_DRAW_RICH_KEYPOINTS)
    cv2.imwrite(str(output_dir / "features.jpg"), img_kps)
    
    # Stage 2: Feature Matching (Lowe ratio)
    bf = cv2.BFMatcher()
    if des1 is None or des2 is None or len(des1) < 2 or len(des2) < 2:
        return stats # Not enough descriptors
        
    matches = bf.knnMatch(des1, des2, k=2)
    good = []
    for m, n in matches:
        if m.distance < 0.75 * n.distance:
            good.append(m)
            
    stats['raw_matches'] = len(matches)
    stats['lowe_matches'] = len(good)
    
    # Match visualization
    img_matches = cv2.drawMatches(img1, kp1, img2, kp2, good[:50], None, flags=cv2.DrawMatchesFlags_NOT_DRAW_SINGLE_POINTS)
    cv2.imwrite(str(output_dir / "matches.jpg"), img_matches)
    
    if len(good) < 8: # need 8 points for essential matrix
        return stats
        
    # Stage 3: Geometric Verification (Essential Matrix)
    pts1 = np.float32([kp1[m.queryIdx].pt for m in good])
    pts2 = np.float32([kp2[m.trainIdx].pt for m in good])
    
    E, mask = cv2.findEssentialMat(pts1, pts2, focal=focal, pp=pp, method=cv2.RANSAC, prob=0.999, threshold=1.0)
    
    if E is None:
        return stats
        
    inliers1 = pts1[mask.ravel() == 1]
    inliers2 = pts2[mask.ravel() == 1]
    
    stats['geometric_inliers'] = len(inliers1)
    stats['inlier_ratio'] = len(inliers1) / len(good)
    
    # Stage 4: Camera Geometry
    _, R, t, mask_pose = cv2.recoverPose(E, inliers1, inliers2, focal=focal, pp=pp)
    
    cameras = [
        {"id": 0, "frame": frame1_path.name, "rotation": np.eye(3).tolist(), "translation": np.zeros(3).tolist()},
        {"id": 1, "frame": frame2_path.name, "rotation": R.tolist(), "translation": t.ravel().tolist()}
    ]
    with open(output_dir / "cameras.json", "w") as f:
        json.dump(cameras, f, indent=2)
        
    # Stage 5: Triangulation
    P1 = np.hstack((np.eye(3), np.zeros((3, 1))))
    P2 = np.hstack((R, t))
    K = np.array([[focal, 0, pp[0]], [0, focal, pp[1]], [0, 0, 1]])
    P1 = K @ P1
    P2 = K @ P2
    
    # filter for points valid in pose
    valid_inliers1 = inliers1[mask_pose.ravel() == 255]
    valid_inliers2 = inliers2[mask_pose.ravel() == 255]
    
    if len(valid_inliers1) > 0:
        points4D = cv2.triangulatePoints(P1, P2, valid_inliers1.T, valid_inliers2.T)
        points3D = points4D[:3, :] / points4D[3, :]
        points3D = points3D.T
        
        # filter negative depth in both cameras
        valid_depth = []
        colors = []
        for i, p in enumerate(points3D):
            if p[2] > 0:
                p_c2 = R @ p + t.ravel()
                if p_c2[2] > 0:
                    valid_depth.append(p)
                    # sample color from img1
                    pt = valid_inliers1[i]
                    c = img1[int(pt[1]), int(pt[0])]
                    colors.append([c[2], c[1], c[0]]) # BGR to RGB
                    
        valid_depth = np.array(valid_depth)
        colors = np.array(colors)
        
        if len(valid_depth) > 0:
            save_ply(str(output_dir / "points.ply"), valid_depth, colors)
            stats['reconstructed_points'] = len(valid_depth)
            
    with open(output_dir / "statistics.json", "w") as f:
        json.dump(stats, f, indent=2)
        
    return stats
