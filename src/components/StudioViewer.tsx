import { useEffect, useRef, useState, useCallback, useImperativeHandle, forwardRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { TransformControls } from "three/addons/controls/TransformControls.js";
import { PLYLoader } from "three/addons/loaders/PLYLoader.js";

import type { Twin, CameraPose } from "../types/twin";
import type { PlacedFurniture } from "../types/furniture";
import { transformPointsToRoomFrame, cameraAxesRoomFrame } from "../lib/frames";
import { polygonToFilledGeometry, polygonToLineLoopGeometry } from "../lib/polygon3d";
import { makeTextSprite } from "../lib/labelSprite";
import { buildFrustumGeometry } from "../lib/frustum";
import { cloudUrl } from "../lib/api";
import { validatePlacementGeometry } from "../lib/clearance";
import {
  createWoodFloorMaterial,
  createPlasterWallMaterial,
  createCeilingMaterial,
  createFurnitureBoxMaterial,
} from "../lib/studioMaterials";
import CameraControlsHUD, { type CameraPreset } from "./CameraControlsHUD";

export interface StudioToggles {
  pointCloud: boolean;
  geometry: boolean;
  labels: boolean;
  cameras: boolean;
  furniture: boolean;
  woodFloor: boolean;
}

export interface StudioViewerRef {
  takeSnapshot: (filename?: string) => void;
  setGizmoMode: (mode: "translate" | "rotate") => void;
}

interface Props {
  sessionId: string;
  twin: Twin;
  selectedPlaneId: string | null;
  onSelectPlane: (planeId: string | null) => void;
  placedFurniture?: PlacedFurniture[];
  onPlacedFurnitureChange?: (items: PlacedFurniture[]) => void;
  selectedFurnitureId?: string | null;
  onSelectFurniture?: (id: string | null) => void;
  toggles?: StudioToggles;
  onToggleChange?: (toggles: StudioToggles) => void;
}

const DEFAULT_TOGGLES: StudioToggles = {
  pointCloud: true,
  geometry: true,
  labels: true,
  cameras: false,
  furniture: true,
  woodFloor: true,
};

const StudioViewer = forwardRef<StudioViewerRef, Props>(function StudioViewer(
  {
    sessionId,
    twin,
    selectedPlaneId,
    onSelectPlane,
    placedFurniture = [],
    onPlacedFurnitureChange,
    selectedFurnitureId,
    onSelectFurniture,
    toggles: externalToggles,
    onToggleChange,
  },
  ref
) {
  const containerRef = useRef<HTMLDivElement>(null);

  const [internalToggles, setInternalToggles] = useState<StudioToggles>(DEFAULT_TOGGLES);
  const toggles = externalToggles ?? internalToggles;

  const [activePreset, setActivePreset] = useState<CameraPreset | null>("isometric");
  const [gizmoMode, setGizmoModeState] = useState<"translate" | "rotate">("translate");

  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const controlsRef = useRef<OrbitControls | null>(null);
  const transformControlsRef = useRef<TransformControls | null>(null);
  const rafRef = useRef<number | null>(null);

  // Guard to prevent deselecting object on mouseUp after dragging gizmo
  const isDraggingGizmoRef = useRef(false);

  // Camera lerp animation target
  const cameraAnimTarget = useRef<{
    pos: THREE.Vector3;
    target: THREE.Vector3;
  } | null>(null);

  // Scene subgroups
  const groupsRef = useRef<{
    pointCloud: THREE.Group;
    planes: THREE.Group;
    woodFloor: THREE.Group;
    labels: THREE.Group;
    intersections: THREE.Group;
    boundingPolygon: THREE.Group;
    cameras: THREE.Group;
    furniture: THREE.Group;
  } | null>(null);

  const planeMeshesRef = useRef<Map<string, THREE.Mesh>>(new Map());
  const furnitureMeshesRef = useRef<Map<string, THREE.Mesh>>(new Map());

  // Ref mirror for placed furniture to avoid closure stale issues in transform callback
  const placedFurnitureRef = useRef(placedFurniture);
  placedFurnitureRef.current = placedFurniture;

  const twinRef = useRef(twin);
  twinRef.current = twin;

  // Expose methods to parent via ref
  useImperativeHandle(ref, () => ({
    takeSnapshot: (filename = `visionforge-${sessionId}-snapshot.png`) => {
      const renderer = rendererRef.current;
      const scene = sceneRef.current;
      const camera = cameraRef.current;
      if (!renderer || !scene || !camera) return;

      renderer.render(scene, camera);
      const dataUrl = renderer.domElement.toDataURL("image/png");
      const a = document.createElement("a");
      a.download = filename;
      a.href = dataUrl;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    },
    setGizmoMode: (mode: "translate" | "rotate") => {
      setGizmoModeState(mode);
      if (transformControlsRef.current) {
        transformControlsRef.current.setMode(mode);
        if (mode === "translate") {
          transformControlsRef.current.showY = false;
          transformControlsRef.current.showX = true;
          transformControlsRef.current.showZ = true;
        } else {
          transformControlsRef.current.showX = false;
          transformControlsRef.current.showZ = false;
          transformControlsRef.current.showY = true;
        }
      }
    },
  }));

  const handleToggle = (key: keyof StudioToggles) => {
    const next = { ...toggles, [key]: !toggles[key] };
    if (onToggleChange) onToggleChange(next);
    else setInternalToggles(next);
  };

  const handleSelectPreset = useCallback(
    (preset: CameraPreset) => {
      setActivePreset(preset);

      const roomL = twin.room_model?.room?.length ?? 5.0;
      const roomW = twin.room_model?.room?.width ?? 4.0;
      const maxDim = Math.max(roomL, roomW, 4.0);

      let pos: THREE.Vector3;
      let target = new THREE.Vector3(0, 0.8, 0);

      if (preset === "isometric") {
        pos = new THREE.Vector3(maxDim * 1.1, maxDim * 1.1, maxDim * 1.1);
      } else if (preset === "topdown") {
        pos = new THREE.Vector3(0, maxDim * 2.2, 0.01);
        target = new THREE.Vector3(0, 0, 0);
      } else {
        pos = new THREE.Vector3(0, 1.4, maxDim * 0.85);
        target = new THREE.Vector3(0, 1.1, 0);
      }

      cameraAnimTarget.current = { pos, target };
    },
    [twin]
  );

  // Initialize Three.js scene & controls
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0e1117);
    scene.fog = new THREE.FogExp2(0x0e1117, 0.025);
    sceneRef.current = scene;

    const camera = new THREE.PerspectiveCamera(
      55,
      container.clientWidth / container.clientHeight,
      0.05,
      1000
    );
    camera.position.set(6, 6, 6);
    cameraRef.current = camera;

    const renderer = new THREE.WebGLRenderer({
      antialias: true,
      preserveDrawingBuffer: true,
    });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(container.clientWidth, container.clientHeight);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    container.appendChild(renderer.domElement);
    rendererRef.current = renderer;

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.06;
    controls.maxPolarAngle = Math.PI / 2 + 0.05;
    controlsRef.current = controls;

    controls.addEventListener("start", () => {
      cameraAnimTarget.current = null;
      setActivePreset(null);
    });

    // Interactive 3D TransformControls (Gizmo)
    const transformControls = new TransformControls(camera, renderer.domElement);
    transformControls.setMode("translate");
    transformControls.showY = false; // Strictly constrained to XZ floor plane
    transformControls.showX = true;
    transformControls.showZ = true;
    transformControls.size = 0.85;

    const gizmoHelper = (transformControls.getHelper
      ? transformControls.getHelper()
      : transformControls) as unknown as THREE.Object3D;
    scene.add(gizmoHelper);
    transformControlsRef.current = transformControls;

    // Disable OrbitControls during gizmo dragging so camera doesn't rotate simultaneously
    transformControls.addEventListener("dragging-changed", (e) => {
      controls.enabled = !e.value;
      if (e.value) {
        isDraggingGizmoRef.current = true;
      } else {
        // Keep flag briefly active to prevent click handler deselecting item on mouseUp
        setTimeout(() => {
          isDraggingGizmoRef.current = false;
        }, 120);
      }
    });

    // Handle in-canvas furniture movement live & sync back to placedFurniture state
    transformControls.addEventListener("objectChange", () => {
      const obj = transformControls.object;
      if (!obj || !obj.userData?.furnitureId) return;

      const fId = obj.userData.furnitureId;
      const currentList = [...placedFurnitureRef.current];
      const idx = currentList.findIndex((item) => item.id === fId);
      if (idx === -1) return;

      const updated = { ...currentList[idx] };
      const itemHeight = updated.height ?? 0.8;

      // Constrain vertical position strictly to floor plane
      obj.position.y = itemHeight / 2;

      updated.center_x = Number(obj.position.x.toFixed(2));
      updated.center_z = Number(obj.position.z.toFixed(2));

      // Calculate Y rotation in degrees
      const deg = Math.round((-obj.rotation.y * 180) / Math.PI) % 360;
      updated.angle_deg = deg < 0 ? deg + 360 : deg;

      // Real-time SAT clearance validation
      const currentTwin = twinRef.current;
      if (currentTwin?.room_model) {
        const val = validatePlacementGeometry(
          currentTwin.room_model,
          {
            furniture_id: updated.furniture_id,
            center_x: updated.center_x,
            center_z: updated.center_z,
            angle_deg: updated.angle_deg,
            custom_length: updated.length,
            custom_width: updated.width,
          },
          currentList.filter((_, i) => i !== idx)
        );
        updated.valid = val.valid;
        updated.reason = val.reason;

        // Immediate visual color feedback on the mesh during dragging
        const mesh = furnitureMeshesRef.current.get(fId);
        if (mesh) {
          mesh.material = createFurnitureBoxMaterial(updated.color || "#3b82f6", updated.valid);
          const edgeLine = mesh.children.find((c) => c instanceof THREE.LineSegments) as
            | THREE.LineSegments
            | undefined;
          if (edgeLine && edgeLine.material) {
            (edgeLine.material as THREE.LineBasicMaterial).color.set(
              updated.valid ? 0xffffff : 0xff4d4d
            );
          }
        }
      }

      currentList[idx] = updated;
      if (onPlacedFurnitureChange) {
        onPlacedFurnitureChange(currentList);
      }
    });

    // Three-point warm studio lighting
    const ambientLight = new THREE.AmbientLight(0xfff5ea, 0.55);
    scene.add(ambientLight);

    const hemiLight = new THREE.HemisphereLight(0xddeeff, 0x1b202c, 0.65);
    scene.add(hemiLight);

    const keyLight = new THREE.DirectionalLight(0xfff0db, 1.5);
    keyLight.position.set(6, 12, 8);
    keyLight.castShadow = true;
    keyLight.shadow.mapSize.width = 1024;
    keyLight.shadow.mapSize.height = 1024;
    keyLight.shadow.bias = -0.0005;
    scene.add(keyLight);

    const fillLight = new THREE.DirectionalLight(0xbad2e8, 0.75);
    fillLight.position.set(-8, 6, -6);
    scene.add(fillLight);

    const grid = new THREE.GridHelper(24, 24, 0x2e384d, 0x171c26);
    grid.position.y = -0.005;
    scene.add(grid);

    const groups = {
      pointCloud: new THREE.Group(),
      planes: new THREE.Group(),
      woodFloor: new THREE.Group(),
      labels: new THREE.Group(),
      intersections: new THREE.Group(),
      boundingPolygon: new THREE.Group(),
      cameras: new THREE.Group(),
      furniture: new THREE.Group(),
    };
    Object.values(groups).forEach((g) => scene.add(g));
    groupsRef.current = groups;

    const handleResize = () => {
      if (!container) return;
      camera.aspect = container.clientWidth / container.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(container.clientWidth, container.clientHeight);
    };
    window.addEventListener("resize", handleResize);

    const raycaster = new THREE.Raycaster();
    const mouse = new THREE.Vector2();

    const handleClick = (e: MouseEvent) => {
      // Ignore click if finishing a gizmo drag
      if (isDraggingGizmoRef.current) return;

      const rect = renderer.domElement.getBoundingClientRect();
      mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(mouse, camera);

      // Check furniture hits first to attach gizmo
      const furnMeshes = Array.from(furnitureMeshesRef.current.values());
      const furnHits = raycaster.intersectObjects(furnMeshes, true);
      if (furnHits.length > 0) {
        let hitObj: THREE.Object3D | null = furnHits[0].object;
        while (hitObj && !hitObj.userData?.furnitureId) {
          hitObj = hitObj.parent;
        }
        if (hitObj && hitObj.userData?.furnitureId) {
          const furnId = hitObj.userData.furnitureId;
          if (onSelectFurniture) onSelectFurniture(furnId);
          transformControls.attach(hitObj);
          return;
        }
      }

      // Check planes
      const meshes = Array.from(planeMeshesRef.current.values());
      const hits = raycaster.intersectObjects(meshes, false);
      if (hits.length > 0) {
        const id = hits[0].object.userData.planeId as string;
        onSelectPlane(id);
      } else {
        onSelectPlane(null);
        if (onSelectFurniture) onSelectFurniture(null);
        transformControls.detach();
      }
    };
    renderer.domElement.addEventListener("click", handleClick);

    const animate = () => {
      if (cameraAnimTarget.current) {
        camera.position.lerp(cameraAnimTarget.current.pos, 0.08);
        controls.target.lerp(cameraAnimTarget.current.target, 0.08);

        if (
          camera.position.distanceTo(cameraAnimTarget.current.pos) < 0.05 &&
          controls.target.distanceTo(cameraAnimTarget.current.target) < 0.05
        ) {
          cameraAnimTarget.current = null;
        }
      }

      controls.update();
      renderer.render(scene, camera);
      rafRef.current = requestAnimationFrame(animate);
    };
    animate();

    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      window.removeEventListener("resize", handleResize);
      renderer.domElement.removeEventListener("click", handleClick);
      transformControls.dispose();
      controls.dispose();
      renderer.dispose();
      if (container.contains(renderer.domElement)) {
        container.removeChild(renderer.domElement);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Rebuild 3D geometry when session or twin changes
  useEffect(() => {
    const groups = groupsRef.current;
    if (!groups) return;

    Object.values(groups).forEach((g) => {
      while (g.children.length > 0) {
        const child = g.children[0];
        g.remove(child);
      }
    });
    planeMeshesRef.current.clear();

    const roomModel = twin.room_model;
    const coordSystem = roomModel?.coordinate_system ?? null;

    if (roomModel && Array.isArray(roomModel.planes)) {
      for (const plane of roomModel.planes) {
        const boundary = plane.boundary_room ?? plane.boundary;
        if (!boundary || boundary.length < 3) continue;

        const isFloor = plane.type === "floor";
        const isCeiling = plane.type === "ceiling";
        const isSelected = selectedPlaneId === plane.id;

        const fillGeom = polygonToFilledGeometry(boundary);
        let material: THREE.Material;

        if (isFloor) {
          material = createWoodFloorMaterial();
        } else if (isCeiling) {
          material = createCeilingMaterial();
        } else {
          material = createPlasterWallMaterial(isSelected);
        }

        const mesh = new THREE.Mesh(fillGeom, material);
        mesh.userData.planeId = plane.id;
        mesh.receiveShadow = true;

        if (isFloor) {
          groups.woodFloor.add(mesh);
        } else {
          groups.planes.add(mesh);
        }
        planeMeshesRef.current.set(plane.id, mesh);

        const lineGeom = polygonToLineLoopGeometry(boundary);
        const lineMat = new THREE.LineBasicMaterial({
          color: isFloor ? 0x8b5a2b : isSelected ? 0xe07a5f : 0xd3c7b6,
          linewidth: isSelected ? 2 : 1,
        });
        const line = new THREE.Line(lineGeom, lineMat);
        groups.planes.add(line);

        const centroid = plane.centroid_room ?? plane.centroid;
        if (centroid && centroid.length >= 3) {
          const typeName = plane.type.charAt(0).toUpperCase() + plane.type.slice(1);
          const label = makeTextSprite(`${typeName} (${plane.id})`);
          label.position.set(centroid[0], centroid[1] + 0.1, centroid[2]);
          groups.labels.add(label);
        }
      }

      for (const inter of roomModel.intersections ?? []) {
        const seg = inter.segment_room ?? inter.segment;
        if (seg && seg.length === 2 && seg[0] && seg[1]) {
          const geom = new THREE.BufferGeometry().setFromPoints(
            seg.map(([x, y, z]) => new THREE.Vector3(x, y, z))
          );
          const line = new THREE.Line(
            geom,
            new THREE.LineBasicMaterial({ color: 0xe07a5f, linewidth: 2 })
          );
          groups.intersections.add(line);
        }
      }
    }

    if (twin.scene_graph && coordSystem) {
      const camerasByName = new Map<string, CameraPose>(
        (twin.cameras ?? []).map((c) => [c.name, c])
      );

      for (const node of twin.scene_graph.nodes) {
        if (node.type !== "camera") continue;
        const props = node.properties as {
          name: string;
          position_room: [number, number, number] | null;
          camera_params: number[];
        };
        if (!props.position_room) continue;
        const pose = camerasByName.get(props.name);
        if (!pose) continue;

        const axes = cameraAxesRoomFrame(pose.rotation_quat, coordSystem);
        const geom = buildFrustumGeometry(
          props.position_room,
          axes.forward,
          axes.up,
          axes.right,
          props.camera_params,
          0.3,
          pose.camera_model
        );
        const frustum = new THREE.LineSegments(
          geom,
          new THREE.LineBasicMaterial({ color: 0x38bdf8 })
        );
        groups.cameras.add(frustum);
      }
    }

    if (coordSystem) {
      const loader = new PLYLoader();
      const plyTargetUrl = cloudUrl(sessionId);
      loader.load(
        plyTargetUrl,
        (geom) => {
          const posAttr = geom.getAttribute("position") as THREE.BufferAttribute | undefined;
          if (!posAttr) return;
          const roomPositions = transformPointsToRoomFrame(
            posAttr.array as Float32Array,
            coordSystem
          );
          const roomGeom = new THREE.BufferGeometry();
          roomGeom.setAttribute("position", new THREE.Float32BufferAttribute(roomPositions, 3));
          const points = new THREE.Points(
            roomGeom,
            new THREE.PointsMaterial({
              color: 0xfde047,
              size: 0.022,
              transparent: true,
              opacity: 0.85,
            })
          );
          groups.pointCloud.add(points);
        },
        undefined,
        () => {}
      );
    }
  }, [sessionId, twin, selectedPlaneId]);

  // Render 3D furniture models & wire up meshes for TransformControls
  useEffect(() => {
    const groups = groupsRef.current;
    if (!groups) return;

    while (groups.furniture.children.length > 0) {
      groups.furniture.remove(groups.furniture.children[0]);
    }
    furnitureMeshesRef.current.clear();

    const floorY = 0.0;

    for (const item of placedFurniture) {
      const length = item.length ?? 1.6;
      const width = item.width ?? 1.0;
      const height = item.height ?? 0.8;
      const valid = item.valid ?? true;

      const geom = new THREE.BoxGeometry(length, height, width);
      const mat = createFurnitureBoxMaterial(item.color || "#3b82f6", valid);
      const box = new THREE.Mesh(geom, mat);
      box.castShadow = true;
      box.receiveShadow = true;
      box.userData = { furnitureId: item.id };

      box.position.set(item.center_x, floorY + height / 2, item.center_z);
      box.rotation.y = -(item.angle_deg * Math.PI) / 180.0;

      const edges = new THREE.EdgesGeometry(geom);
      const edgeLine = new THREE.LineSegments(
        edges,
        new THREE.LineBasicMaterial({
          color: valid ? 0xffffff : 0xff4d4d,
          linewidth: 1.5,
        })
      );
      box.add(edgeLine);

      const label = makeTextSprite(item.name || item.furniture_id);
      label.position.set(0, height / 2 + 0.15, 0);
      label.scale.set(0.65, 0.32, 1);
      box.add(label);

      groups.furniture.add(box);
      furnitureMeshesRef.current.set(item.id, box);

      // Re-attach gizmo if this item is currently selected
      if (selectedFurnitureId === item.id && transformControlsRef.current) {
        transformControlsRef.current.attach(box);
      }
    }
  }, [placedFurniture, selectedFurnitureId]);

  // Apply visibility toggles
  useEffect(() => {
    const groups = groupsRef.current;
    if (!groups) return;

    groups.pointCloud.visible = toggles.pointCloud;
    groups.planes.visible = toggles.geometry;
    groups.woodFloor.visible = toggles.woodFloor && toggles.geometry;
    groups.labels.visible = toggles.labels;
    groups.cameras.visible = toggles.cameras;
    groups.furniture.visible = toggles.furniture;
  }, [toggles]);

  return (
    <div className="studio-viewport-container">
      <div ref={containerRef} className="threejs-canvas-wrapper" />

      {/* Floating Camera Presets HUD */}
      <CameraControlsHUD
        camera={cameraRef.current}
        controls={controlsRef.current}
        activePreset={activePreset}
        onSelectPreset={handleSelectPreset}
      />

      {/* 3D Gizmo Mode Switcher (visible when furniture is selected) */}
      {selectedFurnitureId && (
        <div className="gizmo-mode-hud">
          <span className="gizmo-label">Floor Gizmo:</span>
          <button
            type="button"
            className={`gizmo-btn ${gizmoMode === "translate" ? "active" : ""}`}
            onClick={() => {
              setGizmoModeState("translate");
              if (transformControlsRef.current) {
                transformControlsRef.current.setMode("translate");
                transformControlsRef.current.showY = false;
                transformControlsRef.current.showX = true;
                transformControlsRef.current.showZ = true;
              }
            }}
          >
            Move (XZ Plane)
          </button>
          <button
            type="button"
            className={`gizmo-btn ${gizmoMode === "rotate" ? "active" : ""}`}
            onClick={() => {
              setGizmoModeState("rotate");
              if (transformControlsRef.current) {
                transformControlsRef.current.setMode("rotate");
                transformControlsRef.current.showX = false;
                transformControlsRef.current.showZ = false;
                transformControlsRef.current.showY = true;
              }
            }}
          >
            Rotate (Y Axis)
          </button>
        </div>
      )}

      {/* Floating Layer Controls */}
      <div className="studio-layer-toggles">
        <label className={`toggle-pill ${toggles.woodFloor ? "active" : ""}`}>
          <input
            type="checkbox"
            checked={toggles.woodFloor}
            onChange={() => handleToggle("woodFloor")}
          />
          Wood Floor
        </label>
        <label className={`toggle-pill ${toggles.pointCloud ? "active" : ""}`}>
          <input
            type="checkbox"
            checked={toggles.pointCloud}
            onChange={() => handleToggle("pointCloud")}
          />
          Point Cloud
        </label>
        <label className={`toggle-pill ${toggles.geometry ? "active" : ""}`}>
          <input
            type="checkbox"
            checked={toggles.geometry}
            onChange={() => handleToggle("geometry")}
          />
          Walls
        </label>
        <label className={`toggle-pill ${toggles.furniture ? "active" : ""}`}>
          <input
            type="checkbox"
            checked={toggles.furniture}
            onChange={() => handleToggle("furniture")}
          />
          Furniture
        </label>
        <label className={`toggle-pill ${toggles.labels ? "active" : ""}`}>
          <input
            type="checkbox"
            checked={toggles.labels}
            onChange={() => handleToggle("labels")}
          />
          Labels
        </label>
      </div>
    </div>
  );
});

export default StudioViewer;
