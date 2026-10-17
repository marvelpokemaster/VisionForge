export interface FurnitureCatalogItem {
  id: string;
  name: string;
  category: string;
  length: number;
  width: number;
  height: number;
  color: string;
}

export interface PlacedFurniture {
  id: string;
  furniture_id: string;
  name: string;
  center_x: number;
  center_z: number;
  angle_deg: number;
  length: number;
  width: number;
  height: number;
  color: string;
  valid: boolean;
  reason: string;
}

export interface AutoPackResult {
  furniture_id: string;
  furniture_name: string;
  unit_dimensions: {
    length: number;
    width: number;
    height: number;
  };
  max_count: number;
  placements: Array<{
    id: string;
    furniture_id: string;
    center_x: number;
    center_z: number;
    angle_deg: number;
    custom_length: number;
    custom_width: number;
    custom_height: number;
  }>;
  floor_area_m2: number;
  occupied_area_m2: number;
  usable_free_area_m2: number;
  coverage_ratio: number;
}
