"use client";

import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame, type ThreeEvent } from "@react-three/fiber";
import { OrbitControls, ContactShadows, Environment } from "@react-three/drei";
import * as THREE from "three";
import type { PartMeshId } from "../mock-data";

type Common = {
  selectedMeshId: PartMeshId | null;
  highlightedMeshIds: PartMeshId[];
  onSelect: (id: PartMeshId | null) => void;
};

// ──────────────────────────────────────────────
// 平面図(10tアームロール CCA101*-20)を元に、各部品を
// プログラムで立体に起こして組み上げる。
// 1つの「部品グループ」= 1つの meshId。クリックでばらける。
// 設計座標: X=前(0)→後(8)、Y=上、Z=幅。地面 Y=0。
// ──────────────────────────────────────────────

const DESIGN_SCALE = 0.5;
const CENTER = new THREE.Vector3(4.0, 1.05, 0); // 車両中心(設計座標)
const EXPLODE_DIST = 1.9; // 分解時に外へ逃がす距離(設計座標)

const SELECT_COLOR = 0xfbbf24;
const HILITE_COLOR = 0x3b82f6;

// ── ベースマテリアル ──
const M = {
  cabBody: new THREE.MeshStandardMaterial({ color: 0xeef2f6, metalness: 0.35, roughness: 0.4 }),
  cabGlass: new THREE.MeshStandardMaterial({ color: 0x1b2733, metalness: 0.6, roughness: 0.1 }),
  cabTrim: new THREE.MeshStandardMaterial({ color: 0x2a2f36, metalness: 0.5, roughness: 0.5 }),
  frame: new THREE.MeshStandardMaterial({ color: 0x3a4250, metalness: 0.65, roughness: 0.5 }),
  subframe: new THREE.MeshStandardMaterial({ color: 0x2c333d, metalness: 0.7, roughness: 0.5 }),
  arm: new THREE.MeshStandardMaterial({ color: 0x4f6b8a, metalness: 0.55, roughness: 0.45 }),
  hook: new THREE.MeshStandardMaterial({ color: 0xb9c2cc, metalness: 0.85, roughness: 0.3 }),
  barrel: new THREE.MeshStandardMaterial({ color: 0x6b7480, metalness: 0.8, roughness: 0.35 }),
  rod: new THREE.MeshStandardMaterial({ color: 0xd7dde3, metalness: 0.95, roughness: 0.12 }),
  tank: new THREE.MeshStandardMaterial({ color: 0x394150, metalness: 0.6, roughness: 0.4 }),
  pump: new THREE.MeshStandardMaterial({ color: 0x556070, metalness: 0.8, roughness: 0.3 }),
  valve: new THREE.MeshStandardMaterial({ color: 0x8a6a3a, metalness: 0.7, roughness: 0.4 }),
  pipe: new THREE.MeshStandardMaterial({ color: 0x9aa4b0, metalness: 0.85, roughness: 0.25 }),
  wire: new THREE.MeshStandardMaterial({ color: 0x20242b, metalness: 0.3, roughness: 0.7 }),
  tire: new THREE.MeshStandardMaterial({ color: 0x16191e, metalness: 0.1, roughness: 0.85 }),
  hub: new THREE.MeshStandardMaterial({ color: 0x9099a3, metalness: 0.9, roughness: 0.25 }),
  acc: new THREE.MeshStandardMaterial({ color: 0xc2410c, metalness: 0.4, roughness: 0.55 }),
};

// ── プリミティブ生成ヘルパー(マテリアルは都度clone=部品別ハイライト用) ──
function box(w: number, h: number, d: number, mat: THREE.Material, pos: [number, number, number]) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat.clone());
  m.position.set(...pos);
  m.castShadow = true;
  return m;
}
function cylZ(r: number, len: number, mat: THREE.Material, pos: [number, number, number], seg = 18) {
  // Z軸方向の円柱(車輪・ローラー向け)
  const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, len, seg), mat.clone());
  m.rotation.x = Math.PI / 2;
  m.position.set(...pos);
  m.castShadow = true;
  return m;
}
function cylY(r: number, len: number, mat: THREE.Material, pos: [number, number, number], seg = 16) {
  const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, len, seg), mat.clone());
  m.position.set(...pos);
  m.castShadow = true;
  return m;
}

