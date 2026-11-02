import * as THREE from "three";
import { step } from "./sim.js";

const canvas = document.getElementById("view");
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x02060f);
const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 50);
camera.position.set(3.2, 2.4, 4.2);
camera.lookAt(0, 0.6, 0);

scene.add(new THREE.AmbientLight(0x8f99ad, 0.6));
const sun = new THREE.DirectionalLight(0xffb000, 2);
sun.position.set(3, 6, 2);
scene.add(sun);

const floor = new THREE.Mesh(
  new THREE.CircleGeometry(3, 48),
  new THREE.MeshStandardMaterial({ color: 0x0b121d, roughness: 0.9 })
);
floor.rotation.x = -Math.PI / 2;
scene.add(floor);

const box = new THREE.Mesh(
  new THREE.BoxGeometry(0.6, 0.6, 0.6),
  new THREE.MeshStandardMaterial({ color: 0xfd6c0f, roughness: 0.45 })
);
scene.add(box);

const body = { y: 3, vy: 0, floor: 0.3, landed: false };
let last = performance.now();

function frame(now) {
  const dt = Math.min(0.05, (now - last) / 1000);
  last = now;
  step(body, dt);
  box.position.y = body.y;
  const w = canvas.clientWidth || 1;
  const h = canvas.clientHeight || 1;
  if (canvas.width !== w || canvas.height !== h) {
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  renderer.render(scene, camera);
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
