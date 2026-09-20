# VisionForge

A classical-computer-vision indoor digital twin system.

## Prototype 0 - Video Ingestion
Prototype 0 provides a simple video ingestion script to extract frames from a video and generate a contact sheet.
For detailed documentation on how to run this, see [docs/prototype_0.md](docs/prototype_0.md).

## Prototype 1 - Classical 3D Reconstruction
Prototype 1 takes the sequential frames and performs classical computer vision reconstruction (SIFT extraction, sequential matching, geometric verification, and incremental SfM) to output a sparse 3D point cloud and camera trajectories.
For detailed documentation, see [docs/prototype_1.md](docs/prototype_1.md).

## Prototype 2 - Room Geometry
Prototype 2 turns the sparse reconstructed point cloud into a clean geometric room model, detecting architectural planes (floor, ceiling, walls) and estimating room scale and dimensions.
For detailed documentation, see [docs/prototype_2.md](docs/prototype_2.md).