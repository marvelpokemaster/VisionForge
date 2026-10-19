import type { Twin, QuestionResponse, Measurement } from "../types/twin";
import type { RoomMeasurementsResponse } from "./api";

export class ClientSpatialQueryEngine {
  constructor(private twin: Twin) {}

  private get roomModel() {
    return this.twin.room_model;
  }

  private get scale() {
    return this.roomModel?.scale ?? { metric_available: true, scale_factor: 1.0 };
  }

  private wrapMeasurement(
    val: number | null | undefined,
    method?: string | null
  ): Measurement | null {
    if (val === null || val === undefined) return null;
    return {
      value: Number(val.toFixed(2)),
      metric: this.scale.metric_available,
      units: this.scale.metric_available ? "m" : "reconstruction_units",
      ...(method ? { method } : {}),
    };
  }

  getRoomDimensions(): RoomMeasurementsResponse {
    const room = this.roomModel?.room;
    return {
      length: this.wrapMeasurement(room?.length, room?.length_method ?? "bounding_box"),
      width: this.wrapMeasurement(room?.width, room?.width_method ?? "bounding_box"),
      height: this.wrapMeasurement(room?.height, room?.height_method ?? "floor_to_ceiling"),
      floor_area: room?.floor_area
        ? {
            value: Number(room.floor_area.toFixed(2)),
            metric: this.scale.metric_available,
            units: this.scale.metric_available ? "m²" : "reconstruction_units²",
            method: room.floor_area_method ?? "polygon_area",
          }
        : null,
    };
  }

  getLargestWall(): { wall_id: string | null; area: Measurement | null } {
    const planes = this.roomModel?.planes ?? [];
    const walls = planes.filter((p) => p.type === "wall");
    if (walls.length === 0) return { wall_id: null, area: null };

    let bestWall = walls[0];
    let maxArea = bestWall.area ?? 0;

    for (const w of walls) {
      const area = w.area ?? (w.extent ? w.extent.width * w.extent.height : 0);
      if (area > maxArea) {
        maxArea = area;
        bestWall = w;
      }
    }

    return {
      wall_id: bestWall.id,
      area: {
        value: Number(maxArea.toFixed(2)),
        metric: this.scale.metric_available,
        units: this.scale.metric_available ? "m²" : "reconstruction_units²",
        method: "plane_support_extent",
      },
    };
  }

  getParallelWalls(): Record<string, string[]> {
    const planes = this.roomModel?.planes ?? [];
    const walls = planes.filter((p) => p.type === "wall");
    const result: Record<string, string[]> = {};

    for (const w1 of walls) {
      result[w1.id] = [];
      for (const w2 of walls) {
        if (w1.id === w2.id) continue;
        const dot = Math.abs(
          w1.normal[0] * w2.normal[0] +
          w1.normal[1] * w2.normal[1] +
          w1.normal[2] * w2.normal[2]
        );
        if (dot > 0.88) {
          result[w1.id].push(w2.id);
        }
      }
    }
    return result;
  }

  getNearestWallToCamera(): { wall_id: string | null; distance: Measurement | null } {
    const planes = this.roomModel?.planes ?? [];
    const walls = planes.filter((p) => p.type === "wall");
    const cameras = this.twin.cameras ?? [];

    if (walls.length === 0 || cameras.length === 0) {
      return { wall_id: null, distance: null };
    }

    const cam = cameras[0];
    const pos = cam.translation;

    let nearestWall = walls[0];
    let minDist = Infinity;

    for (const w of walls) {
      const normal = w.normal;
      const d = w.equation[3];
      const dist = Math.abs(normal[0] * pos[0] + normal[1] * pos[1] + normal[2] * pos[2] + d);
      if (dist < minDist) {
        minDist = dist;
        nearestWall = w;
      }
    }

    return {
      wall_id: nearestWall.id,
      distance: this.wrapMeasurement(minDist, "camera_point_to_plane"),
    };
  }

  answerQuestion(question: string): QuestionResponse {
    const q = question.toLowerCase().trim();

    if (/height|tall|ceiling/.test(q)) {
      const dim = this.getRoomDimensions();
      return {
        question_type: "room_height",
        supported: true,
        answer: dim.height,
      };
    }

    if (/largest.*wall|biggest.*wall|most area/.test(q)) {
      const largest = this.getLargestWall();
      return {
        question_type: "largest_wall",
        supported: true,
        answer: largest,
      };
    }

    if (/parallel.*wall|which walls are parallel/.test(q)) {
      const par = this.getParallelWalls();
      return {
        question_type: "parallel_walls",
        supported: true,
        answer: par,
      };
    }

    if (/camera.*(nearest|closest|wall)|distance.*camera/.test(q)) {
      const nearest = this.getNearestWallToCamera();
      return {
        question_type: "camera_nearest_wall",
        supported: true,
        answer: nearest,
      };
    }

    if (/floor.*area|area.*room|how (big|large).*room/.test(q)) {
      const dim = this.getRoomDimensions();
      return {
        question_type: "floor_area",
        supported: true,
        answer: dim.floor_area,
      };
    }

    if (/dimension|length|width|size/.test(q)) {
      const dim = this.getRoomDimensions();
      return {
        question_type: "room_dimensions",
        supported: true,
        answer: dim,
      };
    }

    return {
      question_type: null,
      supported: false,
      answer: null,
      message: "Unsupported question. Try asking about room height, largest wall, parallel walls, floor area, or camera distance.",
      supported_question_types: [
        "What is the room height?",
        "Which wall is largest?",
        "Which walls are parallel?",
        "How far is the camera from the nearest wall?",
        "What is the floor area?",
        "What are the room dimensions?",
      ],
    };
  }
}
