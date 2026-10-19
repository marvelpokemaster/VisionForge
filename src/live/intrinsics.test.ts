import { describe, expect, it } from "vitest";
import { configureMessage, parseCamerasJson, phoneDefaultIntrinsics } from "./intrinsics";
import { encodedSize } from "./encode";

describe("phoneDefaultIntrinsics", () => {
  it("is 0.8 × the longer side at the centre, in either orientation", () => {
    const p = phoneDefaultIntrinsics(640, 1138);
    expect(p.fx).toBeCloseTo(910.4, 9);
    expect(p).toMatchObject({ fy: p.fx, cx: 320, cy: 569, k1: 0, source: "phone_default" });
    expect(phoneDefaultIntrinsics(1280, 720)).toMatchObject({ fx: 1024, fy: 1024, cx: 640, cy: 360 });
  });

  it("is computed for the SENT size, so it scales with the client downscale", () => {
    const camera = { width: 1080, height: 1920 }; // the phone's portrait stream
    const sent = encodedSize(camera, 640); // what the pump actually sends
    expect(sent).toEqual({ width: 640, height: 1138 });
    const atCamera = phoneDefaultIntrinsics(camera.width, camera.height);
    const atSent = phoneDefaultIntrinsics(sent.width, sent.height);
    // equal to scaling the camera-size default, up to the integer rounding of the sent height (1137.8 -> 1138)
    const k = sent.width / camera.width;
    expect(atSent.fx).toBeCloseTo(atCamera.fx * k, 0);
    expect(atSent.cx).toBeCloseTo(atCamera.cx * k, 6);
    expect(atSent.cy).toBeCloseTo(atCamera.cy * k, 0);
  });
});

describe("parseCamerasJson", () => {
  const calibrate = JSON.stringify([
    { id: 0, name: "median", camera_model: "SIMPLE_RADIAL", camera_params: [1500, 540, 960, -0.02], width: 1080, height: 1920 },
    { id: 1, name: "frame_000000", camera_model: "SIMPLE_RADIAL", camera_params: [1510, 540, 960, -0.02], width: 1080, height: 1920 }
  ]);

  it("accepts a calibrate output and reads the size off the first entry", () => {
    const p = parseCamerasJson(calibrate);
    expect(p.cameras).toHaveLength(2);
    expect(p.cameras[0]).toEqual({ camera_model: "SIMPLE_RADIAL", camera_params: [1500, 540, 960, -0.02], width: 1080, height: 1920, name: "median" });
    expect(p.size).toEqual([1080, 1920]);
  });

  it("accepts a plain cameras.json entry without a size, and a single object", () => {
    const p = parseCamerasJson('[{"camera_model":"PINHOLE","camera_params":[800,800,400,300]}]');
    expect(p.size).toBeNull();
    expect(parseCamerasJson('{"camera_model":"PINHOLE","camera_params":[1,2,3,4]}').cameras).toHaveLength(1);
  });

  it("explains what is wrong", () => {
    expect(() => parseCamerasJson("{")).toThrow(/not JSON/);
    expect(() => parseCamerasJson("[]")).toThrow(/empty/);
    expect(() => parseCamerasJson('[{"camera_params":[1]}]')).toThrow(/camera_model/);
    expect(() => parseCamerasJson('[{"camera_model":"PINHOLE","camera_params":["a"]}]')).toThrow(/numeric camera_params/);
  });
});

describe("configureMessage", () => {
  const sent = { width: 640, height: 1138 };

  it("sends the phone default for the sent size when no calibration is set", () => {
    expect(configureMessage(sent, { cameras: null, record: false })).toEqual({
      width: 640,
      height: 1138,
      intrinsics: phoneDefaultIntrinsics(640, 1138)
    });
  });

  it("sends the first calibration entry with its size, and the record flag only when on", () => {
    const cameras = parseCamerasJson(
      '[{"name":"median","camera_model":"SIMPLE_RADIAL","camera_params":[1500,540,960,-0.02],"width":1080,"height":1920},{"camera_model":"SIMPLE_RADIAL","camera_params":[1,1,1,1]}]'
    );
    const msg = configureMessage(sent, { cameras, record: true });
    expect(msg).toEqual({
      width: 640,
      height: 1138,
      record: true,
      intrinsics_from_cameras: [cameras.cameras[0]],
      intrinsics_size: [1080, 1920]
    });
    expect("intrinsics" in msg).toBe(false);
    const noSize = configureMessage(sent, { cameras: parseCamerasJson('[{"camera_model":"PINHOLE","camera_params":[1,1,1,1]}]'), record: false });
    expect("intrinsics_size" in noSize).toBe(false);
    expect("record" in noSize).toBe(false);
  });
});
