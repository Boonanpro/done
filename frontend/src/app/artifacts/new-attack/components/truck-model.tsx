"use client";

import { Suspense, useEffect, useState } from "react";
import { Canvas, useFrame, type ThreeEvent } from "@react-three/fiber";
import {
  OrbitControls,
  Stage,
  useGLTF,
  ContactShadows,
} from "@react-three/drei";
import * as THREE from "three";
import type { PartMeshId } from "../mock-data";

type Common = {
  selectedMeshId: PartMeshId | null;
  highlightedMeshIds: PartMeshId[];
  onSelect: (id: PartMeshId | null) => void;
};

const MODEL_URL = "/models/garbage_truck/scene.gltf";

// GLBノード名 → 新明和の部品(meshId)。位置と名前から対応づけ。
const PART_NODES: Record<string, PartMeshId> = {
  // キャブ（運転席まわり・前方）
  plastic002_19: "cab",
  cab_01_20: "cab",
  polimero_21: "cab",
  cromium_22: "cab",
  grill_23: "cab",
  glass_scania__24: "cab",
  polimero_2_25: "cab",
  // ボデー（荷箱・中央）
  frame_box_5: "body",
  side_truck_9: "body",
  bx_boo_4: "body",
  descarga__3: "body",
  punto_de_apollo_6: "body",
  // ホッパー（後部投入箱）
  centro_bk_2: "hopper",
  DESCARGA__7: "hopper",
  punto_de_carga__8: "hopper",
  // リアゲート
  Cylinder001_62: "tailgate",
  Object078_63: "tailgate",
  Object076_58: "tailgate",
  barra_c_10: "tailgate",
  // 回転板（後部内部・左右の羽根）
  Object056_14: "rotating-plate",
  Object057_15: "rotating-plate",
  Object059_16: "rotating-plate",
  Object060_17: "rotating-plate",
  // スライドプレート
  Object050_12: "slide-plate",
  Object061_18: "slide-plate",
  // 油圧シリンダー
  cilindro_h_11: "hydraulic-cylinder",
  // ピストンポンプ（シャシ上の機器）
  Object070_52: "hydraulic-pump",
  Object074_56: "hydraulic-pump",
  Object075_57: "hydraulic-pump",
  casco_de_bateria__51: "hydraulic-pump",
  // パイピング ボデー（配管・シャシ）
  cableado_43: "piping-body",
  chassis_001_40: "piping-body",
  chassis__60: "piping-body",
  // パイピング バルブ
  Object071_53: "piping-valve",
  Object072_54: "piping-valve",
  Object073_55: "piping-valve",
  // PTO（タンク類で代表）
  tanque_de_combutible__50: "pto",
  tanque_01_49: "pto",
  // 前輪
  Torus006_34: "wheel-fl",
  Object065_35: "wheel-fl",
  Box004_28: "wheel-fl",
  Object002_29: "wheel-fl",
  Box008_36: "wheel-fl",
  Object066_37: "wheel-fl",
  // 後輪
  Torus004_32: "wheel-rl",
  Object063_31: "wheel-rl",
  Object067_38: "wheel-rl",
  Object068_39: "wheel-rl",
  Box007_33: "wheel-rl",
  // キャブのガラス類
  vidrio01_41: "cab",
  vidrio_03_44: "cab",
  vidrio_02_59: "cab",
  // フェンダー（泥除け）→ ボデー
  caucho_guarda_fango_42: "body",
  guarda_fango_45: "body",
  // エアサス → PTO/シャシ機器
  suspencion_neumatica_48: "pto",
  // 配管テンショナー → パイピング
  tensador_plastico_46: "piping-body",
  // プレート類（板メッシュを割り当て）
  PlaneShape_65: "mfg-plate",
  PlaneShape001_66: "mfg-plate",
  PlaneShape002_67: "mfg-plate",
  Plane003_61: "mfg-plate",
  LIBRO_BASURA__64: "mfg-plate",
};

const SELECT_COLOR = 0xfbbf24;
const HILITE_COLOR = 0x3b82f6;
const VEHICLE_CENTER = new THREE.Vector3(0.15, 0.0, 0.4);

type PartEntry = {
  node: THREE.Object3D;
  meshId: PartMeshId;
  home: THREE.Vector3;
  exploded: THREE.Vector3;
};

