import {useSyncExternalStore} from 'react';
import * as SecureStore from 'expo-secure-store';
export type UiLanguage = 'en' | 'ja';
let language: UiLanguage = 'en';
let revision = 0;
let started = false;
const listeners = new Set<() => void>();
const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; };
export function useUiLanguage() {
  if (!started) {
    started = true;
    void SecureStore.getItemAsync('done_ui_language').then(value => {
      if (revision === 0 && (value === 'en' || value === 'ja')) {language = value; listeners.forEach(l => l());}
    }).catch(() => undefined);
  }
  return useSyncExternalStore(subscribe, () => language, () => 'en' as UiLanguage);
}
let pendingSave: Promise<void> = Promise.resolve();
export function setUiLanguage(value: UiLanguage) {
  revision++; language = value; listeners.forEach(l => l());
  pendingSave = pendingSave.catch(() => undefined).then(() => SecureStore.setItemAsync('done_ui_language', value));
  return pendingSave;
}
export const ui = (en: string, ja: string) => language === 'ja' ? ja : en;
