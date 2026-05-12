import { registerPlugin } from '@capacitor/core'

export interface NativeTtsPlayerPlugin {
  available(): Promise<{ available: boolean }>
  speak(options: {
    text: string
    lang?: string
    rate?: number
    pitch?: number
    volume?: number
    preferFemale?: boolean
  }): Promise<void>
  pause(): Promise<void>
  resume(): Promise<void>
  stop(): Promise<void>
  addListener(
    eventName: 'playbackState',
    listenerFunc: (data: { state: string; message?: string }) => void
  ): Promise<{ remove: () => Promise<void> }>
}

export const NativeTtsPlayer = registerPlugin<NativeTtsPlayerPlugin>('NativeTtsPlayer')
