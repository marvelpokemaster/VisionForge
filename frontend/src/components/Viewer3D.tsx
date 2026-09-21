import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { PLYLoader } from "three/addons/loaders/PLYLoader.js";

import type { Twin, PlaneType, CameraPose } from "../types/twin";
import { transformPointsToRoomFrame, cameraAxesRoomFrame } from "../lib/frames";
import { polygonToFilledGeometry, polygonToLineLoopGeometry } from "../lib/polygon3d";
import { makeTextSprite } from "../lib/labelSprite";
import { buildFrustumGeometry } from "../lib/frustum";
import { cloudUrl } from "../lib/api";

const PLANE_COLORS: Record<PlaneType, number> = {
  floor: 0x2ecc71, // green
  wall: 0xe74c3c, // red
  ceiling: 0x3498db, // blue
  unknown: 0x95a5a6 // grey
};

const HIGHLIGHT_COLOR = 0xffd700;

export interface Toggles {
  pointCloud: boolean;
  geometry: boolean;
  labels: boolean;
  cameras: boolean;
}

interface Groups {
  pointCloud: THREE.Group;
  planes: THREE.Group;
  labels: THREE.Group;
  intersections: THREE.Group;
  boundingPolygon: THREE.Group;
  cameras: THREE.Group;
  trajectory: THREE.Group;
}

interface Props {
  sessionId: string;
  twin: Twin;
  toggles: Toggles;
  selectedPlaneId: string | null;
  onSelectPlane: (planeId: string | null) => void;
}