// 油圧シリンダー(barrel+rod)。+X方向にロッドが出る向きのグループを返す。
function hydraulic(barrelLen: number, barrelR: number, rodLen: number, rodR: number) {
  const g = new THREE.Group();
  const barrel = new THREE.Mesh(new THREE.CylinderGeometry(barrelR, barrelR, barrelLen, 18), M.barrel.clone());
  barrel.rotation.z = Math.PI / 2;
  barrel.position.x = barrelLen / 2;
  barrel.castShadow = true;
  g.add(barrel);
  const rod = new THREE.Mesh(new THREE.CylinderGeometry(rodR, rodR, rodLen, 14), M.rod.clone());
  rod.rotation.z = Math.PI / 2;
  rod.position.x = barrelLen + rodLen / 2;
  rod.castShadow = true;
  g.add(rod);
  // クレビス(根元/先端)
  const c1 = box(0.12, barrelR * 1.6, barrelR * 1.6, M.barrel, [-0.02, 0, 0]);
  const c2 = box(0.12, rodR * 2.2, rodR * 2.2, M.rod, [barrelLen + rodLen + 0.04, 0, 0]);
  g.add(c1, c2);
  return g;
}

// 2点間に円柱を渡す(配管・リンク用)
function strut(a: THREE.Vector3, b: THREE.Vector3, r: number, mat: THREE.Material) {
  const dir = new THREE.Vector3().subVectors(b, a);
  const len = dir.length();
  const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, len, 12), mat.clone());
  m.position.copy(a).addScaledVector(dir, 0.5);
  m.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.clone().normalize());
  m.castShadow = true;
  return m;
}

function wheel(x: number, z: number) {
  const g = new THREE.Group();
  g.add(cylZ(0.52, 0.34, M.tire, [x, 0.52, z], 22));
  g.add(cylZ(0.22, 0.36, M.hub, [x, 0.52, z], 16));
  // ホイールナット風
  for (let i = 0; i < 6; i++) {
    const a = (i / 6) * Math.PI * 2;
    g.add(cylZ(0.03, 0.4, M.frame, [x + Math.cos(a) * 0.13, 0.52 + Math.sin(a) * 0.13, z], 8));
  }
  return g;
}

type PartEntry = {
  group: THREE.Group;
  meshId: PartMeshId;
  home: THREE.Vector3;
  exploded: THREE.Vector3;
};

