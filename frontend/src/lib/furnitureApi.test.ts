import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  fetchFurnitureCatalog,
  validateFurniturePlacement,
  autoPackFurniture,
  calibrateScale,
  saveFurnitureLayout,
  fetchFurnitureLayout,
} from "./furnitureApi";

describe("furnitureApi client", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("fetchFurnitureCatalog calls /furniture/catalog", async () => {
    const mockCatalog = { bed_queen: { id: "bed_queen", name: "Queen Bed" } };
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockCatalog,
    } as Response);

    const data = await fetchFurnitureCatalog();
    expect(data).toEqual(mockCatalog);
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/furniture/catalog"),
      expect.anything()
    );
  });

  it("validateFurniturePlacement posts payload correctly", async () => {
    const mockRes = { valid: true, reason: "Clear", corners: [] };
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockRes,
    } as Response);

    const res = await validateFurniturePlacement("session_123", {
      furniture_id: "bed_queen",
      center_x: 0,
      center_z: 0,
      angle_deg: 0,
    });
    expect(res.valid).toBe(true);
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/sessions/session_123/furniture/validate"),
      expect.objectContaining({ method: "POST" })
    );
  });

  it("autoPackFurniture calls auto_pack endpoint", async () => {
    const mockResult = { furniture_id: "bed_queen", max_count: 4, placements: [] };
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockResult,
    } as Response);

    const res = await autoPackFurniture("session_123", "bed_queen", 0.2);
    expect(res.max_count).toBe(4);
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/sessions/session_123/furniture/auto_pack"),
      expect.objectContaining({ method: "POST" })
    );
  });

  it("validateFurniturePlacement preserves rejection results from backend", async () => {
    const mockRes = { valid: false, reason: "Collides with wall", corners: [] };
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockRes,
    } as Response);

    const res = await validateFurniturePlacement("session_123", {
      furniture_id: "bed_queen",
      center_x: 5.0,
      center_z: 5.0,
      angle_deg: 0,
    });
    expect(res.valid).toBe(false);
    expect(res.reason).toBe("Collides with wall");
  });

  it("validateFurniturePlacement throws on server error", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      statusText: "Internal Server Error",
      json: async () => ({ detail: "Engine crash" }),
    } as Response);

    await expect(
      validateFurniturePlacement("session_123", {
        furniture_id: "bed_queen",
        center_x: 0,
        center_z: 0,
        angle_deg: 0,
      })
    ).rejects.toThrow("Engine crash");
  });

  it("calibrateScale handles server errors gracefully", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      statusText: "Bad Request",
      json: async () => ({ detail: "Invalid distance" }),
    } as Response);

    await expect(calibrateScale("session_123", "room_width", -5)).rejects.toThrow("Invalid distance");
  });

  it("saveFurnitureLayout posts placed items and spacing", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: "saved", session_id: "session_123" }),
    } as Response);

    const items = [
      {
        id: "f_1",
        furniture_id: "bed_queen",
        name: "Queen Bed",
        center_x: 1.0,
        center_z: 2.0,
        angle_deg: 90,
        length: 2.0,
        width: 1.6,
        height: 0.9,
        color: "#3b82f6",
        valid: true,
        reason: "Clear",
      },
    ];

    const res = await saveFurnitureLayout("session_123", items, 0.3);
    expect(res.status).toBe("saved");
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/sessions/session_123/furniture/layout"),
      expect.objectContaining({
        method: "POST",
        body: expect.stringContaining('"pack_spacing":0.3'),
      })
    );
  });

  it("fetchFurnitureLayout returns parsed items and spacing", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        placed_items: [
          {
            id: "f_1",
            furniture_id: "bed_queen",
            name: "Queen Bed",
            center_x: 1.0,
            center_z: 2.0,
            angle_deg: 90,
            custom_length: 2.0,
            custom_width: 1.6,
            custom_height: 0.9,
            color: "#3b82f6",
            valid: true,
            reason: "Clear",
          },
        ],
        pack_spacing: 0.35,
      }),
    } as Response);

    const layout = await fetchFurnitureLayout("session_123");
    expect(layout).not.toBeNull();
    expect(layout?.placedItems.length).toBe(1);
    expect(layout?.placedItems[0].furniture_id).toBe("bed_queen");
    expect(layout?.packSpacing).toBe(0.35);
  });

  it("fetchFurnitureLayout returns null on 404", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      statusText: "Not Found",
    } as Response);

    const layout = await fetchFurnitureLayout("session_empty");
    expect(layout).toBeNull();
  });
});

