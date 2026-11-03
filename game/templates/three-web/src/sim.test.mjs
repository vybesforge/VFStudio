import { step } from "./sim.js";

const body = { y: 3, vy: 0, floor: 0.5, landed: false };
for (let i = 0; i < 180; i++) step(body, 1 / 60);
if (!body.landed || body.y > 0.51) {
  console.error("THREE_SELFTEST FAIL", body);
  process.exit(1);
}
console.log("THREE_SELFTEST OK y=" + body.y.toFixed(3));
