"use client";

/**
 * The 3D document stack (React Three Fiber). Loaded only when a run starts,
 * through next/dynamic with ssr: false, so it never weighs on the first paint.
 *
 * Card faces are the case's own page renders when the API has them (the
 * invoice, the lease page, the email); a kind without one is drawn on a
 * canvas with system fonts, so the stack still works offline and before the
 * images arrive. The cards throw a contact shadow onto a dark stage.
 */

// react-three-fiber props (position, args, transparent, intensity…) are not DOM
// attributes; the "unknown property" rule cannot tell, hence the NOSONAR markers.

import { Canvas, useFrame } from "@react-three/fiber";
import { ContactShadows, RoundedBox } from "@react-three/drei";
import { useEffect, useMemo, useRef, useState } from "react";
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
  c.height = 332;
  const g = c.getContext("2d")!;
  const css = (n: string) => `rgb(${getComputedStyle(document.documentElement).getPropertyValue(`--${n}`).trim().split(/\s+/).join(",")})`;
  g.fillStyle = css("raised");
  g.fillRect(0, 0, 256, 332);
  g.fillStyle = css("ink-soft");
  g.font = "600 22px system-ui, sans-serif";
  g.fillText(kind.toUpperCase(), 22, 44);
  for (let i = 0; i < 9; i++) {
    g.fillStyle = found && i === 3 ? css("warn") : css("line-strong");
    g.fillRect(22, 74 + i * 24, i % 3 === 2 ? 140 : 210, 10);
  }
  if (found && label) {
    g.fillStyle = css("ink");
    g.font = "500 17px system-ui, sans-serif";
    g.fillText(label.length > 24 ? `${label.slice(0, 23)}…` : label, 22, 310);
  }
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 4;
  return t;
}

/** The page render as a texture; null until it loads, and null for good if it will not (the drawn face stays). */
function usePageTexture(url: string | undefined): THREE.Texture | null {
  const [tex, setTex] = useState<THREE.Texture | null>(null);
  useEffect(() => {
    if (!url) return;
    let live = true;
    const loader = new THREE.TextureLoader();
    // the API's page images need the session cookie; same-origin behind the rewrite, with credentials across ports
    loader.setCrossOrigin("use-credentials");
    loader.load(
      url,
      (t) => {
        if (!live) return t.dispose();
        t.colorSpace = THREE.SRGBColorSpace;
        t.anisotropy = 8;
        setTex(t);
      },
      undefined,
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, [url]);
  useEffect(() => () => tex?.dispose(), [tex]);
  return tex;
}

function Card({ index, mode, label, image, onLanded }: { index: number; mode: StackProps["mode"]; label?: string | null; image?: string; onLanded?: () => void }) {
  const ref = useRef<THREE.Group>(null);
  const mat = useRef<THREE.MeshStandardMaterial>(null);
  const found = index === FOUND_INDEX;
  const n = CARD_KINDS.length;
  const drawn = useMemo(() => faceTexture(CARD_KINDS[index], found, label), [index, found, label]);
  const page = usePageTexture(image);
  const landed = useRef(false);
  const born = useRef<number | null>(null);
  useEffect(() => () => drawn.dispose(), [drawn]);

  useFrame((state, dt) => {
    const g = ref.current;
    if (!g) return;
    if (born.current == null) born.current = state.clock.elapsedTime;
    const age = state.clock.elapsedTime - born.current;
    const k = 1 - Math.pow(0.0015, dt); // frame-rate independent ease
    const a = (index - (n - 1) / 2) / n; // -0.5..0.5 across the fan
    const intro = Math.min(1, Math.max(0, (age - index * 0.07) / 0.8));

    // a gentle arc that fits a single document pane; the pass reads slowly
    let tx = Math.sin(a * Math.PI * 0.8) * 0.85 * intro;
    let ty = -Math.abs(a) * 0.3 * intro + Math.sin(state.clock.elapsedTime * 1.1 + index) * 0.03;
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
      <RoundedBox args={[1.1, 1.42, 0.02]} radius={0.03} smoothness={2} castShadow /* NOSONAR */>
        <meshStandardMaterial ref={mat} map={page ?? drawn} transparent roughness={0.7} metalness={0} /* NOSONAR */ />
      </RoundedBox>
      {found && mode === "found" ? (
        <mesh position={[0, 0, -0.02]} /* NOSONAR */>
          <planeGeometry args={[1.24, 1.56]} /* NOSONAR */ />
          <meshBasicMaterial color={token("accent", "white")} transparent opacity={0.35} /* NOSONAR */ />
        </mesh>
      ) : null}
    </group>
  );
}

export default function DocumentStack3D({ mode, foundLabel, onLanded, textures }: StackProps) {
  return (
    <Canvas
      className="!absolute inset-0"
      dpr={[1, 2]}
      camera={{ position: [0, 0.15, 4.8], fov: 40 }}
      gl={{ antialias: true, alpha: true }}
      shadows
      aria-hidden
    >
      {/* pages are paper: lit bright so they read white against the stage */}
      <ambientLight intensity={2.8} /* NOSONAR */ />
      <directionalLight position={[2, 3, 4]} intensity={1.2} castShadow /* NOSONAR */ />
      {CARDS.map(({ id, kind }, i) => (
        <Card key={id} index={i} mode={mode} image={textures?.[kind]} label={i === FOUND_INDEX ? foundLabel : null} onLanded={i === FOUND_INDEX ? onLanded : undefined} />
      ))}
      {/* the stage: the cards sit on it, their shadows pooling beneath */}
      <ContactShadows position={[0, -1.05, 0]} opacity={0.55} scale={6} blur={2.4} far={2.6} color="#000000" /* NOSONAR */ />
    </Canvas>
  );
}
