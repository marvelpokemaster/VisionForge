// Frame sources for the live screen. Both expose the same interface: start()
// resolves with the frame size, frame() hands back the <video> element when it
// has a decodable frame, stop() releases everything. The pump's encoder draws
// that element to a canvas; neither source stores frames.
//
// CameraSource uses plain getUserMedia (rear camera preferred). Inside
// Capacitor 8's Android WebView this works once android.permission.CAMERA is
// declared in the manifest and granted at runtime (Capacitor's WebChromeClient
// forwards the WebView permission request). That path is UNVERIFIED here (no
// device); if a human test shows the WebView refusing, @capacitor/camera's
// preview plugin is the fallback.
export interface FrameSize {
  width: number;
  height: number;
}

export interface FrameSource {
  readonly kind: "camera" | "file";
  readonly video: HTMLVideoElement;
  readonly ended: boolean;
  start(): Promise<FrameSize>;
  frame(): HTMLVideoElement | null;
  stop(): void;
}

function waitForVideoSize(video: HTMLVideoElement, timeoutMs = 10000): Promise<FrameSize> {
  return new Promise((resolve, reject) => {
    const done = () => {
      if (video.videoWidth > 0 && video.videoHeight > 0) {
        cleanup();
        resolve({ width: video.videoWidth, height: video.videoHeight });
        return true;
      }
      return false;
    };
    const timer = setTimeout(() => {
      cleanup();
      reject(new Error("video never reported a frame size"));
    }, timeoutMs);
    const cleanup = () => {
      clearTimeout(timer);
      video.removeEventListener("loadedmetadata", onMeta);
      video.removeEventListener("resize", onMeta);
    };
    const onMeta = () => void done();
    if (done()) return;
    video.addEventListener("loadedmetadata", onMeta);
    video.addEventListener("resize", onMeta);
  });
}

export class CameraSource implements FrameSource {
  readonly kind = "camera" as const;
  readonly ended = false;
  private stream: MediaStream | null = null;

  constructor(readonly video: HTMLVideoElement) {}

  async start(): Promise<FrameSize> {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("getUserMedia is not available in this browser/WebView (needs a secure context: https or localhost)");
    }
    this.stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 } },
      audio: false
    });
    this.video.srcObject = this.stream;
    this.video.muted = true;
    this.video.playsInline = true;
    await this.video.play();
    return waitForVideoSize(this.video);
  }

  frame(): HTMLVideoElement | null {
    return this.video.readyState >= 2 && this.video.videoWidth > 0 ? this.video : null;
  }

  stop(): void {
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.video.srcObject = null;
  }
}

export class FileSource implements FrameSource {
  readonly kind = "file" as const;
  ended = false;
  private url: string | null = null;

  constructor(readonly video: HTMLVideoElement, private readonly file: File) {}

  async start(): Promise<FrameSize> {
    this.url = URL.createObjectURL(this.file);
    this.video.src = this.url;
    this.video.muted = true;
    this.video.playsInline = true;
    this.video.loop = false;
    this.video.onended = () => {
      this.ended = true;
    };
    await this.video.play();
    return waitForVideoSize(this.video);
  }

  frame(): HTMLVideoElement | null {
    if (this.ended) return null;
    return this.video.readyState >= 2 && this.video.videoWidth > 0 ? this.video : null;
  }

  stop(): void {
    this.video.pause();
    this.video.onended = null;
    this.video.removeAttribute("src");
    this.video.load();
    if (this.url) URL.revokeObjectURL(this.url);
    this.url = null;
  }
}