function buildArmRoll(): { root: THREE.Group; parts: PartEntry[] } {
  const root = new THREE.Group();
  const groups: Record<string, THREE.Group> = {};
  const add = (id: PartMeshId, ...objs: THREE.Object3D[]) => {
    if (!groups[id]) {
      groups[id] = new THREE.Group();
      groups[id].name = id;
      root.add(groups[id]);
    }
    groups[id].add(...objs);
  };

  // ── キャブ(運転席) cab ──
  add("cab", box(1.8, 1.55, 2.0, M.cabBody, [1.3, 1.85, 0]));
  add("cab", box(1.82, 0.5, 1.85, M.cabGlass, [1.35, 2.25, 0])); // フロント上ガラス帯
  add("cab", box(0.05, 0.7, 1.7, M.cabGlass, [0.42, 1.95, 0])); // 正面ガラス
  add("cab", box(1.7, 0.18, 2.05, M.cabTrim, [1.35, 1.08, 0])); // 下端
  add("cab", box(0.2, 0.5, 0.12, M.cabTrim, [0.45, 1.95, 0.78])); // ミラー左
  add("cab", box(0.2, 0.5, 0.12, M.cabTrim, [0.45, 1.95, -0.78])); // ミラー右
  add("cab", box(1.0, 0.18, 1.6, M.acc, [1.3, 2.66, 0])); // 屋根灯バー(警告灯)
  add("cab", box(0.6, 0.25, 2.1, M.cabTrim, [0.2, 0.7, 0])); // フロントバンパー

  // ── シャシ・フレーム(13 フレームSETG) frame ──
  for (const z of [0.42, -0.42]) {
    add("frame", box(5.8, 0.24, 0.14, M.frame, [4.8, 1.0, z])); // メインレール
  }
  // クロスメンバー
  for (const x of [2.4, 3.6, 4.8, 6.0, 7.2]) {
    add("frame", box(0.12, 0.16, 0.84, M.frame, [x, 1.0, 0]));
  }
  // アームロール用サブフレーム(レール上)
  for (const z of [0.34, -0.34]) {
    add("frame", box(5.4, 0.14, 0.16, M.subframe, [4.9, 1.18, z]));
  }
  // 後端ローラー(コンテナ摺動)
  add("frame", cylZ(0.16, 1.0, M.hub, [7.55, 1.2, 0], 16));
  // 燃料タンク(シャシ付属)
  add("frame", cylY(0.28, 0.9, M.tank, [3.0, 0.78, -0.62]));

  // ── タイヤ(前・後タンデム) ──
  add("wheel-front", wheel(1.3, 0.95), wheel(1.3, -0.95));
  add("wheel-rear", wheel(6.0, 0.95), wheel(7.0, 0.95), wheel(6.0, -0.95), wheel(7.0, -0.95));

  // ── アームASSY(10-1/10-2) arm ──
  // 水平メインビーム
  add("arm", box(4.2, 0.26, 0.3, M.arm, [5.0, 1.42, 0]));
  // フック支柱(前方で立ち上がる)
  add("arm", box(0.3, 1.5, 0.3, M.arm, [3.05, 2.05, 0]));
  // 立ち上がり斜材
  add("arm", strut(new THREE.Vector3(3.2, 1.45, 0), new THREE.Vector3(3.05, 2.7, 0), 0.12, M.arm));
  // ビーム左右補強
  for (const z of [0.16, -0.16]) add("arm", box(4.0, 0.12, 0.06, M.subframe, [5.0, 1.42, z]));

  // ── ロック&フック(11) hook ──
  add("hook", box(0.34, 0.34, 0.5, M.hook, [3.0, 2.78, 0])); // フック頭
  add("hook", box(0.2, 0.55, 0.2, M.hook, [2.78, 2.55, 0])); // 前傾フック
  add("hook", box(0.26, 0.2, 0.6, M.hook, [2.78, 2.3, 0])); // ロック爪

  // ── リフトCYL.ASSY(03) lift-cyl ── 後方ピボット→アーム下面、左右2本
  for (const z of [0.26, -0.26]) {
    const cyl = hydraulic(1.5, 0.13, 1.0, 0.07);
    // 根元(6.9,1.05)→先端方向(4.6,1.5) へ向ける
    const a = new THREE.Vector3(6.9, 1.08, z);
    const b = new THREE.Vector3(4.7, 1.5, z);
    cyl.position.copy(a);
    cyl.quaternion.setFromUnitVectors(new THREE.Vector3(1, 0, 0), b.clone().sub(a).normalize());
    add("lift-cyl", cyl);
  }

  // ── スライドCYL.ASSY(04) slide-cyl ── フレーム中央、水平1本
  {
    const cyl = hydraulic(1.4, 0.12, 0.9, 0.06);
    const a = new THREE.Vector3(3.7, 1.16, 0.0);
    cyl.position.copy(a);
    add("slide-cyl", cyl); // +X水平
  }

  // ── コンテナロックCYL.ASSY(06) container-lock-cyl ── 前方の短いシリンダー
  {
    const cyl = hydraulic(0.5, 0.08, 0.35, 0.045);
    const a = new THREE.Vector3(3.25, 1.12, 0.5);
    cyl.position.copy(a);
    cyl.rotation.y = Math.PI / 2;
    add("container-lock-cyl", cyl);
  }

  // ── ジャッキCYL.ASSY(05) jack-cyl ── 後端、垂直2本(ロッド下向き)
  for (const z of [0.7, -0.7]) {
    const cyl = hydraulic(0.7, 0.09, 0.55, 0.05);
    const a = new THREE.Vector3(7.45, 1.05, z);
    cyl.position.copy(a);
    cyl.quaternion.setFromUnitVectors(new THREE.Vector3(1, 0, 0), new THREE.Vector3(0, -1, 0));
    add("jack-cyl", cyl);
  }

  // ── ジャッキSETG(12) jack ── 後端アウトリガー脚+接地パッド
  for (const z of [0.72, -0.72]) {
    add("jack", box(0.16, 0.7, 0.16, M.subframe, [7.6, 0.5, z]));
    add("jack", box(0.5, 0.1, 0.34, M.frame, [7.6, 0.12, z])); // 接地パッド
  }

  // ── ポンプSETG(01)/プランジャポンプ(07) pump ── フレーム上の油圧ポンプ
  add("pump", cylY(0.18, 0.5, M.pump, [2.55, 1.3, 0.5]));
  add("pump", box(0.4, 0.3, 0.4, M.pump, [2.55, 1.05, 0.5]));
  add("pump", cylZ(0.1, 0.3, M.hub, [2.55, 1.3, 0.62], 12));

  // ── コントロールバルブASSY(08) control-valve ──
  add("control-valve", box(0.46, 0.3, 0.34, M.valve, [2.7, 1.12, -0.4]));
  for (let i = 0; i < 3; i++) add("control-valve", cylY(0.025, 0.3, M.rod, [2.6 + i * 0.1, 1.4, -0.4], 8)); // レバー

  // ── オイルリザーバASSY(09) oil-tank ── フレーム側面の油タンク
  add("oil-tank", box(0.7, 0.55, 0.34, M.tank, [3.1, 1.35, 0.6]));
  add("oil-tank", cylY(0.04, 0.18, M.pipe, [3.1, 1.68, 0.6], 10)); // 注入口

  // ── パイピング(02-1/02-2) piping ── ポンプ→各シリンダーの配管
  add("piping", strut(new THREE.Vector3(2.6, 1.25, 0.5), new THREE.Vector3(3.7, 1.2, 0.2), 0.04, M.pipe));
  add("piping", strut(new THREE.Vector3(3.7, 1.2, 0.2), new THREE.Vector3(6.6, 1.15, 0.26), 0.04, M.pipe));
  add("piping", strut(new THREE.Vector3(2.7, 1.2, -0.4), new THREE.Vector3(6.6, 1.15, -0.26), 0.04, M.pipe));
  add("piping", strut(new THREE.Vector3(3.1, 1.3, 0.55), new THREE.Vector3(7.4, 1.1, 0.7), 0.035, M.pipe));

  // ── 電装(14) wiring ── キャブ後ろの配線・コネクタBOX
  add("wiring", box(0.24, 0.3, 0.22, M.wire, [2.3, 1.55, -0.55]));
  add("wiring", strut(new THREE.Vector3(2.3, 1.5, -0.5), new THREE.Vector3(2.3, 1.1, 0.0), 0.03, M.wire));
  add("wiring", strut(new THREE.Vector3(2.3, 1.4, -0.5), new THREE.Vector3(7.3, 1.05, -0.6), 0.025, M.wire));

  // ── アクセサリ(15) accessory ── 工具箱
  add("accessory", box(0.5, 0.34, 0.7, M.acc, [4.3, 0.8, -0.6]));

  // ── 各グループの分解先を計算 ──
  const parts: PartEntry[] = [];
  for (const [id, g] of Object.entries(groups)) {
    g.traverse((o) => (o.userData.partMeshId = id));
    const box3 = new THREE.Box3().setFromObject(g);
    const c = box3.getCenter(new THREE.Vector3());
    const dir = c.clone().sub(CENTER);
    if (dir.lengthSq() < 1e-3) dir.set(0, 1, 0);
    dir.y = Math.max(dir.y, 0) + 0.5; // 上にも逃がす
    dir.normalize();
    parts.push({
      group: g,
      meshId: id as PartMeshId,
      home: new THREE.Vector3(0, 0, 0),
      exploded: dir.multiplyScalar(EXPLODE_DIST),
    });
  }
  return { root, parts };
}