function GarbageTruck({ selectedMeshId, highlightedMeshIds, onSelect }: Common) {
  const { scene } = useGLTF(MODEL_URL);
  const [parts, setParts] = useState<PartEntry[]>([]);

  // Stage によるスケール/センタリング適用後に部品の分解先を計算する
  useEffect(() => {
    const t = setTimeout(() => {
      // ハイライトを部品ごとに効かせるためマテリアルを複製
      scene.traverse((o) => {
        const mesh = o as THREE.Mesh;
        if ((mesh as unknown as { isMesh?: boolean }).isMesh && mesh.material) {
          mesh.material = Array.isArray(mesh.material)
            ? mesh.material.map((m) => m.clone())
            : (mesh.material as THREE.Material).clone();
        }
      });

      const list: PartEntry[] = [];
      for (const [name, meshId] of Object.entries(PART_NODES)) {
        const node = scene.getObjectByName(name);
        if (!node) continue;
        node.traverse((o) => {
          o.userData.partMeshId = meshId;
        });
        const box = new THREE.Box3().setFromObject(node);
        const wc = box.getCenter(new THREE.Vector3());
        const dir = wc.clone().sub(VEHICLE_CENTER);
        if (dir.lengthSq() < 1e-4) dir.set(0, 1, 0);
        dir.normalize();
        dir.y += 0.25; // 少し上にも逃がして見やすく
        dir.normalize();
        const worldHome = node.getWorldPosition(new THREE.Vector3());
        const worldTarget = worldHome.clone().add(dir.multiplyScalar(1.3));
        const parent = node.parent ?? scene;
        const localTarget = parent.worldToLocal(worldTarget.clone());
        list.push({
          node,
          meshId,
          home: node.position.clone(),
          exploded: localTarget,
        });
      }
      setParts(list);
    }, 900);
    return () => clearTimeout(t);
  }, [scene]);

  useFrame(() => {
    const anySel = selectedMeshId != null;
    // 位置（選択部品を車から分解）
    for (const p of parts) {
      const sel = selectedMeshId === p.meshId;
      p.node.position.lerp(sel ? p.exploded : p.home, 0.15);
    }
    // 透明度・発光（選択部品を際立たせ、他は半透明に）
    scene.traverse((o) => {
      const mat = (o as THREE.Mesh).material as
        | THREE.MeshStandardMaterial
        | undefined;
      if (!mat || mat.opacity === undefined) return;
      const mid = o.userData.partMeshId as PartMeshId | undefined;
      const isSel = anySel && mid === selectedMeshId;
      const targetOp = anySel && !isSel ? 0.2 : 1;
      mat.transparent = targetOp < 0.99;
      mat.opacity = THREE.MathUtils.lerp(mat.opacity, targetOp, 0.18);
      mat.depthWrite = mat.opacity > 0.85;
      if (mat.emissive) {
        if (isSel) {
          mat.emissive.setHex(SELECT_COLOR);
          mat.emissiveIntensity = 0.45;
        } else if (!anySel && mid && highlightedMeshIds.includes(mid)) {
          mat.emissive.setHex(HILITE_COLOR);
          mat.emissiveIntensity = 0.4;
        } else {
          mat.emissiveIntensity = 0;
        }
      }
    });
  });

  return (
    <primitive
      object={scene}
      onClick={(e: ThreeEvent<MouseEvent>) => {
        e.stopPropagation();
        const mid = (e.object.userData?.partMeshId as PartMeshId) ?? null;
        if (mid) onSelect(mid);
      }}
      onPointerMissed={() => onSelect(null)}
    />
  );
}
useGLTF.preload(MODEL_URL);

export function TruckModel(props: Common) {
  return (
    <div className="relative h-full w-full">
      <Canvas
        shadows
        dpr={[1, 2]}
        camera={{ position: [6, 4, 9], fov: 40 }}
        gl={{ antialias: true, alpha: true, toneMappingExposure: 1.0 }}
      >
        <color attach="background" args={["#0c1018"]} />
        <fog attach="fog" args={["#0c1018", 20, 45]} />

        <Suspense fallback={null}>
          <Stage
            environment="city"
            intensity={0.5}
            adjustCamera={1.2}
            shadows={false}
          >
            <GarbageTruck {...props} />
          </Stage>
          <ContactShadows
            position={[0, -0.01, 0]}
            opacity={0.5}
            scale={20}
            blur={2.2}
            far={5}
            resolution={1024}
            color="#000000"
          />
        </Suspense>

        <OrbitControls
          makeDefault
          enablePan={false}
          minDistance={2}
          maxDistance={40}
          minPolarAngle={Math.PI / 8}
          maxPolarAngle={Math.PI / 2.05}
        />
      </Canvas>
    </div>
  );
}
