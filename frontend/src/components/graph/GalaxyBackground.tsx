import { useRef, useMemo } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";

interface GalaxyBackgroundProps {
  count?: number;
}

export default function GalaxyBackground({ count = 8000 }: GalaxyBackgroundProps) {
  const pointsRef = useRef<THREE.Points>(null);

  const { positions, colors } = useMemo(() => {
    const positions = new Float32Array(count * 3);
    const colors = new Float32Array(count * 3);

    for (let i = 0; i < count; i++) {
      // Spread over a large, distant spherical shell so stars surround the graph
      const radius = 800 + Math.random() * 600;
      const theta = Math.random() * 2 * Math.PI;
      const phi = Math.acos(2 * Math.random() - 1);

      positions[i * 3] = radius * Math.sin(phi) * Math.cos(theta);
      positions[i * 3 + 1] = radius * Math.sin(phi) * Math.sin(theta);
      positions[i * 3 + 2] = radius * Math.cos(phi);

      // Cool cyan/teal palette with subtle variation
      const t = Math.random();
      colors[i * 3] = 0.25 + 0.15 * t;     // low red
      colors[i * 3 + 1] = 0.55 + 0.25 * t;  // green/teal
      colors[i * 3 + 2] = 0.85 + 0.10 * t;  // blue/cyan
    }

    return { positions, colors };
  }, [count]);

  useFrame((state) => {
    if (pointsRef.current) {
      // Slow rotation for subtle parallax effect
      pointsRef.current.rotation.y = state.clock.elapsedTime * 0.005;
    }
  });

  const material = useMemo(
    () =>
      new THREE.PointsMaterial({
        size: 0.8,
        transparent: true,
        depthTest: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        vertexColors: true,
        opacity: 0.35,
        sizeAttenuation: true,
      }),
    []
  );

  return (
    <points ref={pointsRef} rotation={[0, 0, 0.2]}>
      <bufferGeometry>
        <bufferAttribute
          attach="attributes-position"
          args={[positions, 3]}
        />
        <bufferAttribute
          attach="attributes-color"
          args={[colors, 3]}
        />
      </bufferGeometry>
      <primitive object={material} />
    </points>
  );
}
