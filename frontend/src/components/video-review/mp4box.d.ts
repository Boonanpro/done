// Minimal ambient types for the subset of mp4box.js (v0.5.x) we use in the
// WebCodecs preview decoder. mp4box ships no .d.ts; we only need demuxing:
// fetch -> appendBuffer -> onReady (track + codec) -> setExtractionOptions ->
// onSamples (encoded frames). See frame-source.ts.
declare module 'mp4box' {
  export interface MP4VideoTrack {
    id: number;
    codec: string;
    timescale: number;
    nb_samples: number;
    track_width: number;
    track_height: number;
    duration: number; // in track timescale
    movie_duration: number;
    movie_timescale: number;
  }
  export interface MP4Info {
    duration: number; // in movie timescale
    timescale: number;
    videoTracks: MP4VideoTrack[];
    tracks: MP4VideoTrack[];
  }
  export interface MP4Sample {
    number: number;
    track_id: number;
    timescale: number;
    is_sync: boolean;
    cts: number; // composition (presentation) time, in track timescale
    dts: number;
    duration: number;
    size: number;
    data: Uint8Array;
  }
  export interface MP4ArrayBuffer extends ArrayBuffer {
    fileStart: number;
  }
  export interface MP4Box {
    write(stream: DataStream): void;
  }
  export interface MP4SampleDescriptionEntry {
    avcC?: MP4Box;
    hvcC?: MP4Box;
    vpcC?: MP4Box;
    av1C?: MP4Box;
  }
  export interface MP4Track {
    mdia: { minf: { stbl: { stsd: { entries: MP4SampleDescriptionEntry[] } } } };
  }
  export interface MP4File {
    onReady?: (info: MP4Info) => void;
    onError?: (e: string) => void;
    onSamples?: (id: number, user: unknown, samples: MP4Sample[]) => void;
    appendBuffer(data: MP4ArrayBuffer): number;
    start(): void;
    stop(): void;
    flush(): void;
    setExtractionOptions(id: number, user?: unknown, options?: { nbSamples?: number; rapAlignement?: boolean }): void;
    getTrackById(id: number): MP4Track;
  }
  export function createFile(): MP4File;

  export class DataStream {
    static BIG_ENDIAN: boolean;
    static LITTLE_ENDIAN: boolean;
    constructor(arrayBuffer?: ArrayBuffer, byteOffset?: number, endianness?: boolean);
    buffer: ArrayBuffer;
  }
}
