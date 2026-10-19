import { useState, useEffect } from "react";
import type { Twin } from "../types/twin";
import type { FurnitureCatalogItem, PlacedFurniture, AutoPackResult } from "../types/furniture";
import {
  fetchFurnitureCatalog,
  validateFurniturePlacement,
  autoPackFurniture,
  calibrateScale,
  saveFurnitureLayout,
  fetchFurnitureLayout,
} from "../lib/furnitureApi";

interface Props {
  sessionId: string;
  twin: Twin;
  placedFurniture: PlacedFurniture[];
  onPlacedFurnitureChange: (items: PlacedFurniture[]) => void;
  onSessionUpdated: () => void;
}

export default function FurniturePanel({
  sessionId,
  twin,
  placedFurniture,
  onPlacedFurnitureChange,
  onSessionUpdated,
}: Props) {
  const [catalog, setCatalog] = useState<Record<string, FurnitureCatalogItem>>({});
  const [selectedFurnitureId, setSelectedFurnitureId] = useState<string>("bed_queen");
  const [autoPackResult, setAutoPackResult] = useState<AutoPackResult | null>(null);
  const [isPacking, setIsPacking] = useState(false);
  const [packSpacing, setPackSpacing] = useState<number>(0.2);

  // Persistence state
  const [isSavingLayout, setIsSavingLayout] = useState(false);
  const [saveStatusMsg, setSaveStatusMsg] = useState<string | null>(null);

  // Calibration state
  const [calibrateDimension, setCalibrateDimension] = useState<"room_width" | "room_length">("room_width");
  const [calibrateDistance, setCalibrateDistance] = useState<number>(3.5);
  const [isCalibrating, setIsCalibrating] = useState(false);
  const [calibrateMsg, setCalibrateMsg] = useState<string | null>(null);

  useEffect(() => {
    fetchFurnitureCatalog()
      .then((cat) => {
        setCatalog(cat);
        const keys = Object.keys(cat);
        if (keys.length > 0 && !cat[selectedFurnitureId]) {
          setSelectedFurnitureId(keys[0]);
        }
      })
      .catch((err) => console.error("Could not load furniture catalog", err));
  }, []);

  useEffect(() => {
    let active = true;
    fetchFurnitureLayout(sessionId)
      .then((layout) => {
        if (!active) return;
        if (layout && layout.placedItems.length > 0) {
          onPlacedFurnitureChange(layout.placedItems);
          if (layout.packSpacing) setPackSpacing(layout.packSpacing);
        }
      })
      .catch((err) => console.warn("Could not load saved furniture layout", err));
    return () => {
      active = false;
    };
  }, [sessionId]);

  const handleSaveLayout = async () => {
    setIsSavingLayout(true);
    setSaveStatusMsg(null);
    try {
      await saveFurnitureLayout(sessionId, placedFurniture, packSpacing);
      setSaveStatusMsg("✓ Layout saved");
      setTimeout(() => setSaveStatusMsg(null), 3000);
    } catch (err: any) {
      setSaveStatusMsg(`Failed to save: ${err.message}`);
    } finally {
      setIsSavingLayout(false);
    }
  };

  const scale = twin.scale || twin.provenance?.scale || { metric_available: false, scale_factor: 1.0 };
  const floorBoundary = twin?.room_model?.room?.bounding_polygon_room;
  const hasFloorBoundary = Boolean(floorBoundary && Array.isArray(floorBoundary) && floorBoundary.length >= 3);

  // Handle Scale Calibration
  const handleCalibrate = async () => {
    if (calibrateDistance <= 0) return;
    setIsCalibrating(true);
    setCalibrateMsg(null);
    try {
      await calibrateScale(sessionId, calibrateDimension, calibrateDistance);
      setCalibrateMsg("Metric scale successfully calibrated!");
      onSessionUpdated();
    } catch (err: any) {
      setCalibrateMsg(`Error: ${err.message}`);
    } finally {
      setIsCalibrating(false);
    }
  };

  // Add Item to Placed Furniture
  const handleAddPiece = async () => {
    const itemDef = catalog[selectedFurnitureId];
    if (!itemDef) return;

    const newItemId = `furniture_${Date.now()}`;
    const initialItem: PlacedFurniture = {
      id: newItemId,
      furniture_id: itemDef.id,
      name: itemDef.name,
      center_x: 0.0,
      center_z: 0.0,
      angle_deg: 0.0,
      length: itemDef.length,
      width: itemDef.width,
      height: itemDef.height,
      color: itemDef.color,
      valid: true,
      reason: "Checking...",
    };

    // Validate placement
    try {
      const val = await validateFurniturePlacement(sessionId, initialItem, placedFurniture);
      initialItem.valid = val.valid;
      initialItem.reason = val.reason;
    } catch (err: any) {
      initialItem.valid = false;
      initialItem.reason = err.message || "Validation error";
    }

    onPlacedFurnitureChange([...placedFurniture, initialItem]);
  };

  // Move or Rotate an existing placed piece
  const handleUpdateItem = async (
    index: number,
    deltaX: number,
    deltaZ: number,
    rotateDeg: number = 0
  ) => {
    const updated = [...placedFurniture];
    const item = { ...updated[index] };
    item.center_x = parseFloat((item.center_x + deltaX).toFixed(2));
    item.center_z = parseFloat((item.center_z + deltaZ).toFixed(2));
    item.angle_deg = (item.angle_deg + rotateDeg) % 360;

    const otherItems = updated.filter((_, i) => i !== index);
    try {
      const val = await validateFurniturePlacement(sessionId, item, otherItems);
      item.valid = val.valid;
      item.reason = val.reason;
    } catch (err: any) {
      item.valid = false;
      item.reason = err.message || "Validation error";
    }

    updated[index] = item;
    onPlacedFurnitureChange(updated);
  };

  // Remove an item
  const handleRemoveItem = (index: number) => {
    onPlacedFurnitureChange(placedFurniture.filter((_, i) => i !== index));
  };

  // Run Auto-Pack ("Can It Fit?")
  const handleAutoPack = async () => {
    setIsPacking(true);
    setAutoPackResult(null);
    try {
      const result = await autoPackFurniture(sessionId, selectedFurnitureId, packSpacing);
      setAutoPackResult(result);
    } catch (err: any) {
      alert(`Auto pack failed: ${err.message}`);
    } finally {
      setIsPacking(false);
    }
  };

  // Apply Auto-Pack results to 3D scene
  const handleApplyAutoPack = () => {
    if (!autoPackResult) return;
    const cat = catalog[autoPackResult.furniture_id];
    const items: PlacedFurniture[] = autoPackResult.placements.map((p, idx) => ({
      id: `pack_${idx + 1}`,
      furniture_id: autoPackResult.furniture_id,
      name: autoPackResult.furniture_name,
      center_x: p.center_x,
      center_z: p.center_z,
      angle_deg: p.angle_deg,
      length: p.custom_length || cat?.length || 1.0,
      width: p.custom_width || cat?.width || 1.0,
      height: p.custom_height || cat?.height || 0.8,
      color: cat?.color || "#3b82f6",
      valid: true,
      reason: "Clear",
    }));
    onPlacedFurnitureChange(items);
  };

  return (
    <div className="furniture-panel" style={{ padding: "0.75rem", background: "#1c1e24", borderRadius: "6px", color: "#e5e7eb", marginTop: "0.5rem" }}>
      <h3 style={{ fontSize: "1rem", margin: "0 0 0.5rem 0", color: "#60a5fa" }}>
        Furniture Placement & Clearance
      </h3>

      {/* Missing Floor Boundary Notice */}
      {!hasFloorBoundary && (
        <div style={{ padding: "0.5rem", background: "#3b1e1e", border: "1px solid #ef4444", borderRadius: "4px", fontSize: "0.8rem", color: "#fca5a5", marginBottom: "0.75rem" }}>
          ⚠ Room floor boundary polygon is unavailable. A room floor boundary polygon must be detected from geometry before planning furniture.
        </div>
      )}

      {/* Metric Scale Calibration Section */}
      <div style={{ marginBottom: "0.75rem", padding: "0.5rem", background: "#252830", borderRadius: "4px", fontSize: "0.85rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.4rem" }}>
          <span>Scale Provenance:</span>
          <span style={{ color: scale.metric_available ? "#34d399" : "#fbbf24", fontWeight: "bold" }}>
            {scale.metric_available ? `✓ Metric (1 unit = ${(1 / scale.scale_factor).toFixed(2)}m)` : "⚠ Arbitrary Units"}
          </span>
        </div>
        <div style={{ display: "flex", gap: "0.4rem", alignItems: "center" }}>
          <select
            value={calibrateDimension}
            onChange={(e) => setCalibrateDimension(e.target.value as any)}
            style={{ background: "#1e2128", color: "#fff", border: "1px solid #374151", borderRadius: "4px", padding: "0.3rem" }}
          >
            <option value="room_width">Room Width</option>
            <option value="room_length">Room Length</option>
          </select>
          <input
            type="number"
            inputMode="decimal"
            step="0.1"
            value={calibrateDistance}
            onChange={(e) => setCalibrateDistance(parseFloat(e.target.value) || 0)}
            style={{ width: "65px", background: "#1e2128", color: "#fff", border: "1px solid #374151", borderRadius: "4px", padding: "0.3rem" }}
          />
          <span>m</span>
          <button
            onClick={handleCalibrate}
            disabled={isCalibrating}
            style={{ padding: "0.3rem 0.75rem", background: "#3b82f6", color: "#fff", border: "none", borderRadius: "4px", cursor: isCalibrating ? "wait" : "pointer", marginLeft: "auto" }}
          >
            {isCalibrating ? "..." : "Calibrate"}
          </button>
        </div>
        {calibrateMsg && <p style={{ margin: "0.3rem 0 0 0", color: "#34d399", fontSize: "0.8rem" }}>{calibrateMsg}</p>}
      </div>

      {/* Catalog & Placement Tools */}
      <div style={{ marginBottom: "0.75rem" }}>
        <label style={{ fontSize: "0.85rem", display: "block", marginBottom: "0.25rem" }}>Select Furniture Item:</label>
        <div style={{ display: "flex", gap: "0.4rem", marginBottom: "0.5rem" }}>
          <select
            value={selectedFurnitureId}
            onChange={(e) => setSelectedFurnitureId(e.target.value)}
            style={{ flex: 1, background: "#252830", color: "#fff", border: "1px solid #374151", borderRadius: "4px", padding: "0.4rem" }}
          >
            {Object.values(catalog).map((item) => (
              <option key={item.id} value={item.id}>
                {item.name} ({item.length}m × {item.width}m)
              </option>
            ))}
          </select>
          <button
            onClick={handleAddPiece}
            disabled={!hasFloorBoundary}
            title={hasFloorBoundary ? "Add piece to room" : "Floor boundary polygon is unavailable"}
            style={{
              padding: "0.4rem 0.85rem",
              background: hasFloorBoundary ? "#10b981" : "#4b5563",
              color: "#fff",
              border: "none",
              borderRadius: "4px",
              cursor: hasFloorBoundary ? "pointer" : "not-allowed",
            }}
          >
            + Add
          </button>
        </div>

        {/* Can It Fit? / Auto-Pack */}
        <div style={{ display: "flex", gap: "0.4rem", alignItems: "center" }}>
          <button
            onClick={handleAutoPack}
            disabled={isPacking || !hasFloorBoundary}
            title={hasFloorBoundary ? "Auto-pack candidate furniture" : "Floor boundary polygon is unavailable"}
            style={{
              flex: 1,
              padding: "0.4rem",
              background: hasFloorBoundary ? "#8b5cf6" : "#4b5563",
              color: "#fff",
              border: "none",
              borderRadius: "4px",
              cursor: hasFloorBoundary && !isPacking ? "pointer" : "not-allowed",
            }}
          >
            {isPacking ? "Analyzing..." : "Can It Fit? (Auto-Pack)"}
          </button>
          <label style={{ fontSize: "0.75rem", color: "#9ca3af" }}>
            Gap:
            <input
              type="number"
              inputMode="decimal"
              step="0.1"
              value={packSpacing}
              onChange={(e) => setPackSpacing(parseFloat(e.target.value) || 0.1)}
              style={{ width: "45px", marginLeft: "0.2rem", background: "#252830", color: "#fff", border: "1px solid #374151", borderRadius: "3px", padding: "0.2rem" }}
            />
            m
          </label>
        </div>

        {/* Auto-pack result display */}
        {autoPackResult && (
          <div style={{ marginTop: "0.5rem", padding: "0.5rem", background: "#2d1a4d", border: "1px solid #8b5cf6", borderRadius: "4px", fontSize: "0.8rem" }}>
            <p style={{ margin: "0 0 0.3rem 0", fontWeight: "bold", color: "#c4b5fd" }}>
              ✓ Max Capacity: {autoPackResult.max_count} × {autoPackResult.furniture_name}
            </p>
            <p style={{ margin: "0 0 0.4rem 0" }}>
              Occupied: {autoPackResult.occupied_area_m2.toFixed(1)} m² ({Math.round(autoPackResult.coverage_ratio * 100)}%) | Free: {autoPackResult.usable_free_area_m2.toFixed(1)} m²
            </p>
            <button
              onClick={handleApplyAutoPack}
              style={{ width: "100%", padding: "0.25rem", background: "#7c3aed", color: "#fff", border: "none", borderRadius: "3px", cursor: "pointer" }}
            >
              Apply All {autoPackResult.max_count} to 3D Scene
            </button>
          </div>
        )}
      </div>

      {/* Placed Items List & Position Adjustment */}
      {placedFurniture.length > 0 && (
        <div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.4rem" }}>
            <span style={{ fontSize: "0.85rem", fontWeight: "bold" }}>Placed Items ({placedFurniture.length}):</span>
            <div style={{ display: "flex", gap: "0.4rem", alignItems: "center" }}>
              <button
                onClick={handleSaveLayout}
                disabled={isSavingLayout}
                style={{
                  padding: "0.2rem 0.5rem",
                  background: "#2563eb",
                  color: "#fff",
                  border: "none",
                  borderRadius: "4px",
                  fontSize: "0.75rem",
                  cursor: isSavingLayout ? "wait" : "pointer",
                }}
              >
                {isSavingLayout ? "Saving..." : "Save Layout"}
              </button>
              <button
                onClick={() => onPlacedFurnitureChange([])}
                style={{ fontSize: "0.75rem", background: "none", border: "none", color: "#ef4444", cursor: "pointer", textDecoration: "underline" }}
              >
                Clear All
              </button>
            </div>
          </div>

          {saveStatusMsg && (
            <div
              style={{
                fontSize: "0.75rem",
                color: saveStatusMsg.startsWith("✓") ? "#34d399" : "#f87171",
                marginBottom: "0.4rem",
              }}
            >
              {saveStatusMsg}
            </div>
          )}

          <div style={{ maxHeight: "200px", overflowY: "auto", display: "flex", flexDirection: "column", gap: "0.4rem" }}>
            {placedFurniture.map((item, idx) => (
              <div
                key={item.id}
                style={{
                  padding: "0.4rem",
                  background: item.valid ? "#1f2937" : "#451a1a",
                  border: `1px solid ${item.valid ? "#374151" : "#ef4444"}`,
                  borderRadius: "4px",
                  fontSize: "0.8rem",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.25rem" }}>
                  <span style={{ fontWeight: "bold" }}>{item.name}</span>
                  <button
                    onClick={() => handleRemoveItem(idx)}
                    style={{ background: "none", border: "none", color: "#ef4444", cursor: "pointer", fontWeight: "bold" }}
                  >
                    ✕
                  </button>
                </div>
                <div style={{ color: item.valid ? "#34d399" : "#f87171", marginBottom: "0.3rem" }}>
                  {item.valid ? "✓ Clear" : `⚠ ${item.reason}`}
                </div>
                <div style={{ display: "flex", gap: "0.3rem", alignItems: "center" }}>
                  <span>X: {item.center_x}m</span>
                  <button onClick={() => handleUpdateItem(idx, -0.2, 0)} style={{ padding: "0.1rem 0.3rem" }}>◀</button>
                  <button onClick={() => handleUpdateItem(idx, 0.2, 0)} style={{ padding: "0.1rem 0.3rem" }}>▶</button>
                  <span style={{ marginLeft: "0.3rem" }}>Z: {item.center_z}m</span>
                  <button onClick={() => handleUpdateItem(idx, 0, -0.2)} style={{ padding: "0.1rem 0.3rem" }}>▲</button>
                  <button onClick={() => handleUpdateItem(idx, 0, 0.2)} style={{ padding: "0.1rem 0.3rem" }}>▼</button>
                  <button onClick={() => handleUpdateItem(idx, 0, 0, 90)} style={{ marginLeft: "auto", padding: "0.1rem 0.4rem" }}>⟳ 90°</button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
