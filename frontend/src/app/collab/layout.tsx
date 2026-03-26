'use client';

// No wrapping layout - each page manages its own layout
// Owner pages use MainLayout, guest pages are standalone
export default function CollabLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
