"use client";

/**
 * The 3D document stack (React Three Fiber). Loaded only when a run starts,
 * through next/dynamic with ssr: false, so it never weighs on the first paint.
 * Card faces are drawn on a canvas with system fonts: no font or texture is
 * fetched, so it works offline.
 */

// react-three-fiber props (position, args, transparent, intensity…) are not DOM
// attributes; the "unknown property" rule cannot tell, hence the NOSONAR markers.

import { Canvas, useFrame } from "@react-three/fiber";
import { RoundedBox } from "@react-three/drei";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { CARD_KINDS, CARDS, FOUND_INDEX, type StackProps } from "./DocumentStack";

/** A token from globals.css ("10 11 13") as a three.js colour. */
function token(name: string, fallback: string): THREE.Color {
  const v = typeof window === "undefined" ? "" : getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim();
  return new THREE.Color(v ? `rgb(${v.split(/\s+/).join(",")})` : fallback);
}

function faceTexture(kind: string, found: boolean, label: string | null | undefined): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  c.width = 256;
  c.height = 360;
  const g = c.getContext("2d")!;
  const css = (n: string) => `rgb(${getComputedStyle(document.documentElement).getPropertyValue(`--${n}`).trim().split(/\s+/).join(",")})`;
  g.fillStyle = css("raised");
  g.fillRect(0, 0, 256, 360);
  g.fillStyle = css("ink-soft");
  g.font = "600 22px system-ui, sans-serif";
  g.fillText(kind.toUpperCase(), 22, 44);
  for (let i = 0; i < 9; i++) {
    g.fillStyle = found && i === 3 ? css("warn") : css("line-strong");
    g.fillRect(22, 74 + i * 26, i % 3 === 2 ? 140 : 210, 10);
  }
  if (found && label) {
    g.fillStyle = css("ink");
    g.font = "500 17px system-ui, sans-serif";
    g.fillText(label.length > 24 ? `${label.slice(0, 23)}…` : label, 22, 330);
  }
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 4;
  return t;
}

function Card({ index, mode, label, onLanded }: { index: number; mode: StackProps["mode"]; label?: string | null; onLanded?: () => void }) {
  const ref = useRef<THREE.Group>(null);
  const mat = useRef<THREE.MeshStandardMaterial>(null);
  const found = index === FOUND_INDEX;
  const n = CARD_KINDS.length;
  const tex = useMemo(() => faceTexture(CARD_KINDS[index], found, label), [index, found, label]);
  const landed = useRef(false);
  const born = useRef<number | null>(null);
  useEffect(() => () => tex.dispose(), [tex]);

  useFrame((state, dt) => {
    const g = ref.current;
    if (!g) return;
    if (born.current == null) born.current = state.clock.elapsedTime;
    const age = state.clock.elapsedTime - born.current;
    const k = 1 - Math.pow(0.0015, dt); // frame-rate independent ease
    const a = (index - (n - 1) / 2) / n; // -0.5..0.5 across the fan
    const intro = Math.min(1, Math.max(0, (age - index * 0.05) / 0.6));

    // a gentle arc that fits a single document pane
    let tx = Math.sin(a * Math.PI * 0.8) * 0.8 * intro;
    let ty = -Math.abs(a) * 0.35 * intro + Math.sin(state.clock.elapsedTime * 1.4 + index) * 0.03;
    let tz = -Math.cos(a * Math.PI * 0.8) * 0.6 * intro + index * 0.02;
    let ry = -a * 1.2 * intro;
    let opacity = 1;
    if (mode === "found") {
      if (found) {
        tx = 0;
        ty = 0.1;
        tz = 1.4;
        ry = 0;
      } else {
        opacity = 0.15;
        tz -= 0.6;
      }
    }
    g.position.x += (tx - g.position.x) * k;
    g.position.y += (ty - g.position.y) * k;
    g.position.z += (tz - g.position.z) * k;
    g.rotation.y += (ry - g.rotation.y) * k;
    if (mat.current) mat.current.opacity += (opacity - mat.current.opacity) * k;

    if (mode === "found" && found && !landed.current && Math.abs(g.position.z - tz) < 0.05) {
      landed.current = true;
      onLanded?.();
    }
  });

  return (
    <group ref={ref}>
      <RoundedBox args={[1.1, 1.55, 0.02]} radius={0.04} smoothness={2}>
        <meshStandardMaterial ref={mat} map={tex} transparent roughness={0.6} metalness={0} /* NOSONAR */ />
      </RoundedBox>
      {found && mode === "found" ? (
        <mesh position={[0, 0, -0.02]} /* NOSONAR */>
          <planeGeometry args={[1.26, 1.71]} /* NOSONAR */ />
          <meshBasicMaterial color={token("accent", "white")} transparent opacity={0.35} /* NOSONAR */ />
        </mesh>
      ) : null}
    </group>
  );
}

export default function DocumentStack3D({ mode, foundLabel, onLanded }: StackProps) {
  return (
    <Canvas
      className="!absolute inset-0"
      dpr={[1, 2]}
      camera={{ position: [0, 0.15, 4.8], fov: 40 }}
      gl={{ antialias: true, alpha: true }}
      aria-hidden
    >
      <ambientLight intensity={2.2} /* NOSONAR */ />
      <directionalLight position={[2, 3, 4]} intensity={1.2} /* NOSONAR */ />
      {CARDS.map(({ id }, i) => (
        <Card key={id} index={i} mode={mode} label={i === FOUND_INDEX ? foundLabel : null} onLanded={i === FOUND_INDEX ? onLanded : undefined} />
      ))}
    </Canvas>
  );
}
