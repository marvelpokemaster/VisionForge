import cv2
import numpy as np
import open3d as o3d
import time
import sys

class ClassicalTracker:
    def __init__(self, fx=800, fy=800, cx=320, cy=240):
        self.K = np.array([
            [fx, 0, cx],
            [0, fy, cy],
            [0,  0,  1]
        ])
        
        self.detector = cv2.FastFeatureDetector_create(threshold=25, nonmaxSuppression=True)
        self.lk_params = dict(winSize=(21, 21), maxLevel=3,
                              criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))
                              
        self.prev_gray = None
        self.prev_pts = None
        
        self.global_R = np.eye(3)
        self.global_t = np.zeros((3, 1))
        
        self.trajectory = []
        self.mapped_points = []
        
    def process_frame(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        if self.prev_gray is None or self.prev_pts is None or len(self.prev_pts) < 100:
            # Need new features
            keypoints = self.detector.detect(gray, None)
            if len(keypoints) > 0:
                self.prev_pts = np.array([kp.pt for kp in keypoints], dtype=np.float32).reshape(-1, 1, 2)
            self.prev_gray = gray
            return False # no movement yet
            
        # Track features
        curr_pts, status, err = cv2.calcOpticalFlowPyrLK(self.prev_gray, gray, self.prev_pts, None, **self.lk_params)
        
        good_new = curr_pts[status == 1]
        good_old = self.prev_pts[status == 1]
        
        if len(good_new) < 20:
            self.prev_pts = None
            return False
            
        # Estimate Essential Matrix
        E, mask = cv2.findEssentialMat(good_new, good_old, self.K, method=cv2.RANSAC, prob=0.999, threshold=1.0)
        
        if E is None or E.shape != (3, 3):
            self.prev_pts = good_new.reshape(-1, 1, 2)
            self.prev_gray = gray
            return False
            
        # Recover pose
        _, R, t, mask_pose = cv2.recoverPose(E, good_new, good_old, self.K, mask=mask)
        
        # Simple scale heuristic: we cannot observe scale from monocular vision, assume constant velocity / scale = 1
        scale = 1.0 
        
        # Update global pose (Global_R, Global_t represents camera to world)
        self.global_t = self.global_t + scale * self.global_R.dot(t)
        self.global_R = self.global_R.dot(R)
        
        self.trajectory.append(self.global_t.copy())
        
        # Triangulate points (simple approach: triangulate between current and previous frame)
        # Note: robust SLAM would do bundle adjustment here. We do a lightweight triangulation for the demo map.
        P1 = np.hstack((np.eye(3), np.zeros((3,1))))
        P2 = np.hstack((R.T, -R.T.dot(t)))
        
        proj1 = self.K.dot(P1)
        proj2 = self.K.dot(P2)
        
        pts4d = cv2.triangulatePoints(proj1, proj2, good_old[mask_pose.ravel()==1].T, good_new[mask_pose.ravel()==1].T)
        pts3d = pts4d[:3, :] / pts4d[3, :]
        
        # Transform points to global coordinates
        pts_global = self.global_R.dot(pts3d) + self.global_t
        self.mapped_points.extend(pts_global.T.tolist())
        
        self.prev_gray = gray
        self.prev_pts = good_new.reshape(-1, 1, 2)
        
        return True

def run_live_tracker():
    print("==================================================")
    print(" VisionForge: Live Indoor Digital Twin            ")
    print("==================================================")
    print("Initializing webcam...")
    
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Error: Could not open webcam.")
        sys.exit(1)
        
    tracker = ClassicalTracker()
    
    # Initialize Open3D non-blocking visualizer
    vis = o3d.visualization.Visualizer()
    vis.create_window(window_name="VisionForge Live Digital Twin", width=800, height=600)
    
    # Create geometries
    pcd = o3d.geometry.PointCloud()
    traj_lines = o3d.geometry.LineSet()
    
    vis.add_geometry(pcd)
    vis.add_geometry(traj_lines)
    
    print("Live tracking started. Press 'q' in OpenCV window to stop.")
    
    fps = 0
    frames = 0
    start_t = time.time()
    
    # Render loop
    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        t0 = time.time()
        
        # Track
        tracked = tracker.process_frame(frame)
        
        # Draw on frame
        display_frame = frame.copy()
        if tracker.prev_pts is not None:
            for pt in tracker.prev_pts:
                x, y = pt.ravel()
                cv2.circle(display_frame, (int(x), int(y)), 3, (0, 255, 0), -1)
                
        # Stats
        frames += 1
        elapsed = time.time() - start_t
        if elapsed > 1.0:
            fps = frames / elapsed
            frames = 0
            start_t = time.time()
            
        cv2.putText(display_frame, f"FPS: {fps:.1f}", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,255,0), 2)
        cv2.putText(display_frame, f"Mapped Points: {len(tracker.mapped_points)}", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,255,0), 2)
        
        # Update 3D Viewer if there's new data
        if tracked and len(tracker.mapped_points) > 0:
            # We sample points to avoid massive slowdown
            pts_array = np.array(tracker.mapped_points)
            if len(pts_array) > 5000:
                pts_array = pts_array[np.random.choice(len(pts_array), 5000, replace=False)]
                
            pcd.points = o3d.utility.Vector3dVector(pts_array)
            
            # Update trajectory
            if len(tracker.trajectory) > 1:
                traj_pts = np.array(tracker.trajectory).squeeze()
                traj_lines.points = o3d.utility.Vector3dVector(traj_pts)
                lines = [[i, i+1] for i in range(len(traj_pts)-1)]
                traj_lines.lines = o3d.utility.Vector2iVector(lines)
                traj_lines.paint_uniform_color([1, 0, 0])
                
            vis.update_geometry(pcd)
            vis.update_geometry(traj_lines)
            
        vis.poll_events()
        vis.update_renderer()
        
        cv2.imshow("VisionForge Live Camera Feed", display_frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
            
    cap.release()
    cv2.destroyAllWindows()
    vis.destroy_window()
