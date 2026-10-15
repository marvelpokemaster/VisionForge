// DOM half of the pump: draw the source's current frame to a canvas at
// <= maxWidth and JPEG-encode it. Kept out of pump.ts so the scheduling logic
// stays testable without a DOM.
import type { FrameEncoder } from "./pump";
import type { FrameSize, FrameSource } from "./source";

export function encodedSize(size: FrameSize, maxWidth: number): FrameSize {
  const scale = size.width > maxWidth ? maxWidth / size.width : 1;
  return { width: Math.round(size.width * scale), height: Math.round(size.height * scale) };
}

export function makeJpegEncoder(source: FrameSource, maxWidth = 640, quality = 0.7): FrameEncoder {
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("2D canvas not available");
  return async () => {
    const video = source.frame();
    if (!video) return null;
    const { width, height } = encodedSize({ width: video.videoWidth, height: video.videoHeight }, maxWidth);
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    ctx.drawImage(video, 0, 0, width, height);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", quality));
    return blob ? blob.arrayBuffer() : null;
  };
}
