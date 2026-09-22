// Tell Dan where the owner is — only while the app is open (owner's decision: nothing in the background).
// Sent when the app comes to the front, when a voice call starts, and after moving about 250 m.
// The server keeps only the latest fix; chat and voice read it through the same tool.
//
// expo-location is a native module. An installed APK built before it was added must keep working with the same
// JS bundle (OTA), so the module is loaded lazily and every failure is silent.

type LocationModule = typeof import('expo-location');

let moduleCache: LocationModule | null | undefined;
let lastSentAt = 0;
let watching: { remove: () => void } | null = null;

function load(): LocationModule | null {
  if (moduleCache !== undefined) return moduleCache;
  try {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    moduleCache = require('expo-location') as LocationModule;
  } catch {
    moduleCache = null;
  }
  return moduleCache;
}

async function allowed(Location: LocationModule): Promise<boolean> {
  const current = await Location.getForegroundPermissionsAsync();
  if (current.granted) return true;
  if (!current.canAskAgain) return false; // refused once: never nag
  return (await Location.requestForegroundPermissionsAsync()).granted;
}

async function send(apiBase: string, token: string, coords: { latitude: number; longitude: number; accuracy: number | null }, at: number) {
  lastSentAt = Date.now();
  await fetch(`${apiBase}/api/v1/push/native/location`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ lat: coords.latitude, lng: coords.longitude, accuracy: coords.accuracy, at: new Date(at).toISOString() }),
  });
}

/** One fix now. `force` skips the one-minute throttle (a voice call is starting). */
export async function reportLocation(apiBase: string, token: string, force = false): Promise<void> {
  try {
    const Location = load();
    if (!Location || !token) return;
    if (!force && Date.now() - lastSentAt < 60_000) return;
    if (!(await allowed(Location))) return;
    const known = await Location.getLastKnownPositionAsync({ maxAge: 120_000, requiredAccuracy: 200 });
    const fix = known ?? (await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced }));
    await send(apiBase, token, fix.coords, fix.timestamp);
  } catch {
    // no location is not an error the owner should see
  }
}

/** Keep Dan up to date while the app is in front; call the returned function when it goes to the background. */
export async function watchLocation(apiBase: string, token: string): Promise<() => void> {
  try {
    const Location = load();
    if (!Location || !token || watching) return () => undefined;
    if (!(await allowed(Location))) return () => undefined;
    watching = await Location.watchPositionAsync(
      { accuracy: Location.Accuracy.Balanced, distanceInterval: 250, timeInterval: 60_000 },
      (fix) => { void send(apiBase, token, fix.coords, fix.timestamp).catch(() => undefined); },
    );
  } catch {
    watching = null;
  }
  return () => { watching?.remove(); watching = null; };
}
