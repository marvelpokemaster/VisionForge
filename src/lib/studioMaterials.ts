import * as THREE from "three";

/**
 * Procedural architectural materials for VisionForge Studio.
 * Zero external asset dependencies: all textures and finishes are synthesized
 * on an offscreen HTML5 canvas to guarantee 100% offline reliability.
 */

let cachedWoodTexture: THREE.CanvasTexture | null = null;

export function generateOakPlankTexture(): THREE.CanvasTexture {
  if (cachedWoodTexture) return cachedWoodTexture;

  const canvas = document.createElement("canvas");
  canvas.width = 1024;
  canvas.height = 1024;
  const ctx = canvas.getContext("2d");

  if (!ctx) {
    // Fallback if 2d context unavailable
    const dummy = new THREE.DataTexture(new Uint8Array([200, 160, 120, 255]), 1, 1);
    dummy.needsUpdate = true;
    return dummy as unknown as THREE.CanvasTexture;
  }

  // Base warm honey-oak background
  ctx.fillStyle = "#c79e67";
  ctx.fillRect(0, 0, 1024, 1024);

  const numPlanks = 16;
  const plankHeight = 1024 / numPlanks;

  for (let i = 0; i < numPlanks; i++) {
    const y = i * plankHeight;

    // Subtle plank-to-plank color variation
    const toneVariation = (Math.sin(i * 12.3) + Math.cos(i * 7.1)) * 12;
    const r = Math.min(240, Math.max(160, Math.floor(199 + toneVariation)));
    const g = Math.min(210, Math.max(130, Math.floor(158 + toneVariation * 0.8)));
    const b = Math.min(170, Math.max(90, Math.floor(103 + toneVariation * 0.6)));

    ctx.fillStyle = `rgb(${r}, ${g}, ${b})`;
    ctx.fillRect(0, y, 1024, plankHeight);

    // Subtle wood grain lines along plank direction
    ctx.strokeStyle = `rgba(130, 85, 45, 0.12)`;
    ctx.lineWidth = 1.2;
    for (let gIdx = 0; gIdx < 12; gIdx++) {
      const lineY = y + (gIdx * plankHeight) / 12 + Math.sin(gIdx + i) * 3;
      ctx.beginPath();
      ctx.moveTo(0, lineY);
      ctx.bezierCurveTo(
        256,
        lineY + Math.sin(i + gIdx) * 4,
        768,
        lineY - Math.cos(i + gIdx) * 4,
        1024,
        lineY
      );
      ctx.stroke();
    }

    // Horizontal plank seam (shadow and highlight bevel)
    ctx.strokeStyle = "rgba(45, 25, 12, 0.45)";
    ctx.lineWidth = 2.0;
    ctx.beginPath();
    ctx.moveTo(0, y + plankHeight - 1);
    ctx.lineTo(1024, y + plankHeight - 1);
    ctx.stroke();

    ctx.strokeStyle = "rgba(255, 240, 210, 0.15)";
    ctx.lineWidth = 1.0;
    ctx.beginPath();
    ctx.moveTo(0, y + plankHeight);
    ctx.lineTo(1024, y + plankHeight);
    ctx.stroke();
  }

  // Vertical staggered board joints
  ctx.strokeStyle = "rgba(45, 25, 12, 0.5)";
  ctx.lineWidth = 2.0;
  for (let i = 0; i < numPlanks; i++) {
    const y = i * plankHeight;
    const offset = (i % 3) * 340 + 120;
    for (let x = offset; x < 1024; x += 512) {
      ctx.beginPath();
      ctx.moveTo(x, y);
      ctx.lineTo(x, y + plankHeight);
      ctx.stroke();
    }
  }

  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(3, 3);
  texture.anisotropy = 4;
  texture.needsUpdate = true;

  cachedWoodTexture = texture;
  return texture;
}

export function createWoodFloorMaterial(): THREE.MeshStandardMaterial {
  const texture = generateOakPlankTexture();
  return new THREE.MeshStandardMaterial({
    map: texture,
    roughness: 0.38,
    metalness: 0.05,
    side: THREE.DoubleSide,
  });
}

export function createPlasterWallMaterial(selected = false): THREE.MeshStandardMaterial {
  return new THREE.MeshStandardMaterial({
    color: selected ? 0xffdfba : 0xf2ece4,
    roughness: 0.85,
    metalness: 0.02,
    transparent: true,
    opacity: selected ? 0.95 : 0.75,
    side: THREE.DoubleSide,
    depthWrite: true,
  });
}

export function createCeilingMaterial(): THREE.MeshStandardMaterial {
  return new THREE.MeshStandardMaterial({
    color: 0x93b5c6,
    roughness: 0.9,
    metalness: 0.0,
    transparent: true,
    opacity: 0.25,
    side: THREE.DoubleSide,
    depthWrite: false,
  });
}

export function createFurnitureBoxMaterial(colorHex: string, valid = true): THREE.MeshStandardMaterial {
  const baseColor = valid ? colorHex : "#e76f51";
  return new THREE.MeshStandardMaterial({
    color: baseColor,
    roughness: 0.35,
    metalness: 0.15,
    transparent: true,
    opacity: valid ? 0.88 : 0.75,
  });
}

export function disposeStudioMaterials(): void {
  if (cachedWoodTexture) {
    cachedWoodTexture.dispose();
    cachedWoodTexture = null;
  }
}
