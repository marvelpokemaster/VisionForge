# VisionForge

A classical-computer-vision indoor digital twin system.

## Prototype 0 - Video Ingestion
Prototype 0 provides a simple video ingestion script to extract frames from a video and generate a contact sheet.
For detailed documentation on how to run this, see [docs/prototype_0.md](docs/prototype_0.md).

## Prototype 1 - Classical 3D Reconstruction
Prototype 1 takes the sequential frames and performs classical computer vision reconstruction (SIFT extraction, sequential matching, geometric verification, and incremental SfM) to output a sparse 3D point cloud and camera trajectories.
For detailed documentation, see [docs/prototype_1.md](docs/prototype_1.md).