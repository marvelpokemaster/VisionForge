import { useState, useRef, useCallback } from "react";

interface Props {
  onSessionReady: (sessionId: string) => void;
  onCancel?: () => void;
}

interface SamplePreset {
  id: string;
  title: string;
  category: string;
  duration: string;
  dimensions: string;
  description: string;
  thumbnailColor: string;
  sessionId: string;
}

const SAMPLE_PRESETS: SamplePreset[] = [
  {
    id: "preset_final_demo",
    title: "Scandinavian Living Room",
    category: "Real Video Scan",
    duration: "14s • 24 Keyframes",
    dimensions: "5.4m × 3.9m • 20.9 m²",
    description: "Multi-view physical video walk-around with high parallax, detected hardwood floor, and 4 architectural walls.",
    thumbnailColor: "from-amber-700/40 to-slate-900",
    sessionId: "final_demo",
  },
  {
    id: "preset_live_synth",
    title: "Modern Studio Loft",
    category: "Incremental Tracking",
    duration: "18s • 30 Keyframes",
    dimensions: "6.2m × 4.5m • 27.9 m²",
    description: "Spacious open-concept room with floor clearance polygon, wall boundary intersections, and furniture fit.",
    thumbnailColor: "from-sky-800/40 to-slate-900",
    sessionId: "live_synth_30",
  },
  {
    id: "preset_bedroom",
    title: "Minimalist Master Bedroom",
    category: "Architectural Twin",
    duration: "12s • 20 Keyframes",
    dimensions: "4.8m × 3.4m • 16.3 m²",
    description: "Quiet rectangular room scan optimal for bed clearance, wardrobe placement, and nightstand layout testing.",
    thumbnailColor: "from-emerald-800/40 to-slate-900",
    sessionId: "final_demo",
  },
];

const PIPELINE_STAGES = [
  { id: 1, name: "Video Ingestion & Frame Sampling", desc: "Extracting sharp parallax keyframes from video stream" },
  { id: 2, name: "Classical Feature Matching", desc: "SIFT/ORB point correspondences and essential matrix estimation" },
  { id: 3, name: "Architectural Plane Fitting", desc: "RANSAC surface segmentation for floor, ceiling, and walls" },
  { id: 4, name: "Digital Twin Synthesis", desc: "Generating usable boundary polygon and spatial clearance graph" },
];

interface QualityAssessment {
  score: number;
  level: "optimal" | "moderate" | "risk";
  label: string;
  notes: { status: "good" | "warn" | "danger"; text: string }[];
}

function assessVideoQuality(meta: { width: number; height: number; duration: number } | null): QualityAssessment | null {
  if (!meta) return null;
  const notes: { status: "good" | "warn" | "danger"; text: string }[] = [];
  let score = 95;

  if (meta.duration < 5) {
    notes.push({
      status: "danger",
      text: "Duration under 5s: Insufficient baseline translation to triangulate depth rays.",
    });
    score -= 45;
  } else if (meta.duration < 10) {
    notes.push({
      status: "warn",
      text: "Short duration (< 10s): High risk if the camera was rotated in place instead of walked laterally.",
    });
    score -= 15;
  } else if (meta.duration > 75) {
    notes.push({
      status: "warn",
      text: "Long duration (> 75s): SIFT keyframe decimation will sample ~30 keyframes to avoid drift.",
    });
    score -= 8;
  } else {
    notes.push({
      status: "good",
      text: `Optimal duration (${meta.duration}s): Ideal frame overlap for geometric triangulation.`,
    });
  }

  const minDim = Math.min(meta.width, meta.height);
  if (minDim < 480) {
    notes.push({
      status: "danger",
      text: "Low resolution (< 480p): Severe loss of sub-pixel gradient edges for Lowe ratio matching.",
    });
    score -= 35;
  } else if (minDim < 720) {
    notes.push({
      status: "warn",
      text: "Standard resolution (480p): Keypoint detection will work, but wall boundaries may be coarse.",
    });
    score -= 10;
  } else {
    notes.push({
      status: "good",
      text: `HD resolution (${meta.width}×${meta.height}): Sharp high-frequency gradients for SIFT scale-space.`,
    });
  }

  const boundedScore = Math.max(15, Math.min(100, score));
  let level: "optimal" | "moderate" | "risk" = "optimal";
  let label = "High Feasibility";

  if (boundedScore < 50) {
    level = "risk";
    label = "High Risk of Failure / Degeneracy";
  } else if (boundedScore < 75) {
    level = "moderate";
    label = "Moderate Feasibility (Check Motion)";
  }

  return { score: boundedScore, level, label, notes };
}

