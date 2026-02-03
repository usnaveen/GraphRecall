import { useMemo } from "react";
import { Points } from "@react-three/drei";
import * as THREE from "three";

export default function GalaxyBackground() {
  const positions = useMemo(() => {
    const count = 1200;
    const arr = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      const r = 400 * Math.cbrt(Math.random());
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      arr[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      arr[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
      arr[i * 3 + 2] = r * Math.cos(phi);
    }
    return arr;
  }, []);

  return (
    <Points positions={positions} stride={3} frustumCulled>
      <pointsMaterial size={1.2} color={new THREE.Color("#9bb4ff")} sizeAttenuation depthWrite={false} />
    </Points>
  );
}
