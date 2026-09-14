import type { Metadata } from 'next';
export const metadata: Metadata = {title:'話して、noteに。',robots:{index:false,follow:false},manifest:'/artifacts/voice-note/manifest.webmanifest'};
export default function Layout({children}:{children:React.ReactNode}){return children;}
