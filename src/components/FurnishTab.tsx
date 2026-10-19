import { useState, useEffect } from "react";
import type { Twin } from "../types/twin";
import type { PlacedFurniture, FurnitureCatalogItem } from "../types/furniture";
import {
  fetchFurnitureCatalog,
  validateFurniturePlacement,
  autoPackFurniture,
  saveFurnitureLayout,
  fetchFurnitureLayout,
} from "../lib/furnitureApi";

interface Props {
  sessionId: string;
  twin: Twin;
  placedFurniture: PlacedFurniture[];
  onPlacedFurnitureChange: (items: PlacedFurniture[]) => void;
  onSessionUpdated: () => void;
  selectedFurnitureId?: string | null;
  onSelectFurniture?: (id: string | null) => void;
}

export default function FurnishTab({
  sessionId,
  twin,
  placedFurniture,
  onPlacedFurnitureChange,
  onSessionUpdated,
  selectedFurnitureId,
  onSelectFurniture,
}: Props) {
  const [catalog, setCatalog] = useState<Record<string, FurnitureCatalogItem>>({});
  const [selectedCatalogId, setSelectedCatalogId] = useState<string>("bed_queen");
  const [loading, setLoading] = useState(false);
  const [saveStatus, setSaveStatus] = useState<string | null>(null);

  // Auto-pack options
  const [packSpacing, setPackSpacing] = useState(0.25);
  const [autoPackMessage, setAutoPackMessage] = useState<string | null>(null);

  // Load catalog & saved layout on mount
  useEffect(() => {
    fetchFurnitureCatalog().then((cat) => {
      setCatalog(cat);
    });

    fetchFurnitureLayout(sessionId).then((saved) => {
      if (saved && saved.placedItems.length > 0) {
        onPlacedFurnitureChange(saved.placedItems);
      }
    });
  }, [sessionId, onPlacedFurnitureChange]);

  const addFurniture = async (item: FurnitureCatalogItem) => {
    // Center of room or offset
    const id = `item_${Date.now()}_${Math.floor(Math.random() * 1000)}`;
    const newItem: PlacedFurniture = {
      id,
      furniture_id: item.id,
      name: item.name,
      center_x: 0.0,
      center_z: 0.0,
      angle_deg: 0,
      length: item.length,
      width: item.width,
      height: item.height,
      color: item.color,
      valid: true,
      reason: "Placed in room",
    };

    // Validate placement
    const validation = await validateFurniturePlacement(
      sessionId,
      {
        furniture_id: item.id,
        center_x: 0,
        center_z: 0,
        angle_deg: 0,
        custom_length: item.length,
        custom_width: item.width,
      },
      placedFurniture
    );

    newItem.valid = validation.valid;
    newItem.reason = validation.reason;

    onPlacedFurnitureChange([...placedFurniture, newItem]);
  };

  const updateItemPosition = async (
    idx: number,
    dx: number,
    dz: number,
    angle: number
  ) => {
    const next = [...placedFurniture];
    const target = { ...next[idx] };
    target.center_x = Number(dx.toFixed(2));
    target.center_z = Number(dz.toFixed(2));
    target.angle_deg = angle;

    const validation = await validateFurniturePlacement(
      sessionId,
      {
        furniture_id: target.furniture_id,
        center_x: target.center_x,
        center_z: target.center_z,
        angle_deg: target.angle_deg,
        custom_length: target.length,
        custom_width: target.width,
      },
      placedFurniture.filter((_, i) => i !== idx)
    );

    target.valid = validation.valid;
    target.reason = validation.reason;
    next[idx] = target;

    onPlacedFurnitureChange(next);
  };

  const removeItem = (idx: number) => {
    const next = placedFurniture.filter((_, i) => i !== idx);
    onPlacedFurnitureChange(next);
  };

  const handleAutoPack = async () => {
    setLoading(true);
    setAutoPackMessage(null);
    try {
      const res = await autoPackFurniture(sessionId, selectedCatalogId, packSpacing, 30);
      const cat = catalog[selectedCatalogId];

      const packedItems: PlacedFurniture[] = res.placements.map((p, i) => ({
        id: `pack_${selectedCatalogId}_${i + 1}`,
        furniture_id: selectedCatalogId,
        name: `${cat?.name ?? selectedCatalogId} #${i + 1}`,
        center_x: p.center_x,
        center_z: p.center_z,
        angle_deg: p.angle_deg,
        length: cat ? cat.length : 1.0,
        width: cat ? cat.width : 1.0,
        height: cat ? cat.height : 0.8,
        color: cat?.color ?? "#3b82f6",
        valid: true,
        reason: "Auto-packed in clearance boundary",
      }));

      onPlacedFurnitureChange(packedItems);
      setAutoPackMessage(
        `Packed ${res.max_count} units (${(res.coverage_ratio * 100).toFixed(1)}% usable floor coverage)`
      );
    } catch (err) {
      setAutoPackMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  const handleSaveLayout = async () => {
    setLoading(true);
    try {
      await saveFurnitureLayout(sessionId, placedFurniture, packSpacing);
      setSaveStatus("✓ Layout saved!");
      onSessionUpdated();
      setTimeout(() => setSaveStatus(null), 2500);
    } catch {
      setSaveStatus("Error saving layout");
    } finally {
      setLoading(false);
    }
  };

  const roomArea = twin.room_model?.room?.floor_area ?? 20.0;
  const occupiedArea = placedFurniture.reduce(
    (sum, item) => sum + (item.length ?? 1) * (item.width ?? 1),
    0
  );
  const remainingArea = Math.max(0, roomArea - occupiedArea);

  return (
    <div className="furnish-tab-container">
      {/* Usable Space Overview Bar */}
      <div className="space-summary-card">
        <div className="metric-row">
          <div>
            <span className="metric-label">Room Area</span>
            <span className="metric-val">{roomArea.toFixed(1)} m²</span>
          </div>
          <div>
            <span className="metric-label">Occupied</span>
            <span className="metric-val">{occupiedArea.toFixed(1)} m²</span>
          </div>
          <div>
            <span className="metric-label">Free Space</span>
            <span className="metric-val accent">{remainingArea.toFixed(1)} m²</span>
          </div>
        </div>
        <div className="capacity-bar">
          <div
            className="capacity-fill"
            style={{ width: `${Math.min(100, (occupiedArea / roomArea) * 100)}%` }}
          />
        </div>
      </div>

      {/* Furniture Catalog Grid */}
      <div className="dock-section">
        <div className="dock-section-title">
          <h4>Furniture Catalog</h4>
          <span className="subtitle-text">Click to place in room</span>
        </div>

        <div className="catalog-grid">
          {Object.values(catalog).map((item) => (
            <button
              key={item.id}
              type="button"
              className="catalog-item-btn"
              onClick={() => addFurniture(item)}
            >
              <div
                className="color-indicator"
                style={{ backgroundColor: item.color }}
              />
              <div className="catalog-info">
                <span className="catalog-name">{item.name}</span>
                <span className="catalog-dims">
                  {item.length}m × {item.width}m
                </span>
              </div>
              <span className="add-plus">+</span>
            </button>
          ))}
        </div>
      </div>

      {/* Auto-Pack Usable Clearance */}
      <div className="dock-section auto-pack-section">
        <div className="dock-section-title">
          <h4>Auto-Pack Usable Space</h4>
        </div>
        <div className="auto-pack-controls">
          <select
            value={selectedCatalogId}
            onChange={(e) => setSelectedCatalogId(e.target.value)}
            className="studio-select"
          >
            {Object.values(catalog).map((item) => (
              <option key={item.id} value={item.id}>
                Pack: {item.name} ({item.length}×{item.width}m)
              </option>
            ))}
          </select>

          <div className="slider-row">
            <label>Spacing: {packSpacing.toFixed(2)}m</label>
            <input
              type="range"
              min="0.1"
              max="0.6"
              step="0.05"
              value={packSpacing}
              onChange={(e) => setPackSpacing(parseFloat(e.target.value))}
            />
          </div>

          <button
            type="button"
            className="action-btn auto-pack-btn"
            disabled={loading}
            onClick={handleAutoPack}
          >
            {loading ? "Calculating..." : "Compute Max Units Fit"}
          </button>
          {autoPackMessage && <p className="auto-pack-result">{autoPackMessage}</p>}
        </div>
      </div>

      {/* Currently Placed Furniture List */}
      <div className="dock-section">
        <div className="dock-section-title">
          <h4>Placed Items ({placedFurniture.length})</h4>
          {placedFurniture.length > 0 && (
            <button
              type="button"
              className="save-layout-link"
              onClick={handleSaveLayout}
            >
              {saveStatus ?? "Save Layout"}
            </button>
          )}
        </div>

        {placedFurniture.length === 0 ? (
          <p className="empty-hint">No furniture placed yet. Click any item above to test fit.</p>
        ) : (
          <div className="placed-items-list">
            {placedFurniture.map((item, idx) => (
              <div
                key={item.id}
                className={`placed-item-card ${item.valid ? "valid" : "invalid"} ${
                  selectedFurnitureId === item.id ? "selected-gizmo" : ""
                }`}
                onClick={() => onSelectFurniture && onSelectFurniture(item.id)}
              >
                <div className="placed-card-header">
                  <div className="item-title-row">
                    <span
                      className="color-dot"
                      style={{ backgroundColor: item.color }}
                    />
                    <strong>{item.name}</strong>
                  </div>
                  <button
                    type="button"
                    className="delete-item-btn"
                    onClick={() => removeItem(idx)}
                    title="Remove item"
                  >
                    ✕
                  </button>
                </div>

                <div className="item-status-pill">
                  {item.valid ? (
                    <span className="status-good">✓ Valid clearance</span>
                  ) : (
                    <span className="status-bad">⚠ {item.reason}</span>
                  )}
                </div>

                <div className="item-controls-grid">
                  <div className="control-slider">
                    <label>Position X: {item.center_x.toFixed(1)}m</label>
                    <input
                      type="range"
                      min="-3.5"
                      max="3.5"
                      step="0.1"
                      value={item.center_x}
                      onChange={(e) =>
                        updateItemPosition(
                          idx,
                          parseFloat(e.target.value),
                          item.center_z,
                          item.angle_deg
                        )
                      }
                    />
                  </div>

                  <div className="control-slider">
                    <label>Position Z: {item.center_z.toFixed(1)}m</label>
                    <input
                      type="range"
                      min="-3.5"
                      max="3.5"
                      step="0.1"
                      value={item.center_z}
                      onChange={(e) =>
                        updateItemPosition(
                          idx,
                          item.center_x,
                          parseFloat(e.target.value),
                          item.angle_deg
                        )
                      }
                    />
                  </div>

                  <div className="control-slider">
                    <label>Rotation: {item.angle_deg}°</label>
                    <input
                      type="range"
                      min="0"
                      max="360"
                      step="15"
                      value={item.angle_deg}
                      onChange={(e) =>
                        updateItemPosition(
                          idx,
                          item.center_x,
                          item.center_z,
                          parseInt(e.target.value, 10)
                        )
                      }
                    />
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
