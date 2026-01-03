/**
 * Settings Store - Manages user preferences
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type Language = 'ja' | 'en';

interface SettingsState {
  language: Language;

  // Actions
  setLanguage: (language: Language) => void;
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      language: 'ja',

      setLanguage: (language) => set({ language }),
    }),
    {
      name: 'done-settings',
    }
  )
);

