'use client';
import { useEffect } from 'react';
import { installVoiceControls } from './voice-controls';
export function VoiceControlsRuntime() { useEffect(installVoiceControls, []); return null; }