function ArmRoll({ selectedMeshId, highlightedMeshIds, onSelect }: Common) {
  const built = useMemo(() => buildArmRoll(), []);
  const rootRef = useRef<THREE.Group>(null);

  useFrame(() => {
    const anySel = selectedMeshId != null;
    for (const p of built.parts) {
      const sel = selectedMeshId === p.meshId;
      p.group.position.lerp(sel ? p.exploded : p.home, 0.16);
    }
    built.root.traverse((o) => {
      const mat = (o as THREE.Mesh).material as THREE.MeshStandardMaterial | undefined;
      if (!mat || mat.opacity === undefined) return;
      const mid = o.userData.partMeshId as PartMeshId | undefined;
      const isSel = anySel && mid === selectedMeshId;
      const targetOp = anySel && !isSel ? 0.16 : 1;
      mat.transparent = targetOp < 0.99;
      mat.opacity = THREE.MathUtils.lerp(mat.opacity, targetOp, 0.2);
      mat.depthWrite = mat.opacity > 0.8;
      if (mat.emissive) {
        if (isSel) {
          mat.emissive.setHex(SELECT_COLOR);
          mat.emissiveIntensity = 0.5;
        } else if (!anySel && mid && highlightedMeshIds.includes(mid)) {
          mat.emissive.setHex(HILITE_COLOR);
          mat.emissiveIntensity = 0.45;
        } else {
          mat.emissiveIntensity = 0;
        }
      }
    });
  });

  return (
    <group
      ref={rootRef}
      scale={DESIGN_SCALE}
      position={[-CENTER.x * DESIGN_SCALE, 0, 0]}
      onClick={(e: ThreeEvent<MouseEvent>) => {
        e.stopPropagation();
        const mid = (e.object.userData?.partMeshId as PartMeshId) ?? null;
        if (mid) onSelect(mid);
      }}
      onPointerMissed={() => onSelect(null)}
    >
      <primitive object={built.root} />
    </group>
  );
}

export function ArmRollModel(props: Common) {
  return (
    <div className="relative h-full w-full">
      <Canvas
        shadows
        dpr={[1, 2]}
        camera={{ position: [5.5, 3.4, 7], fov: 42 }}
        gl={{ antialias: true, alpha: true }}
      >
        <color attach="background" args={["#0c1018"]} />
        <fog attach="fog" args={["#0c1018", 18, 42]} />
        <ambientLight intensity={0.5} />
        <directionalLight position={[6, 9, 5]} intensity={1.1} castShadow />
        <directionalLight position={[-6, 5, -4]} intensity={0.4} />

        <Suspense fallback={null}>
          <Environment preset="city" />
          <ArmRoll {...props} />
          <ContactShadows
            position={[0, 0, 0]}
            opacity={0.5}
            scale={14}
            blur={2.4}
            far={4}
            resolution={1024}
            color="#000000"
          />
        </Suspense>

        <OrbitControls
          makeDefault
          target={[0, 0.6, 0]}
          enablePan={false}
          minDistance={2.5}
          maxDistance={20}
          minPolarAngle={Math.PI / 9}
          maxPolarAngle={Math.PI / 2.05}
        />
      </Canvas>
    </div>
  );
}
