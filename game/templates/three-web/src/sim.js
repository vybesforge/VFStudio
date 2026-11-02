/** Gravity and a floor. No collision library. Two bodies can overlap. */

export function step(body, dt) {
  const g = body.g ?? 9.81;
  const floor = body.floor ?? 0.5;
  body.vy -= g * dt;
  body.y += body.vy * dt;
  if (body.y < floor) {
    body.y = floor;
    body.vy = 0;
    body.landed = true;
  }
  return body;
}