export default function Viewer3D({ sessionId, twin, toggles, selectedPlaneId, onSelectPlane }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);

  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const controlsRef = useRef<OrbitControls | null>(null);
  const rafRef = useRef<number | null>(null);

  const groupsRef = useRef<Groups | null>(null);

  const planeMeshesRef = useRef<Map<string, THREE.Mesh>>(new Map());
  const planeBaseColorRef = useRef<Map<string, number>>(new Map());

  const onSelectPlaneRef = useRef(onSelectPlane);
  onSelectPlaneRef.current = onSelectPlane;

  // ---- one-time scene/camera/renderer/controls setup ----
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x111318);
    sceneRef.current = scene;

    const camera = new THREE.PerspectiveCamera(60, container.clientWidth / container.clientHeight, 0.01, 1000);
    camera.position.set(5, 5, 5);
    cameraRef.current = camera;

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setSize(container.clientWidth, container.clientHeight);
    container.appendChild(renderer.domElement);
    rendererRef.current = renderer;

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controlsRef.current = controls;

    scene.add(new THREE.AmbientLight(0xffffff, 0.6));
    const dirLight = new THREE.DirectionalLight(0xffffff, 0.8);
    dirLight.position.set(5, 10, 7);
    scene.add(dirLight);
    scene.add(new THREE.GridHelper(20, 20, 0x333333, 0x222222));
    scene.add(new THREE.AxesHelper(1));

    const groups: Groups = {
      pointCloud: new THREE.Group(),
      planes: new THREE.Group(),
      labels: new THREE.Group(),
      intersections: new THREE.Group(),
      boundingPolygon: new THREE.Group(),
      cameras: new THREE.Group(),
      trajectory: new THREE.Group()
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
    const pointer = new THREE.Vector2();
    const handleClick = (event: MouseEvent) => {
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      const meshes = Array.from(planeMeshesRef.current.values());
      const hits = raycaster.intersectObjects(meshes, false);
      if (hits.length > 0) {
        const hit = hits[0].object as THREE.Mesh;
        onSelectPlaneRef.current(hit.userData.planeId as string);
      } else {
        onSelectPlaneRef.current(null);
      }
    };
    renderer.domElement.addEventListener("click", handleClick);

    const animate = () => {
      controls.update();
      renderer.render(scene, camera);
      rafRef.current = requestAnimationFrame(animate);
    };
    animate();

    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      window.removeEventListener("resize", handleResize);
      renderer.domElement.removeEventListener("click", handleClick);
      controls.dispose();
      renderer.dispose();
      if (container.contains(renderer.domElement)) container.removeChild(renderer.domElement);
      disposeGroup(scene);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- (re)build all geometry whenever the session/twin changes ----
  useEffect(() => {
    const groups = groupsRef.current;
    const scene = sceneRef.current;
    if (!groups || !scene) return;

    clearGroup(groups.pointCloud);
    clearGroup(groups.planes);
    clearGroup(groups.labels);
    clearGroup(groups.intersections);
    clearGroup(groups.boundingPolygon);
    clearGroup(groups.cameras);
    clearGroup(groups.trajectory);
    planeMeshesRef.current.clear();
    planeBaseColorRef.current.clear();

    const roomModel = twin.room_model;
    const coordSystem = roomModel?.coordinate_system ?? null;

    // Planes: filled translucent polygon + wireframe outline + label
    if (roomModel) {
      for (const plane of roomModel.planes) {
        const color = PLANE_COLORS[plane.type] ?? PLANE_COLORS.unknown;
        planeBaseColorRef.current.set(plane.id, color);

        const filledGeom = polygonToFilledGeometry(plane.boundary_room);
        const material = new THREE.MeshStandardMaterial({
          color,
          transparent: true,
          opacity: 0.45,
          side: THREE.DoubleSide,
          depthWrite: false
        });
        const mesh = new THREE.Mesh(filledGeom, material);
        mesh.userData.planeId = plane.id;
        groups.planes.add(mesh);
        planeMeshesRef.current.set(plane.id, mesh);

        const lineGeom = polygonToLineLoopGeometry(plane.boundary_room);
        const line = new THREE.Line(lineGeom, new THREE.LineBasicMaterial({ color }));
        groups.planes.add(line);

        const label = makeTextSprite(`${plane.id} (${plane.type})`);
        label.position.set(...plane.centroid_room);
        groups.labels.add(label);
      }

      // Plane-plane intersection segments
      for (const inter of roomModel.intersections) {
        const geom = new THREE.BufferGeometry().setFromPoints(
          inter.segment_room.map(([x, y, z]) => new THREE.Vector3(x, y, z))
        );
        const line = new THREE.Line(geom, new THREE.LineBasicMaterial({ color: 0xffffff, linewidth: 2 }));
        groups.intersections.add(line);
      }

      // Room bounding polygon, placed at the floor's height (or y=0 if no floor)
      const floorPlane = roomModel.planes.find((p) => p.type === "floor");
      const floorY = floorPlane ? floorPlane.centroid_room[1] : 0;
      const polygonPoints = roomModel.room.bounding_polygon_room.map(
        ([x, z]) => new THREE.Vector3(x, floorY, z)
      );
      if (polygonPoints.length > 0) {
        polygonPoints.push(polygonPoints[0].clone());
        const geom = new THREE.BufferGeometry().setFromPoints(polygonPoints);
        const line = new THREE.Line(geom, new THREE.LineBasicMaterial({ color: 0xffff00 }));
        groups.boundingPolygon.add(line);
      }
    }

    // Cameras: frusta (real orientation from cameras.json's rotation_quat,
    // converted into the room frame) + trajectory polyline
    if (twin.scene_graph && coordSystem) {
      const camerasByName = new Map<string, CameraPose>((twin.cameras ?? []).map((c) => [c.name, c]));

      for (const node of twin.scene_graph.nodes) {
        if (node.type !== "camera") continue;
        const props = node.properties as { name: string; position_room: [number, number, number] | null; camera_params: number[] };
        if (!props.position_room) continue;
        const pose = camerasByName.get(props.name);
        if (!pose) continue;

        const axes = cameraAxesRoomFrame(pose.rotation_quat, coordSystem);
        const geom = buildFrustumGeometry(props.position_room, axes.forward, axes.up, axes.right, props.camera_params);
        const frustum = new THREE.LineSegments(geom, new THREE.LineBasicMaterial({ color: 0x00ffff }));
        groups.cameras.add(frustum);
      }

      const trajectoryNode = twin.scene_graph.nodes.find((n) => n.type === "trajectory");
      if (trajectoryNode) {
        const props = trajectoryNode.properties as { positions_room: ([number, number, number] | null)[] };
        const points = props.positions_room.filter((p): p is [number, number, number] => p !== null);
        if (points.length >= 2) {
          const geom = new THREE.BufferGeometry().setFromPoints(points.map(([x, y, z]) => new THREE.Vector3(x, y, z)));
          const line = new THREE.Line(geom, new THREE.LineBasicMaterial({ color: 0xff9900 }));
          groups.trajectory.add(line);
        }
      }
    }

    // Point cloud: the one thing that needs a client-side room-frame
    // transform, since the PLY is only ever produced in the reconstruction
    // frame.
    if (coordSystem) {
      const loader = new PLYLoader();
      loader.load(
        cloudUrl(sessionId),
        (geometry) => {
          const positionAttr = geometry.getAttribute("position") as THREE.BufferAttribute | undefined;
          if (!positionAttr) return;
          const roomPositions = transformPointsToRoomFrame(positionAttr.array as Float32Array, coordSystem);
          const roomGeometry = new THREE.BufferGeometry();
          roomGeometry.setAttribute("position", new THREE.Float32BufferAttribute(roomPositions, 3));
          const points = new THREE.Points(
            roomGeometry,
            new THREE.PointsMaterial({ color: 0xffffff, size: 0.02 })
          );
          groups.pointCloud.add(points);
        },
        undefined,
        (err) => console.error("Failed to load point cloud", err)
      );
    }

    applyToggles(groups, toggles);
    applyHighlight(planeMeshesRef.current, planeBaseColorRef.current, selectedPlaneId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, twin]);

  // ---- lightweight toggle visibility updates (no rebuild) ----
  useEffect(() => {
    const groups = groupsRef.current;
    if (!groups) return;
    applyToggles(groups, toggles);
  }, [toggles]);

  // ---- selection highlight updates (no rebuild) ----
  useEffect(() => {
    applyHighlight(planeMeshesRef.current, planeBaseColorRef.current, selectedPlaneId);
  }, [selectedPlaneId]);

  return <div ref={containerRef} style={{ width: "100%", height: "100%" }} />;
}

function applyToggles(groups: Groups, toggles: Toggles) {
  groups.pointCloud.visible = toggles.pointCloud;
  groups.planes.visible = toggles.geometry;
  groups.intersections.visible = toggles.geometry;
  groups.boundingPolygon.visible = toggles.geometry;
  groups.labels.visible = toggles.labels;
  groups.cameras.visible = toggles.cameras;
  groups.trajectory.visible = toggles.cameras;
}

function applyHighlight(
  meshes: Map<string, THREE.Mesh>,
  baseColors: Map<string, number>,
  selectedPlaneId: string | null
) {
  for (const [planeId, mesh] of meshes.entries()) {
    const material = mesh.material as THREE.MeshStandardMaterial;
    const base = baseColors.get(planeId) ?? 0xffffff;
    if (planeId === selectedPlaneId) {
      material.color.setHex(HIGHLIGHT_COLOR);
      material.opacity = 0.75;
    } else {
      material.color.setHex(base);
      material.opacity = 0.45;
    }
  }
}

function clearGroup(group: THREE.Group) {
  for (const child of [...group.children]) {
    group.remove(child);
    disposeObject(child);
  }
}

function disposeGroup(root: THREE.Object3D) {
  root.traverse(disposeObject);
}

function disposeObject(obj: THREE.Object3D) {
  const mesh = obj as THREE.Mesh | THREE.Line | THREE.Points | THREE.Sprite;
  if ("geometry" in mesh && mesh.geometry) mesh.geometry.dispose();
  if ("material" in mesh && mesh.material) {
    const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    for (const m of materials) {
      const mat = m as THREE.Material & { map?: THREE.Texture | null };
      mat.map?.dispose();
      mat.dispose();
    }
  }
}
