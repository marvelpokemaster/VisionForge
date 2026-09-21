import * as THREE from "three";

/** A small canvas-texture text label as a billboarded THREE.Sprite --
 * three.js has no built-in text mesh, and this avoids pulling in a font
 * loader just for plane id/type labels. */
export function makeTextSprite(text: string, color = "#ffffff"): THREE.Sprite {
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d")!;
  const fontSize = 48;
  ctx.font = `${fontSize}px sans-serif`;
  const metrics = ctx.measureText(text);
  const padding = 16;
  canvas.width = Math.ceil(metrics.width) + padding * 2;
  canvas.height = fontSize + padding * 2;

  ctx.font = `${fontSize}px sans-serif`;
  ctx.fillStyle = "rgba(0, 0, 0, 0.6)";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = color;
  ctx.textBaseline = "middle";
  ctx.fillText(text, padding, canvas.height / 2);

  const texture = new THREE.CanvasTexture(canvas);
  texture.needsUpdate = true;
  const material = new THREE.SpriteMaterial({ map: texture, depthTest: false, transparent: true });
  const sprite = new THREE.Sprite(material);
  const scale = 0.01;
  sprite.scale.set(canvas.width * scale, canvas.height * scale, 1);
  return sprite;
}
