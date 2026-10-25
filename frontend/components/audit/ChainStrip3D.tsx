"use client";

/**
 * The chain strip in 3D (React Three Fiber): one block per event in a row,
 * receding slightly into depth. Selecting a row glides the strip to that
 * block and lifts it forward; the bars between neighbours are the links,
 * prev_hash → hash. A crack (the API's, or a labelled simulation) plays
 * along the strip from its block onward. Loaded through next/dynamic only
 * when WebGL is there and motion is allowed, so it never weighs on the first
 * paint. The camera itself never moves; the strip does.
 *
 * The two labels (the selected event, and the hash link into it) are plain
 * elements of this component's own tree laid over the canvas, which the
 * scene moves each frame to where their anchors project. Not drei's <Html>:
 * that mounts a separate React root per label, and mounting one only while
 * something is selected unmounted those roots in the middle of React's
 * render ("Attempted to synchronously unmount a root while React was
 * already rendering"), and a teardown could then remove a node that was
 * already gone ("Failed to execute 'removeChild' on 'Node'").
 */

// react-three-fiber props (position, args, transparent, intensity…) are not DOM
// attributes; the "unknown property" rule cannot tell, hence the NOSONAR markers.

import { afterCrack } from "@/lib/chain";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { type RefObject, useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import type { StripProps } from "./ChainStrip";

const GAP = 0.62;
const EASE = 0.12;

function token(name: string, fallback: string): string {
  const v = typeof window === "undefined" ? "" : getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim();
  return v ? `rgb(${v.split(/\s+/).join(",")})` : fallback;
}

const short = (h?: string | null) => (h ? `${h.slice(0, 6)}…${h.slice(-4)}` : "—");

interface Palette {
  accent: THREE.Color;
  bad: THREE.Color;
  line: THREE.Color;
  ink: THREE.Color;
  muted: THREE.Color;
}

/** Past the crack, a block turns broken: at once, or, while a simulated crack
 * plays, outward from its block, each later block within ~0.9 s. */
function isCracked(seq: number, i: number, crackSeq: number | null, crackIdx: number, startedAt: number | null): boolean {
  if (!afterCrack(seq, crackSeq)) return false;
  if (startedAt == null) return true;
  const age = (performance.now() - startedAt) / 1000;
  return age > Math.min(0.9, (i - crackIdx) * 0.035);
}

/** Red when refused or past the crack, teal when sealed. */
function blockColor(allowed: boolean, cracked: boolean, c: Palette): THREE.Color {
  return !allowed || cracked ? c.bad : c.accent;
}

/** Faded when the filters leave it out, half-hollow past the crack, else solid. */
function blockOpacity(dim: boolean, cracked: boolean, allowed: boolean): number {
  if (dim) return 0.12;
  if (cracked && allowed) return 0.45;
  return 0.95;
}

/** The selected block breathes; a refused one glows; the rest barely. */
function blockGlow(selected: boolean, allowed: boolean, now: number): number {
  if (selected) return 0.35 + Math.sin(now * 3) * 0.08;
  return allowed ? 0.12 : 0.45;
}

/** A link past the crack is red; the two into and out of the selection are bright. */
function linkColor(cracked: boolean, nearSelection: boolean, c: Palette): THREE.Color {
  if (cracked) return c.bad;
  return nearSelection ? c.ink : c.line;
}

/** The block a label points at: the selection, or the newest when none. */
function selectedIndex(events: StripProps["events"], selectedSeq: number | null): number {
  return selectedSeq == null ? events.length - 1 : events.findIndex((e) => e.seq === selectedSeq);
}

interface Labels {
  block: RefObject<HTMLDivElement | null>;
  link: RefObject<HTMLDivElement | null>;
}

type StripSceneProps = Readonly<StripProps & { crackStartedAt: number | null; labels: Labels }>;

function Strip({ events, selectedSeq, onSelect, crackSeq, visible, crackStartedAt, labels }: StripSceneProps) {
  const group = useRef<THREE.Group>(null);
  const { viewport, camera, size } = useThree();
  const selIdx = useMemo(() => selectedIndex(events, selectedSeq), [events, selectedSeq]);
  const anchor = useMemo(() => new THREE.Vector3(), []);

  // Put a label's element where its anchor (in the strip's own coordinates)
  // lands on the canvas, hidden while the anchor is off screen.
  const place = (el: HTMLDivElement | null, g: THREE.Group, x: number, y: number, z: number) => {
    if (!el) return;
    anchor.set(x, y, z);
    g.localToWorld(anchor);
    anchor.project(camera);
    const onScreen = anchor.z < 1 && Math.abs(anchor.x) <= 1.1 && Math.abs(anchor.y) <= 1.1;
    el.style.transform = `translate(${((anchor.x + 1) / 2) * size.width}px, ${((1 - anchor.y) / 2) * size.height}px) translate(-50%, -50%)`;
    el.style.opacity = onScreen ? "1" : "0";
  };
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
      const cracked = isCracked(e.seq, i, crackSeq, crackIdx, crackStartedAt);
      const dim = visible != null && !visible.has(e.seq);
      mat.color.lerp(blockColor(e.allowed, cracked, colors), 0.2);
      mat.wireframe = cracked && e.allowed;
      mat.opacity += (blockOpacity(dim, cracked, e.allowed) - mat.opacity) * 0.2;
      mat.emissiveIntensity = blockGlow(sel, e.allowed, now);
    });
    // the labels follow the glide: the event above its block, the link below the bar into it
    g.updateMatrixWorld();
    place(labels.block.current, g, selIdx * GAP, 1.05, 0.6);
    place(labels.link.current, g, (selIdx - 0.5) * GAP, -0.42, 0.3);
  });

  return (
    <group ref={group} position={[targetX, 0, 0]} /* NOSONAR */>
      {/* the links: a bar between every pair of neighbours */}
      {events.map((e, i) =>
        i === 0 ? null : (
          <mesh key={`l${e.seq}`} position={[(i - 0.5) * GAP, 0.02, 0]} /* NOSONAR */>
            <boxGeometry args={[GAP - 0.3, 0.035, 0.035]} /* NOSONAR */ />
            <meshBasicMaterial
              color={linkColor(afterCrack(e.seq, crackSeq), i === selIdx || i - 1 === selIdx, colors)}
              transparent /* NOSONAR */
              opacity={afterCrack(e.seq, crackSeq) ? 0.5 : 1}
            />
          </mesh>
        ),
      )}
      {events.map((e, i) => (
        <mesh
          key={e.seq}
          ref={(m) => {
            meshes.current[i] = m;
          }}
          position={[i * GAP, 0.3, 0]} /* NOSONAR */
          onClick={(ev) => {
            ev.stopPropagation();
            onSelect(e.seq);
          }}
          onPointerOver={() => (document.body.style.cursor = "pointer")}
          onPointerOut={() => (document.body.style.cursor = "")}
        >
          <boxGeometry args={[0.3, 0.6, 0.22]} /* NOSONAR */ />
          <meshStandardMaterial
            ref={(mt) => {
              mats.current[i] = mt;
            }}
            color={!e.allowed ? colors.bad : colors.accent}
            emissive={!e.allowed ? colors.bad : colors.accent} /* NOSONAR */
            emissiveIntensity={0.12} /* NOSONAR */
            transparent /* NOSONAR */
            opacity={0.95}
            roughness={0.5} /* NOSONAR */
          />
        </mesh>
      ))}
      {crackIdx >= 0 ? (
        <mesh position={[(crackIdx - 0.5) * GAP, 0.3, 0.3]} rotation={[0, 0, 0.3]} /* NOSONAR */>
          <boxGeometry args={[0.05, 1.4, 0.05]} /* NOSONAR */ />
          <meshBasicMaterial color={colors.bad} />
        </mesh>
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

// Hidden (opacity 0) until the first frame has placed it, so it never flashes at the corner.
const LABEL =
  "pointer-events-none absolute left-0 top-0 z-[5] whitespace-nowrap rounded-xs border border-line bg-surface/95 font-mono text-2xs shadow-raised";

export default function ChainStrip3D(props: Readonly<StripProps & { crackStartedAt: number | null }>) {
  const block = useRef<HTMLDivElement>(null);
  const link = useRef<HTMLDivElement>(null);
  const selIdx = selectedIndex(props.events, props.selectedSeq);
  const sel = selIdx >= 0 ? props.events[selIdx] : undefined;
  const prev = selIdx > 0 ? props.events[selIdx - 1] : undefined;

  return (
    <div className="absolute inset-0">
      <Canvas className="!absolute inset-0" dpr={[1, 2]} camera={{ position: [0, 1.1, 5.2], fov: 32, near: 0.1, far: 60 }} gl={{ antialias: true, alpha: true }} aria-hidden>
        <Clear />
        <ambientLight intensity={1.5} /* NOSONAR */ />
        <directionalLight position={[2, 4, 5]} intensity={1.1} /* NOSONAR */ />
        <Strip {...props} labels={{ block, link }} />
      </Canvas>
      {sel ? (
        <div ref={block} className={`${LABEL} px-2 py-1 text-ink`} style={{ opacity: 0 }} data-testid="chain-label">
          <span className="text-ink-muted">#{sel.seq}</span> {sel.actor_name ?? sel.actor_id} · {sel.action}
          {!sel.allowed ? <span className="ml-1.5 font-semibold text-bad">REFUSED</span> : null}
        </div>
      ) : null}
      {sel && prev ? (
        <div ref={link} className={`${LABEL} px-2 py-0.5 text-ink-muted`} style={{ opacity: 0 }} data-testid="chain-link-label">
          #{prev.seq} hash <span className="text-ink">{short(prev.hash)}</span> → #{sel.seq} prev_hash{" "}
          <span className={sel.prev_hash === prev.hash ? "text-ok" : "text-bad"}>{short(sel.prev_hash)}</span>
        </div>
      ) : null}
    </div>
  );
}
