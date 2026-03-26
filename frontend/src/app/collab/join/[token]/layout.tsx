'use client';

export default function GuestLayout({ children }: { children: React.ReactNode }) {
  // Guest pages have no sidebar - standalone view
  return <>{children}</>;
}
