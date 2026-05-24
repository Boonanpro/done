"use client";

import { Suspense, useRef, useState } from "react";
import { Canvas, useFrame, type ThreeEvent } from "@react-three/fiber";
import { OrbitControls, Environment, ContactShadows } from "@react-three/drei";
import * as THREE from "three";
import type { PartMeshId } from "../mock-data";

type PartMeshProps = {
  meshId: PartMeshId;
  position: [number, number, number];
  args: [number, number, number];
  color: string;
  selectedMeshId: PartMeshId | null;
  highlightedMeshIds: PartMeshId[];
  onSelect: (id: PartMeshId) => void;
  rotation?: [number, number, number];
  shape?: "box" | "cylinder";
  cylinderArgs?: [number, number, number, number]; // radiusTop, radiusBottom, height, radialSegments
};

function PartMesh({
  meshId,
  position,
  args,
  color,
  selectedMeshId,
  highlightedMeshIds,
  onSelect,
  rotation,
  shape = "box",
  cylinderArgs,
}: PartMeshProps) {
  const [hovered, setHovered] = useState(false);
  const isSelected = selectedMeshId === meshId;
  const isHighlighted = highlightedMeshIds.includes(meshId);
  const ref = useRef<THREE.Mesh>(null);

  // 選択 or 検索ハイライト時にゆるい発光
  useFrame((state) => {
    if (!ref.current) return;
    const mat = ref.current.material as THREE.MeshStandardMaterial;
    if (!mat || !mat.isMaterial) return;
    if (isSelected || isHighlighted) {
      const t = Math.sin(state.clock.elapsedTime * 3) * 0.3 + 0.7;
      mat.emissiveIntensity = isSelected ? t * 1.2 : t * 0.6;
    } else {
      mat.emissiveIntensity = hovered ? 0.4 : 0;
    }
  });

  const handleClick = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation();
    onSelect(meshId);
  };

  const emissiveColor = isSelected ? "#fbbf24" : isHighlighted ? "#60a5fa" : color;

  return (
    <mesh
      ref={ref}
      position={position}
      rotation={rotation}
      onClick={handleClick}
      onPointerOver={(e) => {
        e.stopPropagation();
        setHovered(true);
        document.body.style.cursor = "pointer";
      }}
      onPointerOut={() => {
        setHovered(false);
        document.body.style.cursor = "default";
      }}
      castShadow
      receiveShadow
    >
      {shape === "cylinder" && cylinderArgs ? (
        <cylinderGeometry args={cylinderArgs} />
      ) : (
        <boxGeometry args={args} />
      )}
      <meshStandardMaterial
        color={color}
        emissive={emissiveColor}
        emissiveIntensity={0}
        roughness={0.6}
        metalness={0.3}
      />
    </mesh>
  );
}

type TruckModelProps = {
  selectedMeshId: PartMeshId | null;
  highlightedMeshIds: PartMeshId[];
  onSelect: (id: PartMeshId) => void;
};

