"use client";

/**
 * The chain strip in 3D (React Three Fiber): one block per event in a row,
 * receding slightly into depth. Selecting a row glides the strip to that
 * block and lifts it forward; the bars between neighbours are the links,
 * prev_hash → hash. A crack (the API's, or a labelled simulation) plays
 * along the strip from its block onward. Loaded through next/dynamic only
 * when WebGL is there and motion is allowed, so it never weighs on the first
 * paint. The camera itself never moves; the strip does.
 */

import { afterCrack } from "@/lib/chain";
import { Html } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import type { StripProps } from "./ChainStrip";

const GAP = 0.62;
const EASE = 0.12;

function token(name: string, fallback: string): string {
  const v = typeof window === "undefined" ? "" : getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim();
  return v ? `rgb(${v.split(/\s+/).join(",")})` : fallback;
}

const short = (h?: string | null) => (h ? `${h.slice(0, 6)}…${h.slice(-4)}` : "—");

function Strip({ events, selectedSeq, onSelect, crackSeq, visible, crackStartedAt }: StripProps & { crackStartedAt: number | null }) {
  const group = useRef<THREE.Group>(null);
  const { viewport } = useThree();
  const selIdx = useMemo(() => (selectedSeq == null ? events.length - 1 : events.findIndex((e) => e.seq === selectedSeq)), [events, selectedSeq]);
  // Nothing selected: the newest block sits at the right edge and the strip spans the width, oldest → newest.
  // A selection glides to the centre; a chain shorter than the width starts at the left edge.
  const targetX = useMemo(() => {
    const half = viewport.width / 2;
    const span = Math.max(0, events.length - 1) * GAP;
    if (span + 0.6 <= viewport.width) return -half + 0.5;
    if (selectedSeq == null) return half - 0.5 - span;
    return Math.min(-half + 0.5, Math.max(half - 0.5 - span, -(Math.max(0, selIdx) * GAP)));
  }, [viewport.width, events.length, selectedSeq, selIdx]);
  const crackIdx = useMemo(() => (crackSeq == null ? -1 : events.findIndex((e) => e.seq >= crackSeq)), [events, crackSeq]);
  const colors = useMemo(
    () => ({
      accent: new THREE.Color(token("accent", "#5eead4")),
      bad: new THREE.Color(token("bad", "#f87171")),
      line: new THREE.Color(token("line-strong", "#383e47")),
      ink: new THREE.Color(token("ink", "#edeff3")),
      muted: new THREE.Color(token("ink-faint", "#636a75")),
    }),
    [],
  );
  const mats = useRef<(THREE.MeshStandardMaterial | null)[]>([]);
  const meshes = useRef<(THREE.Mesh | null)[]>([]);

  // glide the strip so the selected block sits at the centre; lift it forward
  useFrame((state) => {
    const g = group.current;
    if (!g) return;
    g.position.x += (targetX - g.position.x) * EASE;
    const now = state.clock.elapsedTime;
    events.forEach((e, i) => {
      const m = meshes.current[i];
      const mat = mats.current[i];
      if (!m || !mat) return;
      const sel = i === selIdx;
      const z = sel ? 0.55 : 0;
      const s = sel ? 1.35 : 1;
      m.position.z += (z - m.position.z) * EASE;
      m.scale.x += (s - m.scale.x) * EASE;
      m.scale.y += (s - m.scale.y) * EASE;
      // the crack plays outward from its block: each later block turns within ~0.9 s
      const after = afterCrack(e.seq, crackSeq);
      let cracked = after;
      if (after && crackStartedAt != null) {
        const age = (performance.now() - crackStartedAt) / 1000;
        cracked = age > Math.min(0.9, (i - crackIdx) * 0.035);
      }
      const dim = visible && !visible.has(e.seq);
      const color = !e.allowed ? colors.bad : cracked ? colors.bad : colors.accent;
      mat.color.lerp(color, 0.2);
      mat.wireframe = cracked && e.allowed;
      mat.opacity += ((dim ? 0.12 : cracked && e.allowed ? 0.45 : 0.95) - mat.opacity) * 0.2;
      mat.emissiveIntensity = sel ? 0.35 + Math.sin(now * 3) * 0.08 : !e.allowed ? 0.45 : 0.12;
    });
  });

  const sel = events[selIdx];
  const prev = selIdx > 0 ? events[selIdx - 1] : undefined;

  return (
    <group ref={group} position={[targetX, 0, 0]}>
      {/* the links: a bar between every pair of neighbours */}
      {events.map((e, i) =>
        i === 0 ? null : (
          <mesh key={`l${e.seq}`} position={[(i - 0.5) * GAP, 0.02, 0]}>
            <boxGeometry args={[GAP - 0.3, 0.035, 0.035]} />
            <meshBasicMaterial color={afterCrack(e.seq, crackSeq) ? colors.bad : i === selIdx || i - 1 === selIdx ? colors.ink : colors.line} transparent opacity={afterCrack(e.seq, crackSeq) ? 0.5 : 1} />
          </mesh>
        ),
      )}
      {events.map((e, i) => (
        <mesh
          key={e.seq}
          ref={(m) => {
            meshes.current[i] = m;
          }}
          position={[i * GAP, 0.3, 0]}
          onClick={(ev) => {
            ev.stopPropagation();
            onSelect(e.seq);
          }}
          onPointerOver={() => (document.body.style.cursor = "pointer")}
          onPointerOut={() => (document.body.style.cursor = "")}
        >
          <boxGeometry args={[0.3, 0.6, 0.22]} />
          <meshStandardMaterial
            ref={(mt) => {
              mats.current[i] = mt;
            }}
            color={!e.allowed ? colors.bad : colors.accent}
            emissive={!e.allowed ? colors.bad : colors.accent}
            emissiveIntensity={0.12}
            transparent
            opacity={0.95}
            roughness={0.5}
          />
        </mesh>
      ))}
      {crackIdx >= 0 ? (
        <mesh position={[(crackIdx - 0.5) * GAP, 0.3, 0.3]} rotation={[0, 0, 0.3]}>
          <boxGeometry args={[0.05, 1.4, 0.05]} />
          <meshBasicMaterial color={colors.bad} />
        </mesh>
      ) : null}
      {sel ? (
        <Html position={[selIdx * GAP, 1.05, 0.6]} center zIndexRange={[5, 0]} style={{ pointerEvents: "none" }}>
          <div className="whitespace-nowrap rounded-xs border border-line bg-surface/95 px-2 py-1 font-mono text-2xs text-ink shadow-raised">
            <span className="text-ink-muted">#{sel.seq}</span> {sel.actor_name ?? sel.actor_id} · {sel.action}
            {!sel.allowed ? <span className="ml-1.5 font-semibold text-bad">REFUSED</span> : null}
          </div>
        </Html>
      ) : null}
      {sel && prev ? (
        <Html position={[(selIdx - 0.5) * GAP, -0.42, 0.3]} center zIndexRange={[5, 0]} style={{ pointerEvents: "none" }}>
          <div className="whitespace-nowrap rounded-xs border border-line bg-surface/95 px-2 py-0.5 font-mono text-2xs text-ink-muted shadow-raised">
            #{prev.seq} hash <span className="text-ink">{short(prev.hash)}</span> → #{sel.seq} prev_hash <span className={sel.prev_hash === prev.hash ? "text-ok" : "text-bad"}>{short(sel.prev_hash)}</span>
          </div>
        </Html>
      ) : null}
    </group>
  );
}

function Clear() {
  const { gl } = useThree();
  useEffect(() => {
    gl.setClearColor(0x000000, 0);
  }, [gl]);
  return null;
}

export default function ChainStrip3D(props: StripProps & { crackStartedAt: number | null }) {
  return (
    <Canvas className="!absolute inset-0" dpr={[1, 2]} camera={{ position: [0, 1.1, 5.2], fov: 32, near: 0.1, far: 60 }} gl={{ antialias: true, alpha: true }} aria-hidden>
      <Clear />
      <ambientLight intensity={1.5} />
      <directionalLight position={[2, 4, 5]} intensity={1.1} />
      <Strip {...props} />
    </Canvas>
  );
}
