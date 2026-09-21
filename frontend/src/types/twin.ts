// Types generated from the actual JSON returned by the VisionForge API
// (outputs/final_demo/twin.json and GET /sessions), not from memory.

export type Vec2 = [number, number];
export type Vec3 = [number, number, number];
export type Vec4 = [number, number, number, number];

export interface Measurement {
  value: number;
  metric: boolean;
  units: string;
  method?: string;
}

export type PlaneType = "floor" | "wall" | "ceiling" | "unknown";

export interface CoordinateSystem {
  up_axis: Vec3;
  horizontal_axes: [Vec3, Vec3];
  origin: Vec3;
}

export interface Scale {
  metric_available: boolean;
  scale_factor: number;
}

export interface RoomMeasurements {
  length: number;
  width: number;
  height: number;
  floor_area: number;
  length_method: string | null;
  width_method: string | null;
  height_method: string | null;
  floor_area_method: string | null;
  bounding_polygon_room: Vec2[];
}

export interface InPlaneAxes {
  axis_u: Vec3;
  axis_v: Vec3;
}

export interface PlaneExtent {
  width: number;
  height: number;
}

export interface Plane {
  id: string;
  type: PlaneType;
  equation: Vec4;
  normal: Vec3;
  support: number;
  centroid: Vec3;
  centroid_room: Vec3;
  in_plane_axes: InPlaneAxes;
  extent: PlaneExtent;
  area: number;
  boundary: Vec3[];
  boundary_room: Vec3[];
  ply_path: string | null;
}

export interface PlaneIntersection {
  plane_a: string;
  plane_b: string;
  point: Vec3;
  direction: Vec3;
  segment: [Vec3, Vec3];
  point_room: Vec3;
  segment_room: [Vec3, Vec3];
}

export interface RoomModel {
  coordinate_system: CoordinateSystem | null;
  scale: Scale;
  room: RoomMeasurements;
  planes: Plane[];
  intersections: PlaneIntersection[];
}

export interface CameraPose {
  id: number;
  name: string;
  /** [x, y, z, w] of cam_from_world, per pycolmap's convention. */
  rotation_quat: Vec4;
  translation: Vec3;
  camera_model: string;
  camera_params: number[];
}

// ---------------------------------------------------------------------------
// Scene graph
// ---------------------------------------------------------------------------

export type NodeType = "room" | PlaneType | "camera" | "trajectory";

export interface RoomNodeProperties extends RoomMeasurements {
  scale?: Scale;
}

export interface PlaneNodeProperties {
  equation: Vec4;
  normal: Vec3;
  centroid: Vec3;
  centroid_room: Vec3 | null;
  support: number;
  extent: PlaneExtent | null;
  area: number | null;
  boundary: Vec3[] | null;
  boundary_room: Vec3[] | null;
  in_plane_axes: InPlaneAxes | null;
  ply_path: string | null;
}

export interface CameraNodeProperties {
  name: string;
  position: Vec3;
  position_room: Vec3 | null;
  camera_model: string;
  camera_params: number[];
}

export interface TrajectoryNodeProperties {
  positions: Vec3[];
  positions_room: (Vec3 | null)[];
  num_cameras: number;
  path_length: number;
}

export interface SceneGraphNode<P = unknown> {
  id: string;
  type: NodeType;
  properties: P;
}

export type AnySceneGraphNode =
  | SceneGraphNode<RoomNodeProperties>
  | SceneGraphNode<PlaneNodeProperties>
  | SceneGraphNode<CameraNodeProperties>
  | SceneGraphNode<TrajectoryNodeProperties>;

export type RelationType =
  | "contains"
  | "parallel_to"
  | "perpendicular_to"
  | "adjacent_to"
  | "intersects"
  | "above"
  | "below"
  | "inside";

export interface SceneGraphEdge {
  source: string;
  target: string;
  relation: RelationType;
  // parallel_to / perpendicular_to
  angle_deg?: number;
  // adjacent_to
  distance?: number;
  // above / below
  height_difference?: number;
  // intersects
  point?: Vec3;
  direction?: Vec3;
  segment?: [Vec3, Vec3];
  segment_room?: [Vec3, Vec3];
  // inside
  inside?: boolean;
  distance_to_boundary?: number;
}

export interface SceneGraph {
  nodes: AnySceneGraphNode[];
  edges: SceneGraphEdge[];
}

// ---------------------------------------------------------------------------
// Twin / provenance / sessions
// ---------------------------------------------------------------------------

export type InputType = "synthetic" | "real" | "unknown";

export interface Provenance {
  run_dir: string;
  source_files: {
    room_model: string | null;
    cameras: string | null;
    scene_graph: string | null;
    sparse_cloud: string | null;
  };
  stage_status: Record<string, string>;
  input_type: InputType;
  scale: Scale;
  measurement_methods: {
    length_method: string | null;
    width_method: string | null;
    height_method: string | null;
    floor_area_method: string | null;
  };
}

export interface Twin {
  provenance: Provenance;
  room_model: RoomModel | null;
  cameras: CameraPose[] | null;
  scene_graph: SceneGraph | null;
  sparse_cloud_path: string | null;
}

export interface Session {
  id: string;
  run_dir: string;
  provenance: Provenance;
}

// ---------------------------------------------------------------------------
// Query API
// ---------------------------------------------------------------------------

export interface QuestionResponse {
  question_type: string | null;
  supported: boolean;
  answer: unknown;
  message?: string;
  supported_question_types?: string[];
}