function Truck({ selectedMeshId, highlightedMeshIds, onSelect }: TruckModelProps) {
  const common = {
    selectedMeshId,
    highlightedMeshIds,
    onSelect,
  };

  return (
    <group position={[0, 0, 0]}>
      {/* シャシ (車体下部の横長フレーム) */}
      <mesh position={[0, -0.55, 0]} receiveShadow>
        <boxGeometry args={[6.5, 0.2, 1.6]} />
        <meshStandardMaterial color="#1f2937" roughness={0.8} />
      </mesh>

      {/* キャブ (運転席) */}
      <PartMesh
        meshId="cab"
        position={[-2.4, 0.35, 0]}
        args={[1.4, 1.4, 1.6]}
        color="#e5e7eb"
        {...common}
      />
      {/* キャブの窓 (見た目だけ、クリック不可) */}
      <mesh position={[-2.4, 0.6, 0.81]}>
        <boxGeometry args={[1.2, 0.65, 0.02]} />
        <meshStandardMaterial color="#0f172a" metalness={0.4} roughness={0.2} />
      </mesh>

      {/* 警告灯 (キャブ上) */}
      <PartMesh
        meshId="warning-light"
        position={[-2.4, 1.18, 0]}
        args={[0.4, 0.15, 0.4]}
        color="#fcd34d"
        {...common}
      />

      {/* ボデー本体 (荷箱) */}
      <PartMesh
        meshId="body"
        position={[0.2, 0.65, 0]}
        args={[3.4, 1.9, 1.6]}
        color="#3b82f6"
        {...common}
      />

      {/* MFGプレート (ボデー側面の小さな板) */}
      <PartMesh
        meshId="mfg-plate"
        position={[0.2, 0.4, 0.81]}
        args={[0.4, 0.2, 0.02]}
        color="#d1d5db"
        {...common}
      />

      {/* ホッパー (後部) */}
      <PartMesh
        meshId="hopper"
        position={[2.4, 0.4, 0]}
        args={[1.4, 1.6, 1.7]}
        color="#1e40af"
        {...common}
      />

      {/* リアゲート */}
      <PartMesh
        meshId="tailgate"
        position={[3.15, 0.4, 0]}
        args={[0.1, 1.5, 1.6]}
        color="#1e3a8a"
        {...common}
      />

      {/* 回転板 (ホッパー内部、円柱で代表) */}
      <PartMesh
        meshId="rotating-plate"
        position={[2.4, 0.4, 0]}
        args={[0, 0, 0]}
        color="#f59e0b"
        rotation={[Math.PI / 2, 0, 0]}
        shape="cylinder"
        cylinderArgs={[0.5, 0.5, 1.55, 24]}
        {...common}
      />

      {/* スライドプレート (ホッパー下) */}
      <PartMesh
        meshId="slide-plate"
        position={[2.4, -0.35, 0]}
        args={[1.3, 0.08, 1.55]}
        color="#a3a3a3"
        {...common}
      />

      {/* 油圧シリンダー (ボデー右側面) */}
      <PartMesh
        meshId="hydraulic-cylinder"
        position={[1.7, 0.3, 0.65]}
        args={[0, 0, 0]}
        color="#dc2626"
        rotation={[0, 0, Math.PI / 2]}
        shape="cylinder"
        cylinderArgs={[0.12, 0.12, 1.4, 16]}
        {...common}
      />

      {/* 油圧ポンプ (シャシ下) */}
      <PartMesh
        meshId="hydraulic-pump"
        position={[-0.5, -0.3, 0]}
        args={[0.6, 0.5, 0.6]}
        color="#7c2d12"
        {...common}
      />

      {/* パイピング ボデー (細い管) */}
      <PartMesh
        meshId="piping-body"
        position={[0.5, -0.1, 0.78]}
        args={[0, 0, 0]}
        color="#f97316"
        rotation={[0, 0, Math.PI / 2]}
        shape="cylinder"
        cylinderArgs={[0.04, 0.04, 2.8, 12]}
        {...common}
      />

      {/* パイピング バルブ */}
      <PartMesh
        meshId="piping-valve"
        position={[-0.5, -0.1, 0.78]}
        args={[0.2, 0.2, 0.2]}
        color="#ea580c"
        {...common}
      />

      {/* PTO (シャシ中央下) */}
      <PartMesh
        meshId="pto"
        position={[-1.0, -0.45, 0]}
        args={[0.5, 0.3, 0.4]}
        color="#475569"
        {...common}
      />

      {/* 車輪 4個 */}
      <PartMesh
        meshId="wheel-fl"
        position={[-1.8, -0.65, 0.85]}
        args={[0, 0, 0]}
        color="#111827"
        rotation={[Math.PI / 2, 0, 0]}
        shape="cylinder"
        cylinderArgs={[0.45, 0.45, 0.3, 24]}
        {...common}
      />
      <PartMesh
        meshId="wheel-fr"
        position={[-1.8, -0.65, -0.85]}
        args={[0, 0, 0]}
        color="#111827"
        rotation={[Math.PI / 2, 0, 0]}
        shape="cylinder"
        cylinderArgs={[0.45, 0.45, 0.3, 24]}
        {...common}
      />
      <PartMesh
        meshId="wheel-rl"
        position={[1.8, -0.65, 0.85]}
        args={[0, 0, 0]}
        color="#111827"
        rotation={[Math.PI / 2, 0, 0]}
        shape="cylinder"
        cylinderArgs={[0.45, 0.45, 0.3, 24]}
        {...common}
      />
      <PartMesh
        meshId="wheel-rr"
        position={[1.8, -0.65, -0.85]}
        args={[0, 0, 0]}
        color="#111827"
        rotation={[Math.PI / 2, 0, 0]}
        shape="cylinder"
        cylinderArgs={[0.45, 0.45, 0.3, 24]}
        {...common}
      />

    </group>
  );
}

export function TruckModel(props: TruckModelProps) {
  return (
    <div className="relative h-full w-full">
      <Canvas
        shadows
        camera={{ position: [5, 3, 6], fov: 45 }}
        gl={{ antialias: true, alpha: true }}
      >
        <color attach="background" args={["#0b1220"]} />
        <fog attach="fog" args={["#0b1220", 12, 22]} />

        <ambientLight intensity={0.6} />
        <directionalLight
          position={[6, 8, 4]}
          intensity={1.2}
          castShadow
          shadow-mapSize-width={1024}
          shadow-mapSize-height={1024}
        />
        <directionalLight position={[-4, 4, -4]} intensity={0.3} />

        <Suspense fallback={null}>
          <Truck {...props} />
          <ContactShadows
            position={[0, -0.78, 0]}
            opacity={0.5}
            scale={12}
            blur={2}
            far={3}
          />
          <Environment preset="city" />
        </Suspense>

        <OrbitControls
          enablePan={false}
          minDistance={4}
          maxDistance={14}
          minPolarAngle={Math.PI / 6}
          maxPolarAngle={Math.PI / 2.2}
          autoRotate={false}
        />

        {/* 床のグリッド (位置感覚用) */}
        <gridHelper args={[20, 20, "#1e293b", "#1e293b"]} position={[0, -0.78, 0]} />
      </Canvas>
    </div>
  );
}