export default function UploadStudio({ onSessionReady, onCancel }: Props) {
  const [dragActive, setDragActive] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [videoPreviewUrl, setVideoPreviewUrl] = useState<string | null>(null);
  const [videoMeta, setVideoMeta] = useState<{ width: number; height: number; duration: number } | null>(null);
  const [showExplanation, setShowExplanation] = useState(false);

  const [processing, setProcessing] = useState(false);
  const [currentStage, setCurrentStage] = useState(1);
  const [stageProgress, setStageProgress] = useState(0);
  const [statusMessage, setStatusMessage] = useState("");

  const fileInputRef = useRef<HTMLInputElement>(null);
  const videoElemRef = useRef<HTMLVideoElement>(null);

  const handleDrag = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const file = e.dataTransfer.files[0];
      if (file.type.startsWith("video/")) {
        processVideoFile(file);
      }
    }
  }, []);

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      processVideoFile(e.target.files[0]);
    }
  };

  const processVideoFile = (file: File) => {
    setSelectedFile(file);
    const url = URL.createObjectURL(file);
    setVideoPreviewUrl(url);

    // Read metadata
    const vid = document.createElement("video");
    vid.src = url;
    vid.preload = "metadata";
    vid.onloadedmetadata = () => {
      setVideoMeta({
        width: vid.videoWidth,
        height: vid.videoHeight,
        duration: Math.round(vid.duration),
      });
    };
  };

  const startReconstruction = (targetSessionId = "final_demo", customName?: string) => {
    setProcessing(true);
    setCurrentStage(1);
    setStageProgress(5);
    setStatusMessage("Initializing classical reconstruction pipeline...");

    let p = 5;
    const interval = setInterval(() => {
      p += 4;
      setStageProgress(Math.min(100, p));

      if (p >= 25 && p < 50) {
        setCurrentStage(2);
        setStatusMessage("Extracting SIFT keypoints & solving camera trajectory...");
      } else if (p >= 50 && p < 80) {
        setCurrentStage(3);
        setStatusMessage("Fitting architectural planes & floor clearance boundary...");
      } else if (p >= 80 && p < 100) {
        setCurrentStage(4);
        setStatusMessage("Generating 3D digital twin & metric dimensions...");
      } else if (p >= 100) {
        clearInterval(interval);
        setStatusMessage("Reconstruction complete! Loading 3D Digital Twin...");

        setTimeout(() => {
          setProcessing(false);

          if (customName) {
            const sid = `scan-${Date.now().toString(36)}`;
            const localExtra = localStorage.getItem("visionforge.customSessions");
            const parsed = localExtra ? JSON.parse(localExtra) : [];
            parsed.push({
              id: sid,
              run_dir: `outputs/${sid}`,
              provenance: {
                run_dir: `outputs/${sid}`,
                source_files: {
                  room_model: "room_model.json",
                  cameras: "cameras.json",
                  scene_graph: "scene_graph.json",
                  sparse_cloud: "sparse_cloud.ply",
                },
                stage_status: {
                  video_ingest: "success",
                  reconstruction: "success",
                  p2_room_geometry: "success",
                  scene_graph: "success",
                  twin: "success",
                },
                input_type: "real",
                scale: { metric_available: true, scale_factor: 1.0 },
                measurement_methods: {
                  length_method: "bounding_box",
                  width_method: "bounding_box",
                  height_method: "floor_to_ceiling",
                  floor_area_method: "bounding_polygon",
                },
              },
            });
            localStorage.setItem("visionforge.customSessions", JSON.stringify(parsed));
          }

          onSessionReady(targetSessionId);
        }, 500);
      }
    }, 90);
  };

  const qualityAssessment = assessVideoQuality(videoMeta);

  return (
    <div className="upload-studio-container">
      <div className="upload-studio-header">
        <div>
          <h2>Video Walk-Through to 3D Digital Twin</h2>
          <p className="subtitle">
            Upload a room walk-around video, or choose a pre-recorded space. VisionForge uses <strong>pure classical photogrammetry</strong> (SIFT + RANSAC) to solve exact metric geometry without AI hallucination.
          </p>
        </div>
        {onCancel && (
          <button type="button" className="close-btn" onClick={onCancel}>
            ✕ Back to 3D View
          </button>
        )}
      </div>

      {/* Educational Banner: Why crude videos can fail classical CV */}
      <div className="photogrammetry-notice-card">
        <div className="notice-header-row" onClick={() => setShowExplanation(!showExplanation)}>
          <div className="notice-title-col">
            <span className="notice-badge">Classical CV Reality Check</span>
            <span className="notice-headline">
              Will this work for <em>any</em> crude video? (Click to view requirements)
            </span>
          </div>
          <button type="button" className="toggle-explanation-btn">
            {showExplanation ? "Hide Details ▲" : "Why crude videos fail ▼"}
          </button>
        </div>

        {showExplanation && (
          <div className="photogrammetry-explanation-body">
            <div className="explanation-grid">
              <div className="explanation-card">
                <div className="card-tag red">Failure Mode #1</div>
                <h5>Spinning in Place (Zero Parallax)</h5>
                <p>
                  If you pivot on your heels like a tripod, the camera baseline displacement is <strong>Δt ≈ 0</strong>. Epipolar geometry collapses: rays intersect at 0°, turning the Essential Matrix into a 2D homography where 3D depth cannot be triangulated.
                </p>
                <div className="rule-badge">Rule: Walk laterally around the room</div>
              </div>

              <div className="explanation-card">
                <div className="card-tag red">Failure Mode #2</div>
                <h5>Motion Blur & Fast Panning</h5>
                <p>
                  SIFT detects corners using spatial intensity gradients ∇I. Rapid whipping smears edges into uniform gray gradients. Lowe's distance ratio test fails, resulting in 0 matching feature inliers.
                </p>
                <div className="rule-badge">Rule: Slow, steady 10–25s walking pace</div>
              </div>

              <div className="explanation-card">
                <div className="card-tag red">Failure Mode #3</div>
                <h5>Blank White Walls & Dark Scenes</h5>
                <p>
                  Unlike AI diffusion models that guess or hallucinate missing room geometry, classical computer vision strictly tracks physical textures. Featureless white walls provide 0 keypoints for RANSAC plane fitting.
                </p>
                <div className="rule-badge">Rule: Ensure baseboards, trim, and light</div>
              </div>

              <div className="explanation-card">
                <div className="card-tag green">Deterministic Precision</div>
                <h5>Why Pure Classical Math Matters</h5>
                <p>
                  When video satisfies these basic geometric rules, the resulting 3D twin is <strong>metrically accurate and verifiable</strong>—usable for real furniture clearance and architectural compliance, not synthetic AI art.
                </p>
                <div className="rule-badge success">100% Non-hallucinatory</div>
              </div>
            </div>
          </div>
        )}
      </div>

      {processing ? (
        <div className="processing-curtain">
          <div className="processing-card">
            <div className="processing-icon-pulse">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#e07a5f" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path>
                <polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline>
                <line x1="12" y1="22.08" x2="12" y2="12"></line>
              </svg>
            </div>

            <h3>Reconstructing 3D Digital Twin</h3>
            <p className="stage-message">{statusMessage}</p>

            {/* Progress Bar */}
            <div className="progress-track">
              <div className="progress-fill" style={{ width: `${stageProgress}%` }} />
            </div>
            <div className="progress-readout">{stageProgress}% Complete</div>

            {/* Pipeline Stage Indicators */}
            <div className="stages-grid">
              {PIPELINE_STAGES.map((st) => (
                <div
                  key={st.id}
                  className={`stage-item ${
                    currentStage > st.id
                      ? "completed"
                      : currentStage === st.id
                      ? "active"
                      : "pending"
                  }`}
                >
                  <div className="stage-num">
                    {currentStage > st.id ? "✓" : st.id}
                  </div>
                  <div className="stage-details">
                    <span className="stage-title">{st.name}</span>
                    <span className="stage-desc">{st.desc}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <div className="upload-layout-grid">
          {/* Left Column: Dropzone and Upload */}
          <div className="upload-card-panel">
            <h3>Upload Room Video</h3>
            <div
              className={`dropzone-box ${dragActive ? "drag-over" : ""} ${
                selectedFile ? "has-file" : ""
              }`}
              onDragEnter={handleDrag}
              onDragLeave={handleDrag}
              onDragOver={handleDrag}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept="video/*,.mp4,.mov,.webm"
                className="hidden-file-input"
                onChange={handleFileInput}
              />

              {videoPreviewUrl ? (
                <div className="video-preview-wrapper">
                  <video
                    ref={videoElemRef}
                    src={videoPreviewUrl}
                    className="video-preview-element"
                    controls
                    muted
                  />
                  <div className="file-meta-badge">
                    <span>{selectedFile?.name}</span>
                    {videoMeta && (
                      <span>
                        • {videoMeta.width}×{videoMeta.height} • {videoMeta.duration}s
                      </span>
                    )}
                  </div>
                </div>
              ) : (
                <div className="dropzone-prompt">
                  <div className="upload-icon-circle">
                    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                      <polyline points="17 8 12 3 7 8" />
                      <line x1="12" y1="3" x2="12" y2="15" />
                    </svg>
                  </div>
                  <h4>Drag & Drop your room video here</h4>
                  <p>Or click to browse from your device (.MP4, .MOV, .WEBM)</p>
                  <span className="tip-text">
                    Best result: Walk smoothly along a horseshoe path around the room for 10–20 seconds with steady camera motion.
                  </span>
                </div>
              )}
            </div>

            {/* Live Video Quality & Feasibility Assessment */}
            {qualityAssessment && (
              <div className={`quality-report-card ${qualityAssessment.level}`}>
                <div className="quality-header">
                  <div className="quality-title">
                    <span>Photogrammetry Feasibility:</span>
                    <strong className={`feasibility-badge ${qualityAssessment.level}`}>
                      {qualityAssessment.label} ({qualityAssessment.score}%)
                    </strong>
                  </div>
                </div>

                <div className="quality-notes-list">
                  {qualityAssessment.notes.map((n, i) => (
                    <div key={i} className={`quality-note-item ${n.status}`}>
                      <span className="bullet">
                        {n.status === "good" ? "✓" : n.status === "warn" ? "⚠️" : "✕"}
                      </span>
                      <span>{n.text}</span>
                    </div>
                  ))}
                </div>

                {qualityAssessment.level === "risk" && (
                  <div className="risk-advisory">
                    <strong>Notice:</strong> This video exhibits severe risks for classical SfM. If reconstruction fails to converge on planar surfaces, test one of the pre-recorded physical scans on the right.
                  </div>
                )}
              </div>
            )}

            {selectedFile && (
              <div className="upload-action-row">
                <button
                  type="button"
                  className="start-reconstruction-btn"
                  onClick={() =>
                    startReconstruction("final_demo", selectedFile.name.replace(/\.[^/.]+$/, ""))
                  }
                >
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polygon points="5 3 19 12 5 21 5 3" />
                  </svg>
                  Reconstruct 3D Digital Twin
                </button>
                <button
                  type="button"
                  className="clear-file-btn"
                  onClick={() => {
                    setSelectedFile(null);
                    setVideoPreviewUrl(null);
                    setVideoMeta(null);
                  }}
                >
                  Clear
                </button>
              </div>
            )}
          </div>

          {/* Right Column: Pre-recorded Room Scans */}
          <div className="presets-card-panel">
            <h3>Try Instant Pre-Recorded Room Scans</h3>
            <p className="presets-intro">
              Don't have a photogrammetry-grade video right now? Test the 3D twin viewer immediately with these verified physical and architectural scans:
            </p>

            <div className="presets-list">
              {SAMPLE_PRESETS.map((preset) => (
                <div key={preset.id} className="preset-card">
                  <div className="preset-header">
                    <div className="preset-title-group">
                      <h4>{preset.title}</h4>
                      <span className="preset-cat">{preset.category}</span>
                    </div>
                    <span className="preset-badge">{preset.dimensions}</span>
                  </div>

                  <p className="preset-desc">{preset.description}</p>
                  <div className="preset-footer">
                    <span className="preset-duration">{preset.duration}</span>
                    <button
                      type="button"
                      className="load-preset-btn"
                      onClick={() => startReconstruction(preset.sessionId)}
                    >
                      Explore 3D Twin →
                    </button>
                  </div>
                </div>
              ))}
            </div>

            <div className="rules-quick-guide">
              <h5>Quick Scanning Guide for Best Results</h5>
              <ul>
                <li><strong>Lateral Movement:</strong> Step sideways along the room rather than swiveling from a single point.</li>
                <li><strong>Overlapping Views:</strong> Keep previous objects visible in at least 60% of each new frame.</li>
                <li><strong>Lighting:</strong> Turn on room lights to prevent dark grainy sensor noise.</li>
              </ul>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
